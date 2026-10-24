import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { getRouteApi } from '@tanstack/react-router';
import { useDeferredValue, useState } from 'react';
import { Area, AreaChart, Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { simulateQuery } from '../api/queries';
import type { SimulationEvent, SimulationEventType, SimulationProperty, SimulationRequest } from '../api/types';
import { C, ChartFrame, TooltipBody, centsTick, gridProps, useNarrow, xAxisProps, yAxisProps } from '../charts/kit';
import { AssumptionsForm, type FieldDef, type Values } from '../components/AssumptionsForm';
import { HorizonSlider } from '../components/HorizonSlider';
import { Card, PageHeader, Pulse } from '../components/ui';
import { formatCents, parseDollarsToCents } from '../lib/money';
import { useDebounced } from '../lib/useDebounced';

const route = getRouteApi('/simulate');
const $ = (d: number) => Math.round(d * 100);
const START = 2026;

/** The demo household's four rentals: value, debt and NOI before debt service. */
const SEED: (SimulationProperty & { rate: number; remaining_years: number })[] = [
  {
    nickname: 'Maple duplex',
    property_type: 'multifamily',
    current_value_cents: $(620_000),
    debt_cents: $(146_212),
    rate: 0.0425,
    remaining_years: 17,
    noi_cents: $(25_960),
    purchase_price_cents: $(285_000),
    purchase_date: '2012-05-15',
    land_pct: 0.3,
  },
  {
    nickname: 'Tahoe cabin',
    property_type: 'vacation_str',
    current_value_cents: $(725_000),
    debt_cents: $(359_410),
    rate: 0.0525,
    remaining_years: 24,
    noi_cents: $(3_020),
    purchase_price_cents: $(540_000),
    purchase_date: '2019-08-01',
    land_pct: 0.3,
  },
  {
    nickname: 'Elm SFR',
    property_type: 'sfr',
    current_value_cents: $(640_000),
    debt_cents: $(457_500),
    rate: 0.06125,
    remaining_years: 29,
    noi_cents: $(25_826),
    purchase_price_cents: $(610_000),
    purchase_date: '2024-06-14',
    land_pct: 0.3,
  },
  {
    nickname: 'Oak condo',
    property_type: 'sfr',
    current_value_cents: $(455_000),
    debt_cents: $(85_000),
    rate: 0.0875,
    remaining_years: 10,
    noi_cents: $(12_304),
    purchase_price_cents: $(310_000),
    purchase_date: '2015-03-10',
    land_pct: 0.3,
  },
];

const SEED_EVENTS: SimulationEvent[] = [
  { id: 'e1', year: 2027, type: 'refi', property_ref: 'Elm SFR', debt_cents: $(450_000), rate: 0.0625, note: 'Refinance ahead of the ARM reset' },
  { id: 'e2', year: 2028, type: 'sell', property_ref: 'Tahoe cabin', note: 'Exit the short-term rental' },
  {
    id: 'e3',
    year: 2030,
    type: 'exchange',
    property_ref: 'Maple duplex',
    amount_cents: $(820_000),
    debt_cents: $(160_000),
    note: '1031 into a triple-net property',
  },
  { id: 'e4', year: 2032, type: 'sell', property_ref: 'Oak condo', note: 'Retirement year' },
];

const FIELDS: FieldDef[] = [
  { key: 'appreciation_rate', label: 'Appreciation (mean)', kind: 'rate', min: -0.1, max: 0.2 },
  { key: 'appr_sigma', label: 'Appreciation volatility', kind: 'rate', min: 0, max: 0.3 },
  { key: 'rent_growth', label: 'Rent growth (mean)', kind: 'rate', min: -0.1, max: 0.2 },
  { key: 'rent_sigma', label: 'Rent growth volatility', kind: 'rate', min: 0, max: 0.3 },
  { key: 'expense_growth', label: 'Expense growth', kind: 'rate', min: -0.1, max: 0.2 },
  { key: 'reinvest_rate', label: 'Return on reinvested cash', kind: 'rate', min: -0.1, max: 0.2 },
  { key: 'cap_rate', label: 'Cap rate on buys', kind: 'rate', min: 0.01, max: 0.15 },
  { key: 'runs', label: 'Monte Carlo runs', kind: 'int', min: 10, max: 2000 },
];
const DEFAULTS: Values = {
  appreciation_rate: 0.035,
  rent_growth: 0.03,
  expense_growth: 0.03,
  reinvest_rate: 0.06,
  cap_rate: 0.055,
  appr_sigma: 0.06,
  rent_sigma: 0.025,
  runs: 300,
};

const TYPE_LABEL: Record<SimulationEventType, string> = { buy: 'Buy', sell: 'Sell', exchange: '1031', refi: 'Refi' };
const TYPE_COLOR: Record<SimulationEventType, string> = { buy: C.s1, sell: C.s2, exchange: C.s3, refi: C.s4 };

export function SimulatePage() {
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const narrow = useNarrow();
  const [yearsDraft, setYearsDraft] = useState<number | null>(null);
  const years = yearsDraft ?? search.years ?? 12;
  const [events, setEvents] = useState<SimulationEvent[]>(SEED_EVENTS);
  const [a, setA] = useState<Values>({ ...DEFAULTS, runs: search.runs ?? DEFAULTS.runs });
  const deferredYears = useDeferredValue(years);
  const req: SimulationRequest = {
    start_year: START,
    years: deferredYears,
    properties: SEED,
    events: [...events].sort((x, y) => x.year - y.year),
    assumptions: {
      appreciation_rate: a.appreciation_rate as number,
      rent_growth: a.rent_growth as number,
      expense_growth: a.expense_growth as number,
      reinvest_rate: a.reinvest_rate as number,
      cap_rate: a.cap_rate as number,
    },
    monte_carlo: { runs: a.runs as number, appr_sigma: a.appr_sigma as number, rent_sigma: a.rent_sigma as number },
  };
  // Typing in the event table should not fire a POST per keystroke: debounce, then cache by request.
  const debounced = useDebounced(JSON.stringify(req), 300);
  const sim = useQuery({ ...simulateQuery(JSON.parse(debounced) as SimulationRequest), placeholderData: keepPreviousData });
  const names = [...SEED.map((p) => p.nickname), ...events.filter((e) => e.type === 'buy').map((e) => e.property_ref)];
  const update = (id: string, patch: Partial<SimulationEvent>) => setEvents((es) => es.map((e) => (e.id === id ? { ...e, ...patch } : e)));
  const data = sim.data?.series.map((y) => ({
    year: y.year,
    band: [y.net_worth.p10, y.net_worth.p90] as [number, number],
    p10: y.net_worth.p10,
    p50: y.net_worth.p50,
    p90: y.net_worth.p90,
    tax_p50: y.taxes_paid.p50,
    tax_p90: y.taxes_paid.p90,
    equity: y.equity_cents,
    debt: y.debt_cents,
  }));
  const shownEvents = events.filter((e) => e.year >= START && e.year < START + years);
  const t = sim.data?.terminal;

  return (
    <div>
      <PageHeader title="Buy and sell over time">
        Lay out a sequence of purchases, sales, exchanges and refinances for the demo household’s four rentals and see the range of outcomes. Bands run from the
        10th to the 90th percentile across Monte Carlo runs on appreciation and rent growth.
      </PageHeader>
      <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
        <div className="space-y-5 lg:sticky lg:top-16 lg:self-start">
          <Card>
            <HorizonSlider
              label="Years to simulate"
              min={3}
              max={30}
              value={years}
              onChange={setYearsDraft}
              onCommit={(v) => {
                void navigate({ search: (s) => ({ ...s, years: v === 12 ? undefined : v }), replace: true, resetScroll: false });
                setYearsDraft(null);
              }}
            />
          </Card>
          <AssumptionsForm
            title="Assumptions"
            testId="sim-assumptions"
            fields={FIELDS}
            values={a}
            defaults={DEFAULTS}
            onCommit={setA}
            onReset={() => setA(DEFAULTS)}
            busy={sim.isFetching}
          />
        </div>

        <div className="min-w-0 space-y-5">
          <Card
            title="Timeline"
            sub={`${events.length} events, ${START} to ${START + years - 1}`}
            actions={
              <button
                type="button"
                className="btn btn-sm"
                data-testid="add-event"
                onClick={() =>
                  setEvents((es) => [
                    ...es,
                    {
                      id: `e-${crypto.randomUUID().slice(0, 8)}`,
                      year: START + 2,
                      type: 'buy',
                      property_ref: `New rental ${es.filter((e) => e.type === 'buy').length + 1}`,
                      amount_cents: $(550_000),
                      debt_cents: $(385_000),
                      rate: 0.065,
                    },
                  ])
                }
              >
                Add event
              </button>
            }
            bodyClass="pb-2"
          >
            <div className="relative mx-5 mt-5 mb-7 h-6" aria-hidden>
              <div className="absolute top-1/2 right-0 left-0 h-px bg-ink-200" />
              {Array.from({ length: years }, (_, i) => (
                <span
                  key={i}
                  className="num absolute top-full -translate-x-1/2 pt-1 text-[10px] text-ink-500"
                  style={{ left: `${(i / Math.max(1, years - 1)) * 100}%` }}
                >
                  {i % (narrow ? 4 : 2) === 0 ? `’${String(START + i).slice(2)}` : ''}
                </span>
              ))}
              {shownEvents.map((e) => (
                <span
                  key={e.id}
                  className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface"
                  style={{ left: `${((e.year - START) / Math.max(1, years - 1)) * 100}%`, background: TYPE_COLOR[e.type] }}
                />
              ))}
            </div>
            <div
              aria-hidden
              className="hidden grid-cols-[5.5rem_7rem_minmax(0,1fr)_8rem_8rem_5rem_2rem] gap-2 border-b border-ink-100 px-4 pb-1.5 text-xs font-medium text-ink-500 sm:grid"
            >
              <span>Year</span>
              <span>Event</span>
              <span>Property</span>
              <span className="text-right">Price / value</span>
              <span className="text-right">Debt after</span>
              <span className="text-right">Rate %</span>
              <span />
            </div>
            <ul className="divide-y divide-ink-100" data-testid="events">
              {[...events]
                .sort((x, y) => x.year - y.year)
                .map((e) => (
                  <li
                    key={e.id}
                    className="grid grid-cols-2 gap-2 px-4 py-2.5 sm:grid-cols-[5.5rem_7rem_minmax(0,1fr)_8rem_8rem_5rem_2rem] sm:items-center"
                    data-testid="event-row"
                  >
                    <label className="flex flex-col gap-0.5">
                      <span className="text-[11px] text-ink-500 sm:sr-only">Year</span>
                      <input
                        aria-label="Event year"
                        className="input-num"
                        type="number"
                        min={START}
                        max={START + 29}
                        value={e.year}
                        onChange={(ev) => update(e.id, { year: Number(ev.target.value) || START })}
                      />
                    </label>
                    <label className="flex flex-col gap-0.5">
                      <span className="text-[11px] text-ink-500 sm:sr-only">Event</span>
                      <select
                        aria-label="Event type"
                        className="input"
                        value={e.type}
                        onChange={(ev) => update(e.id, { type: ev.target.value as SimulationEventType })}
                      >
                        {(['buy', 'sell', 'exchange', 'refi'] as const).map((t) => (
                          <option key={t} value={t}>
                            {TYPE_LABEL[t]}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="col-span-2 flex flex-col gap-0.5 sm:col-span-1">
                      <span className="text-[11px] text-ink-500 sm:sr-only">Property</span>
                      {e.type === 'buy' ? (
                        <input
                          aria-label="New property name"
                          className="input"
                          value={e.property_ref}
                          onChange={(ev) => update(e.id, { property_ref: ev.target.value })}
                        />
                      ) : (
                        <select
                          aria-label="Property"
                          className="input"
                          value={e.property_ref}
                          onChange={(ev) => update(e.id, { property_ref: ev.target.value })}
                        >
                          {names.map((n) => (
                            <option key={n}>{n}</option>
                          ))}
                        </select>
                      )}
                    </label>
                    <label className="flex flex-col gap-0.5">
                      <span className="text-[11px] text-ink-500 sm:sr-only">Price or new value</span>
                      {e.type === 'buy' || e.type === 'exchange' ? (
                        <CentsInput label="Price or new value" value={e.amount_cents} onChange={(v) => update(e.id, { amount_cents: v })} />
                      ) : (
                        <span className="hidden text-right text-ink-400 sm:block">—</span>
                      )}
                    </label>
                    <label className="flex flex-col gap-0.5">
                      <span className="text-[11px] text-ink-500 sm:sr-only">Debt after</span>
                      {e.type !== 'sell' ? (
                        <CentsInput label="Debt after" value={e.debt_cents} onChange={(v) => update(e.id, { debt_cents: v })} />
                      ) : (
                        <span className="hidden text-right text-ink-400 sm:block">—</span>
                      )}
                    </label>
                    <label className="flex flex-col gap-0.5">
                      <span className="text-[11px] text-ink-500 sm:sr-only">Rate %</span>
                      {e.type === 'buy' || e.type === 'refi' ? (
                        <input
                          aria-label="Rate percent"
                          className="input-num"
                          inputMode="decimal"
                          defaultValue={((e.rate ?? 0.065) * 100).toFixed(2)}
                          onBlur={(ev) => update(e.id, { rate: Number(ev.target.value) / 100 || 0 })}
                        />
                      ) : (
                        <span className="hidden text-right text-ink-400 sm:block">—</span>
                      )}
                    </label>
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost col-span-2 text-ink-500 sm:col-span-1"
                      onClick={() => setEvents((es) => es.filter((x) => x.id !== e.id))}
                      aria-label={`Remove ${TYPE_LABEL[e.type]} ${e.property_ref} ${e.year}`}
                    >
                      <span aria-hidden className="hidden sm:inline">
                        ✕
                      </span>
                      <span className="sm:hidden">Remove</span>
                    </button>
                  </li>
                ))}
            </ul>
          </Card>

          {sim.error && <p className="rounded-md bg-neg-100 px-3 py-2 text-sm text-neg-600">The simulation failed: {sim.error.message}</p>}
          <section aria-label="Outcome at the end" className="grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-ink-100 shadow-card md:grid-cols-4">
            {(
              [
                ['Net worth, bad case (p10)', t?.net_worth.p10],
                ['Net worth, median', t?.net_worth.p50],
                ['Net worth, good case (p90)', t?.net_worth.p90],
                ['Taxes paid, median total', t?.cumulative_taxes.p50],
              ] as const
            ).map(([k, v]) => (
              <div key={k} className="bg-surface px-4 py-3">
                <div className="label">{k}</div>
                <div className="num mt-1 text-lg font-medium" data-testid="sim-kpi">
                  {v === undefined ? <span className="skeleton inline-block h-6 w-28" /> : formatCents(v)}
                </div>
              </div>
            ))}
          </section>

          <Card bodyClass="p-4">
            <ChartFrame
              testId="chart-fan"
              title="Net worth, range of outcomes"
              summary={
                t
                  ? `After ${years} years the median outcome is ${formatCents(t.net_worth.p50)}; one run in ten ends below ${formatCents(t.net_worth.p10)} and one in ten above ${formatCents(t.net_worth.p90)} (${sim.data?.runs ?? 0} runs).`
                  : 'Running the simulation…'
              }
              legend={[
                { label: 'p10 to p90', color: 'color-mix(in oklab, var(--series-1) 22%, var(--surface))' },
                { label: 'Median', color: C.s1 },
              ]}
              actions={<Pulse on={sim.isFetching} label="Simulating" />}
              height={narrow ? 250 : 320}
              table={{
                columns: [
                  { key: 'year', label: 'Year' },
                  { key: 'p10', label: 'p10', money: true },
                  { key: 'p50', label: 'p50', money: true },
                  { key: 'p90', label: 'p90', money: true },
                ],
                rows: data ?? [],
              }}
            >
              {data ? (
                <ResponsiveContainer>
                  <ComposedChart data={data} margin={{ top: 18, right: 10, left: 0, bottom: 0 }}>
                    <CartesianGrid {...gridProps} />
                    <XAxis dataKey="year" {...xAxisProps} minTickGap={14} />
                    <YAxis tickFormatter={centsTick} {...yAxisProps} domain={['auto', 'auto']} />
                    <Tooltip content={(p) => <TooltipBody {...p} />} />
                    <Area dataKey="band" name="p10 to p90" stroke="none" fill={C.s1} fillOpacity={0.16} isAnimationActive={false} />
                    <Line dataKey="p90" name="p90" stroke={C.s1} strokeOpacity={0.45} strokeWidth={1} dot={false} isAnimationActive={false} />
                    <Line dataKey="p10" name="p10" stroke={C.s1} strokeOpacity={0.45} strokeWidth={1} dot={false} isAnimationActive={false} />
                    <Line dataKey="p50" name="Median" stroke={C.s1} strokeWidth={2} dot={false} isAnimationActive={false} />
                    {shownEvents.map((e) => (
                      <ReferenceLine
                        key={e.id}
                        x={e.year}
                        stroke={TYPE_COLOR[e.type]}
                        strokeDasharray="3 3"
                        label={{ value: TYPE_LABEL[e.type], position: 'top', fontSize: 10, fill: 'var(--ink-700)' }}
                      />
                    ))}
                  </ComposedChart>
                </ResponsiveContainer>
              ) : (
                <div className="skeleton h-full" />
              )}
            </ChartFrame>
          </Card>

          <div className="grid gap-5 xl:grid-cols-2">
            <Card bodyClass="p-4">
              <ChartFrame
                testId="chart-taxes"
                title="Taxes paid by year"
                summary="Sales and boot show up as spikes; a 1031 year stays low unless cash comes out."
                legend={[
                  { label: 'Median', color: C.s2 },
                  { label: 'p90', color: C.s2, dashed: true },
                ]}
                height={narrow ? 200 : 230}
                table={{
                  columns: [
                    { key: 'year', label: 'Year' },
                    { key: 'tax_p50', label: 'Median', money: true },
                    { key: 'tax_p90', label: 'p90', money: true },
                  ],
                  rows: data ?? [],
                }}
              >
                {data ? (
                  <ResponsiveContainer>
                    <ComposedChart data={data} margin={{ top: 6, right: 10, left: 0, bottom: 0 }}>
                      <CartesianGrid {...gridProps} />
                      <XAxis dataKey="year" {...xAxisProps} minTickGap={14} />
                      <YAxis tickFormatter={centsTick} {...yAxisProps} />
                      <Tooltip cursor={{ fill: 'var(--ink-50)' }} content={(p) => <TooltipBody {...p} />} />
                      <Bar dataKey="tax_p50" name="Median" fill={C.s2} maxBarSize={14} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                      <Line dataKey="tax_p90" name="p90" stroke={C.s2} strokeDasharray="4 3" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                    </ComposedChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="skeleton h-full" />
                )}
              </ChartFrame>
            </Card>
            <Card bodyClass="p-4">
              <ChartFrame
                testId="chart-equity-debt-sim"
                title="Equity and debt, median path"
                summary="How the portfolio’s value splits between equity and debt as events play out."
                legend={[
                  { label: 'Equity', color: C.s1 },
                  { label: 'Debt', color: C.muted },
                ]}
                height={narrow ? 200 : 230}
                table={{
                  columns: [
                    { key: 'year', label: 'Year' },
                    { key: 'equity', label: 'Equity', money: true },
                    { key: 'debt', label: 'Debt', money: true },
                  ],
                  rows: data ?? [],
                }}
              >
                {data ? (
                  <ResponsiveContainer>
                    <AreaChart data={data} margin={{ top: 6, right: 10, left: 0, bottom: 0 }}>
                      <CartesianGrid {...gridProps} />
                      <XAxis dataKey="year" {...xAxisProps} minTickGap={14} />
                      <YAxis tickFormatter={centsTick} {...yAxisProps} />
                      <Tooltip content={(p) => <TooltipBody {...p} />} />
                      <Area
                        dataKey="debt"
                        name="Debt"
                        stackId="1"
                        stroke={C.muted}
                        fill={C.muted}
                        fillOpacity={0.35}
                        strokeWidth={2}
                        isAnimationActive={false}
                      />
                      <Area dataKey="equity" name="Equity" stackId="1" stroke={C.s1} fill={C.s1} fillOpacity={0.14} strokeWidth={2} isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="skeleton h-full" />
                )}
              </ChartFrame>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

function CentsInput({ value, onChange, label }: { value: number | undefined; onChange: (v: number) => void; label: string }) {
  return (
    <input
      key={value}
      aria-label={label}
      className="input-num"
      inputMode="decimal"
      defaultValue={value === undefined ? '' : Math.round(value / 100).toLocaleString('en-US')}
      onBlur={(e) => {
        const c = parseDollarsToCents(e.target.value);
        if (c !== null && c !== value) onChange(c);
      }}
    />
  );
}
