import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useDismissFinding, useDocument, useDocuments, useFindings, useResolveFinding, useUpload } from '../api/hooks';
import type { Document, ExtractedField, Finding, FindingCandidate } from '../api/types';
import { HouseholdNav } from '../components/Layout';
import { PdfPage } from '../components/PdfPage';
import { fileStore } from '../components/fileStore';
import { Card, ErrorBox, Loading, PageHeader, SeverityTag } from '../components/ui';
import { DOC_KIND_LABEL, formatDateTime, titleCase } from '../lib/format';
import { formatCents, formatRate } from '../lib/money';

function fmtFieldValue(f: { value: unknown; unit?: string }): string {
  const v = f.value;
  if (typeof v === 'number') {
    if (f.unit === 'cents') return formatCents(v, { exact: true });
    if (f.unit === 'rate') return formatRate(v, 3);
    return v.toLocaleString('en-US');
  }
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  return v === null || v === undefined ? '—' : String(v);
}

export function DocumentsPage() {
  const { id = '' } = useParams();
  const [sp, setSp] = useSearchParams();
  const docs = useDocuments(id);
  const selected = sp.get('doc');
  const page = Number(sp.get('page') ?? '1') || 1;
  const select = (docId: string, pg = 1) => setSp({ doc: docId, page: String(pg) }, { replace: true });

  useEffect(() => {
    if (!selected && docs.data?.length) select(docs.data[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docs.data, selected]);

  useEffect(() => {
    if (window.location.hash === '#queue') document.getElementById('queue')?.scrollIntoView({ block: 'start' });
  }, [docs.data]);

  return (
    <div>
      <PageHeader eyebrow="Household" title="Documents & reconciliation">
        Files are processed in memory and dropped; only the sha256 and the extracted fields persist. Page images below come from the copy in this browser tab.
      </PageHeader>
      <HouseholdNav id={id} />
      <UploadZone householdId={id} onUploaded={(d) => select(d.id)} />
      {docs.isLoading && <Loading />}
      {!!docs.error && <ErrorBox error={docs.error} />}
      {docs.data && (
        <div className="mt-5 grid gap-5 lg:grid-cols-[280px_1fr]">
          <DocList docs={docs.data} selected={selected} onSelect={select} />
          {selected ? <DocViewer documentId={selected} page={page} onPage={(p) => select(selected, p)} /> : <div />}
        </div>
      )}
      <ReconciliationQueue householdId={id} onOpenSource={(c) => c.document_id && select(c.document_id, c.page ?? 1)} />
    </div>
  );
}

function UploadZone({ householdId, onUploaded }: { householdId: string; onUploaded: (d: Document) => void }) {
  const upload = useUpload(householdId);
  const [drag, setDrag] = useState(false);
  const [log, setLog] = useState<{ name: string; state: 'uploading' | 'done' | 'error'; msg?: string }[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const handle = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
        setLog((l) => [{ name: file.name, state: 'error', msg: 'not a PDF' }, ...l]);
        continue;
      }
      setLog((l) => [{ name: file.name, state: 'uploading' }, ...l]);
      try {
        const res = await upload.mutateAsync(file);
        fileStore.put(res.document.id, file); // keep the buffer client-side only, for pdf.js
        setLog((l) => l.map((x) => (x.name === file.name && x.state === 'uploading' ? { ...x, state: 'done', msg: `${res.extracted_fields.length} fields · ${res.findings.length} findings` } : x)));
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
        handle(e.dataTransfer.files);
      }}
      className={`flex flex-col gap-3 rounded-md border-2 border-dashed px-4 py-4 transition-colors sm:flex-row sm:items-center ${drag ? 'border-brand-500 bg-brand-50' : 'border-ink-200 bg-white'}`}
    >
      <div className="flex-1">
        <div className="text-sm font-semibold text-ink-950">Drop PDFs here</div>
        <div className="text-xs text-ink-500">Form 1040, Schedule E, 4562, 8582, mortgage statements, closing statements, appraisals. Text-layer or scanned.</div>
      </div>
      <input ref={input} type="file" accept="application/pdf,.pdf" multiple className="hidden" onChange={(e) => e.target.files && handle(e.target.files)} />
      <button type="button" className="btn" onClick={() => input.current?.click()}>
        Choose files
      </button>
      {log.length > 0 && (
        <ul className="max-h-20 min-w-[240px] overflow-y-auto text-xs sm:max-w-[360px]">
          {log.slice(0, 6).map((l, i) => (
            <li key={i} className="flex justify-between gap-2">
              <span className="truncate">{l.name}</span>
              <span className={l.state === 'error' ? 'text-neg-600' : l.state === 'done' ? 'text-pos-600' : 'text-ink-500'}>{l.state === 'uploading' ? 'extracting…' : l.msg}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DocList({ docs, selected, onSelect }: { docs: Document[]; selected: string | null; onSelect: (id: string) => void }) {
  const groups = useMemo(() => {
    const m = new Map<string, Document[]>();
    for (const d of docs) {
      const k = d.tax_year ? `Tax year ${d.tax_year}` : 'Statements & other';
      m.set(k, [...(m.get(k) ?? []), d]);
    }
    return [...m.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [docs]);
  return (
    <nav className="card max-h-[720px] overflow-y-auto" aria-label="Documents">
      {groups.map(([g, ds]) => (
        <div key={g}>
          <div className="label sticky top-0 border-b border-ink-100 bg-ink-50 px-3 py-1.5">{g}</div>
          {ds.map((d) => (
            <button key={d.id} type="button" onClick={() => onSelect(d.id)} className={`block w-full border-b border-ink-100 px-3 py-2 text-left ${selected === d.id ? 'bg-brand-50' : 'hover:bg-ink-50'}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-ink-950">{DOC_KIND_LABEL[d.kind]}</span>
                <span className="text-[10.5px] uppercase tracking-wide text-ink-500">{d.status}</span>
              </div>
              <div className="truncate text-[11px] text-ink-500">{d.filename}</div>
              {fileStore.has(d.id) && <div className="text-[10.5px] text-pos-600">page images available in this tab</div>}
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}

function DocViewer({ documentId, page, onPage }: { documentId: string; page: number; onPage: (p: number) => void }) {
  const { data, isLoading, error } = useDocument(documentId);
  const [hl, setHl] = useState<string | null>(null);
  const rowRefs = useRef(new Map<string, HTMLTableRowElement>());
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? 'not found'} />;
  const d = data.document;
  const pageFields = data.fields.filter((f) => f.page === page);
  const pick = (f: ExtractedField) => {
    setHl(f.id);
    rowRefs.current.get(f.id)?.scrollIntoView({ block: 'nearest' });
  };
  return (
    <div className="card min-w-0">
      <div className="card-head flex-wrap">
        <div className="min-w-0">
          <h2 className="truncate">{d.filename}</h2>
          <div className="font-mono text-[10.5px] text-ink-400" title="sha256">
            sha256 {d.sha256.slice(0, 16)}… · {d.page_count} pages · uploaded {formatDateTime(d.uploaded_at)} · bytes retained: {String(d.bytes_retained)}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button type="button" className="btn btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            ‹
          </button>
          <span className="num px-1 text-xs">
            {page} / {d.page_count}
          </span>
          <button type="button" className="btn btn-sm" disabled={page >= d.page_count} onClick={() => onPage(page + 1)}>
            ›
          </button>
        </div>
      </div>
      <div className="grid gap-4 p-4 xl:grid-cols-[auto_1fr]">
        <div className="mx-auto max-w-full overflow-x-auto">
          <PdfPage documentId={d.id} page={page} fields={data.fields} highlight={hl} onPick={pick} width={Math.min(420, typeof window !== 'undefined' ? window.innerWidth - 64 : 420)} />
          <div className="mt-1 flex gap-1 overflow-x-auto">
            {Array.from({ length: d.page_count }, (_, i) => i + 1).map((p) => (
              <button key={p} type="button" onClick={() => onPage(p)} className={`num h-6 min-w-6 rounded px-1.5 text-[11px] ${p === page ? 'bg-ink-900 text-white' : 'bg-ink-100 text-ink-700'}`}>
                {p}
              </button>
            ))}
          </div>
        </div>
        <div className="min-w-0 overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Field</th>
                <th className="r">Value</th>
                <th className="r">Conf.</th>
                <th>Via</th>
              </tr>
            </thead>
            <tbody>
              {pageFields.length === 0 && (
                <tr>
                  <td colSpan={4} className="text-xs text-ink-500">
                    No fields extracted on this page.
                  </td>
                </tr>
              )}
              {pageFields.map((f) => (
                <tr
                  key={f.id}
                  ref={(el) => {
                    if (el) rowRefs.current.set(f.id, el);
                  }}
                  onMouseEnter={() => setHl(f.id)}
                  className={hl === f.id ? 'bg-brand-50' : ''}
                >
                  <td>
                    <div className="font-mono text-[11.5px] text-ink-900">{f.field}</div>
                    {f.property_key && <div className="truncate text-[10.5px] text-ink-400">{f.property_key}</div>}
                  </td>
                  <td className="r num text-[12.5px]">{fmtFieldValue(f)}</td>
                  <td className={`r num text-[12px] ${f.confidence < 0.9 ? 'text-est-600' : 'text-ink-700'}`}>{Math.round(f.confidence * 100)}%</td>
                  <td className="text-[11px] uppercase text-ink-500">{f.extractor}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: 'sold', label: 'Sold in 2025' },
  { value: 'converted', label: 'Converted to personal use' },
  { value: 'active', label: 'Still a rental (return omitted it)' },
];

function ReconciliationQueue({ householdId, onOpenSource }: { householdId: string; onOpenSource: (c: FindingCandidate) => void }) {
  const { data, isLoading } = useFindings(householdId);
  const open = data?.filter((f) => f.status === 'open') ?? [];
  const closed = data?.filter((f) => f.status !== 'open') ?? [];
  return (
    <section id="queue" className="mt-8 scroll-mt-16">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg">Reconciliation queue</h2>
        <span className="text-xs text-ink-500">
          {open.length} open · {closed.length} closed · blocked figures stay blocked until their finding is resolved; sources are never averaged
        </span>
      </div>
      {isLoading && <Loading />}
      <div className="space-y-3">
        {open.map((f) => (
          <FindingCard key={f.id} f={f} onOpenSource={onOpenSource} />
        ))}
        {open.length === 0 && !isLoading && <div className="card card-body text-sm text-ink-500">Nothing open. Every figure is running on resolved values.</div>}
      </div>
      {closed.length > 0 && (
        <Card title="Closed" className="mt-4" bodyClass="divide-y divide-ink-100">
          {closed.map((f) => (
            <div key={f.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2 text-xs">
              <span className="font-semibold uppercase text-ink-500">{f.status}</span>
              <span className="font-mono text-ink-700">{f.field}</span>
              <span className="text-ink-900">
                {f.resolution?.value !== null && f.resolution?.value !== undefined ? `→ ${typeof f.resolution.value === 'number' ? formatCents(f.resolution.value) : String(f.resolution.value)}` : ''}
              </span>
              <span className="text-ink-500">
                {f.resolution?.who} · {formatDateTime(f.resolution?.when)} {f.resolution?.note ? `· ${f.resolution.note}` : ''}
              </span>
            </div>
          ))}
        </Card>
      )}
    </section>
  );
}

function FindingCard({ f, onOpenSource }: { f: Finding; onOpenSource: (c: FindingCandidate) => void }) {
  const resolve = useResolveFinding();
  const dismiss = useDismissFinding();
  const [note, setNote] = useState('');
  const busy = resolve.isPending || dismiss.isPending;
  const isStatus = f.field === 'property.status';
  const valueCandidates = f.candidates.filter((c) => typeof c.value === 'number');
  return (
    <article className={`card border-l-4 ${f.severity === 'block' ? 'border-l-blk-600' : f.severity === 'warn' ? 'border-l-est-600' : 'border-l-ink-300'}`} data-testid="finding">
      <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
        <SeverityTag severity={f.severity} />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">{titleCase(f.kind)}</span>
        <span className="font-mono text-[11px] text-ink-500">{f.field}</span>
      </div>
      <p className="px-4 pt-1.5 text-sm text-ink-900">{f.message}</p>
      <div className="grid gap-2 px-4 py-3 sm:grid-cols-2 xl:grid-cols-3">
        {f.candidates.map((c, i) => (
          <div key={i} className="flex flex-col rounded border border-ink-200 bg-ink-50/60 px-3 py-2">
            <div className="text-[11px] text-ink-500">{c.source}</div>
            <div className="num mt-0.5 text-base font-semibold text-ink-950">{typeof c.value === 'number' ? formatCents(c.value) : String(c.value)}</div>
            <div className="mt-2 flex items-center gap-2">
              {c.document_id && (
                <button type="button" className="text-xs font-medium text-brand-600 hover:underline" onClick={() => onOpenSource(c)}>
                  View p{c.page ?? 1}
                </button>
              )}
              {typeof c.value === 'number' && (
                <button type="button" disabled={busy} className="btn btn-sm ml-auto" onClick={() => resolve.mutate({ id: f.id, value: c.value, note: note || `chose ${c.source}` })}>
                  Use this value
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-ink-100 px-4 py-2.5">
        {isStatus &&
          STATUS_OPTIONS.map((o) => (
            <button key={o.value} type="button" disabled={busy} className="btn btn-sm" onClick={() => resolve.mutate({ id: f.id, value: o.value, note: note || o.label })}>
              {o.label}
            </button>
          ))}
        {!isStatus && valueCandidates.length === 0 && (
          <button type="button" disabled={busy} className="btn btn-sm" onClick={() => resolve.mutate({ id: f.id, value: null, note: note || 'acknowledged' })}>
            Acknowledge
          </button>
        )}
        <input className="input h-7 max-w-xs flex-1 text-xs" placeholder="Note for the audit trail" value={note} onChange={(e) => setNote(e.target.value)} />
        <button type="button" disabled={busy} className="btn btn-sm ml-auto text-ink-500" onClick={() => dismiss.mutate({ id: f.id, note })}>
          Dismiss
        </button>
      </div>
    </article>
  );
}
