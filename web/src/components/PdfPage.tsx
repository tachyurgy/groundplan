import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { BBox, ExtractedField } from '../api/types';
import { fileStore } from './fileStore';

const LETTER: [number, number] = [612, 792];

type PdfDoc = { numPages: number; getPage: (n: number) => Promise<PdfPageProxy>; destroy: () => Promise<void> };
type PdfPageProxy = {
  getViewport: (o: { scale: number }) => { width: number; height: number; convertToViewportRectangle: (r: number[]) => number[] };
  render: (o: { canvasContext: CanvasRenderingContext2D; viewport: unknown }) => { promise: Promise<void> };
};

let pdfjsPromise: Promise<typeof import('pdfjs-dist')> | null = null;
/** Lazy-load pdf.js (+ its worker) only when a page is actually rendered. */
function loadPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = Promise.all([import('pdfjs-dist'), import('pdfjs-dist/build/pdf.worker.min.mjs?url')]).then(([pdfjs, worker]) => {
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
      return pdfjs;
    });
  }
  return pdfjsPromise;
}

const docCache = new Map<string, Promise<PdfDoc>>();
function openDoc(documentId: string, file: File): Promise<PdfDoc> {
  let p = docCache.get(documentId);
  if (!p) {
    p = file.arrayBuffer().then(async (buf) => {
      const pdfjs = await loadPdfjs();
      return (await pdfjs.getDocument({ data: new Uint8Array(buf) }).promise) as unknown as PdfDoc;
    });
    docCache.set(documentId, p);
  }
  return p;
}

interface Props {
  documentId: string;
  page: number;
  fields: ExtractedField[];
  width?: number;
  highlight?: string | null; // field id
  onPick?: (f: ExtractedField) => void;
  /** optional single bbox (traceability drawer) */
  focusBox?: BBox | null;
}

/**
 * One PDF page with extracted-field bboxes overlaid. Renders the real page from the local upload buffer
 * with pdf.js; if this tab never held the file (fixture docs, or after reload) it draws a schematic page
 * with the boxes and raw text, because the server keeps only sha256 + fields.
 */
export function PdfPage({ documentId, page, fields, width = 420, highlight, onPick, focusBox }: Props) {
  const file = useSyncExternalStore(fileStore.subscribe, () => fileStore.get(documentId));
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState<[number, number]>([LETTER[0], LETTER[1]]);
  const [rects, setRects] = useState<Map<string, number[]>>(new Map());
  const [err, setErr] = useState<string | null>(null);
  const scale = width / size[0];

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    (async () => {
      try {
        const doc = await openDoc(documentId, file);
        const pg = await doc.getPage(Math.min(Math.max(1, page), doc.numPages));
        const base = pg.getViewport({ scale: 1 });
        const vp = pg.getViewport({ scale: width / base.width });
        const canvas = canvasRef.current;
        if (!canvas || cancelled) return;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(vp.width * dpr);
        canvas.height = Math.floor(vp.height * dpr);
        canvas.style.width = `${vp.width}px`;
        canvas.style.height = `${vp.height}px`;
        const ctx = canvas.getContext('2d')!;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        await pg.render({ canvasContext: ctx, viewport: vp }).promise;
        if (cancelled) return;
        setSize([base.width, base.height]);
        const m = new Map<string, number[]>();
        for (const f of fields) m.set(f.id, vp.convertToViewportRectangle(f.bbox));
        if (focusBox) m.set('__focus', vp.convertToViewportRectangle(focusBox));
        setRects(m);
        setErr(null);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [file, documentId, page, width, fields, focusBox]);

  // Schematic fallback geometry (PDF points, origin bottom-left)
  const toCss = (b: BBox) => {
    if (file && !err) {
      return null;
    }
    const s = width / LETTER[0];
    const x0 = Math.min(b[0], b[2]) * s;
    const x1 = Math.max(b[0], b[2]) * s;
    const yTop = (LETTER[1] - Math.max(b[1], b[3])) * s;
    const yBot = (LETTER[1] - Math.min(b[1], b[3])) * s;
    return { left: x0, top: yTop, width: x1 - x0, height: yBot - yTop };
  };
  const rectCss = (id: string, b: BBox) => {
    const r = rects.get(id);
    if (file && !err && r) {
      const [a, bb, c, d] = r;
      return { left: Math.min(a, c), top: Math.min(bb, d), width: Math.abs(c - a), height: Math.abs(d - bb) };
    }
    return toCss(b);
  };
  const height = (file && !err ? size[1] * scale : LETTER[1] * (width / LETTER[0])) || 0;
  const pageFields = fields.filter((f) => f.page === page);

  return (
    <div className="relative overflow-hidden rounded-sm bg-white ring-1 ring-ink-200" style={{ width, height }} data-testid="pdf-page">
      {file && !err ? (
        <canvas ref={canvasRef} className="block" />
      ) : (
        <div className="absolute inset-0 bg-[linear-gradient(transparent_23px,#f1f2f5_24px)] bg-[length:100%_24px]">
          <div className="absolute left-3 right-3 top-3 flex items-center justify-between text-[10px] text-ink-400">
            <span>Page {page}</span>
            <span>{err ? `pdf.js: ${err}` : 'schematic · file bytes not retained'}</span>
          </div>
        </div>
      )}
      {pageFields.map((f) => {
        const css = rectCss(f.id, f.bbox);
        if (!css) return null;
        const on = highlight === f.id;
        return (
          <button
            key={f.id}
            type="button"
            onClick={() => onPick?.(f)}
            title={`${f.field} = ${f.raw_text} (${Math.round(f.confidence * 100)}%, ${f.extractor})`}
            className={`absolute rounded-[2px] border text-left transition-colors ${
              on ? 'border-brand-600 bg-brand-500/25 ring-2 ring-brand-500/40' : f.confidence < 0.9 ? 'border-est-600/70 bg-est-100/40 hover:bg-est-100/80' : 'border-brand-500/60 bg-brand-100/30 hover:bg-brand-100/70'
            }`}
            style={{ left: css.left, top: css.top, width: Math.max(css.width, 6), height: Math.max(css.height, 6) }}
          >
            {!(file && !err) && <span className="block truncate px-0.5 font-mono text-[8px] leading-[10px] text-ink-700">{f.raw_text}</span>}
          </button>
        );
      })}
      {focusBox &&
        (() => {
          const css = rectCss('__focus', focusBox);
          return css ? <div className="pointer-events-none absolute rounded-[2px] border-2 border-neg-600 bg-neg-600/10" style={css} /> : null;
        })()}
    </div>
  );
}
