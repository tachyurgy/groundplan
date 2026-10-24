import { useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { getRouteApi } from '@tanstack/react-router';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { ApiError } from '../api/client';
import { documentQuery, documentsQuery, findingsQuery, useDismissFinding, useResolveFinding, useUpload } from '../api/queries';
import type { Document, ExtractedField, Finding, FindingCandidate } from '../api/types';
import { useMeasure } from '../charts/kit';
import { HouseholdNav } from '../components/HouseholdNav';
import { PdfPage } from '../components/PdfPage';
import { fileStore } from '../components/fileStore';
import { Card, PageHeader, SeverityTag } from '../components/ui';
import { DOC_KIND_LABEL, formatDateTime, titleCase } from '../lib/format';
import { formatCents, formatRate } from '../lib/money';

const route = getRouteApi('/households/$householdId/documents');

function fmtValue(v: unknown, unit?: string): string {
  if (typeof v === 'number') {
    if (unit === 'rate' || (Math.abs(v) < 1 && !Number.isInteger(v))) return formatRate(v, 3);
    if (unit === 'cents' || unit === undefined) return formatCents(v, { exact: unit === 'cents' });
    return v.toLocaleString('en-US');
  }
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  return v === null || v === undefined ? '—' : String(v);
}

export function DocumentsPage() {
  const { householdId } = route.useParams();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const docs = useSuspenseQuery(documentsQuery(householdId)).data;
  const newest = [...docs].sort((a, b) => (b.tax_year ?? 0) - (a.tax_year ?? 0))[0];
  const selected = search.doc ?? newest?.id ?? null;
  const page = search.page ?? 1;
  const select = (doc: string, pg = 1) => navigate({ search: { doc, page: pg }, replace: true, resetScroll: false });

  useEffect(() => {
    if (window.location.hash === '#queue') document.getElementById('queue')?.scrollIntoView({ block: 'start' });
  }, []);

  return (
    <div>
      <PageHeader title="Documents and reconciliation">
        Files are processed in memory and dropped: the server keeps only the SHA-256 and the extracted fields. Page images below come from the copy in this browser tab.
      </PageHeader>
      <HouseholdNav householdId={householdId} />
      <UploadZone householdId={householdId} onUploaded={(d) => select(d.id)} />
      <div className="mt-5 grid gap-5 lg:grid-cols-[280px_1fr]">
        <DocList docs={docs} selected={selected} onSelect={select} />
        {selected ? <DocViewer documentId={selected} page={page} onPage={(p) => select(selected, p)} /> : <div className="card card-body text-sm text-ink-500">No documents yet. Upload a return or a loan statement to start.</div>}
      </div>
      <ReconciliationQueue householdId={householdId} onOpenSource={(c) => c.document_id && select(c.document_id, c.page ?? 1)} />
    </div>
  );
}

type LogRow = { id: string; name: string; state: 'uploading' | 'done' | 'error'; started: number; msg?: string };

/** Turn API failures into something an advisor can act on (413 too big, 503 reader down, 429 limits). */
function uploadError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 413) return 'Over the 15 MB upload limit. Split the PDF or scan at a lower resolution.';
    if (e.status === 503) return 'The document reader is unavailable right now. Nothing was saved; try again in a minute.';
    if (e.status === 429) return e.message || 'Upload limit reached for this sandbox. Reset demo data to start over.';
    if (e.status === 415 || e.status === 422) return e.message || 'This file could not be read as a PDF.';
    if (e.isNetwork) return 'Could not reach the API. Check the connection and try again.';
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

interface Sample {
  file: string;
  label: string;
  kind?: string;
  tax_year?: number;
  scan?: boolean;
}

/** Sample returns shipped with the site (public/samples/index.json), so a reviewer on a phone can try an upload. */
function useSamples() {
  return useQuery({
    queryKey: ['samples'],
    queryFn: async () => {
      const r = await fetch('/samples/index.json');
      if (!r.ok) return [] as Sample[];
      const j = (await r.json()) as unknown;
      return Array.isArray(j) ? (j as Sample[]).filter((s) => s && typeof s.file === 'string') : [];
    },
    staleTime: Infinity,
    retry: 0,
  });
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(since);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, []);
  return <span className="num">{Math.max(0, Math.round((now - since) / 1000))}s</span>;
}

function UploadZone({ householdId, onUploaded }: { householdId: string; onUploaded: (d: Document) => void }) {
  const upload = useUpload(householdId);
  const samples = useSamples();
  const [drag, setDrag] = useState(false);
  const [sample, setSample] = useState('');
  const [log, setLog] = useState<LogRow[]>([]);
  const patch = (id: string, p: Partial<LogRow>) => setLog((l) => l.map((x) => (x.id === id ? { ...x, ...p } : x)));
  const handle = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      const id = `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
        setLog((l) => [{ id, name: file.name, state: 'error', started: Date.now(), msg: 'Only PDF files can be read' }, ...l]);
        continue;
      }
      if (file.size > 15 * 1024 * 1024) {
        setLog((l) => [{ id, name: file.name, state: 'error', started: Date.now(), msg: 'Over the 15 MB upload limit' }, ...l]);
        continue;
      }
      setLog((l) => [{ id, name: file.name, state: 'uploading', started: Date.now() }, ...l]);
      try {
        const res = await upload.mutateAsync(file);
        fileStore.put(res.document.id, file); // keep the bytes in this tab only, for pdf.js
        patch(id, { state: 'done', msg: `${res.extracted_fields.length} fields, ${res.findings.length} findings` });
        onUploaded(res.document);
      } catch (e) {
        patch(id, { state: 'error', msg: uploadError(e) });
      }
    }
  };
  const trySample = async () => {
    const s = samples.data?.find((x) => x.file === sample);
    if (!s) return;
    const id = `sample-${Date.now()}`;
    try {
      const r = await fetch(`/samples/${s.file}`);
      if (!r.ok) throw new Error(`sample not found (${r.status})`);
      const blob = await r.blob();
      await handle([new File([blob], s.file.split('/').pop() ?? s.file, { type: 'application/pdf' })]);
    } catch (e) {
      setLog((l) => [{ id, name: s.file, state: 'error', started: Date.now(), msg: e instanceof Error ? e.message : String(e) }, ...l]);
    }
  };
  const busy = log.some((l) => l.state === 'uploading');
  return (
    <div
      data-testid="dropzone"
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        void handle(e.dataTransfer.files);
      }}
      className={`rounded-lg border-2 border-dashed px-4 py-4 transition-colors ${drag ? 'border-brand-500 bg-brand-50' : 'border-ink-200 bg-surface'}`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex-1">
          <div className="text-sm font-semibold text-ink-950">Drop PDFs here</div>
          <div className="text-xs leading-relaxed text-ink-500">Form 1040, Schedule E, Form 4562, Form 8582, mortgage statements, closing statements, appraisals. Text-layer or scanned, up to 15 MB each.</div>
        </div>
        <label className="btn cursor-pointer">
          Choose files
          <input type="file" accept="application/pdf,.pdf" multiple className="sr-only" data-testid="file-input" onChange={(e) => e.target.files && void handle(e.target.files)} />
        </label>
      </div>
      {!!samples.data?.length && (
        <div className="mt-3 flex flex-col gap-2 border-t border-ink-100 pt-3 sm:flex-row sm:items-center" data-testid="samples">
          <label htmlFor="sample-pick" className="text-sm text-ink-700 sm:shrink-0">
            No returns handy? Try a sample:
          </label>
          <select id="sample-pick" className="input sm:max-w-sm" value={sample} onChange={(e) => setSample(e.target.value)} data-testid="sample-select">
            <option value="">Choose a sample document</option>
            {samples.data.map((s) => (
              <option key={s.file} value={s.file}>
                {s.label}
                {s.scan ? ' (scanned, OCR)' : ''}
              </option>
            ))}
          </select>
          <button type="button" className="btn" disabled={!sample || busy} onClick={() => void trySample()} data-testid="sample-upload">
            Run it through the reader
          </button>
        </div>
      )}
      {log.length > 0 && (
        <ul className="mt-3 space-y-1.5 border-t border-ink-100 pt-3 text-xs" aria-live="polite" data-testid="upload-log">
          {log.slice(0, 6).map((l) => (
            <li key={l.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1">
              <span className="truncate font-medium text-ink-900">{l.name}</span>
              <span className={`text-right ${l.state === 'error' ? 'text-neg-600' : l.state === 'done' ? 'text-pos-600' : 'text-ink-500'}`}>
                {l.state === 'uploading' ? (
                  <>
                    Reading <Elapsed since={l.started} />
                  </>
                ) : (
                  l.msg
                )}
              </span>
              {l.state === 'uploading' && (
                <span className="col-span-2">
                  <span className="block h-1 overflow-hidden rounded-full bg-ink-100" role="progressbar" aria-label={`Reading ${l.name}`}>
                    <span className="block h-full w-1/3 animate-[gp-indeterminate_1.2s_ease-in-out_infinite] rounded-full bg-brand-500" />
                  </span>
                  <span className="mt-0.5 block text-[11px] text-ink-500">Text PDFs take about a second; scanned pages go through OCR and can take 10 seconds or more.</span>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DocList({ docs, selected, onSelect }: { docs: Document[]; selected: string | null; onSelect: (id: string) => void }) {
  useSyncExternalStore(fileStore.subscribe, fileStore.version);
  const groups = new Map<string, Document[]>();
  for (const d of docs) {
    const k = d.tax_year ? `Tax year ${d.tax_year}` : 'Statements and other';
    groups.set(k, [...(groups.get(k) ?? []), d]);
  }
  const sorted = [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  return (
    <>
      <label className="block lg:hidden">
        <span className="label mb-1 block">Document</span>
        <select className="input" value={selected ?? ''} onChange={(e) => onSelect(e.target.value)} data-testid="doc-select">
          {sorted.map(([g, ds]) => (
            <optgroup key={g} label={g}>
              {ds.map((d) => (
                <option key={d.id} value={d.id}>
                  {DOC_KIND_LABEL[d.kind] ?? d.kind}: {d.filename}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      <nav className="card hidden max-h-[760px] overflow-y-auto lg:block" aria-label="Documents" data-testid="doc-list">
        {sorted.map(([g, ds]) => (
          <div key={g}>
            <div className="sticky top-0 border-b border-ink-100 bg-surface-2 px-3 py-1.5 text-xs font-medium text-ink-500">{g}</div>
            {ds.map((d) => (
              <button key={d.id} type="button" aria-current={selected === d.id} onClick={() => onSelect(d.id)} className={`block w-full cursor-pointer border-b border-ink-100 px-3 py-2 text-left ${selected === d.id ? 'bg-brand-50' : 'hover:bg-ink-50'}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-ink-950">{DOC_KIND_LABEL[d.kind] ?? d.kind}</span>
                  <span className="text-[11px] text-ink-500">{d.status}</span>
                </div>
                <div className="truncate text-[11px] text-ink-500">{d.filename}</div>
                {fileStore.has(d.id) && <div className="text-[11px] text-pos-600">Page images available in this tab</div>}
              </button>
            ))}
          </div>
        ))}
      </nav>
    </>
  );
}

function DocViewer({ documentId, page, onPage }: { documentId: string; page: number; onPage: (p: number) => void }) {
  const { data, isPending, error } = useQuery(documentQuery(documentId));
  const [hl, setHl] = useState<string | null>(null);
  const rowRefs = useRef(new Map<string, HTMLElement>());
  const [ref, width] = useMeasure<HTMLDivElement>();
  if (isPending) return <div className="card h-[520px] skeleton" />;
  if (error || !data) return <div className="card card-body text-sm text-neg-600">This document could not be loaded: {error?.message ?? 'not found'}</div>;
  const d = data.document;
  const pageFields = data.fields.filter((f) => f.page === page);
  const pick = (f: ExtractedField) => {
    setHl(f.id);
    rowRefs.current.get(f.id)?.scrollIntoView({ block: 'nearest' });
  };
  const pdfWidth = Math.max(240, Math.min(440, width));
  return (
    <div className="card min-w-0" data-testid="doc-viewer">
      <div className="card-head flex-wrap">
        <div className="min-w-0">
          <h2 className="truncate">{d.filename}</h2>
          <div className="font-mono text-[11px] break-all text-ink-500" title={d.sha256}>
            sha256 {d.sha256.slice(0, 16)}…, {d.page_count} pages, uploaded {formatDateTime(d.uploaded_at)}, bytes retained: {String(d.bytes_retained)}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button type="button" className="btn btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
            ‹
          </button>
          <span className="num px-1 text-xs">
            {page} / {d.page_count}
          </span>
          <button type="button" className="btn btn-sm" disabled={page >= d.page_count} onClick={() => onPage(page + 1)} aria-label="Next page">
            ›
          </button>
        </div>
      </div>
      <div className="grid gap-4 p-4 xl:grid-cols-[auto_1fr]">
        <div ref={ref} className="min-w-0 xl:w-[440px]">
          {width > 0 && <PdfPage documentId={d.id} page={page} fields={data.fields} highlight={hl} onPick={pick} width={pdfWidth} />}
        </div>
        <div className="min-w-0">
          <h3 className="mb-2 text-sm">Extracted on page {page}</h3>
          {pageFields.length === 0 && <p className="text-xs text-ink-500">No fields extracted on this page.</p>}
          <ul className="divide-y divide-ink-100" data-testid="extracted-fields">
            {pageFields.map((f) => (
              <li
                key={f.id}
                ref={(el) => {
                  if (el) rowRefs.current.set(f.id, el);
                }}
                onMouseEnter={() => setHl(f.id)}
                className={`grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 py-1.5 ${hl === f.id ? 'bg-brand-50' : ''}`}
              >
                <span className="min-w-0 font-mono text-[11.5px] break-all text-ink-900">{f.field}</span>
                <span className="num text-right text-[13px]">{fmtValue(f.value, f.unit)}</span>
                <span className="min-w-0 truncate text-[11px] text-ink-500">{f.property_key ?? 'household'}</span>
                <span className={`text-right text-[11px] ${f.confidence < 0.9 ? 'text-est-600' : 'text-ink-500'}`}>
                  {Math.round(f.confidence * 100)}% via {f.extractor}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function ReconciliationQueue({ householdId, onOpenSource }: { householdId: string; onOpenSource: (c: FindingCandidate) => void }) {
  const { data = [] } = useQuery(findingsQuery(householdId));
  // Mutations live here, not in the card: the optimistic update removes the card at once, and a
  // failure has to be reported by something that is still on screen when the rollback lands.
  const resolve = useResolveFinding();
  const dismiss = useDismissFinding();
  const err = resolve.error ?? dismiss.error;
  const open = data.filter((f) => f.status === 'open');
  const closed = data.filter((f) => f.status !== 'open');
  return (
    <section id="queue" className="mt-8 scroll-mt-20" aria-labelledby="queue-title">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="queue-title" className="text-lg">
          Reconciliation queue
        </h2>
        <span className="text-xs text-ink-500">
          {open.length} open, {closed.length} closed. Sources are never averaged: a blocked figure stays blocked until its finding is resolved.
        </span>
      </div>
      {err && (
        <p role="alert" className="mb-3 rounded-md bg-neg-100 px-3 py-2 text-sm text-neg-600">
          Could not save that decision ({err.message}). The finding is back in the queue.
        </p>
      )}
      <div className="space-y-3">
        {open.map((f) => (
          <FindingCard
            key={f.id}
            f={f}
            busy={(resolve.isPending && resolve.variables?.id === f.id) || (dismiss.isPending && dismiss.variables?.id === f.id)}
            onResolve={(value, note) => resolve.mutate({ id: f.id, householdId, value, note })}
            onDismiss={(note) => dismiss.mutate({ id: f.id, householdId, note })}
            onOpenSource={onOpenSource}
          />
        ))}
        {open.length === 0 && <div className="card card-body text-sm text-ink-500">Nothing open. Every figure runs on resolved values.</div>}
      </div>
      {closed.length > 0 && (
        <Card title="Closed" className="mt-4" bodyClass="divide-y divide-ink-100">
          {closed.map((f) => (
            <div key={f.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2 text-xs" data-testid="closed-finding">
              <span className="font-semibold text-ink-700">{titleCase(f.status)}</span>
              <span className="font-mono break-all text-ink-700">{f.field}</span>
              {f.resolution?.value !== null && f.resolution?.value !== undefined && <span className="num text-ink-900">→ {fmtValue(f.resolution.value)}</span>}
              <span className="text-ink-500">
                {f.resolution?.who ?? ''}
                {f.resolution?.when ? `, ${formatDateTime(f.resolution.when)}` : ''}
                {f.resolution?.note ? `: ${f.resolution.note}` : ''}
              </span>
            </div>
          ))}
        </Card>
      )}
    </section>
  );
}

const STATUS_OPTIONS = [
  { value: 'sold', label: 'Sold' },
  { value: 'converted', label: 'Converted to personal use' },
  { value: 'active', label: 'Still a rental (return omitted it)' },
];

function FindingCard({ f, busy, onResolve, onDismiss, onOpenSource }: { f: Finding; busy: boolean; onResolve: (value: unknown, note: string) => void; onDismiss: (note: string) => void; onOpenSource: (c: FindingCandidate) => void }) {
  const [note, setNote] = useState('');
  const isStatus = f.field === 'property.status' || f.kind === 'missing';
  const hasValues = f.candidates.some((c) => c.value !== null && c.value !== undefined);
  return (
    <article className={`card border-l-4 ${f.severity === 'block' ? 'border-l-blk-600' : f.severity === 'warn' ? 'border-l-est-600' : 'border-l-ink-300'}`} data-testid="finding" data-severity={f.severity}>
      <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
        <SeverityTag severity={f.severity} />
        <span className="text-xs font-medium text-ink-500">{titleCase(f.kind)}</span>
        <span className="font-mono text-[11px] break-all text-ink-500">{f.field}</span>
      </div>
      <p className="px-4 pt-1.5 text-sm leading-relaxed text-ink-900">{f.message}</p>
      {f.candidates.length > 0 && (
        <div className="grid gap-2 px-4 py-3 sm:grid-cols-2 xl:grid-cols-3">
          {f.candidates.map((c, i) => (
            <div key={i} className="flex flex-col rounded-md bg-surface-2 px-3 py-2 ring-1 ring-ink-100">
              <div className="text-[11px] text-ink-500">{c.source}</div>
              <div className="num mt-0.5 text-base font-medium text-ink-950">{fmtValue(c.value)}</div>
              <div className="mt-2 flex items-center gap-2">
                {c.document_id && (
                  <button type="button" className="cursor-pointer text-xs font-medium text-brand-600 hover:underline" onClick={() => onOpenSource(c)}>
                    View page {c.page ?? 1}
                  </button>
                )}
                {!isStatus && c.value !== null && c.value !== undefined && (
                  <button type="button" disabled={busy} className="btn btn-sm ml-auto" data-testid="use-value" onClick={() => onResolve(c.value, note || `Chose ${c.source}`)}>
                    Use this value
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 border-t border-ink-100 px-4 py-2.5">
        {isStatus &&
          STATUS_OPTIONS.map((o) => (
            <button key={o.value} type="button" disabled={busy} className="btn btn-sm" data-testid={`status-${o.value}`} onClick={() => onResolve(o.value, note || o.label)}>
              {o.label}
            </button>
          ))}
        {!isStatus && !hasValues && (
          <button type="button" disabled={busy} className="btn btn-sm" data-testid="acknowledge" onClick={() => onResolve(null, note || 'Acknowledged')}>
            Acknowledge
          </button>
        )}
        <label className="min-w-[180px] flex-1">
          <span className="sr-only">Note for the audit trail</span>
          <input className="input h-9 text-xs sm:h-8" placeholder="Note for the audit trail" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <button type="button" disabled={busy} className="btn btn-sm btn-ghost text-ink-500" data-testid="dismiss" onClick={() => onDismiss(note)}>
          Dismiss
        </button>
      </div>
    </article>
  );
}
