import { useEffect, useMemo, useState } from 'react';
import { Area, AreaChart, Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from 'recharts';
import { useSimulate } from '../api/hooks';
import type { SimulationEvent, SimulationEventType, SimulationProperty, SimulationRequest } from '../api/types';
import { AssumptionsPanel, type AssumptionField, type AssumptionValues } from '../components/AssumptionsPanel';
import { ChartTooltip } from '../components/charts';
import { SERIES, axisProps, centsTick, gridProps } from '../lib/chartTheme';
import { Card, ErrorBox, PageHeader } from '../components/ui';
import { formatCents, parseDollarsToCents } from '../lib/money';
import { useDebounced } from '../lib/useDebounced';

const $ = (d: number) => Math.round(d * 100);

/** Seeded with the Okafor-Lindqvist portfolio (values, debt, NOI before debt service). */
const SEED_PROPERTIES: SimulationProperty[] = [
  { nickname: 'Maple duplex', property_type: 'multifamily', current_value_cents: $(620_000), debt_cents: $(146_212), noi_cents: $(25_960), purchase_price_cents: $(285_000), purchase_date: '2012-05-15', land_pct: 0.6 },
  { nickname: 'Tahoe cabin', property_type: 'vacation_str', current_value_cents: $(725_000), debt_cents: $(359_410), noi_cents: $(3_020), purchase_price_cents: $(540_000), purchase_date: '2019-08-01', land_pct: 0.7 },
  { nickname: 'Elm SFR', property_type: 'sfr', current_value_cents: $(640_000), debt_cents: $(457_500), noi_cents: $(25_826), purchase_price_cents: $(610_000), purchase_date: '2024-06-14', land_pct: 0.7 },
  { nickname: 'Oak condo', property_type: 'sfr', current_value_cents: $(455_000), debt_cents: $(85_000), noi_cents: $(12_304), purchase_price_cents: $(310_000), purchase_date: '2015-03-10', land_pct: 0.7 },
];

const SEED_EVENTS: SimulationEvent[] = [
  { id: 'e1', year: 2027, type: 'refi', property_ref: 'Elm SFR', debt_cents: $(450_000), rate: 0.0625, note: 'Refi ahead of the ARM reset' },
  { id: 'e2', year: 2028, type: 'sell', property_ref: 'Tahoe cabin', note: 'Exit the STR' },
  { id: 'e3', year: 2030, type: 'exchange', property_ref: 'Maple duplex', amount_cents: $(820_000), debt_cents: $(160_000), note: '1031 into a DST / NNN' },
  { id: 'e4', year: 2032, type: 'sell', property_ref: 'Oak condo', note: 'Retirement year' },
];

const FIELDS: AssumptionField[] = [
  { key: 'appreciation_rate', label: 'Appreciation (mean)', kind: 'rate', min: -0.1, max: 0.2 },
  { key: 'rent_growth', label: 'Rent growth (mean)', kind: 'rate', min: -0.1, max: 0.2 },
  { key: 'expense_growth', label: 'Expense growth', kind: 'rate', min: -0.1, max: 0.2 },
  { key: 'reinvest_rate', label: 'Reinvestment return', kind: 'rate', min: -0.1, max: 0.2 },
  { key: 'cap_rate', label: 'Cap rate on buys / exchanges', kind: 'rate', min: 0.01, max: 0.15 },
  { key: 'appr_sigma', label: 'Appreciation σ', kind: 'rate', min: 0, max: 0.3 },
  { key: 'rent_sigma', label: 'Rent growth σ', kind: 'rate', min: 0, max: 0.3 },
  { key: 'runs', label: 'Monte Carlo runs', kind: 'int', min: 1, max: 2000 },
];

const DEFAULTS: AssumptionValues = { appreciation_rate: 0.035, rent_growth: 0.03, expense_growth: 0.03, reinvest_rate: 0.06, cap_rate: 0.055, appr_sigma: 0.06, rent_sigma: 0.025, runs: 300 };

const TYPE_STYLE: Record<SimulationEventType, string> = { buy: 'bg-brand-100 text-brand-700', sell: 'bg-ink-200 text-ink-900', exchange: 'bg-[#dff1ee] text-[#1f6d63]', refi: 'bg-est-100 text-est-600' };

export function SimulatePage() {
  const startYear = 2026;
  const [years, setYears] = useState(12);
  const [events, setEvents] = useState<SimulationEvent[]>(SEED_EVENTS);
  const [a, setA] = useState<AssumptionValues>(DEFAULTS);
  const sim = useSimulate();
  const req: SimulationRequest = useMemo(
    () => ({
      start_year: startYear,
      years,
      properties: SEED_PROPERTIES,
      events: [...events].sort((x, y) => x.year - y.year),
      assumptions: { appreciation_rate: a.appreciation_rate as number, rent_growth: a.rent_growth as number, expense_growth: a.expense_growth as number, reinvest_rate: a.reinvest_rate as number, cap_rate: a.cap_rate as number },
      monte_carlo: { runs: a.runs as number, appr_sigma: a.appr_sigma as number, rent_sigma: a.rent_sigma as number },
    }),
    [years, events, a],
  );
  const debounced = useDebounced(req, 300);
  const { mutate } = sim;
  useEffect(() => mutate(debounced), [debounced, mutate]);

  const names = useMemo(() => [...SEED_PROPERTIES.map((p) => p.nickname), ...events.filter((e) => e.type === 'buy').map((e) => e.property_ref)], [events]);
  const data = sim.data?.series.map((y) => ({
    year: y.year,
    nw_lo: y.net_worth.p10,
    nw_band: y.net_worth.p90 - y.net_worth.p10,
    nw_p50: y.net_worth.p50,
    cf_p50: y.cash_flow.p50,
    tax_p50: y.taxes_paid.p50,
    tax_p90: y.taxes_paid.p90,
    equity: y.equity_cents,
    debt: y.debt_cents,
  }));
  const update = (id: string, patch: Partial<SimulationEvent>) => setEvents((es) => es.map((e) => (e.id === id ? { ...e, ...patch } : e)));
  return (
    <div>
      <PageHeader eyebrow="Playground" title="Buy / sell over time">
        Lay out a sequence of buys, sales, exchanges and refinances for the Okafor-Lindqvist portfolio and see the range of outcomes. Bands are p10 to p90 across Monte Carlo runs on appreciation and rent growth.
      </PageHeader>
      <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
        <div className="space-y-5">
          <section className="card">
            <div className="card-head">
              <h2>Years</h2>
              <span className="num text-sm font-semibold">
                {startYear}–{startYear + years - 1}
              </span>
            </div>
            <div className="card-body">
              <input aria-label="Years" type="range" min={3} max={30} value={years} onChange={(e) => setYears(Number(e.target.value))} className="w-full accent-brand-600" />
            </div>
          </section>
          <AssumptionsPanel fields={FIELDS} values={a} defaults={DEFAULTS} onChange={setA} onReset={() => setA(DEFAULTS)} busy={sim.isPending} />
        </div>
        <div className="min-w-0 space-y-5">
          <Card
            title="Timeline"
            actions={
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setEvents((es) => [...es, { id: `e${Date.now()}`, year: startYear + 2, type: 'buy', property_ref: `New rental ${es.filter((e) => e.type === 'buy').length + 1}`, amount_cents: $(550_000), debt_cents: $(385_000), rate: 0.065 }])}
              >
                + Add event
              </button>
            }
            bodyClass=""
          >
            <div className="relative mx-4 my-3 h-8">
              <div className="absolute left-0 right-0 top-1/2 h-px bg-ink-200" />
              {Array.from({ length: years }, (_, i) => (
                <span key={i} className="num absolute top-full -translate-x-1/2 pt-0.5 text-[9.5px] text-ink-400" style={{ left: `${(i / Math.max(1, years - 1)) * 100}%` }}>
                  {i % 2 === 0 ? `’${String(startYear + i).slice(2)}` : ''}
                </span>
              ))}
              {events
                .filter((e) => e.year >= startYear && e.year < startYear + years)
                .map((e) => (
                  <span key={e.id} title={`${e.year} ${e.type} ${e.property_ref}`} className={`absolute top-1/2 -translate-x-1/2 -translate-y-1/2 rounded px-1 text-[9.5px] font-semibold uppercase ${TYPE_STYLE[e.type]}`} style={{ left: `${((e.year - startYear) / Math.max(1, years - 1)) * 100}%` }}>
                    {e.type}
                  </span>
                ))}
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="tbl min-w-[720px]">
                <thead>
                  <tr>
                    <th>Year</th>
                    <th>Event</th>
                    <th>Property</th>
                    <th className="r">Price / new value</th>
                    <th className="r">Debt after</th>
                    <th className="r">Rate</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {[...events]
                    .sort((x, y) => x.year - y.year)
                    .map((e) => (
                      <tr key={e.id}>
                        <td>
                          <input aria-label="event year" className="input-num h-7 w-20" type="number" value={e.year} onChange={(ev) => update(e.id, { year: Number(ev.target.value) })} />
                        </td>
                        <td>
                          <select aria-label="event type" className="input h-7 w-28" value={e.type} onChange={(ev) => update(e.id, { type: ev.target.value as SimulationEventType })}>
                            {(['buy', 'sell', 'exchange', 'refi'] as const).map((t) => (
                              <option key={t} value={t}>
                                {t}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          {e.type === 'buy' ? (
                            <input aria-label="new property name" className="input h-7" value={e.property_ref} onChange={(ev) => update(e.id, { property_ref: ev.target.value })} />
                          ) : (
                            <select aria-label="property" className="input h-7" value={e.property_ref} onChange={(ev) => update(e.id, { property_ref: ev.target.value })}>
                              {names.map((n) => (
                                <option key={n}>{n}</option>
                              ))}
                            </select>
                          )}
                        </td>
                        <td className="r">
                          {e.type !== 'sell' && e.type !== 'refi' ? <CentsInput value={e.amount_cents} onChange={(v) => update(e.id, { amount_cents: v })} /> : <span className="text-ink-300">—</span>}
                        </td>
                        <td className="r">{e.type !== 'sell' ? <CentsInput value={e.debt_cents} onChange={(v) => update(e.id, { debt_cents: v })} /> : <span className="text-ink-300">—</span>}</td>
                        <td className="r">
                          {e.type === 'buy' || e.type === 'refi' ? (
                            <input aria-label="rate" className="input-num h-7 w-20" value={((e.rate ?? 0.065) * 100).toFixed(2)} onChange={(ev) => update(e.id, { rate: Number(ev.target.value) / 100 })} />
                          ) : (
                            <span className="text-ink-300">—</span>
                          )}
                        </td>
                        <td>
                          <button type="button" className="text-xs text-ink-400 hover:text-neg-600" onClick={() => setEvents((es) => es.filter((x) => x.id !== e.id))} aria-label="remove event">
                            ✕
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </Card>

          {sim.error && <ErrorBox error={sim.error} />}
          {sim.data && data && (
            <>
              <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md bg-ink-200 shadow-card md:grid-cols-4">
                {(
                  [
                    ['Net worth p10', sim.data.terminal.net_worth.p10],
                    ['Net worth p50', sim.data.terminal.net_worth.p50],
                    ['Net worth p90', sim.data.terminal.net_worth.p90],
                    ['Cumulative taxes p50', sim.data.terminal.cumulative_taxes.p50],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k} className="bg-white px-4 py-3">
                    <div className="label">{k}</div>
                    <div className="num mt-1 text-lg font-semibold">{formatCents(v)}</div>
                  </div>
                ))}
              </div>
              <Card title="Net worth, Monte Carlo bands" actions={<span className="text-xs text-ink-500">{sim.data.runs} runs · p10–p90 shaded, p50 line</span>}>
                <div className="h-64" data-testid="mc-chart">
                  <ResponsiveContainer>
                    <ComposedChart data={data} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                      <CartesianGrid {...gridProps} />
                      <XAxis dataKey="year" {...axisProps} />
                      <YAxis tickFormatter={centsTick} {...axisProps} width={60} />
                      <Tooltip content={<ChartTooltip />} />
                      <Area dataKey="nw_lo" stackId="b" stroke="none" fill="transparent" name="p10" />
                      <Area dataKey="nw_band" stackId="b" stroke="none" fill={SERIES.band} fillOpacity={0.18} name="p10→p90 width" />
                      <Line dataKey="nw_p50" stroke={SERIES.hold} strokeWidth={2} dot={false} name="p50" />
                      {events.map((e) => (
                        <ReferenceLine key={e.id} x={e.year} stroke="#d6d9e0" strokeDasharray="2 3" />
                      ))}
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </Card>
              <div className="grid gap-4 xl:grid-cols-2">
                <Card title="Taxes paid by year">
                  <div className="h-52">
                    <ResponsiveContainer>
                      <ComposedChart data={data} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                        <CartesianGrid {...gridProps} />
                        <XAxis dataKey="year" {...axisProps} />
                        <YAxis tickFormatter={centsTick} {...axisProps} width={54} />
                        <Tooltip content={<ChartTooltip />} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Bar dataKey="tax_p50" name="p50" fill={SERIES.warm} barSize={14} />
                        <Line dataKey="tax_p90" name="p90" stroke={SERIES.neg} strokeDasharray="3 3" dot={false} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title="Equity vs debt (one seeded run)">
                  <div className="h-52">
                    <ResponsiveContainer>
                      <AreaChart data={data} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                        <CartesianGrid {...gridProps} />
                        <XAxis dataKey="year" {...axisProps} />
                        <YAxis tickFormatter={centsTick} {...axisProps} width={60} />
                        <Tooltip content={<ChartTooltip />} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Area dataKey="debt" name="Debt" stackId="1" stroke={SERIES.sell} fill={SERIES.sell} fillOpacity={0.5} />
                        <Area dataKey="equity" name="Equity" stackId="1" stroke={SERIES.hold} fill={SERIES.hold} fillOpacity={0.35} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function CentsInput({ value, onChange }: { value: number | undefined; onChange: (v: number) => void }) {
  const [t, setT] = useState(value === undefined ? '' : Math.round(value / 100).toLocaleString('en-US'));
  useEffect(() => setT(value === undefined ? '' : Math.round(value / 100).toLocaleString('en-US')), [value]);
  return (
    <input
      aria-label="amount"
      className="input-num h-7 w-32"
      value={t}
      onChange={(e) => setT(e.target.value)}
      onBlur={() => {
        const c = parseDollarsToCents(t);
        if (c !== null) onChange(c);
      }}
    />
  );
}
