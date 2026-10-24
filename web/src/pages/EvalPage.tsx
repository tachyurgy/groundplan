import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { evalQuery } from '../api/queries';
import { C, ChartFrame, TooltipBody, useNarrow } from '../charts/kit';
import { Card, PageHeader } from '../components/ui';
import { VirtualTable } from '../components/VirtualTable';
import { DOC_KIND_LABEL, formatDateTime } from '../lib/format';

/** Shape of fixtures/documents/eval-latest.json written by `python -m gp_pipeline.eval` (read defensively). */
interface Prf {
  gold: number;
  extracted: number;
  correct: number;
  precision: number | null;
  recall: number | null;
}
interface Variant {
  variant: string;
  seconds?: number;
  documents: number;
  overall: Prf & { doc_exact_match: number };
  classification: { kind_accuracy: number; tax_year_accuracy: number; confusion: { gold: string; predicted: string; count: number }[] };
  per_form: Record<string, Prf>;
  per_field: Record<string, Prf>;
  entity_resolution: { mentions: number; correct: number; accuracy: number | null; gold_properties: number; resolved_properties: number };
  findings: { planted: number; found: number; recall: number | null; rows: { id: string; kind: string; found: boolean }[]; unplanted_non_info?: number };
  errors_sample?: { file: string; field: string; gold: unknown; got: unknown }[];
  params?: Record<string, unknown>;
}
interface EvalFile {
  generated_at: string;
  pipeline_version?: string;
  variants: Record<string, Variant>;
}

const pct = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? '—' : `${(x * 100).toFixed(d)}%`);
const VLABEL: Record<string, string> = { text: 'Text layer', scan: 'Scan (150 dpi, OCR)', noise: 'Heavy noise (100 dpi, 2°, JPEG 35)' };
const VCOLOR: Record<string, string> = { text: C.s1, scan: C.s2, noise: C.s3 };

function scoreCls(x: number | null | undefined) {
  if (x === null || x === undefined) return 'text-ink-500';
  if (x >= 0.97) return 'text-ink-950';
  if (x >= 0.9) return 'text-est-600';
  return 'font-semibold text-neg-600';
}

export function EvalPage() {
  const q = useQuery(evalQuery());
  const narrow = useNarrow();
  const [filter, setFilter] = useState('');
  const data = q.data as unknown as EvalFile | undefined;
  if (q.isPending) return <div className="skeleton h-[480px] rounded-lg" />;
  if (q.error || !data?.variants)
    return (
      <div>
        <PageHeader title="Document pipeline evaluation" />
        <div className="card card-body text-sm leading-relaxed text-ink-700">
          No evaluation has been published by this backend yet{q.error ? ` (${q.error.message})` : ''}. It is produced by{' '}
          <code className="rounded bg-ink-100 px-1 font-mono text-xs">
            python -m gp_pipeline.eval --docs fixtures/documents --out fixtures/documents/eval-latest.json
          </code>{' '}
          and served at <code className="font-mono text-xs">/api/v1/eval/latest</code>.
        </div>
      </div>
    );
  const vs = Object.keys(data.variants);
  const metrics: [string, (v: Variant) => number | null][] = [
    ['Field precision', (v) => v.overall.precision],
    ['Field recall', (v) => v.overall.recall],
    ['Documents fully right', (v) => v.overall.doc_exact_match],
    ['Form classified', (v) => v.classification.kind_accuracy],
    ['Entity resolution', (v) => v.entity_resolution.accuracy],
    ['Planted findings raised', (v) => v.findings.recall],
  ];
  const chartRows = metrics.map(([label, fn]) => ({ label, ...Object.fromEntries(vs.map((v) => [v, fn(data.variants[v]) ?? 0])) }));
  const forms = [...new Set(vs.flatMap((v) => Object.keys(data.variants[v].per_form)))];
  const fields = [...new Set(vs.flatMap((v) => Object.keys(data.variants[v].per_field)))].filter((f) => !filter || f.includes(filter.toLowerCase()));
  const worst = vs[vs.length - 1];
  const confusion = data.variants[worst].classification.confusion;
  const labels = [...new Set(confusion.flatMap((c) => [c.gold, c.predicted]))].sort();
  const max = Math.max(1, ...confusion.map((c) => c.count));
  return (
    <div>
      <PageHeader title="Document pipeline evaluation">
        Synthetic returns and statements with gold labels, extracted three ways: from the PDF text layer, from a 150 dpi scan through OCR, and from a
        deliberately degraded scan. Generated {formatDateTime(data.generated_at)}
        {data.pipeline_version ? `, pipeline ${data.pipeline_version}` : ''}.
      </PageHeader>

      <section aria-label="Summary by variant" className="mb-5 grid gap-px overflow-hidden rounded-lg bg-ink-100 shadow-card md:grid-cols-3">
        {vs.map((v) => {
          const r = data.variants[v];
          return (
            <div key={v} className="bg-surface px-4 py-3" data-testid="eval-variant">
              <div className="flex items-center gap-2">
                <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: VCOLOR[v] ?? C.muted }} />
                <span className="label">{VLABEL[v] ?? v}</span>
              </div>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="num text-2xl font-medium">{pct(r.overall.precision)}</span>
                <span className="text-xs text-ink-500">field precision</span>
              </div>
              <div className="num mt-1 text-xs text-ink-700">
                recall {pct(r.overall.recall)}, {r.documents} documents, findings {r.findings.found}/{r.findings.planted}
              </div>
            </div>
          );
        })}
      </section>

      <Card bodyClass="p-4" className="mb-5">
        <ChartFrame
          testId="chart-eval"
          title="How each measure holds up as the input degrades"
          summary={`Text-layer and 150 dpi scans stay near perfect; the deliberately degraded scan drops field recall to ${pct(data.variants[worst]?.overall.recall, 0)}, which is the case a human review queue exists for.`}
          legend={vs.map((v) => ({ label: VLABEL[v] ?? v, color: VCOLOR[v] ?? C.muted }))}
          height={narrow ? 360 : 300}
          table={{
            columns: [{ key: 'label', label: 'Measure' }, ...vs.map((v) => ({ key: v, label: VLABEL[v] ?? v, align: 'right' as const }))],
            rows: chartRows.map((r) => ({ ...r, ...Object.fromEntries(vs.map((v) => [v, pct((r as Record<string, unknown>)[v] as number)])) })),
          }}
        >
          <ResponsiveContainer>
            <BarChart data={chartRows} layout="vertical" margin={{ top: 0, right: 16, left: 0, bottom: 0 }} barGap={2} barCategoryGap={narrow ? 8 : 12}>
              <CartesianGrid stroke="var(--grid)" horizontal={false} vertical />
              <XAxis
                type="number"
                domain={[0, 1]}
                tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                tick={{ fontSize: 11, fill: 'var(--ink-500)', fontFamily: 'var(--font-mono)' }}
                tickLine={false}
                axisLine={{ stroke: 'var(--axis)' }}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={narrow ? 110 : 170}
                tick={{ fontSize: 12, fill: 'var(--ink-700)' }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip cursor={{ fill: 'var(--ink-50)' }} content={(p) => <TooltipBody {...p} fmt={(v) => pct(v)} />} />
              {vs.map((v) => (
                <Bar key={v} dataKey={v} name={VLABEL[v] ?? v} fill={VCOLOR[v] ?? C.muted} maxBarSize={10} radius={[0, 3, 3, 0]} isAnimationActive={false} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </ChartFrame>
      </Card>

      <div className="mb-5 grid gap-5 xl:grid-cols-2">
        <Card title="Per form" sub="precision / recall" bodyClass="overflow-x-auto">
          <table className="tbl min-w-[460px]" data-testid="eval-forms">
            <thead>
              <tr>
                <th>Form</th>
                <th className="r">Fields</th>
                {vs.map((v) => (
                  <th key={v} className="r">
                    {v}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {forms.map((f) => (
                <tr key={f}>
                  <td>{DOC_KIND_LABEL[f] ?? f}</td>
                  <td className="r num">{data.variants[vs[0]].per_form[f]?.gold ?? '—'}</td>
                  {vs.map((v) => {
                    const r = data.variants[v].per_form[f];
                    return (
                      <td key={v} className={`r num text-[12px] ${scoreCls(r?.recall)}`}>
                        {r ? `${pct(r.precision, 0)} / ${pct(r.recall, 0)}` : '—'}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="Planted findings" sub="The problems seeded into the synthetic household, and whether each variant caught them">
          <ul className="divide-y divide-ink-100 text-sm">
            {data.variants[vs[0]].findings.rows.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="min-w-0">
                  <span className="font-mono text-[12px] break-all text-ink-900">{row.id}</span> <span className="text-xs text-ink-500">{row.kind}</span>
                </span>
                <span className="flex gap-1.5">
                  {vs.map((v) => {
                    const found = data.variants[v].findings.rows.find((r) => r.id === row.id)?.found;
                    return (
                      <span
                        key={v}
                        className={`chip ${found ? 'bg-pos-100 text-pos-600 ring-pos-600/25' : 'bg-neg-100 text-neg-600 ring-neg-600/25'}`}
                        title={VLABEL[v]}
                      >
                        {found ? '✓' : '✗'} {v}
                      </span>
                    );
                  })}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="mb-5 grid gap-5 xl:grid-cols-[1fr_1.2fr]">
        <Card
          title={`Form classification, ${VLABEL[worst] ?? worst}`}
          sub="Rows are the true form; columns what the classifier said. Off-diagonal cells are mistakes."
          bodyClass="card-body overflow-x-auto"
        >
          <table className="text-[11px]" data-testid="confusion">
            <thead>
              <tr>
                <th className="px-1 py-1 text-left font-medium text-ink-500">true ↓ / predicted →</th>
                {labels.map((l) => (
                  <th key={l} className="px-1 py-1 font-mono font-normal text-ink-500" style={{ writingMode: 'vertical-rl' }}>
                    {l}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {labels.map((g) => (
                <tr key={g}>
                  <td className="px-1 py-0.5 font-mono whitespace-nowrap text-ink-700">{g}</td>
                  {labels.map((p) => {
                    const v = confusion.find((c) => c.gold === g && c.predicted === p)?.count ?? 0;
                    const diag = g === p;
                    return (
                      <td
                        key={p}
                        className={`num h-7 w-7 text-center ${v === 0 ? 'text-ink-300' : diag ? 'font-medium text-ink-950' : 'font-semibold text-neg-600'}`}
                        style={{
                          background:
                            v === 0
                              ? 'var(--surface-2)'
                              : diag
                                ? `color-mix(in oklab, var(--series-1) ${Math.round(18 + 50 * (v / max))}%, var(--surface))`
                                : 'var(--neg-100)',
                        }}
                      >
                        {v}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card
          title="Per field"
          actions={
            <input
              className="input h-8 w-44 text-xs sm:w-56"
              aria-label="Filter fields"
              placeholder="Filter, e.g. line21"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          }
        >
          <VirtualTable
            testId="eval-fields"
            label="Per-field recall by variant"
            rows={fields}
            height={380}
            cols={[
              { key: 'f', label: 'Field', width: 'minmax(0,2.2fr)', render: (f) => <span className="font-mono text-[11.5px]">{f}</span> },
              ...vs.map((v) => ({
                key: v,
                label: `${v} recall`,
                right: true,
                render: (f: string) => <span className={scoreCls(data.variants[v].per_field[f]?.recall)}>{pct(data.variants[v].per_field[f]?.recall, 0)}</span>,
              })),
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
