import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from 'recharts';
import { useStrategies } from '../api/hooks';
import type { StrategyComparison, StrategyPath, StrategyPathResult } from '../api/types';
import { AssumptionsPanel, type AssumptionField, type AssumptionValues } from '../components/AssumptionsPanel';
import { FigureRow } from '../components/FigureValue';
import { StrategyMatrix } from '../components/Matrix';
import { StatusChip } from '../components/StatusChip';
import { TraceScope } from '../lib/traceContext';
import { ChartTooltip } from '../components/charts';
import { SERIES, axisProps, centsTick, gridProps } from '../lib/chartTheme';
import { Card, ErrorBox, Loading, PageHeader } from '../components/ui';
import { formatCents } from '../lib/money';
import { rollupStatus } from '../lib/status';
import { useDebounced } from '../lib/useDebounced';

const STRATEGY_FIELDS: AssumptionField[] = [
  { key: 'appreciation_rate', label: 'Appreciation', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'rent_growth', label: 'Rent growth', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'expense_growth', label: 'Expense growth', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'reinvest_rate', label: 'Reinvestment return', kind: 'rate', min: -0.1, max: 0.2, hint: 'Applied to sale proceeds and to every path’s reinvested cash flows' },
  { key: 'arm_index', label: 'ARM index after reset', kind: 'rate', min: 0, max: 0.2 },
];

const EXCHANGE_FIELDS: AssumptionField[] = [
  { key: 'replacement_value_cents', label: 'Replacement value', kind: 'cents', min: 0 },
  { key: 'replacement_debt_cents', label: 'Replacement debt', kind: 'cents', min: 0 },
  { key: 'cash_taken_cents', label: 'Cash taken out (boot)', kind: 'cents', min: 0 },
];

const DST_FIELDS: AssumptionField[] = [
  { key: 'dst', label: 'Exchange into a DST', kind: 'bool' },
  { key: 'load_rate', label: 'DST load (fees)', kind: 'rate', min: 0, max: 0.25 },
  { key: 'dst_yield', label: 'DST distribution yield', kind: 'rate', min: 0, max: 0.15 },
];

const PATH_COLOR: Record<StrategyPath, string> = { hold: SERIES.hold, sell: SERIES.sell, exchange: SERIES.exchange };

function defaultsFrom(s: StrategyComparison): AssumptionValues {
  const a = s.assumptions;
  return {
    appreciation_rate: a.appreciation_rate,
    rent_growth: a.rent_growth,
    expense_growth: a.expense_growth,
    reinvest_rate: a.reinvest_rate,
    arm_index: 0.04,
    replacement_value_cents: a.exchange.replacement_value_cents,
    replacement_debt_cents: a.exchange.replacement_debt_cents,
    cash_taken_cents: a.exchange.cash_taken_cents,
    dst: a.exchange.dst,
    load_rate: a.exchange.load_rate,
    dst_yield: a.exchange.dst_yield,
  };
}

export function StrategiesPage() {
  const { id = '' } = useParams();
  return <StrategiesView key={id} id={id} />;
}

function StrategiesView({ id }: { id: string }) {
  const [horizon, setHorizon] = useState(10);
  const [overrides, setOverrides] = useState<AssumptionValues>({});
  const params = useDebounced({ horizon, ...overrides }, 150);
  const q = useStrategies(id, params);
  const [base, setBase] = useState<AssumptionValues | null>(null);
  const s = q.data;
  if (s && !base && Object.keys(overrides).length === 0) setBase(defaultsFrom(s));
  if (q.isLoading) return <Loading />;
  if (q.error || !s) return <ErrorBox error={q.error ?? 'not found'} />;
  const values = { ...(base ?? defaultsFrom(s)), ...overrides };
  const set = (v: AssumptionValues) => setOverrides(Object.fromEntries(Object.entries(v).filter(([k, x]) => base?.[k] !== x)));
  const hold = s.paths.find((p) => p.path === 'hold')!;
  const chartData = hold.series.map((row, i) => {
    const o: Record<string, number> = { year: row.year };
    for (const p of s.paths) {
      o[`${p.path}_wealth`] = p.series[i]?.wealth_cents ?? 0;
      o[`${p.path}_deferred`] = p.series[i]?.cumulative_tax_deferred_cents ?? 0;
      o[`${p.path}_cum`] = p.series.slice(0, i + 1).reduce((acc, r) => acc + r.cash_flow_cents, 0);
    }
    return o;
  });
  const exchange = s.paths.find((p) => p.path === 'exchange')!;
  return (
    <TraceScope.Provider value={{ propertyId: id, params }}>
      <PageHeader
        eyebrow={
          <Link to={`/properties/${id}`} className="hover:text-brand-600">
            ← Property analysis
          </Link>
        }
        title="Hold, sell, or exchange"
      >
        Three paths on identical assumptions over the same horizon. One edit updates all three. The page describes trade-offs; it does not pick a path.
      </PageHeader>

      <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
        <div className="space-y-5 lg:sticky lg:top-16 lg:self-start">
          <section className="card">
            <div className="card-head">
              <h2>Horizon</h2>
              <span className="num text-sm font-semibold">{horizon} yrs</span>
            </div>
            <div className="card-body">
              <input aria-label="Horizon" type="range" min={1} max={30} value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} className="w-full accent-brand-600" />
              <div className="flex justify-between text-[11px] text-ink-400">
                <span>1</span>
                <span>30</span>
              </div>
            </div>
          </section>
          <AssumptionsPanel title="Shared assumptions" fields={STRATEGY_FIELDS} values={values} defaults={base ?? undefined} onChange={set} onReset={() => setOverrides({})} busy={q.isFetching} />
          <AssumptionsPanel title="1031 replacement" fields={EXCHANGE_FIELDS} values={values} defaults={base ?? undefined} onChange={set} />
          <AssumptionsPanel title="DST" fields={DST_FIELDS.map((f) => ({ ...f, hidden: f.key !== 'dst' && !values.dst }))} values={values} defaults={base ?? undefined} onChange={set} />
        </div>

        <div className="min-w-0 space-y-5">
          <div className="grid gap-4 md:grid-cols-3">
            {s.paths.map((p) => (
              <PathColumn key={p.path} p={p} />
            ))}
          </div>

          <Card title="Leads / trails / neutral">
            <StrategyMatrix matrix={s.matrix} paths={s.paths} />
          </Card>

          <div className="grid gap-4 xl:grid-cols-3">
            <ChartCard title="After-tax wealth" data={chartData} suffix="wealth" paths={s.paths} />
            <ChartCard title="Cumulative cash flow" data={chartData} suffix="cum" paths={s.paths} />
            <ChartCard title="Deferred tax (growing)" data={chartData} suffix="deferred" paths={s.paths} />
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            {exchange.boot && (
              <Card title="Boot calculator">
                <FigureRow label="Cash boot (cash taken)" figure={exchange.boot.cash_boot} />
                <FigureRow label="Mortgage boot (debt relief not replaced)" figure={exchange.boot.mortgage_boot} />
                <FigureRow label="Total boot" figure={exchange.boot.total_boot} strong />
                <FigureRow label="Gain recognized = min(boot, total gain)" figure={exchange.boot.gain_recognized} />
                <FigureRow label="Tax on boot (same exit-tax stack)" figure={exchange.boot.tax_on_boot} strong />
                <p className="mt-2 text-[11px] text-ink-500">Mortgage boot = max(0, old debt paid off − replacement debt). Raise replacement debt or add cash to bring it to zero.</p>
              </Card>
            )}
            <Card title="What the proceeds do">
              <div className="grid gap-4 sm:grid-cols-2">
                {s.paths
                  .filter((p) => p.proceeds_use)
                  .map((p) => (
                    <div key={p.path}>
                      <h3 className="mb-1">{p.label}</h3>
                      {p.proceeds_use!.map((u, i) => (
                        <FigureRow key={u.label} label={u.label} figure={u.value} signed={u.value.value_cents < 0} strong={i === p.proceeds_use!.length - 1 && p.path === 'sell'} />
                      ))}
                    </div>
                  ))}
              </div>
            </Card>
          </div>
        </div>
      </div>
    </TraceScope.Provider>
  );
}

function PathColumn({ p }: { p: StrategyPathResult }) {
  const t = p.terminal;
  const st = rollupStatus([t.terminal_wealth, t.cumulative_cash_flow, t.tax_paid_now, t.deferred_liability]);
  return (
    <article className="card flex flex-col" data-testid={`path-${p.path}`}>
      <div className="card-head">
        <h2 className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: PATH_COLOR[p.path] }} />
          {p.label}
        </h2>
        <StatusChip status={st} compact />
      </div>
      <div className="card-body">
        <FigureRow label="Terminal wealth" figure={t.terminal_wealth} strong />
        <FigureRow label="Cumulative cash flow" figure={t.cumulative_cash_flow} signed />
        <FigureRow label="Tax paid now" figure={t.tax_paid_now} />
        <FigureRow label="Deferred liability" figure={t.deferred_liability} />
        <FigureRow label="Ending equity" figure={t.ending_equity} />
      </div>
      <div className="mt-auto border-t border-ink-100 px-4 py-3">
        <div className="label mb-1">Caveats</div>
        <ul className="list-disc space-y-1 pl-4 text-xs text-ink-700">
          {p.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </div>
    </article>
  );
}

function ChartCard({ title, data, suffix, paths }: { title: string; data: Record<string, number>[]; suffix: string; paths: StrategyPathResult[] }) {
  return (
    <Card title={title}>
      <div className="h-52">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="year" {...axisProps} />
            <YAxis tickFormatter={centsTick} {...axisProps} width={54} />
            <Tooltip content={<ChartTooltip fmt={(v) => formatCents(v)} />} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <ReferenceLine y={0} stroke="#d6d9e0" />
            {paths.map((p) => (
              <Line key={p.path} type="monotone" dataKey={`${p.path}_${suffix}`} name={p.label} stroke={PATH_COLOR[p.path]} strokeWidth={2} dot={false} strokeDasharray={p.path === 'sell' ? '4 3' : undefined} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
