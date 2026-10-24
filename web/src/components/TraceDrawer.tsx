import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Figure, FigureInput } from '../api/types';
import { useFigure, useDocument } from '../api/hooks';
import { formatCents, formatRate, signClass } from '../lib/money';
import { SOURCE_LABEL } from '../lib/status';
import { StatusChip } from './StatusChip';
import { useTrace } from '../lib/traceContext';
import { PdfPage } from './PdfPage';

const SRC_CLASS: Record<string, string> = {
  document: 'bg-brand-50 text-brand-700 ring-brand-600/20',
  manual: 'bg-ink-100 text-ink-700 ring-ink-500/20',
  public_data: 'bg-est-100 text-est-600 ring-est-600/20',
  default: 'bg-est-100 text-est-600 ring-est-600/20',
};

function fmtValue(i: FigureInput): string {
  const v = i.value;
  if (typeof v === 'number') {
    if (i.unit === 'rate' || (Math.abs(v) < 1 && v !== 0 && !Number.isInteger(v))) return formatRate(v, 3);
    if (i.unit === 'cents' || i.figure) return formatCents(v);
    return v.toLocaleString('en-US');
  }
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (v === null || v === undefined) return '—';
  return String(v);
}

function InputNode({ input, depth, onSource }: { input: FigureInput; depth: number; onSource: (i: FigureInput) => void }) {
  const [open, setOpen] = useState(depth < 1);
  const nested = input.figure;
  return (
    <li className="border-l border-ink-200 pl-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1">
        <div className="flex min-w-0 items-baseline gap-1.5">
          {nested ? (
            <button type="button" onClick={() => setOpen(!open)} className="w-3 shrink-0 text-xs text-ink-400" aria-label={open ? 'collapse' : 'expand'}>
              {open ? '▾' : '▸'}
            </button>
          ) : (
            <span className="w-3 shrink-0" />
          )}
          <span className="truncate text-[13px] text-ink-900" title={input.key}>
            {input.label ?? nested?.label ?? input.key}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {nested ? (
            <StatusChip status={nested.status} compact />
          ) : (
            <button type="button" onClick={() => onSource(input)} className={`rounded px-1.5 py-px text-[10.5px] font-medium ring-1 ring-inset ${SRC_CLASS[input.source.type]}`} title={input.source.ref}>
              {SOURCE_LABEL[input.source.type]}
              {input.source.page ? ` · p${input.source.page}` : ''}
            </button>
          )}
          <span className={`num text-[13px] ${typeof input.value === 'number' && (input.unit === 'cents' || nested) ? signClass(input.value) : 'text-ink-900'}`}>{fmtValue(input)}</span>
        </div>
      </div>
      {!nested && <div className="truncate pb-1 pl-[18px] text-[11px] text-ink-400">{input.source.ref}</div>}
      {nested && open && (
        <div className="pb-1 pl-[18px]">
          <div className="mb-1 font-mono text-[11px] text-ink-500">= {nested.formula}</div>
          <ul>
            {nested.inputs.map((c, i) => (
              <InputNode key={`${c.key}-${i}`} input={c} depth={depth + 1} onSource={onSource} />
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

function SourcePreview({ input, householdId }: { input: FigureInput; householdId?: string }) {
  const docId = input.source.document_id ?? null;
  const { data } = useDocument(docId);
  if (input.source.type !== 'document' || !docId) {
    return (
      <div className="rounded border border-ink-200 bg-ink-50 p-3 text-xs text-ink-700">
        <div className="label mb-1">{SOURCE_LABEL[input.source.type]}</div>
        {input.source.ref}
        {(input.source.type === 'default' || input.source.type === 'public_data') && <p className="mt-1 text-est-600">This input makes the figure Estimated. Replace it with a document or manual entry to confirm.</p>}
      </div>
    );
  }
  const page = input.source.page ?? 1;
  return (
    <div className="rounded border border-ink-200 p-2">
      <div className="mb-2 flex items-center justify-between gap-2 text-xs">
        <span className="truncate font-medium">{data?.document.filename ?? docId}</span>
        <span className="num text-ink-500">page {page}</span>
      </div>
      <PdfPage documentId={docId} page={page} fields={(data?.fields ?? []).filter((f) => f.page === page)} focusBox={input.source.bbox ?? null} width={360} />
      {householdId && (
        <Link to={`/households/${householdId}/documents?doc=${docId}&page=${page}`} className="mt-2 inline-block text-xs font-medium text-brand-600 hover:underline">
          Open in documents →
        </Link>
      )}
    </div>
  );
}

export function TraceDrawer() {
  const { target, close } = useTrace();
  const [source, setSource] = useState<FigureInput | null>(null);
  const remote = useFigure(target?.propertyId ?? null, target?.figure.key ?? null, target?.params ?? {});
  useEffect(() => setSource(null), [target]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [close]);
  if (!target) return null;
  // Prefer the server's full tree when it returns one; fall back to the figure we already hold.
  const f: Figure = remote.data && remote.data.inputs.length >= target.figure.inputs.length ? remote.data : target.figure;
  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Traceability">
      <div className="absolute inset-0 bg-ink-950/20" onClick={close} />
      <aside className="absolute right-0 top-0 flex h-full w-full max-w-[460px] flex-col bg-white shadow-drawer" data-testid="trace-drawer">
        <header className="border-b border-ink-100 px-5 pb-3 pt-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="label">Traceability</div>
              <h2 className="mt-0.5 truncate text-lg">{f.label ?? f.key}</h2>
              <div className="mt-0.5 font-mono text-[11px] text-ink-400">{f.key}</div>
            </div>
            <button type="button" onClick={close} className="btn btn-sm" aria-label="Close">
              Esc
            </button>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <span className={`num text-2xl font-semibold ${signClass(f.value_cents)} ${f.status === 'blocked' ? 'line-through decoration-blk-600' : ''}`}>{formatCents(f.value_cents, { exact: true })}</span>
            <StatusChip status={f.status} />
            {remote.isFetching && <span className="text-[11px] text-ink-400">refreshing…</span>}
          </div>
        </header>
        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <section>
            <div className="label mb-1">Formula</div>
            <pre className="whitespace-pre-wrap rounded bg-ink-50 px-3 py-2 font-mono text-[12px] leading-relaxed text-ink-900 ring-1 ring-ink-100">{f.formula}</pre>
          </section>
          {f.status === 'blocked' && (
            <div className="rounded border border-blk-600/30 bg-blk-100 px-3 py-2 text-xs text-blk-600">
              Blocked: an open blocking finding touches an input. The engine never averages conflicting sources; resolve it in the reconciliation queue.
              {target.householdId && (
                <Link to={`/households/${target.householdId}/documents#queue`} className="ml-1 font-semibold underline">
                  Go to queue
                </Link>
              )}
            </div>
          )}
          <section>
            <div className="label mb-1">Inputs ({f.inputs.length})</div>
            {f.inputs.length === 0 ? (
              <p className="text-xs text-ink-500">No inputs (constant or structural zero).</p>
            ) : (
              <ul className="-ml-3">
                {f.inputs.map((i, idx) => (
                  <InputNode key={`${i.key}-${idx}`} input={i} depth={0} onSource={setSource} />
                ))}
              </ul>
            )}
          </section>
          {source && (
            <section>
              <div className="label mb-1">Source · {source.label ?? source.key}</div>
              <SourcePreview input={source} householdId={target.householdId} />
            </section>
          )}
          {f.notes.length > 0 && (
            <section>
              <div className="label mb-1">Notes</div>
              <ul className="list-disc space-y-1 pl-4 text-xs text-ink-700">
                {f.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}
