import { keepPreviousData, useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { Link, getRouteApi } from '@tanstack/react-router';
import { Dialog } from 'radix-ui';
import { startTransition, useActionState, useDeferredValue, useState } from 'react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { z } from 'zod';
import { analysisQuery, usePatchProperty, type Params } from '../api/queries';
import type { AnalysisT, FigureT, LoanSummaryT, LoanMonthT } from '../api/schemas';
import { C, ChartFrame, TooltipBody, centsTick, gridProps, useNarrow, xAxisProps, yAxisProps } from '../charts/kit';
import { AssumptionsForm, type FieldDef, type Values } from '../components/AssumptionsForm';
import { SaleWaterfall, StackingExplainer, TaxLayersBar } from '../components/ExitTaxViz';
import { FigureRow, FigureValue } from '../components/FigureValue';
import { HorizonSlider } from '../components/HorizonSlider';
import { KpiTile } from '../components/KpiTile';
import { Card, PageHeader, SeverityTag, TabPanel, Tabs } from '../components/ui';
import { VirtualTable } from '../components/VirtualTable';
import { LOAN_TYPE_LABEL, PROPERTY_TYPE_LABEL, formatDate } from '../lib/format';
import { formatCents, formatCentsCompact, formatRate, parseDollarsToCents } from '../lib/money';
import { PROPERTY_TABS, overridesOnly, type PropertySearch, type PropertyTab } from '../lib/search';
import { TraceScope } from '../lib/traceScope';

const route = getRouteApi('/properties/$propertyId');

const TAB_LABEL: Record<PropertyTab, string> = { cash: 'Cash flow', equity: 'Equity', appreciation: 'Appreciation', depreciation: 'Depreciation', exit: 'Exit tax', loans: 'Loans' };

const FIELDS: FieldDef[] = [
  { key: 'current_value_cents', label: 'Current value', kind: 'cents', min: 0, max: 100_000_000_00 },
  { key: 'appreciation_rate', label: 'Appreciation', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'rent_growth_rate', label: 'Rent growth', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'expense_growth_rate', label: 'Expense growth', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'vacancy_rate', label: 'Vacancy', kind: 'rate', min: 0, max: 0.9 },
  { key: 'capex_reserve_rate', label: 'CapEx reserve (of rent)', kind: 'rate', min: 0, max: 0.5 },
  { key: 'selling_cost_rate', label: 'Selling costs', kind: 'rate', min: 0, max: 0.2 },
  { key: 'land_pct', label: 'Land share', kind: 'rate', min: 0, max: 1, hint: 'Land share is bounded to 20-40% by the engine, with a note' },
  { key: 'arm_index', label: 'ARM index after reset', kind: 'rate', min: 0, max: 0.2 },
];
const DEFAULT_HORIZON = 10;
const ARM_INDEX_DEFAULT = 0.04;

function baseValues(a: AnalysisT): Values {
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
    arm_index: ARM_INDEX_DEFAULT,
  };
}

const deduct = (f: FigureT) => (f.value_cents === 0 ? formatCents(0) : `−${formatCents(Math.abs(f.value_cents))}`);

export function PropertyPage() {
  const { propertyId } = route.useParams();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const narrow = useNarrow();
  const base = useSuspenseQuery(analysisQuery(propertyId, {})).data;

  // Horizon: the slider moves a local draft every frame; the query follows a *deferred* copy, so dragging
  // never blocks input; the URL is written once, on release.
  const [draft, setDraft] = useState<number | null>(null);
  const horizon = draft ?? search.horizon ?? DEFAULT_HORIZON;
  const deferredHorizon = useDeferredValue(horizon);

  const { tab: _tab, horizon: _h, ...overrides } = search;
  const params: Params = { ...overrides, horizon: deferredHorizon === DEFAULT_HORIZON ? undefined : deferredHorizon };
  const live = useQuery({ ...analysisQuery(propertyId, params), placeholderData: keepPreviousData });
  const a = live.data ?? base;
  const recomputing = live.isFetching || deferredHorizon !== horizon;

  const defaults = baseValues(base);
  const values: Values = { ...defaults, ...(overrides as Values) };
  const p = a.property;
  const tab: PropertyTab = search.tab ?? 'cash';
  const setSearch = (next: Partial<PropertySearch>) => startTransition(() => navigate({ search: (prev) => ({ ...prev, ...next }), replace: true, resetScroll: false }));

  return (
    <TraceScope.Provider value={{ propertyId, householdId: p.household_id, params }}>
      <PageHeader
        back={
          <Link to="/households/$householdId" params={{ householdId: p.household_id }} className="text-ink-500 hover:text-ink-900 hover:underline">
            Portfolio
          </Link>
        }
        title={p.nickname}
        actions={
          <>
            <EditPropertyDialog a={base} />
            <Link to="/properties/$propertyId/strategies" params={{ propertyId }} className="btn btn-primary">
              Hold, sell or 1031
            </Link>
          </>
        }
      >
        {p.address_line1}, {p.city} {p.state} {p.zip}. {PROPERTY_TYPE_LABEL[p.property_type] ?? p.property_type}
        {p.units > 1 ? `, ${p.units} units` : ''}. Bought {formatDate(p.purchase_date)} for {formatCents(p.purchase_price_cents)}. Analysis year {a.year}.
      </PageHeader>

      {/* phones: the three numbers that matter stay pinned while scrolling through tabs */}
      <div className="sticky top-14 z-20 -mx-4 mb-4 grid grid-cols-3 gap-2 border-b border-ink-100 bg-page/95 px-4 py-2 backdrop-blur lg:hidden" data-testid="sticky-figures">
        {(
          [
            ['Equity', a.equity.equity, false],
            ['Cash flow', a.cash_flow.net_cash_flow, true],
            ['Exit tax', a.exit_tax.exit_tax_total, false],
          ] as const
        ).map(([k, f, s]) => (
          <div key={k} className="min-w-0">
            <div className="text-[11px] text-ink-500">{k}</div>
            <div className="text-sm font-medium">
              <FigureValue figure={f} signed={s} compact />
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
        <div className="order-2 space-y-5 lg:sticky lg:top-16 lg:order-1 lg:self-start">
          <Card>
            <HorizonSlider value={horizon} onChange={setDraft} onCommit={(v) => { setSearch({ horizon: v === DEFAULT_HORIZON ? undefined : v }); setDraft(null); }} label="Projection horizon" />
          </Card>
          <AssumptionsForm
            title="Assumptions"
            fields={FIELDS}
            values={values}
            defaults={defaults}
            busy={recomputing}
            onCommit={(v) => setSearch({ ...Object.fromEntries(FIELDS.map((f) => [f.key, undefined])), ...overridesOnly(v, defaults) })}
            onReset={() => startTransition(() => navigate({ search: { tab: search.tab }, replace: true, resetScroll: false }))}
          />
          {a.observations.length > 0 && (
            <Card title="Observations" bodyClass="divide-y divide-ink-100">
              {a.observations.map((o) => (
                <div key={o.id} className="flex items-start gap-2 px-4 py-2 text-xs">
                  <SeverityTag severity={o.severity} />
                  <span className="min-w-0 text-ink-900">{o.message}</span>
                </div>
              ))}
            </Card>
          )}
        </div>

        <div className="order-1 min-w-0 space-y-5 lg:order-2">
          <section aria-label="Key figures" className={`grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-ink-100 shadow-card transition-opacity md:grid-cols-5 ${recomputing ? 'opacity-80' : ''}`}>
            <KpiTile label="Value" figure={a.equity.value} />
            <KpiTile label="Equity" figure={a.equity.equity} />
            <KpiTile label="Net cash flow" figure={a.cash_flow.net_cash_flow} signed />
            <KpiTile label="ROE" figure={a.equity.roe} display={formatRate(a.equity.roe_rate, 1)} />
            <div className="col-span-2 flex md:col-span-1 [&>*]:flex-1">
              <KpiTile label="Exit tax today" figure={a.exit_tax.exit_tax_total} />
            </div>
          </section>

          <div className="card">
            <Tabs label="Analysis" tabs={PROPERTY_TABS.map((id) => ({ id, label: TAB_LABEL[id] }))} value={tab} onChange={(t) => setSearch({ tab: t === 'cash' ? undefined : t })}>
              <div className="p-4">
                <TabPanel value="cash">
                  <CashTab a={a} narrow={narrow} />
                </TabPanel>
                <TabPanel value="equity">
                  <EquityTab a={a} />
                </TabPanel>
                <TabPanel value="appreciation">
                  <AppreciationTab a={a} narrow={narrow} />
                </TabPanel>
                <TabPanel value="depreciation">
                  <DepreciationTab a={a} narrow={narrow} />
                </TabPanel>
                <TabPanel value="exit">
                  <ExitTab a={a} />
                </TabPanel>
                <TabPanel value="loans">
                  <LoansTab a={a} narrow={narrow} />
                </TabPanel>
              </div>
            </Tabs>
          </div>
        </div>
      </div>
    </TraceScope.Provider>
  );
}

function CashTab({ a, narrow }: { a: AnalysisT; narrow: boolean }) {
  const c = a.cash_flow;
  const b = c.schedule_e_bridge;
  const last = c.projection[c.projection.length - 1];
  return (
    <div className="grid gap-x-8 gap-y-6 xl:grid-cols-2">
      <div>
        <h3 className="mb-1">Engine cash flow, {a.year}</h3>
        <FigureRow label="Gross rent" figure={c.gross_rent} />
        <FigureRow label="Vacancy allowance" figure={c.vacancy_loss} indent display={deduct(c.vacancy_loss)} />
        <FigureRow label="Other income" figure={c.other_income} indent />
        <FigureRow label="Operating expenses" figure={c.operating_expenses} indent display={deduct(c.operating_expenses)} />
        <FigureRow label="CapEx reserve" figure={c.capex_reserve} indent display={deduct(c.capex_reserve)} />
        <FigureRow label="Net operating income" figure={c.noi} signed strong />
        <FigureRow label="Debt service (principal + interest)" figure={c.debt_service} indent display={deduct(c.debt_service)} />
        <FigureRow label="Net cash flow" figure={c.net_cash_flow} signed strong />
      </div>
      <div>
        <h3 className="mb-1">Schedule E to cash flow</h3>
        <FigureRow label="Line 21 income or loss" figure={b.line21} signed />
        <FigureRow label="Add back line 18 depreciation" figure={b.line18_depreciation} indent />
        <FigureRow label="Less principal paid" figure={b.principal_paid} indent display={deduct(b.principal_paid)} />
        <FigureRow label="Less capital improvements paid" figure={b.capital_improvements_paid} indent display={deduct(b.capital_improvements_paid)} />
        <FigureRow label="Cash flow from the return" figure={b.cash_flow_from_return} signed strong />
        <FigureRow label="Difference vs engine" figure={b.delta_vs_engine} signed indent />
        <p className="mt-2 text-[11px] leading-relaxed text-ink-500">Interest is already inside line 21 and is never subtracted twice. The difference is the planning reserves (vacancy, capex) plus any statement-vs-return interest gap.</p>
      </div>
      <div className="xl:col-span-2">
        <ChartFrame
          testId="chart-cash-projection"
          title={`Projection, ${c.projection.length} years`}
          summary={last ? `Net cash flow moves from ${formatCents(c.projection[0].net_cash_flow_cents)} to ${formatCents(last.net_cash_flow_cents)} by ${last.year} as rents and expenses grow.` : 'No projection.'}
          legend={[
            { label: 'NOI', color: C.s1 },
            { label: 'Debt service', color: C.muted },
            { label: 'Net cash flow', color: C.s2, dashed: false },
          ]}
          height={narrow ? 200 : 240}
          table={{
            columns: [
              { key: 'year', label: 'Year' },
              { key: 'noi_cents', label: 'NOI', money: true },
              { key: 'debt_service_cents', label: 'Debt service', money: true },
              { key: 'net_cash_flow_cents', label: 'Net cash flow', money: true },
            ],
            rows: c.projection,
          }}
        >
          <ResponsiveContainer>
            <ComposedChart data={c.projection} margin={{ top: 6, right: 6, left: 0, bottom: 0 }} barGap={2}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="year" {...xAxisProps} interval={narrow ? 'preserveStartEnd' : 0} minTickGap={8} />
              <YAxis tickFormatter={centsTick} {...yAxisProps} />
              <Tooltip cursor={{ fill: 'var(--ink-50)' }} content={(p) => <TooltipBody {...p} />} />
              <ReferenceLine y={0} stroke="var(--axis)" />
              <Bar dataKey="noi_cents" name="NOI" fill={C.s1} maxBarSize={narrow ? 8 : 14} radius={[3, 3, 0, 0]} isAnimationActive={false} />
              <Bar dataKey="debt_service_cents" name="Debt service" fill={C.muted} maxBarSize={narrow ? 8 : 14} radius={[3, 3, 0, 0]} isAnimationActive={false} />
              <Line dataKey="net_cash_flow_cents" name="Net cash flow" stroke={C.s2} strokeWidth={2} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartFrame>
      </div>
    </div>
  );
}

function EquityTab({ a }: { a: AnalysisT }) {
  const e = a.equity;
  const value = Math.max(1, e.value.value_cents);
  const debtPct = Math.min(1, e.total_debt.value_cents / value);
  const lendPct = Math.max(0, Math.min(0.7, 0.7) - debtPct);
  return (
    <div className="grid gap-x-8 gap-y-6 xl:grid-cols-2">
      <div>
        <FigureRow label="Value" figure={e.value} />
        <FigureRow label="Total debt, all liens" figure={e.total_debt} indent display={deduct(e.total_debt)} />
        <FigureRow label="Equity" figure={e.equity} strong />
        <FigureRow label="Lendable equity (to 70% loan-to-value)" figure={e.lendable_equity} />
        <FigureRow label="Return on equity" figure={e.roe} display={formatRate(e.roe_rate, 2)} hint="(cash flow + principal paydown + appreciation) ÷ equity at start of year" />
        <div className="flex justify-between py-1.5 text-sm">
          <span className="text-ink-700">Loan-to-value today</span>
          <span className="num">{formatRate(debtPct, 1)}</span>
        </div>
      </div>
      <div>
        <h3 className="mb-2">Capital stack</h3>
        <div className="flex h-11 gap-[2px] overflow-hidden rounded-md" role="img" aria-label={`Debt ${formatRate(debtPct, 0)}, lendable equity ${formatRate(lendPct, 0)}, remaining equity ${formatRate(1 - debtPct - lendPct, 0)} of value`} data-testid="capital-stack">
          {debtPct > 0 && (
            <div className="flex items-center bg-[var(--series-muted)] px-2 text-[11px] font-medium text-ink-950" style={{ width: `${debtPct * 100}%` }}>
              {debtPct > 0.12 ? 'Debt' : ''}
            </div>
          )}
          {lendPct > 0 && (
            <div className="flex items-center px-2 text-[11px] font-medium text-white" style={{ width: `${lendPct * 100}%`, background: 'var(--series-1)' }}>
              {lendPct > 0.14 ? 'Lendable' : ''}
            </div>
          )}
          <div className="flex flex-1 items-center bg-brand-100 px-2 text-[11px] font-medium text-brand-700">Equity</div>
        </div>
        <div className="relative mt-1 h-4 text-[11px] text-ink-500">
          <span className="absolute left-0">0%</span>
          <span className="absolute -translate-x-1/2" style={{ left: '70%' }}>
            70% line
          </span>
          <span className="absolute right-0">100%</span>
        </div>
        <ul className="mt-4 divide-y divide-ink-100 text-sm">
          {a.loans.map((l) => (
            <li key={l.loan.id} className="flex items-baseline justify-between gap-3 py-1.5">
              <span className="min-w-0 text-ink-700">
                Lien {l.loan.lien_position}: {l.loan.lender} ({LOAN_TYPE_LABEL[l.loan.loan_type] ?? l.loan.loan_type}){l.loan.is_paid_off ? ', paid off' : ''}
              </span>
              <span className="num shrink-0">{formatCents(l.loan.balance_cents)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function AppreciationTab({ a, narrow }: { a: AnalysisT; narrow: boolean }) {
  const ap = a.appreciation;
  const first = ap.projected[0];
  const last = ap.projected[ap.projected.length - 1];
  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-x-10 gap-y-3">
        <div>
          <div className="label">Growth since purchase (CAGR)</div>
          <div className="num mt-1 text-lg font-medium">{ap.cagr_since_purchase === null || ap.cagr_since_purchase === undefined ? '—' : formatRate(ap.cagr_since_purchase)}</div>
        </div>
        <div>
          <div className="label">Projected value, {last?.year ?? a.year + a.horizon}</div>
          <div className="mt-1 text-lg font-medium">
            <FigureValue figure={ap.projected_value_horizon} chip />
          </div>
        </div>
      </div>
      <ChartFrame
        testId="chart-appreciation"
        title="Value split into equity and debt"
        summary={first && last ? `Equity grows from ${formatCents(first.equity_cents)} to ${formatCents(last.equity_cents)} while debt falls from ${formatCents(first.debt_cents)} to ${formatCents(last.debt_cents)}.` : ''}
        legend={[
          { label: 'Equity', color: C.s1 },
          { label: 'Debt', color: C.muted },
        ]}
        height={narrow ? 220 : 280}
        table={{
          columns: [
            { key: 'year', label: 'Year' },
            { key: 'value_cents', label: 'Value', money: true },
            { key: 'equity_cents', label: 'Equity', money: true },
            { key: 'debt_cents', label: 'Debt', money: true },
          ],
          rows: ap.projected,
        }}
      >
        <ResponsiveContainer>
          <AreaChart data={ap.projected} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="year" {...xAxisProps} minTickGap={12} />
            <YAxis tickFormatter={centsTick} {...yAxisProps} />
            <Tooltip content={(p) => <TooltipBody {...p} />} />
            <Area dataKey="debt_cents" name="Debt" stackId="v" stroke={C.muted} fill={C.muted} fillOpacity={0.35} strokeWidth={2} isAnimationActive={false} />
            <Area dataKey="equity_cents" name="Equity" stackId="v" stroke={C.s1} fill={C.s1} fillOpacity={0.14} strokeWidth={2} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </ChartFrame>
    </div>
  );
}

function DepreciationTab({ a, narrow }: { a: AnalysisT; narrow: boolean }) {
  const d = a.depreciation;
  const rows = withCumulative(d.schedule, a.year);
  return (
    <div className="grid gap-x-8 gap-y-6 xl:grid-cols-[1fr_1.1fr]">
      <div>
        <FigureRow label="Depreciable basis" figure={d.depreciable_basis} />
        <FigureRow label={`Depreciation ${a.year}`} figure={d.annual} />
        <FigureRow label={`Accumulated through ${a.year}`} figure={d.accumulated} strong />
        <p className="mt-2 mb-4 text-[11px] leading-relaxed text-ink-500">
          {d.method === 'sl_27_5' ? '27.5-year straight line, mid-month convention (IRS Pub 946 Table A-6).' : d.method === 'sl_39' ? '39-year straight line, mid-month.' : `Method: ${d.method}.`} {d.land_pct_bounded ? 'Land share was bounded to 20-40%. ' : ''}Recapture uses allowable depreciation even where a return claimed less.
        </p>
        <ChartFrame
          testId="chart-depreciation"
          title="Depreciation by year"
          summary={`${formatCents(d.accumulated.value_cents)} claimed or allowable through ${a.year}; later bars are projected.`}
          legend={[
            { label: 'Taken', color: C.s1 },
            { label: 'Projected', color: C.muted },
          ]}
          height={narrow ? 180 : 210}
          table={{ columns: [{ key: 'year', label: 'Year' }, { key: 'amount_cents', label: 'Amount', money: true }], rows }}
        >
          <ResponsiveContainer>
            <BarChart data={rows} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="year" {...xAxisProps} minTickGap={14} />
              <YAxis tickFormatter={centsTick} {...yAxisProps} />
              <Tooltip cursor={{ fill: 'var(--ink-50)' }} content={(p) => <TooltipBody {...p} />} />
              <Bar dataKey="amount_cents" name="Depreciation" maxBarSize={12} radius={[3, 3, 0, 0]} isAnimationActive={false}>
                {rows.map((r) => (
                  <Cell key={r.year} fill={r.projected ? C.muted : C.s1} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartFrame>
      </div>
      <div>
        <h3 className="mb-2">Schedule</h3>
        <VirtualTable
          testId="depreciation-table"
          label="Depreciation schedule"
          rows={rows}
          height={420}
          rowClass={(r) => (r.projected ? 'text-ink-500' : '')}
          cols={[
            { key: 'year', label: 'Year', width: '5.5rem', render: (r) => <span className="num">{r.year}{r.projected ? '*' : ''}</span> },
            { key: 'pct', label: 'Table %', right: true, render: (r) => (r.pct === null || r.pct === undefined ? '—' : Number(r.pct).toFixed(3)) },
            { key: 'amt', label: 'Amount', right: true, render: (r) => formatCents(r.amount_cents) },
            { key: 'cum', label: 'Cumulative', right: true, render: (r) => formatCents(r.cum) },
          ]}
        />
        <p className="mt-1 text-[11px] text-ink-500">* projected</p>
      </div>
    </div>
  );
}

function withCumulative(schedule: AnalysisT['depreciation']['schedule'], year: number) {
  return schedule.reduce<(AnalysisT['depreciation']['schedule'][number] & { cum: number; projected: boolean })[]>((out, r) => {
    out.push({ ...r, cum: (out.length ? out[out.length - 1].cum : 0) + r.amount_cents, projected: r.year > year });
    return out;
  }, []);
}

function ExitTab({ a }: { a: AnalysisT }) {
  const x = a.exit_tax;
  return (
    <div className="space-y-8">
      <div className="grid gap-x-8 gap-y-6 xl:grid-cols-2">
        <SaleWaterfall x={x} title={`Sale in ${a.year}: where the price goes`} />
        <div>
          <h3 className="mb-1">The numbers</h3>
          <FigureRow label="Adjusted basis" figure={x.adjusted_basis} />
          <FigureRow label="Total gain" figure={x.total_gain} />
          <FigureRow label="Unrecaptured §1250 gain" figure={x.unrecaptured_1250} indent />
          <FigureRow label="§1245 recapture" figure={x.sec1245} indent />
          <FigureRow label="Long-term capital gain" figure={x.ltcg} indent />
          <FigureRow label="Exit tax total" figure={x.exit_tax_total} strong />
          <FigureRow label="Net proceeds after tax" figure={x.net_proceeds} signed strong />
        </div>
      </div>
      <TaxLayersBar x={x} />
      <StackingExplainer x={x} />
    </div>
  );
}

const MARKER_LABEL: Record<string, string> = { io: 'IO', arm_reset: 'ARM reset', balloon: 'Balloon', maturity: 'Maturity' };

function LoansTab({ a, narrow }: { a: AnalysisT; narrow: boolean }) {
  if (!a.loans.length) return <p className="text-sm text-ink-500">No loans on this property: it is owned free and clear.</p>;
  return (
    <div className="space-y-10">
      {a.loans.map((l) => (
        <LoanBlock key={l.loan.id} l={l} narrow={narrow} />
      ))}
    </div>
  );
}

function LoanBlock({ l, narrow }: { l: LoanSummaryT; narrow: boolean }) {
  const resetYear = l.annual.find((y) => y.marker === 'arm_reset')?.year;
  const ioYears = l.annual.filter((y) => y.marker === 'io').map((y) => y.year);
  const ioEndYear = ioYears.length ? ioYears[ioYears.length - 1] + 1 : undefined;
  const months = l.months ?? [];
  const active = l.annual.some((y) => y.principal_cents + y.interest_cents > 0);
  return (
    <section aria-label={`Lien ${l.loan.lien_position}`}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="flex flex-wrap items-center gap-2">
          Lien {l.loan.lien_position}: {l.loan.lender}
          <span className="chip bg-ink-100 text-ink-700 ring-ink-200">{LOAN_TYPE_LABEL[l.loan.loan_type] ?? l.loan.loan_type}</span>
          {l.loan.is_paid_off && <span className="chip bg-pos-100 text-pos-600 ring-pos-600/25">Paid off</span>}
        </h3>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-700">
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
            DSCR <FigureValue figure={l.dscr} display={(l.dscr.ratio ?? l.dscr.value_cents / 100).toFixed(2)} />
          </span>
          {l.loan.maturity_date && <span>Matures {formatDate(l.loan.maturity_date)}</span>}
        </div>
      </div>
      {active ? (
        <div className="grid gap-6 xl:grid-cols-2">
          <ChartFrame
            testId="chart-loan"
            title="Principal and interest by year"
            summary={`${resetYear ? `The rate resets in ${resetYear}. ` : ''}${ioEndYear ? `Interest-only payments end in ${ioEndYear}. ` : ''}Annual payments split into principal and interest.`}
            legend={[
              { label: 'Interest', color: C.muted },
              { label: 'Principal', color: C.s1 },
            ]}
            height={narrow ? 190 : 220}
            table={{
              columns: [
                { key: 'year', label: 'Year' },
                { key: 'principal_cents', label: 'Principal', money: true },
                { key: 'interest_cents', label: 'Interest', money: true },
                { key: 'balance_end_cents', label: 'Balance', money: true },
              ],
              rows: l.annual,
            }}
          >
            <ResponsiveContainer>
              <BarChart data={l.annual} margin={{ top: 14, right: 6, left: 0, bottom: 0 }}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="year" {...xAxisProps} minTickGap={12} />
                <YAxis tickFormatter={centsTick} {...yAxisProps} />
                <Tooltip cursor={{ fill: 'var(--ink-50)' }} content={(p) => <TooltipBody {...p} />} />
                <Bar dataKey="interest_cents" name="Interest" stackId="ds" fill={C.muted} stroke="var(--surface)" strokeWidth={1} maxBarSize={16} isAnimationActive={false} />
                <Bar dataKey="principal_cents" name="Principal" stackId="ds" fill={C.s1} stroke="var(--surface)" strokeWidth={1} radius={[3, 3, 0, 0]} maxBarSize={16} isAnimationActive={false} />
                {ioEndYear && ioEndYear !== resetYear && <ReferenceLine x={ioEndYear} stroke={C.s4} strokeDasharray="4 3" strokeWidth={1.5} label={{ value: 'IO ends', fontSize: 10.5, fill: 'var(--ink-700)', position: 'top' }} />}
                {resetYear && <ReferenceLine x={resetYear} stroke={C.s2} strokeDasharray="4 3" strokeWidth={1.5} label={{ value: ioEndYear === resetYear ? 'IO ends, ARM resets' : 'ARM reset', fontSize: 10.5, fill: 'var(--ink-700)', position: 'top' }} />}
              </BarChart>
            </ResponsiveContainer>
          </ChartFrame>
          <div className="min-w-0">
            <h3 className="mb-2 text-sm">{months.length ? `Monthly schedule, ${months.length} payments` : 'Annual schedule'}</h3>
            {months.length ? (
              <VirtualTable<LoanMonthT>
                testId="amortization-table"
                label={`Monthly amortization, lien ${l.loan.lien_position}`}
                rows={months}
                height={300}
                rowClass={(m) => (m.phase === 'io' || m.phase === 'heloc' ? 'bg-est-100/40' : m.phase === 'arm' ? '' : '')}
                cols={[
                  { key: 'n', label: '#', width: '3rem', render: (m) => <span className="num text-ink-500">{m.index}</span> },
                  { key: 'd', label: 'Month', width: narrow ? '4.5rem' : '5.5rem', render: (m) => <span className="num">{`${m.year}-${String(m.month).padStart(2, '0')}`}</span> },
                  ...(narrow ? [] : [{ key: 'r', label: 'Rate', right: true, render: (m: LoanMonthT) => formatRate(m.rate, 3) }]),
                  { key: 'p', label: 'Principal', right: true, render: (m) => (narrow ? formatCentsCompact(m.principal_cents) : formatCents(m.principal_cents)) },
                  { key: 'i', label: 'Interest', right: true, render: (m) => (narrow ? formatCentsCompact(m.interest_cents) : formatCents(m.interest_cents)) },
                  { key: 'b', label: 'Balance', right: true, render: (m) => (narrow ? formatCentsCompact(m.balance_cents) : formatCents(m.balance_cents)) },
                ]}
              />
            ) : (
              <VirtualTable
                label="Annual schedule"
                rows={l.annual}
                height={300}
                cols={[
                  { key: 'y', label: 'Year', width: '4.5rem', render: (y) => <span className="num">{y.year}</span> },
                  { key: 'p', label: 'Principal', right: true, render: (y) => formatCents(y.principal_cents) },
                  { key: 'i', label: 'Interest', right: true, render: (y) => formatCents(y.interest_cents) },
                  { key: 'b', label: 'Balance', right: true, render: (y) => formatCents(y.balance_end_cents) },
                  { key: 'm', label: '', width: '4.5rem', render: (y) => (y.marker ? <span className="chip bg-est-100 text-est-600 ring-est-600/30">{MARKER_LABEL[y.marker] ?? y.marker}</span> : null) },
                ]}
              />
            )}
            {months.some((m) => m.phase === 'io' || m.phase === 'heloc') && <p className="mt-1 text-[11px] text-ink-500">Shaded rows are interest-only payments.</p>}
          </div>
        </div>
      ) : (
        <p className="text-sm text-ink-500">No payments in the projection window{l.loan.is_paid_off ? ': this lien is paid off and appears for the audit trail only.' : '.'}</p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------------- property edit

const editSchema = z.object({
  nickname: z.string().trim().min(1, 'Give the property a name').max(80),
  current_value: z
    .string()
    .transform((s, ctx) => {
      const c = parseDollarsToCents(s);
      if (c === null || c <= 0) {
        ctx.addIssue({ code: 'custom', message: 'Enter a value above $0' });
        return z.NEVER;
      }
      return c;
    }),
  value_source: z.enum(['estimated', 'confirmed']),
  value_as_of: z.iso.date({ message: 'Use a date like 2025-09-30' }),
});

type EditState = { errors: Record<string, string>; error?: string };

function EditPropertyDialog({ a }: { a: AnalysisT }) {
  const p = a.property;
  const patch = usePatchProperty(p.id, p.household_id);
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState(
    async (_prev: EditState, fd: FormData): Promise<EditState> => {
      const parsed = editSchema.safeParse(Object.fromEntries(fd));
      if (!parsed.success) return { errors: Object.fromEntries(parsed.error.issues.map((i) => [String(i.path[0]), i.message])) };
      try {
        await patch.mutateAsync({ nickname: parsed.data.nickname, current_value_cents: parsed.data.current_value, value_source: parsed.data.value_source, value_as_of: parsed.data.value_as_of });
        setOpen(false);
        return { errors: {} };
      } catch (e) {
        return { errors: {}, error: e instanceof Error ? e.message : String(e) };
      }
    },
    { errors: {} } as EditState,
  );
  const field = (name: string, label: string, input: React.ReactNode) => (
    <div>
      <label htmlFor={`edit-${name}`} className="mb-1 block text-sm text-ink-700">
        {label}
      </label>
      {input}
      {state.errors[name] && <p className="mt-1 text-xs text-neg-600">{state.errors[name]}</p>}
    </div>
  );
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" className="btn">
          Edit property
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/30" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(440px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-surface p-5 shadow-pop">
          <Dialog.Title className="text-base font-semibold text-ink-950">Edit {p.nickname}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-ink-500">A value you enter here is a manual input: figures that depend on it become Confirmed instead of Estimated.</Dialog.Description>
          <form action={action} className="mt-4 space-y-3" noValidate>
            {field('nickname', 'Name', <input id="edit-nickname" name="nickname" className="input" defaultValue={p.nickname} />)}
            {field('current_value', 'Current value ($)', <input id="edit-current_value" name="current_value" inputMode="decimal" className="input-num" defaultValue={Math.round(p.current_value_cents / 100).toLocaleString('en-US')} />)}
            {field(
              'value_source',
              'Value source',
              <select id="edit-value_source" name="value_source" className="input" defaultValue={p.value_source === 'confirmed' ? 'confirmed' : 'estimated'}>
                <option value="estimated">Estimated (public data, BPO)</option>
                <option value="confirmed">Confirmed (appraisal, sale)</option>
              </select>,
            )}
            {field('value_as_of', 'Value as of', <input id="edit-value_as_of" name="value_as_of" type="date" className="input" defaultValue={p.value_as_of ?? ''} />)}
            {state.error && <p className="text-sm text-neg-600">{state.error}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <Dialog.Close asChild>
                <button type="button" className="btn">
                  Cancel
                </button>
              </Dialog.Close>
              <button type="submit" className="btn btn-primary" disabled={pending}>
                {pending ? 'Saving…' : 'Save property'}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

