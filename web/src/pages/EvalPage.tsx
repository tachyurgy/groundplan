import { useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useEval } from '../api/hooks';
import { ChartTooltip, SERIES, axisProps, gridProps } from '../components/charts';
import { Card, Loading, PageHeader } from '../components/ui';
import { DOC_KIND_LABEL, formatDateTime } from '../lib/format';

const p = (x: number) => `${(x * 100).toFixed(1)}%`;

function scoreClass(x: number) {
  if (x >= 0.97) return 'text-ink-950';
  if (x >= 0.9) return 'text-est-600';
  return 'text-neg-600 font-semibold';
}

export function EvalPage() {
  const { data, isLoading, error } = useEval();
  const [filter, setFilter] = useState('');
  const perForm = useMemo(() => {
    if (!data) return [];
    const forms = [...new Set(data.per_form.map((r) => r.form))];
    return forms.map((form) => {
      const t = data.per_form.find((r) => r.form === form && r.variant === 'text');
      const s = data.per_form.find((r) => r.form === form && r.variant === 'scan');
      return { form, label: DOC_KIND_LABEL[form] ?? form, t, s, text_em: t?.exact_match ?? 0, scan_em: s?.exact_match ?? 0 };
    });
  }, [data]);
  const perField = useMemo(() => {
    if (!data) return [];
    const keys = [...new Set(data.per_field.map((r) => `${r.form}|${r.field}`))];
    return keys
      .map((k) => {
        const [form, field] = k.split('|');
        const t = data.per_field.find((r) => r.form === form && r.field === field && r.variant === 'text');
        const s = data.per_field.find((r) => r.form === form && r.field === field && r.variant === 'scan');
        return { form, field, t, s };
      })
      .filter((r) => !filter || `${r.form}.${r.field}`.includes(filter.toLowerCase()));
  }, [data, filter]);
  if (isLoading) return <Loading />;
  if (error || !data)
    return (
      <div>
        <PageHeader eyebrow="Document pipeline" title="Pipeline eval" />
        <div className="card card-body text-sm text-ink-700">
          No eval summary yet. Run <code className="rounded bg-ink-100 px-1 font-mono text-xs">python -m gp_pipeline.eval --docs fixtures/documents --out fixtures/documents/eval-latest.json</code>; the API serves it at <code className="font-mono text-xs">/api/v1/eval/latest</code>.
        </div>
      </div>
    );
  return (
    <div>
      <PageHeader eyebrow="Document pipeline" title="Pipeline eval">
        {data.docs_dir} · generated {formatDateTime(data.generated_at)} · {data.noise ? `noise: ${data.noise.dpi} dpi, ${data.noise.rotation_deg}° rotation, JPEG q${data.noise.jpeg_q}` : 'standard variants (text layer vs 150 dpi scan)'}
      </PageHeader>
      <div className="mb-5 grid gap-px overflow-hidden rounded-md bg-ink-200 shadow-card sm:grid-cols-2 xl:grid-cols-4">
        {data.overall.map((o) => (
          <div key={o.variant} className="bg-white px-4 py-3">
            <div className="label">{o.variant === 'text' ? 'Text layer' : 'Scanned (OCR)'} · n={o.n}</div>
            <div className="mt-1 flex items-baseline gap-4">
              <span className="num text-xl font-semibold">{p(o.exact_match)}</span>
              <span className="text-xs text-ink-500">exact match</span>
            </div>
            <div className="num mt-0.5 text-xs text-ink-700">
              P {p(o.precision)} · R {p(o.recall)}
            </div>
          </div>
        ))}
        <div className="bg-white px-4 py-3">
          <div className="label">Entity resolution · n={data.entity_resolution.n}</div>
          <div className="num mt-1 text-xl font-semibold">{p(data.entity_resolution.accuracy)}</div>
          <div className="text-xs text-ink-500">properties matched across years</div>
        </div>
        <div className="bg-white px-4 py-3">
          <div className="label">Planted findings raised</div>
          <div className="num mt-1 text-xl font-semibold">
            {data.finding_recall.raised} / {data.finding_recall.planted}
          </div>
          <div className="text-xs text-ink-500">{data.finding_recall.missed.length ? `missed: ${data.finding_recall.missed.join(', ')}` : 'none missed'}</div>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Per form: text vs scan" bodyClass="">
          <div className="h-56 px-2 pt-3">
            <ResponsiveContainer>
              <BarChart data={perForm} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="label" {...axisProps} tick={{ ...axisProps.tick, fontSize: 9.5 }} interval={0} />
                <YAxis domain={[0.6, 1]} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} {...axisProps} width={40} />
                <Tooltip content={<ChartTooltip fmt={p} />} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="text_em" name="Text exact match" fill={SERIES.hold} />
                <Bar dataKey="scan_em" name="Scan exact match" fill={SERIES.sell} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Form</th>
                  <th className="r">n</th>
                  <th className="r">Text P / R / EM</th>
                  <th className="r">Scan P / R / EM</th>
                  <th className="r">Δ EM</th>
                </tr>
              </thead>
              <tbody>
                {perForm.map((r) => (
                  <tr key={r.form}>
                    <td>{r.label}</td>
                    <td className="r num">{r.t?.n}</td>
                    <td className="r num text-[12px]">{r.t ? `${p(r.t.precision)} / ${p(r.t.recall)} / ${p(r.t.exact_match)}` : '—'}</td>
                    <td className="r num text-[12px]">{r.s ? `${p(r.s.precision)} / ${p(r.s.recall)} / ${p(r.s.exact_match)}` : '—'}</td>
                    <td className="r num text-[12px] text-neg-600">{r.t && r.s ? `${((r.s.exact_match - r.t.exact_match) * 100).toFixed(1)}` : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Document classification confusion" bodyClass="card-body overflow-x-auto">
          <table className="text-[11px]">
            <thead>
              <tr>
                <th className="label px-1 py-1 text-left">gold ↓ / predicted →</th>
                {data.confusion.labels.map((l) => (
                  <th key={l} className="px-1 py-1 font-mono font-normal text-ink-500" style={{ writingMode: 'vertical-rl' }}>
                    {l}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.confusion.matrix.map((row, i) => {
                const max = Math.max(...data.confusion.matrix.flat(), 1);
                return (
                  <tr key={i}>
                    <td className="whitespace-nowrap px-1 py-0.5 font-mono text-ink-700">{data.confusion.labels[i]}</td>
                    {row.map((v, j) => (
                      <td key={j} className={`num h-7 w-7 text-center ${v === 0 ? 'text-ink-300' : i === j ? 'text-white' : 'font-semibold text-neg-600'}`} style={{ background: v === 0 ? '#f6f7f9' : i === j ? `rgba(22,58,95,${0.35 + 0.65 * (v / max)})` : '#fbe9e7' }}>
                        {v}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {data.entity_resolution.mismatches.length > 0 && (
            <div className="mt-4">
              <div className="label mb-1">Entity-resolution misses</div>
              <ul className="space-y-1 text-xs">
                {data.entity_resolution.mismatches.map((m, i) => (
                  <li key={i}>
                    <span className="font-mono text-ink-700">{m.gold}</span> → <span className="font-mono text-neg-600">{m.predicted}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>

      <Card
        className="mt-5"
        title="Per field"
        actions={<input className="input h-7 w-56 text-xs" placeholder="filter, e.g. schedule_e.line21" value={filter} onChange={(e) => setFilter(e.target.value)} />}
        bodyClass="overflow-x-auto"
      >
        <table className="tbl min-w-[720px]">
          <thead>
            <tr>
              <th>Form</th>
              <th>Field</th>
              <th className="r">n</th>
              <th className="r">Text P</th>
              <th className="r">Text R</th>
              <th className="r">Text EM</th>
              <th className="r">Scan P</th>
              <th className="r">Scan R</th>
              <th className="r">Scan EM</th>
            </tr>
          </thead>
          <tbody>
            {perField.map((r) => (
              <tr key={`${r.form}.${r.field}`}>
                <td className="text-ink-700">{DOC_KIND_LABEL[r.form] ?? r.form}</td>
                <td className="font-mono text-[11.5px]">{r.field}</td>
                <td className="r num">{r.t?.n ?? r.s?.n}</td>
                {[r.t?.precision, r.t?.recall, r.t?.exact_match, r.s?.precision, r.s?.recall, r.s?.exact_match].map((v, i) => (
                  <td key={i} className={`r num text-[12px] ${v === undefined ? '' : scoreClass(v)}`}>
                    {v === undefined ? '—' : p(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
