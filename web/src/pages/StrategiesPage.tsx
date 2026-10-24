import { keepPreviousData, useQueries, useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { Link, getRouteApi } from '@tanstack/react-router';
import { startTransition, useActionState, useDeferredValue, useState } from 'react';
import { Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { analysisQuery, strategiesQuery, useSaveScenario, type Params } from '../api/queries';
import type { StrategiesT, StrategyPathT } from '../api/schemas';
import { Heatmap, type HeatCell, type PathId } from '../charts/Heatmap';
import { C, ChartFrame, PATH_COLOR, TooltipBody, centsTick, gridProps, useNarrow, xAxisProps, yAxisProps } from '../charts/kit';
import { AssumptionsForm, type FieldDef, type Values } from '../components/AssumptionsForm';
import { SaleWaterfall } from '../components/ExitTaxViz';
import { FigureRow } from '../components/FigureValue';
import { HorizonSlider } from '../components/HorizonSlider';
import { StatusChip } from '../components/StatusChip';
import { Card, PageHeader, Pulse } from '../components/ui';
import { formatCents, formatRate } from '../lib/money';
import { overridesOnly, type StrategiesSearch } from '../lib/search';
import { rollupStatus } from '../lib/status';
import { TraceScope } from '../lib/traceScope';
import { useDebounced } from '../lib/useDebounced';

const route = getRouteApi('/properties/$propertyId/strategies');
const DEFAULT_HORIZON = 10;

const SHARED: FieldDef[] = [
  { key: 'appreciation_rate', label: 'Appreciation', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'rent_growth', label: 'Rent growth', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'expense_growth', label: 'Expense growth', kind: 'rate', min: -0.2, max: 0.3 },
  {
    key: 'reinvest_rate',
    label: 'Return on reinvested cash',
    kind: 'rate',
    min: -0.1,
    max: 0.2,
    hint: 'Applied to sale proceeds and to every path’s reinvested cash flow',
  },
  { key: 'arm_index', label: 'ARM index after reset', kind: 'rate', min: 0, max: 0.2 },
];
const EXCHANGE: FieldDef[] = [
  { key: 'replacement_value_cents', label: 'Replacement value', kind: 'cents', min: 0, max: 100_000_000_00 },
  { key: 'replacement_debt_cents', label: 'Replacement debt', kind: 'cents', min: 0, max: 100_000_000_00 },
  { key: 'cash_taken_cents', label: 'Cash taken out (boot)', kind: 'cents', min: 0, max: 100_000_000_00 },
  { key: 'dst', label: 'Exchange into a DST', kind: 'bool' },
];
const DST: FieldDef[] = [
  { key: 'load_rate', label: 'DST load (fees)', kind: 'rate', min: 0, max: 0.25 },
  { key: 'dst_yield', label: 'DST distribution yield', kind: 'rate', min: 0, max: 0.15 },
];
const ALL = [...SHARED, ...EXCHANGE, ...DST];

const MEASURE_LABEL: Record<string, string> = {
  terminal_wealth: 'After-tax wealth at the horizon',
  cumulative_cash_flow: 'Cash received over the horizon',
  tax_paid_now: 'Tax due at decision time',
  liquidity: 'Liquidity',
  management_burden: 'Management burden',
  concentration: 'Concentration',
};
const VERDICT: Record<string, { cls: string; glyph: string }> = {
  leads: { cls: 'bg-ink-950 text-surface', glyph: '▲' },
  trails: { cls: 'bg-surface text-ink-700 ring-1 ring-ink-200 ring-inset', glyph: '▼' },
  neutral: { cls: 'bg-ink-100 text-ink-700', glyph: '●' },
};

function baseValues(s: StrategiesT): Values {
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
  const { propertyId } = route.useParams();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const narrow = useNarrow();
  const base = useSuspenseQuery(strategiesQuery(propertyId, {})).data;
  const analysis = useQuery(analysisQuery(propertyId, {}));

  const [draft, setDraft] = useState<number | null>(null);
  const horizon = draft ?? search.horizon ?? DEFAULT_HORIZON;
  const deferredHorizon = useDeferredValue(horizon);
  const { horizon: _h, ...overrides } = search;
  const params: Params = { ...overrides, horizon: deferredHorizon === DEFAULT_HORIZON ? undefined : deferredHorizon };
  const live = useQuery({ ...strategiesQuery(propertyId, params), placeholderData: keepPreviousData });
  const s = live.data ?? base;
  // The long run (30 years) on the same assumptions draws the wealth curves; the horizon is a marker on it.
  const long = useQuery({ ...strategiesQuery(propertyId, { ...overrides, horizon: 30 }), placeholderData: keepPreviousData });
  const recomputing = live.isFetching || deferredHorizon !== horizon;

  const defaults = baseValues(base);
  const values: Values = { ...defaults, ...(overrides as Values) };
  const setSearch = (next: Partial<StrategiesSearch>) =>
    startTransition(() => navigate({ search: (prev) => ({ ...prev, ...next }), replace: true, resetScroll: false }));
  const commit = (v: Values) =>
    setSearch({ ...Object.fromEntries(ALL.map((f) => [f.key, undefined])), ...overridesOnly({ ...values, ...v }, defaults) } as Partial<StrategiesSearch>);

  const paths = s.paths;
  const startYear = paths[0]?.series[0]?.year ?? new Date().getFullYear();
  const horizonYear = startYear + horizon - 1;
  const longPaths = long.data?.paths ?? paths;
  const chartRows = (longPaths[0]?.series ?? []).map((row, i) => {
    const o: Record<string, number> = { year: row.year };
    for (const p of longPaths) {
      o[`${p.path}_wealth`] = p.series[i]?.wealth_cents ?? 0;
      o[`${p.path}_deferred`] = p.series[i]?.cumulative_tax_deferred_cents ?? 0;
    }
    return o;
  });
  const exchange = paths.find((p) => p.path === 'exchange');
  const bestNow = [...paths].sort((a, b) => b.terminal.terminal_wealth.value_cents - a.terminal.terminal_wealth.value_cents);
  const spread = bestNow.length > 1 ? bestNow[0].terminal.terminal_wealth.value_cents - bestNow[bestNow.length - 1].terminal.terminal_wealth.value_cents : 0;
  const nick = analysis.data?.property.nickname;

  return (
    <TraceScope.Provider value={{ propertyId, householdId: analysis.data?.property.household_id, params }}>
      <PageHeader
        back={
          <Link to="/properties/$propertyId" params={{ propertyId }} className="text-ink-500 hover:text-ink-900 hover:underline">
            {nick ?? 'Property analysis'}
          </Link>
        }
        title="Hold, sell or exchange"
      >
        Three paths on identical assumptions over the same horizon; one edit updates all three. The page lays out the trade-offs. It does not pick a path.
      </PageHeader>

      <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
        <div className="order-2 space-y-5 lg:sticky lg:top-16 lg:order-1 lg:self-start">
          <Card className="hidden lg:block">
            <HorizonSlider
              value={horizon}
              onChange={setDraft}
              onCommit={(v) => {
                setSearch({ horizon: v === DEFAULT_HORIZON ? undefined : v });
                setDraft(null);
              }}
            />
          </Card>
          <AssumptionsForm
            title="Shared assumptions"
            fields={SHARED}
            values={values}
            defaults={defaults}
            busy={recomputing}
            onCommit={commit}
            onReset={() => startTransition(() => navigate({ search: {}, replace: true, resetScroll: false }))}
          />
          <AssumptionsForm
            testId="exchange-panel"
            title="1031 replacement"
            fields={values.dst ? [...EXCHANGE, ...DST] : EXCHANGE}
            values={values}
            defaults={defaults}
            onCommit={commit}
          />
          <SaveScenario propertyId={propertyId} horizon={horizon} values={values} />
        </div>

        <div className="order-1 min-w-0 space-y-5 lg:order-2">
          {/* phones: the horizon control sits above the results it drives */}
          <Card className="lg:hidden">
            <HorizonSlider
              value={horizon}
              onChange={setDraft}
              onCommit={(v) => {
                setSearch({ horizon: v === DEFAULT_HORIZON ? undefined : v });
                setDraft(null);
              }}
            />
          </Card>
          <div className="flex items-center justify-between">
            <p className="text-sm text-ink-700">
              At <span className="num">{horizon}</span> years the three paths end <span className="num font-medium text-ink-950">{formatCents(spread)}</span>{' '}
              apart in after-tax wealth.
            </p>
            <Pulse on={recomputing} />
          </div>
          <section aria-label="The three paths" className="grid gap-4 md:grid-cols-3">
            {paths.map((p) => (
              <PathColumn key={p.path} p={p} />
            ))}
          </section>

          <Card bodyClass="p-4">
            <ChartFrame
              testId="chart-wealth"
              title="After-tax wealth over time"
              summary={`Wealth if each path were wound up in a given year, out to 30 years; the line marks the ${horizon}-year horizon (${horizonYear}).`}
              legend={longPaths.map((p) => ({ label: p.label, color: PATH_COLOR[p.path] }))}
              height={narrow ? 240 : 300}
              table={{
                columns: [{ key: 'year', label: 'Year' }, ...longPaths.map((p) => ({ key: `${p.path}_wealth`, label: p.label, money: true }))],
                rows: chartRows,
              }}
            >
              <ResponsiveContainer>
                <LineChart data={chartRows} margin={{ top: 16, right: 10, left: 0, bottom: 0 }}>
                  <CartesianGrid {...gridProps} />
                  <XAxis dataKey="year" {...xAxisProps} minTickGap={16} />
                  <YAxis tickFormatter={centsTick} {...yAxisProps} domain={['auto', 'auto']} />
                  <Tooltip content={(p) => <TooltipBody {...p} />} />
                  <ReferenceLine
                    x={horizonYear}
                    stroke="var(--ink-700)"
                    strokeDasharray="3 3"
                    label={{ value: `${horizon}-yr horizon`, position: 'top', fontSize: 11, fill: 'var(--ink-700)' }}
                  />
                  {longPaths.map((p) => (
                    <Line
                      key={p.path}
                      type="monotone"
                      dataKey={`${p.path}_wealth`}
                      name={p.label}
                      stroke={PATH_COLOR[p.path]}
                      strokeWidth={2}
                      dot={false}
                      strokeDasharray={p.path === 'sell' ? '5 3' : undefined}
                      isAnimationActive={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </ChartFrame>
          </Card>

          <div className="grid gap-5 xl:grid-cols-2">
            <Card bodyClass="p-4">
              <ChartFrame
                testId="chart-deferred"
                title="Deferred tax liability, growing"
                summary="Tax that holding or exchanging postpones: it does not disappear, and it grows with every year of depreciation and appreciation."
                legend={longPaths.filter((p) => p.path !== 'sell').map((p) => ({ label: p.label, color: PATH_COLOR[p.path] }))}
                height={narrow ? 200 : 230}
                table={{
                  columns: [
                    { key: 'year', label: 'Year' },
                    ...longPaths.filter((p) => p.path !== 'sell').map((p) => ({ key: `${p.path}_deferred`, label: p.label, money: true })),
                  ],
                  rows: chartRows,
                }}
              >
                <ResponsiveContainer>
                  <AreaChart data={chartRows} margin={{ top: 16, right: 10, left: 0, bottom: 0 }}>
                    <CartesianGrid {...gridProps} />
                    <XAxis dataKey="year" {...xAxisProps} minTickGap={16} />
                    <YAxis tickFormatter={centsTick} {...yAxisProps} />
                    <Tooltip content={(p) => <TooltipBody {...p} />} />
                    <ReferenceLine x={horizonYear} stroke="var(--ink-700)" strokeDasharray="3 3" />
                    {longPaths
                      .filter((p) => p.path !== 'sell')
                      .map((p) => (
                        <Area
                          key={p.path}
                          type="monotone"
                          dataKey={`${p.path}_deferred`}
                          name={p.label}
                          stroke={PATH_COLOR[p.path]}
                          fill={PATH_COLOR[p.path]}
                          fillOpacity={0.1}
                          strokeWidth={2}
                          isAnimationActive={false}
                        />
                      ))}
                  </AreaChart>
                </ResponsiveContainer>
              </ChartFrame>
            </Card>
            <Card bodyClass="p-4">
              {analysis.data ? <SaleWaterfall x={analysis.data.exit_tax} title="Selling now: where the price goes" /> : <div className="h-[300px] skeleton" />}
            </Card>
          </div>

          <Card
            title="Leads, trails or neutral, one measure at a time"
            sub="Each row compares the three paths on one measure. No row, and no combination of rows, says which path to choose."
          >
            <Matrix s={s} />
          </Card>

          <Sensitivity propertyId={propertyId} overrides={overrides} appreciation={values.appreciation_rate as number} horizon={horizon} />

          <div className="grid gap-5 xl:grid-cols-2">
            {exchange?.boot && (
              <Card title="Boot calculator" sub="Boot is the part of a 1031 that is taxed now.">
                <FigureRow label="Cash boot (cash taken out)" figure={exchange.boot.cash_boot} />
                <FigureRow label="Mortgage boot (debt paid off and not replaced)" figure={exchange.boot.mortgage_boot} />
                <FigureRow label="Total boot" figure={exchange.boot.total_boot} strong />
                <FigureRow label="Gain recognized = min(boot, total gain)" figure={exchange.boot.gain_recognized} />
                <FigureRow label="Tax on boot, same exit-tax stack" figure={exchange.boot.tax_on_boot} strong />
                <p className="mt-2 text-[11px] leading-relaxed text-ink-500">
                  Mortgage boot = max(0, old debt paid off − replacement debt). Raising replacement debt or adding cash brings it to zero.
                </p>
              </Card>
            )}
            <Card title="What the proceeds do">
              <div className="space-y-5">
                {paths
                  .filter((p) => p.proceeds_use?.length)
                  .map((p) => (
                    <div key={p.path}>
                      <h3 className="mb-1 flex items-center gap-2">
                        <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: PATH_COLOR[p.path] }} />
                        {p.label}
                      </h3>
                      {p.proceeds_use!.map((u) => (
                        <FigureRow key={u.label} label={u.label} figure={u.value} />
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

function PathColumn({ p }: { p: StrategyPathT }) {
  const t = p.terminal;
  const st = rollupStatus([t.terminal_wealth, t.cumulative_cash_flow, t.tax_paid_now, t.deferred_liability]);
  return (
    <article className="card flex flex-col" data-testid={`path-${p.path}`}>
      <div className="card-head">
        <h2 className="flex min-w-0 items-center gap-2">
          <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: PATH_COLOR[p.path] }} />
          <span className="truncate">{p.label}</span>
        </h2>
        <StatusChip status={st} compact />
      </div>
      <div className="card-body">
        <FigureRow label="After-tax wealth" figure={t.terminal_wealth} strong />
        <FigureRow label="Cash received" figure={t.cumulative_cash_flow} signed />
        <FigureRow label="Tax paid now" figure={t.tax_paid_now} />
        <FigureRow label="Deferred tax still owed" figure={t.deferred_liability} />
        <FigureRow label="Ending equity" figure={t.ending_equity} />
      </div>
      <details className="mt-auto border-t border-ink-100 px-4 py-3 text-xs">
        <summary className="cursor-pointer font-medium text-ink-700">Caveats ({p.caveats.length})</summary>
        <ul className="mt-2 list-disc space-y-1 pl-4 leading-relaxed text-ink-700">
          {p.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </details>
    </article>
  );
}

function Matrix({ s }: { s: StrategiesT }) {
  const measures = Object.keys(MEASURE_LABEL).filter((m) => s.matrix[m]);
  return (
    <div className="-mx-4 overflow-x-auto px-4" tabIndex={0} role="region" aria-label="Comparison by measure, scrolls sideways">
      <table className="tbl min-w-[520px]" data-testid="strategy-matrix">
        <thead>
          <tr>
            <th>Measure</th>
            {s.paths.map((p) => (
              <th key={p.path} className="text-center">
                {p.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {measures.map((m) => (
            <tr key={m}>
              <td className="text-ink-700">{MEASURE_LABEL[m]}</td>
              {s.paths.map((p) => {
                const v = s.matrix[m][p.path] ?? 'neutral';
                return (
                  <td key={p.path} className="text-center">
                    <span
                      data-testid={`cell-${m}-${p.path}`}
                      data-verdict={v}
                      className={`inline-flex min-w-[5.5rem] items-center justify-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold ${VERDICT[v]?.cls ?? VERDICT.neutral.cls}`}
                    >
                      <span aria-hidden className="text-[9px]">
                        {VERDICT[v]?.glyph}
                      </span>
                      {v}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Sensitivity: which path ends with the most after-tax wealth across appreciation × horizon.
 * 25 strategy queries, debounced off the other assumptions and cached by Query, so revisiting a grid
 * (or moving back to a previous assumption) is instant and only changed cells refetch.
 */
function Sensitivity({
  propertyId,
  overrides,
  appreciation,
  horizon,
}: {
  propertyId: string;
  overrides: Omit<StrategiesSearch, 'horizon'>;
  appreciation: number;
  horizon: number;
}) {
  const [enabled, setEnabled] = useState(false);
  const center = Math.round(appreciation * 200) / 200; // nearest 0.5%
  const rates = [-0.02, -0.01, 0, 0.01, 0.02].map((d) => Math.round((center + d) * 1000) / 1000);
  const horizons = [3, 5, 10, 15, 20];
  const { appreciation_rate: _a, ...rest } = overrides;
  const debounced = useDebounced(JSON.stringify(rest), 400);
  const restParams = JSON.parse(debounced) as Params;
  const grid = rates.flatMap((r) => horizons.map((h) => ({ r, h })));
  const results = useQueries({
    queries: grid.map(({ r, h }) => ({
      ...strategiesQuery(propertyId, { ...restParams, appreciation_rate: r, horizon: h }),
      placeholderData: undefined,
      enabled,
    })),
  });
  const cells = new Map<string, HeatCell | undefined>();
  grid.forEach(({ r, h }, i) => {
    const d = results[i].data;
    if (!d) return cells.set(`${r}|${h}`, undefined);
    const w = Object.fromEntries(d.paths.map((p) => [p.path, p.terminal.terminal_wealth.value_cents])) as Record<PathId, number>;
    const sorted = [...d.paths].sort((a, b) => b.terminal.terminal_wealth.value_cents - a.terminal.terminal_wealth.value_cents);
    const top = sorted[0].terminal.terminal_wealth.value_cents;
    const second = sorted[1]?.terminal.terminal_wealth.value_cents ?? top;
    const margin = second !== 0 ? (top - second) / Math.abs(second) : 0;
    cells.set(`${r}|${h}`, { rate: r, horizon: h, wealth: w, leader: margin < 0.01 ? null : (sorted[0].path as PathId), margin });
  });
  const done = results.filter((q) => q.data).length;
  const counts = { hold: 0, sell: 0, exchange: 0, tie: 0 } as Record<string, number>;
  cells.forEach((c) => c && (counts[c.leader ?? 'tie'] += 1));
  return (
    <Card bodyClass="p-4" id="sensitivity">
      <ChartFrame
        testId="chart-heatmap"
        title="Which path leads, by appreciation and horizon"
        summary={
          enabled
            ? done < grid.length
              ? `Computing ${done} of ${grid.length} scenarios…`
              : `Across ${grid.length} scenarios: hold leads in ${counts.hold}, selling in ${counts.sell}, the 1031 in ${counts.exchange}, and ${counts.tie} are within 1%. Shade shows the size of the lead.`
            : `Runs the full three-path comparison ${grid.length} times (appreciation ${formatRate(rates[0], 1)} to ${formatRate(rates[rates.length - 1], 1)}, 3 to 20 years) on the assumptions above.`
        }
        legend={[
          { label: 'Hold leads', color: C.s1 },
          { label: 'Sell leads', color: C.s2 },
          { label: '1031 leads', color: C.s3 },
        ]}
        height={enabled ? 300 : 64}
        table={{
          columns: [{ key: 'rate', label: 'Appreciation' }, ...horizons.map((h) => ({ key: String(h), label: `${h} yrs` }))],
          rows: rates.map((r) => ({
            rate: formatRate(r, 1),
            ...Object.fromEntries(horizons.map((h) => [String(h), cells.get(`${r}|${h}`)?.leader ?? (cells.get(`${r}|${h}`) ? 'tie' : '…')])),
          })),
        }}
      >
        {enabled ? (
          <Heatmap rates={rates} horizons={horizons} cells={cells} current={{ rate: center, horizon }} />
        ) : (
          <button type="button" className="btn" onClick={() => setEnabled(true)} data-testid="run-sensitivity">
            Run the sensitivity grid ({grid.length} scenarios)
          </button>
        )}
      </ChartFrame>
    </Card>
  );
}

function SaveScenario({ propertyId, horizon, values }: { propertyId: string; horizon: number; values: Values }) {
  const save = useSaveScenario(propertyId);
  const [state, action, pending] = useActionState(async (_prev: { ok?: string; error?: string }, fd: FormData): Promise<{ ok?: string; error?: string }> => {
    const name = String(fd.get('name') ?? '').trim();
    if (!name) return { error: 'Name the scenario first' };
    if (name.length > 80) return { error: 'Keep the name under 80 characters' };
    const v = values;
    try {
      await save.mutateAsync({
        name,
        horizon_years: horizon,
        assumptions: {
          appreciation_rate: v.appreciation_rate,
          rent_growth: v.rent_growth,
          expense_growth: v.expense_growth,
          reinvest_rate: v.reinvest_rate,
          exchange: {
            replacement_value_cents: v.replacement_value_cents,
            replacement_debt_cents: v.replacement_debt_cents,
            cash_taken_cents: v.cash_taken_cents,
            dst: v.dst,
            load_rate: v.load_rate,
            dst_yield: v.dst_yield,
          },
        },
      });
      return { ok: `Saved “${name}”` };
    } catch (e) {
      return { error: e instanceof Error ? e.message : String(e) };
    }
  }, {});
  return (
    <form action={action} className="card card-body space-y-2" data-testid="save-scenario">
      <label htmlFor="scenario-name" className="text-sm font-semibold text-ink-950">
        Save these assumptions
      </label>
      <div className="flex gap-2">
        <input id="scenario-name" name="name" className="input" placeholder="e.g. Base case, 3% growth" aria-invalid={!!state.error} />
        <button type="submit" className="btn shrink-0" disabled={pending}>
          {pending ? 'Saving…' : 'Save scenario'}
        </button>
      </div>
      <p aria-live="polite" className={`text-xs ${state.error ? 'text-neg-600' : 'text-pos-600'}`}>
        {state.error ?? state.ok ?? ''}
      </p>
    </form>
  );
}
