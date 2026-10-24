import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { Dialog } from 'radix-ui';
import { useState } from 'react';
import { documentQuery, figureQuery } from '../api/queries';
import type { FigureInputT, FigureT } from '../api/schemas';
import type { BBox } from '../api/types';
import { formatCents, formatRate, signClass } from '../lib/money';
import { useUi } from '../lib/theme';
import { PdfPage } from './PdfPage';
import { StatusChip } from './StatusChip';

const SOURCE_LABEL: Record<string, string> = {
  document: 'Document',
  manual: 'Manual entry',
  public_data: 'Public data',
  default: 'Default',
  figure: 'Computed',
};
const SRC_CLASS: Record<string, string> = {
  document: 'bg-brand-50 text-brand-700 ring-brand-500/30',
  manual: 'bg-ink-100 text-ink-700 ring-ink-300',
  public_data: 'bg-est-100 text-est-600 ring-est-600/30',
  default: 'bg-est-100 text-est-600 ring-est-600/30',
  figure: 'bg-ink-50 text-ink-700 ring-ink-200',
};

function fmtValue(i: FigureInputT): string {
  const v = i.value;
  const n = typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v) ? Number(v) : v;
  if (typeof n === 'number') {
    if (i.unit === 'rate' || (Math.abs(n) < 1 && n !== 0 && !Number.isInteger(n))) return formatRate(n, 3);
    if (i.unit === 'cents' || i.figure || /_cents$|cents$/.test(i.key) || i.source.type === 'figure') return formatCents(n);
    return n.toLocaleString('en-US');
  }
  if (typeof n === 'boolean') return n ? 'yes' : 'no';
  if (n === null || n === undefined) return '—';
  if (typeof n === 'object')
    return Object.entries(n as Record<string, unknown>)
      .map(([k, x]) => `${k}: ${String(x)}`)
      .join(' · ');
  return String(n);
}

function InputNode({ input, depth, onSource }: { input: FigureInputT; depth: number; onSource: (i: FigureInputT) => void }) {
  const [open, setOpen] = useState(depth < 1);
  const nested = input.figure;
  const label = input.label ?? nested?.label ?? input.key;
  return (
    <li className="border-l border-ink-200 pl-3" data-testid="trace-input">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1">
        <div className="flex min-w-0 items-baseline gap-1.5">
          {nested ? (
            <button
              type="button"
              onClick={() => setOpen(!open)}
              className="w-4 shrink-0 cursor-pointer text-xs text-ink-500"
              aria-expanded={open}
              aria-label={`${open ? 'Collapse' : 'Expand'} ${label}`}
            >
              {open ? '▾' : '▸'}
            </button>
          ) : (
            <span className="w-4 shrink-0" />
          )}
          <span className="min-w-0 text-[13px] break-words text-ink-900" title={input.key}>
            {label}
          </span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {nested ? (
            <StatusChip status={nested.status} compact />
          ) : (
            <button
              type="button"
              onClick={() => onSource(input)}
              className={`chip cursor-pointer ${SRC_CLASS[input.source.type] ?? SRC_CLASS.figure}`}
              title={input.source.ref ?? undefined}
            >
              {SOURCE_LABEL[input.source.type] ?? input.source.type}
              {input.source.page ? ` · p${input.source.page}` : ''}
            </button>
          )}
          <span
            className={`num text-[13px] ${typeof input.value === 'number' && (input.unit === 'cents' || nested) ? signClass(input.value) : 'text-ink-900'}`}
          >
            {fmtValue(input)}
          </span>
        </div>
      </div>
      {!nested && input.source.ref && <div className="pb-1 pl-[22px] text-[11px] break-words text-ink-500">{input.source.ref}</div>}
      {nested && open && (
        <div className="pb-1 pl-[22px]">
          <div className="mb-1 font-mono text-[11px] break-words text-ink-500">= {nested.formula}</div>
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

function SourcePreview({ input, householdId }: { input: FigureInputT; householdId?: string }) {
  const docId = input.source.type === 'document' ? (input.source.document_id ?? null) : null;
  const doc = useQuery({ ...documentQuery(docId ?? ''), enabled: !!docId });
  if (!docId) {
    const soft = input.source.type === 'default' || input.source.type === 'public_data';
    return (
      <div className="rounded-md border border-ink-200 bg-surface-2 p-3 text-xs text-ink-700">
        <div className="mb-1 font-medium">{SOURCE_LABEL[input.source.type] ?? input.source.type}</div>
        {input.source.ref ?? input.key}
        {soft && <p className="mt-1 text-est-600">This input makes the figure Estimated. Replace it with a document or a manual entry to confirm it.</p>}
      </div>
    );
  }
  const page = input.source.page ?? 1;
  return (
    <div className="rounded-md border border-ink-200 p-2">
      <div className="mb-2 flex items-center justify-between gap-2 text-xs">
        <span className="truncate font-medium">{doc.data?.document.filename ?? docId}</span>
        <span className="num text-ink-500">page {page}</span>
      </div>
      <PdfPage
        documentId={docId}
        page={page}
        fields={(doc.data?.fields ?? []).filter((f) => f.page === page)}
        focusBox={(input.source.bbox as BBox | null | undefined) ?? null}
        width={340}
      />
      {householdId && (
        <Link
          to="/households/$householdId/documents"
          params={{ householdId }}
          search={{ doc: docId, page }}
          className="mt-2 inline-block text-xs font-medium text-brand-600 hover:underline"
        >
          Open in documents
        </Link>
      )}
    </div>
  );
}

/** Figure → inputs tree → source (document page + bbox, manual entry or default) with the formula. */
export default function TraceDrawer() {
  const target = useUi((s) => s.trace);
  const close = useUi((s) => s.closeTrace);
  const [source, setSource] = useState<{ key: string; input: FigureInputT } | null>(null);
  const remote = useQuery({ ...figureQuery(target?.propertyId ?? '', target?.figure.key ?? '', target?.params ?? {}), enabled: !!target?.propertyId });
  if (!target) return null;
  // Prefer the server's fuller tree when it has one; otherwise show the figure already in hand.
  const f: FigureT =
    remote.data && remote.data.inputs.length >= target.figure.inputs.length && remote.data.value_cents === target.figure.value_cents
      ? remote.data
      : target.figure;
  const shownSource = source && source.key === f.key ? source.input : null;
  return (
    <Dialog.Root open onOpenChange={(o) => !o && close()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/25" />
        <Dialog.Content
          data-testid="trace-drawer"
          onCloseAutoFocus={(e) => e.preventDefault()}
          className="fixed inset-x-0 bottom-0 z-50 flex max-h-[88dvh] flex-col rounded-t-xl bg-surface shadow-pop outline-none sm:inset-y-0 sm:right-0 sm:left-auto sm:max-h-none sm:w-[440px] sm:rounded-none"
        >
          <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-ink-200 sm:hidden" aria-hidden />
          <header className="border-b border-ink-100 px-5 pt-3 pb-3 sm:pt-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <Dialog.Description className="text-xs text-ink-500">How this number is calculated</Dialog.Description>
                <Dialog.Title className="mt-0.5 text-lg font-semibold break-words text-ink-950">{f.label ?? f.key}</Dialog.Title>
                <div className="mt-0.5 font-mono text-[11px] break-all text-ink-500">{f.key}</div>
              </div>
              <Dialog.Close asChild>
                <button type="button" className="btn btn-sm shrink-0" aria-label="Close">
                  Close
                </button>
              </Dialog.Close>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <span
                data-testid="trace-value"
                className={`num text-2xl font-medium ${signClass(f.value_cents)} ${f.status === 'blocked' ? 'line-through decoration-blk-600' : ''}`}
              >
                {f.unit === 'ratio' ? (f.ratio ?? f.value_cents / 100).toFixed(2) : formatCents(f.value_cents, { exact: true })}
              </span>
              <StatusChip status={f.status} />
              {remote.isFetching && <span className="text-[11px] text-ink-500">loading full tree…</span>}
            </div>
          </header>
          <div className="flex-1 space-y-5 overflow-y-auto overscroll-contain px-5 py-4">
            <section>
              <h3 className="mb-1 text-xs font-medium text-ink-500">Formula</h3>
              <pre
                data-testid="trace-formula"
                className="rounded-md bg-surface-2 px-3 py-2 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-ink-900 ring-1 ring-ink-100"
              >
                {f.formula || '—'}
              </pre>
            </section>
            {f.status === 'blocked' && (
              <div className="rounded-md border border-blk-600/30 bg-blk-100 px-3 py-2 text-xs text-blk-600">
                Blocked: an open blocking finding touches an input. The engine never averages conflicting sources; resolve it in the reconciliation queue.
                {target.householdId && (
                  <Link
                    to="/households/$householdId/documents"
                    params={{ householdId: target.householdId }}
                    hash="queue"
                    className="ml-1 font-semibold underline"
                    onClick={close}
                  >
                    Go to the queue
                  </Link>
                )}
              </div>
            )}
            <section>
              <h3 className="mb-1 text-xs font-medium text-ink-500">Inputs ({f.inputs.length})</h3>
              {f.inputs.length === 0 ? (
                <p className="text-xs text-ink-500">No inputs: a constant or a structural zero.</p>
              ) : (
                <ul className="-ml-3">
                  {f.inputs.map((i, idx) => (
                    <InputNode key={`${i.key}-${idx}`} input={i} depth={0} onSource={(input) => setSource({ key: f.key, input })} />
                  ))}
                </ul>
              )}
            </section>
            {shownSource && (
              <section>
                <h3 className="mb-1 text-xs font-medium text-ink-500">Source: {shownSource.label ?? shownSource.key}</h3>
                <SourcePreview input={shownSource} householdId={target.householdId} />
              </section>
            )}
            {f.notes.length > 0 && (
              <section>
                <h3 className="mb-1 text-xs font-medium text-ink-500">Notes</h3>
                <ul className="list-disc space-y-1 pl-4 text-xs leading-relaxed text-ink-700">
                  {f.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
