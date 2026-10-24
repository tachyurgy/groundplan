import { useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { getRouteApi } from '@tanstack/react-router';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
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

type LogRow = { name: string; state: 'uploading' | 'done' | 'error'; msg?: string };

function UploadZone({ householdId, onUploaded }: { householdId: string; onUploaded: (d: Document) => void }) {
  const upload = useUpload(householdId);
  const [drag, setDrag] = useState(false);
  const [log, setLog] = useState<LogRow[]>([]);
  const handle = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
        setLog((l) => [{ name: file.name, state: 'error', msg: 'Only PDF files can be read' }, ...l]);
        continue;
      }
      if (file.size > 15 * 1024 * 1024) {
        setLog((l) => [{ name: file.name, state: 'error', msg: 'Larger than the 15 MB limit' }, ...l]);
        continue;
      }
      setLog((l) => [{ name: file.name, state: 'uploading' }, ...l]);
      try {
        const res = await upload.mutateAsync(file);
        fileStore.put(res.document.id, file); // keep the bytes in this tab only, for pdf.js
        setLog((l) => l.map((x) => (x.name === file.name && x.state === 'uploading' ? { ...x, state: 'done', msg: `${res.extracted_fields.length} fields, ${res.findings.length} findings` } : x)));
        onUploaded(res.document);
      } catch (e) {
        setLog((l) => l.map((x) => (x.name === file.name && x.state === 'uploading' ? { ...x, state: 'error', msg: e instanceof Error ? e.message : String(e) } : x)));
      }
    }
  };
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
      className={`flex flex-col gap-3 rounded-lg border-2 border-dashed px-4 py-4 transition-colors sm:flex-row sm:items-center ${drag ? 'border-brand-500 bg-brand-50' : 'border-ink-200 bg-surface'}`}
    >
      <div className="flex-1">
        <div className="text-sm font-semibold text-ink-950">Drop PDFs here</div>
        <div className="text-xs leading-relaxed text-ink-500">Form 1040, Schedule E, Form 4562, Form 8582, mortgage statements, closing statements, appraisals. Text-layer or scanned, up to 15 MB each.</div>
      </div>
      <label className="btn cursor-pointer">
        Choose files
        <input type="file" accept="application/pdf,.pdf" multiple className="sr-only" data-testid="file-input" onChange={(e) => e.target.files && void handle(e.target.files)} />
      </label>
      {log.length > 0 && (
        <ul className="max-h-24 min-w-0 overflow-y-auto text-xs sm:w-[340px]" aria-live="polite" data-testid="upload-log">
          {log.slice(0, 6).map((l, i) => (
            <li key={i} className="flex justify-between gap-3 py-0.5">
              <span className="truncate">{l.name}</span>
              <span className={`shrink-0 ${l.state === 'error' ? 'text-neg-600' : l.state === 'done' ? 'text-pos-600' : 'text-ink-500'}`}>{l.state === 'uploading' ? 'extracting…' : l.msg}</span>
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
