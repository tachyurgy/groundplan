import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell } from 'recharts';
import { useAnalysis } from '../api/hooks';
import type { PropertyAnalysis } from '../api/types';
import { AssumptionsPanel, type AssumptionField, type AssumptionValues } from '../components/AssumptionsPanel';
import { FigureRow, FigureValue } from '../components/FigureValue';
import { Metric } from '../components/Metric';
import { StatusChip } from '../components/StatusChip';
import { TraceScope } from '../lib/traceContext';
import { ChartTooltip } from '../components/charts';
import { SERIES, axisProps, centsTick, gridProps } from '../lib/chartTheme';
import { Card, ErrorBox, Loading, PageHeader, SeverityTag, Tabs } from '../components/ui';
import { LOAN_TYPE_LABEL, PROPERTY_TYPE_LABEL, formatDate } from '../lib/format';
import { formatCents, formatRate, signClass } from '../lib/money';
import { useDebounced } from '../lib/useDebounced';

type Tab = 'cash' | 'equity' | 'appreciation' | 'depreciation' | 'exit' | 'loans';
const TABS: { id: Tab; label: string }[] = [
  { id: 'cash', label: 'Cash flow' },
  { id: 'equity', label: 'Equity & lendable equity' },
  { id: 'appreciation', label: 'Appreciation' },
  { id: 'depreciation', label: 'Depreciation' },
  { id: 'exit', label: 'Exit tax' },
  { id: 'loans', label: 'Loans' },
];

const PROPERTY_FIELDS: AssumptionField[] = [
  { key: 'current_value_cents', label: 'Current value', kind: 'cents', min: 0 },
  { key: 'appreciation_rate', label: 'Appreciation', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'rent_growth_rate', label: 'Rent growth', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'expense_growth_rate', label: 'Expense growth', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'vacancy_rate', label: 'Vacancy', kind: 'rate', min: 0, max: 0.9 },
  { key: 'capex_reserve_rate', label: 'CapEx reserve (of rent)', kind: 'rate', min: 0, max: 0.5 },
  { key: 'selling_cost_rate', label: 'Selling costs', kind: 'rate', min: 0, max: 0.2 },
  { key: 'land_pct', label: 'Land allocation', kind: 'rate', min: 0, max: 1, hint: 'Land share, bounded to 20-40% (improvements 60-80%), with a note' },
  { key: 'arm_index', label: 'ARM index after reset', kind: 'rate', min: 0, max: 0.2 },
  { key: 'horizon', label: 'Horizon (years)', kind: 'int', min: 1, max: 30 },
];

function defaultsFrom(a: PropertyAnalysis): AssumptionValues {
  const p = a.property;
  return {
    current_value_cents: p.current_value_cents,
    appreciation_rate: p.appreciation_rate,
    rent_growth_rate: p.rent_growth_rate,
    expense_growth_rate: p.expense_growth_rate,
    vacancy_rate: p.vacancy_rate,
    capex_reserve_rate: p.capex_reserve_rate,
    selling_cost_rate: p.selling_cost_rate,
    land_pct: p.land_pct,
    arm_index: 0.04,
    horizon: 10,
  };
}

export function PropertyPage() {
  const { id = '' } = useParams();
  return <PropertyView key={id} id={id} />;
}

function PropertyView({ id }: { id: string }) {
  const [tab, setTab] = useState<Tab>('cash');
  const [overrides, setOverrides] = useState<AssumptionValues>({});
  const params = useDebounced(overrides, 150);
  const q = useAnalysis(id, params as Record<string, number>);
  const a = q.data;
  // Defaults = the property's stored assumptions, captured from the first (override-free) response.
  const [base, setBase] = useState<AssumptionValues | null>(null);
  if (a && !base && Object.keys(params).length === 0) setBase(defaultsFrom(a));
  if (q.isLoading) return <Loading />;
  if (q.error || !a) return <ErrorBox error={q.error ?? 'not found'} />;
  const p = a.property;
  const values = { ...(base ?? defaultsFrom(a)), ...overrides };
  return (
    <TraceScope.Provider value={{ propertyId: id, householdId: p.household_id, params }}>
      <PageHeader
        eyebrow={
          <Link to={`/households/${p.household_id}`} className="hover:text-brand-600">
            ← Portfolio
          </Link>
        }
        title={p.nickname}
        actions={
          <Link to={`/properties/${id}/strategies`} className="btn btn-primary">
            Hold / Sell / 1031 →
          </Link>
        }
      >
        {p.address_line1}, {p.city} {p.state} {p.zip} · {PROPERTY_TYPE_LABEL[p.property_type]}
        {p.units > 1 ? ` · ${p.units} units` : ''} · bought {formatDate(p.purchase_date)} for {formatCents(p.purchase_price_cents)} · analysis year {a.year}
      </PageHeader>

      <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
        <div className="space-y-5 lg:sticky lg:top-16 lg:self-start">
          <AssumptionsPanel fields={PROPERTY_FIELDS} values={values} defaults={base ?? undefined} onChange={(v) => setOverrides(diff(v, base ?? {}))} onReset={() => setOverrides({})} busy={q.isFetching} />
          {a.observations.length > 0 && (
            <Card title="Observations" bodyClass="divide-y divide-ink-100">
              {a.observations.map((o) => (
                <div key={o.id} className="flex gap-2 px-4 py-2 text-xs">
                  <SeverityTag severity={o.severity} />
                  <span className="text-ink-900">{o.message}</span>
                </div>
              ))}
            </Card>
          )}
        </div>

        <div className="min-w-0 space-y-5">
          <section className="card grid grid-cols-2 gap-x-6 gap-y-4 px-4 py-4 md:grid-cols-5">
            <Metric label="Value" figure={a.equity.value} />
            <Metric label="Equity" figure={a.equity.equity} />
            <Metric label="Net cash flow" figure={a.cash_flow.net_cash_flow} signed />
            <Metric label="ROE" figure={a.equity.roe} display={formatRate(a.equity.roe_rate, 1)} />
            <Metric label="Exit tax today" figure={a.exit_tax.exit_tax_total} />
          </section>

          <div className="card">
            <div className="px-2 pt-1">
              <Tabs tabs={TABS} value={tab} onChange={setTab} />
            </div>
            <div className="p-4">
              {tab === 'cash' && <CashTab a={a} />}
              {tab === 'equity' && <EquityTab a={a} />}
              {tab === 'appreciation' && <AppreciationTab a={a} />}
              {tab === 'depreciation' && <DepreciationTab a={a} />}
              {tab === 'exit' && <ExitTab a={a} />}
              {tab === 'loans' && <LoansTab a={a} />}
            </div>
          </div>
        </div>
      </div>
    </TraceScope.Provider>
  );
}

function diff(v: AssumptionValues, base: AssumptionValues): AssumptionValues {
  return Object.fromEntries(Object.entries(v).filter(([k, x]) => base[k] !== x));
}

function CashTab({ a }: { a: PropertyAnalysis }) {
  const c = a.cash_flow;
  const b = c.schedule_e_bridge;
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div>
        <h3 className="mb-2">Engine cash flow, {a.year}</h3>
        <FigureRow label="Gross rent" figure={c.gross_rent} />
        <FigureRow label="Vacancy allowance" figure={c.vacancy_loss} signed indent />
        <FigureRow label="Other income" figure={c.other_income} indent />
        <FigureRow label="Operating expenses" figure={c.operating_expenses} signed indent />
        <FigureRow label="CapEx reserve" figure={c.capex_reserve} signed indent />
        <FigureRow label="Net operating income" figure={c.noi} signed strong />
        <FigureRow label="Debt service (P + I)" figure={c.debt_service} signed indent />
        <FigureRow label="Net cash flow" figure={c.net_cash_flow} signed strong />
      </div>
      <div>
        <h3 className="mb-2">Schedule E → cash-flow bridge</h3>
        <FigureRow label="Line 21 income / (loss)" figure={b.line21} signed />
        <FigureRow label="+ Line 18 depreciation" figure={b.line18_depreciation} indent />
        <FigureRow label="− Principal paid" figure={neg(b.principal_paid)} signed indent />
        <FigureRow label="− Capital improvements paid" figure={neg(b.capital_improvements_paid)} signed indent />
        <FigureRow label="Cash flow from the return" figure={b.cash_flow_from_return} signed strong />
        <FigureRow label="Delta vs engine" figure={b.delta_vs_engine} signed indent />
        <p className="mt-2 text-[11px] text-ink-500">Interest is already inside line 21 and is never subtracted twice. The delta is the planning reserves (vacancy, capex) plus any statement-vs-return interest difference.</p>
      </div>
      <div className="xl:col-span-2">
        <h3 className="mb-2">Projection ({a.horizon} years)</h3>
        <div className="h-56">
          <ResponsiveContainer>
            <ComposedChart data={c.projection} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="year" {...axisProps} />
              <YAxis tickFormatter={centsTick} {...axisProps} width={56} />
              <Tooltip content={<ChartTooltip />} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <ReferenceLine y={0} stroke="#a7adbb" />
              <Bar dataKey="noi_cents" name="NOI" fill={SERIES.hold} barSize={14} />
              <Bar dataKey="debt_service_cents" name="Debt service" fill={SERIES.sell} barSize={14} />
              <Line dataKey="net_cash_flow_cents" name="Net cash flow" stroke={SERIES.warm} strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function neg<T extends { value_cents: number }>(f: T): T {
  return { ...f, value_cents: -f.value_cents };
}

function EquityTab({ a }: { a: PropertyAnalysis }) {
  const e = a.equity;
  const ltv = e.value.value_cents > 0 ? e.total_debt.value_cents / e.value.value_cents : 0;
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div>
        <FigureRow label="Value" figure={e.value} />
        <FigureRow label="Total debt (all liens)" figure={neg(e.total_debt)} signed indent />
        <FigureRow label="Equity" figure={e.equity} strong />
        <FigureRow label="Lendable equity (70% LTV)" figure={e.lendable_equity} />
        <FigureRow label="ROE numerator" figure={e.roe} signed />
        <div className="flex justify-between py-1 text-sm">
          <span className="text-ink-700">ROE</span>
          <span className="num">{formatRate(e.roe_rate)}</span>
        </div>
        <div className="flex justify-between py-1 text-sm">
          <span className="text-ink-700">Current LTV</span>
          <span className="num">{formatRate(ltv, 1)}</span>
        </div>
      </div>
      <div>
        <h3 className="mb-2">Capital stack</h3>
        <div className="h-10 overflow-hidden rounded bg-ink-100" aria-label="capital stack">
          <div className="flex h-full">
            <div className="flex h-full items-center bg-ink-700 px-2 text-[11px] text-white" style={{ width: `${Math.min(100, ltv * 100)}%` }}>
              {ltv > 0.12 ? 'Debt' : ''}
            </div>
            <div className="flex h-full items-center bg-brand-500 px-2 text-[11px] text-white" style={{ width: `${Math.max(0, Math.min(100 - ltv * 100, 70 - ltv * 100))}%` }}>
              {e.lendable_equity.value_cents > 0 ? 'Lendable' : ''}
            </div>
            <div className="flex h-full flex-1 items-center bg-brand-100 px-2 text-[11px] text-brand-700">Equity</div>
          </div>
        </div>
        <div className="mt-1 flex justify-between text-[11px] text-ink-500">
          <span>0%</span>
          <span>70% LTV line</span>
          <span>100%</span>
        </div>
        <ul className="mt-4 space-y-1 text-xs text-ink-700">
          {a.loans.map((l) => (
            <li key={l.loan.id} className="flex justify-between">
              <span>
                Lien {l.loan.lien_position}: {l.loan.lender} ({LOAN_TYPE_LABEL[l.loan.loan_type]}){l.loan.is_paid_off ? ' · paid off' : ''}
              </span>
              <span className="num">{formatCents(l.loan.balance_cents)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function AppreciationTab({ a }: { a: PropertyAnalysis }) {
  const ap = a.appreciation;
  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-8">
        <div>
          <div className="label">CAGR since purchase</div>
          <div className="num mt-1 text-lg font-semibold">{formatRate(ap.cagr_since_purchase)}</div>
        </div>
        <div>
          <div className="label">Projected value, {a.year + a.horizon}</div>
          <div className="mt-1 text-lg font-semibold">
            <FigureValue figure={ap.projected_value_horizon} chip />
          </div>
        </div>
      </div>
      <div className="h-64">
        <ResponsiveContainer>
          <AreaChart data={ap.projected} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="year" {...axisProps} />
            <YAxis tickFormatter={centsTick} {...axisProps} width={60} />
            <Tooltip content={<ChartTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Area dataKey="debt_cents" name="Debt" stackId="1" stroke={SERIES.sell} fill={SERIES.sell} fillOpacity={0.5} />
            <Area dataKey="equity_cents" name="Equity" stackId="1" stroke={SERIES.hold} fill={SERIES.hold} fillOpacity={0.35} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function DepreciationTab({ a }: { a: PropertyAnalysis }) {
  const d = a.depreciation;
  const rows = d.schedule;
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_1.1fr]">
      <div>
        <FigureRow label="Depreciable basis" figure={d.depreciable_basis} />
        <FigureRow label={`Depreciation ${a.year}`} figure={d.annual} />
        <FigureRow label={`Accumulated through ${a.year}`} figure={d.accumulated} strong />
        <p className="mt-2 text-[11px] text-ink-500">
          Method {d.method === 'sl_27_5' ? '27.5-yr straight line, mid-month (Pub 946 Table A-6)' : d.method}. {d.land_pct_bounded ? 'Land share was bounded to 20-40%.' : ''} Recapture uses allowable even where the return claimed less.
        </p>
        <div className="mt-4 h-52">
          <ResponsiveContainer>
            <BarChart data={rows} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="year" {...axisProps} interval="preserveStartEnd" />
              <YAxis tickFormatter={centsTick} {...axisProps} width={52} />
              <Tooltip content={<ChartTooltip />} />
              <Bar dataKey="amount_cents" name="Depreciation" barSize={10}>
                {rows.map((r) => (
                  <Cell key={r.year} fill={r.year > a.year ? '#a7adbb' : SERIES.hold} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="max-h-[420px] overflow-y-auto">
        <table className="tbl">
          <thead className="sticky top-0 bg-white">
            <tr>
              <th>Year</th>
              <th className="r">Table %</th>
              <th className="r">Amount</th>
              <th className="r">Cumulative</th>
            </tr>
          </thead>
          <tbody>
            {rows.reduce<{ el: JSX.Element[]; cum: number }>(
              (acc, r) => {
                acc.cum += r.amount_cents;
                acc.el.push(
                  <tr key={r.year} className={r.year > a.year ? 'text-ink-400' : ''}>
                    <td className="num">
                      {r.year}
                      {r.year > a.year ? ' (proj.)' : ''}
                    </td>
                    <td className="r num">{r.pct?.toFixed(3) ?? '—'}</td>
                    <td className="r num">{formatCents(r.amount_cents)}</td>
                    <td className="r num">{formatCents(acc.cum)}</td>
                  </tr>,
                );
                return acc;
              },
              { el: [], cum: 0 },
            ).el}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const EXIT_PARTS = [
  { k: 'fed_1250', label: '§1250 (≤25%)', color: SERIES.hold },
  { k: 'fed_1245', label: '§1245', color: '#5b6478' },
  { k: 'fed_ltcg', label: 'LTCG', color: SERIES.accent },
  { k: 'niit', label: 'NIIT', color: SERIES.warm },
  { k: 'state', label: 'State', color: SERIES.exchange },
] as const;

function ExitTab({ a }: { a: PropertyAnalysis }) {
  const x = a.exit_tax;
  const row: Record<string, number | string> = { name: 'Exit tax' };
  for (const part of EXIT_PARTS) row[part.k] = x[part.k].value_cents;
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div>
        <h3 className="mb-2">Sale this year</h3>
        <FigureRow label="Sale price" figure={x.sale_price} />
        <FigureRow label="Selling costs" figure={x.selling_costs} signed indent />
        <FigureRow label="Loan payoffs" figure={x.loan_payoffs} signed indent />
        <FigureRow label="Net before tax" figure={x.net_before_tax} strong />
        <div className="mt-3" />
        <FigureRow label="Adjusted basis" figure={x.adjusted_basis} />
        <FigureRow label="Total gain" figure={x.total_gain} />
        <FigureRow label="Unrecaptured §1250" figure={x.unrecaptured_1250} indent />
        <FigureRow label="§1245 recapture" figure={x.sec1245} indent />
        <FigureRow label="Long-term capital gain" figure={x.ltcg} indent />
        <div className="mt-3" />
        <FigureRow label="Federal on §1250" figure={x.fed_1250} indent />
        <FigureRow label="Federal on §1245" figure={x.fed_1245} indent />
        <FigureRow label="Federal LTCG" figure={x.fed_ltcg} indent />
        <FigureRow label="NIIT" figure={x.niit} indent />
        <FigureRow label={x.state.label ?? 'State'} figure={x.state} indent />
        <FigureRow label="Exit tax total" figure={x.exit_tax_total} strong />
        <FigureRow label="Net proceeds after tax" figure={x.net_proceeds} signed strong />
      </div>
      <div>
        <h3 className="mb-2">Composition</h3>
        <div className="h-24">
          <ResponsiveContainer>
            <BarChart data={[row]} layout="vertical" margin={{ top: 0, right: 8, left: 0, bottom: 0 }}>
              <XAxis type="number" tickFormatter={centsTick} {...axisProps} />
              <YAxis type="category" dataKey="name" hide />
              <Tooltip content={<ChartTooltip />} cursor={false} />
              {EXIT_PARTS.map((part) => (
                <Bar key={part.k} dataKey={part.k} name={part.label} stackId="t" fill={part.color} barSize={28} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-700">
          {EXIT_PARTS.map((part) => (
            <span key={part.k} className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm" style={{ background: part.color }} />
              {part.label} <span className="num text-ink-950">{formatCents(x[part.k].value_cents)}</span>
            </span>
          ))}
        </div>
        <h3 className="mb-2 mt-5">How the gain stacks</h3>
        <ol className="space-y-1.5 text-xs leading-relaxed text-ink-700">
          {x.stacking_notes.map((n, i) => (
            <li key={i} className="flex gap-2">
              <span className="num mt-px h-4 w-4 shrink-0 rounded-full bg-ink-100 text-center text-[10px] leading-4 text-ink-700">{i + 1}</span>
              <span>{n}</span>
            </li>
          ))}
        </ol>
        <div className="mt-4 flex items-center gap-2 text-[11px] text-ink-500">
          Status of the total: <StatusChip status={x.exit_tax_total.status} />
        </div>
      </div>
    </div>
  );
}

const MARKER_LABEL: Record<string, string> = { io: 'IO', arm_reset: 'ARM reset', balloon: 'Balloon', maturity: 'Maturity' };

function LoansTab({ a }: { a: PropertyAnalysis }) {
  if (!a.loans.length) return <p className="text-sm text-ink-500">No loans on this property.</p>;
  return (
    <div className="space-y-6">
      {a.loans.map((l) => {
        const resetYear = l.annual.find((y) => y.marker === 'arm_reset')?.year;
        const ioEndYear = [...l.annual].reverse().find((y) => y.marker === 'io')?.year;
        return (
          <div key={l.loan.id}>
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h3>
                Lien {l.loan.lien_position} · {l.loan.lender}{' '}
                <span className="ml-1 rounded bg-ink-100 px-1.5 py-px text-[10.5px] font-semibold uppercase text-ink-700">{LOAN_TYPE_LABEL[l.loan.loan_type]}</span>
                {l.loan.is_paid_off && <span className="ml-1 rounded bg-pos-100 px-1.5 py-px text-[10.5px] font-semibold uppercase text-pos-600">Paid off</span>}
              </h3>
              <div className="flex flex-wrap gap-4 text-xs text-ink-700">
                <span>
                  Rate <span className="num">{formatRate(l.loan.rate, 3)}</span>
                </span>
                <span>
                  Balance <FigureValue figure={l.balance_at_year_end} />
                </span>
                <span>
                  Debt service <FigureValue figure={l.annual_debt_service} />
                </span>
                <span>
                  DSCR <FigureValue figure={l.dscr} display={(l.dscr.value_cents / 100).toFixed(2)} />
                </span>
                <span>Matures {formatDate(l.loan.maturity_date)}</span>
              </div>
            </div>
            <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
              <div className="h-44">
                <ResponsiveContainer>
                  <ComposedChart data={l.annual} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                    <CartesianGrid {...gridProps} />
                    <XAxis dataKey="year" {...axisProps} />
                    <YAxis tickFormatter={centsTick} {...axisProps} width={52} />
                    <Tooltip content={<ChartTooltip />} />
                    <Bar dataKey="interest_cents" name="Interest" stackId="ds" fill={SERIES.sell} barSize={12} />
                    <Bar dataKey="principal_cents" name="Principal" stackId="ds" fill={SERIES.hold} barSize={12} />
                    {ioEndYear && <ReferenceLine x={ioEndYear} stroke={SERIES.warm} strokeDasharray="3 3" label={{ value: 'IO ends', fontSize: 10, fill: SERIES.warm, position: 'insideTopRight' }} />}
                    {resetYear && <ReferenceLine x={resetYear} stroke={SERIES.neg} strokeDasharray="3 3" label={{ value: 'ARM reset', fontSize: 10, fill: SERIES.neg, position: 'insideTopLeft' }} />}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div className="max-h-44 overflow-y-auto">
                <table className="tbl">
                  <thead className="sticky top-0 bg-white">
                    <tr>
                      <th>Year</th>
                      <th className="r">Rate</th>
                      <th className="r">Principal</th>
                      <th className="r">Interest</th>
                      <th className="r">Balance</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {l.annual.map((y) => (
                      <tr key={y.year}>
                        <td className="num">{y.year}</td>
                        <td className="r num">{formatRate(y.rate, 3)}</td>
                        <td className="r num">{formatCents(y.principal_cents)}</td>
                        <td className="r num">{formatCents(y.interest_cents)}</td>
                        <td className={`r num ${signClass(0)}`}>{formatCents(y.balance_end_cents)}</td>
                        <td>{y.marker && <span className="rounded bg-est-100 px-1 py-px text-[10px] font-semibold uppercase text-est-600">{MARKER_LABEL[y.marker]}</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
