import { useQueries, useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { Link, getRouteApi } from '@tanstack/react-router';
import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { downloadBinary } from '../api/client';
import { alertsQuery, analysisQuery, dashboardQuery } from '../api/queries';
import type { PropertyCardT } from '../api/schemas';
import { DivergingBars } from '../charts/DivergingBars';
import { C, ChartFrame, TooltipBody, centsTick, gridProps, useNarrow, xAxisProps } from '../charts/kit';
import { FigureValue } from '../components/FigureValue';
import { HouseholdNav } from '../components/HouseholdNav';
import { KpiTile } from '../components/KpiTile';
import { StatusChip } from '../components/StatusChip';
import { Card, PageHeader, SeverityTag } from '../components/ui';
import { householdTitle, FILING_LABEL, PROPERTY_TYPE_LABEL, formatDate, formatDateTime, titleCase } from '../lib/format';
import { formatCents, formatCentsCompact, formatRate } from '../lib/money';
import { rollupStatus } from '../lib/status';
import { TraceScope } from '../lib/traceScope';

const route = getRouteApi('/households/$householdId');
const ALERT_LABEL: Record<string, string> = {
  arm_reset: 'ARM reset',
  io_period_ending: 'Interest-only period ends',
  cash_flow_negative: 'Negative cash flow',
  value_drift: 'Stale value',
  loan_maturity: 'Loan maturity',
  roe_below_threshold: 'Low return on equity',
};

const PROP_COLORS = [C.s1, C.s2, C.s3, C.s4, C.s5];

function ReportButton({ householdId }: { householdId: string }) {
  const [state, setState] = useState<'idle' | 'busy' | 'error'>('idle');
  return (
    <button
      type="button"
      className="btn btn-primary"
      data-testid="report-pdf"
      disabled={state === 'busy'}
      onClick={async () => {
        setState('busy');
        try {
          await downloadBinary(`/households/${householdId}/report.pdf`, 'groundplan-portfolio-report.pdf');
          setState('idle');
        } catch {
          setState('error');
        }
      }}
    >
      {state === 'busy' ? 'Generating…' : state === 'error' ? 'Report failed, retry' : 'Generate report (PDF)'}
    </button>
  );
}

function PropertyCardView({ c, householdId, color }: { c: PropertyCardT; householdId: string; color: string }) {
  const p = c.property;
  return (
    <TraceScope.Provider value={{ propertyId: p.id, householdId }}>
      <article className="card flex flex-col" data-testid="property-card">
        <div className="card-head items-start">
          <div className="flex min-w-0 items-start gap-2.5">
            <span aria-hidden className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: color }} />
            <div className="min-w-0">
              <Link
                to="/properties/$propertyId"
                params={{ propertyId: p.id }}
                className="block truncate font-semibold text-ink-950 hover:text-brand-600 hover:underline"
              >
                {p.nickname}
              </Link>
              <div className="truncate text-xs text-ink-500">
                {p.address_line1}, {p.city}, {PROPERTY_TYPE_LABEL[p.property_type] ?? p.property_type}
                {p.units > 1 ? `, ${p.units} units` : ''}
              </div>
            </div>
          </div>
          <StatusChip status={rollupStatus(c.status_chips)} />
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3 text-sm">
          {(
            [
              ['Value', <FigureValue key="v" figure={c.value} />],
              ['Equity', <FigureValue key="e" figure={c.equity} />],
              ['Net cash flow', <FigureValue key="n" figure={c.net_cash_flow} signed />],
              ['Exit tax today', <FigureValue key="x" figure={c.exit_tax} />],
              ['Return on equity', <FigureValue key="r" figure={c.roe} display={formatRate(c.roe_rate, 1)} />],
              [
                'Open findings',
                <span key="f" className={`num ${c.open_findings ? 'font-semibold text-blk-600' : 'text-ink-500'}`}>
                  {c.open_findings}
                </span>,
              ],
            ] as const
          ).map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="label">{k}</dt>
              <dd className="mt-0.5 min-w-0">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-ink-100 px-4 py-2.5 text-sm font-medium">
          <Link to="/properties/$propertyId" params={{ propertyId: p.id }} className="text-brand-600 hover:underline">
            Analysis
          </Link>
          <Link to="/properties/$propertyId/strategies" params={{ propertyId: p.id }} className="text-brand-600 hover:underline">
            Hold, sell or 1031
          </Link>
          <span className="ml-auto text-xs font-normal text-ink-500">
            Value {p.value_source}
            {p.value_as_of ? `, ${formatDate(p.value_as_of)}` : ''}
          </span>
        </div>
      </article>
    </TraceScope.Provider>
  );
}

export function DashboardPage() {
  const { householdId } = route.useParams();
  const { data } = useSuspenseQuery(dashboardQuery(householdId));
  const alerts = useQuery(alertsQuery(householdId));
  const narrow = useNarrow();
  const h = data.household;
  const m = data.metrics;
  const cards = data.properties;
  const colorOf = new Map(cards.map((c, i) => [c.property.id, PROP_COLORS[i % PROP_COLORS.length]]));

  // 10-year trend for the KPI sparklines: sum each property's base projection (prefetched in parallel).
  const projections = useQueries({ queries: cards.map((c) => ({ ...analysisQuery(c.property.id, {}), staleTime: 60_000 })) });
  const ready = projections.length > 0 && projections.every((q) => q.data);
  const sumBy = (pick: (row: { value_cents: number; equity_cents: number; debt_cents: number }) => number) => {
    if (!ready) return undefined;
    const len = Math.min(...projections.map((q) => q.data!.appreciation.projected.length));
    return Array.from({ length: len }, (_, i) => projections.reduce((s, q) => s + pick(q.data!.appreciation.projected[i]), 0));
  };
  const cfTrend = ready
    ? Array.from({ length: Math.min(...projections.map((q) => q.data!.cash_flow.projection.length)) }, (_, i) =>
        projections.reduce((s, q) => s + q.data!.cash_flow.projection[i].net_cash_flow_cents, 0),
      )
    : undefined;

  const stack = cards.map((c) => ({
    name: c.property.nickname,
    equity: Math.max(0, c.equity.value_cents),
    debt: Math.max(0, c.value.value_cents - c.equity.value_cents),
    id: c.property.id,
  }));
  const reEquity = cards.reduce((s, c) => s + Math.max(0, c.equity.value_cents), 0);
  const netWorth = typeof h.net_worth_cents === 'number' && (h.net_worth_cents as number) > reEquity ? (h.net_worth_cents as number) : null;
  const donut = [
    ...cards.map((c) => ({ name: c.property.nickname, value: Math.max(0, c.equity.value_cents), color: colorOf.get(c.property.id)! })),
    ...(netWorth ? [{ name: 'Everything else', value: netWorth - reEquity, color: 'var(--ink-200)' }] : []),
  ];
  const top = [...cards].sort((a, b) => b.equity.value_cents - a.equity.value_cents)[0];
  const topShare = top && (netWorth ?? reEquity) > 0 ? top.equity.value_cents / (netWorth ?? reEquity) : 0;
  const negCount = cards.filter((c) => c.net_cash_flow.value_cents < 0).length;

  return (
    <TraceScope.Provider value={{ householdId }}>
      <PageHeader
        back={
          <Link to="/" className="text-ink-500 hover:text-ink-900 hover:underline">
            Households
          </Link>
        }
        title={householdTitle(h.name)}
        actions={<ReportButton householdId={householdId} />}
      >
        {FILING_LABEL[h.filing_status]}, {h.state}, tax year {h.tax_year_latest}. Goal: <span className="text-ink-900">{h.goal}</span>
      </PageHeader>
      <HouseholdNav householdId={householdId} />

      {alerts.data && alerts.data.length > 0 && (
        <section
          aria-label="Monitoring alerts"
          tabIndex={0}
          className="-mx-4 mb-5 flex snap-x gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0"
          data-testid="alerts-strip"
        >
          {alerts.data.map((a) => (
            <div key={a.id} className="flex w-[280px] shrink-0 snap-start items-start gap-2.5 rounded-md bg-surface px-3 py-2.5 text-xs shadow-card">
              <span className="num mt-px shrink-0 rounded bg-ink-100 px-1.5 py-0.5 text-[11px] font-medium text-ink-700">{formatDate(a.due_date)}</span>
              <span className="min-w-0">
                <span className="font-semibold text-ink-950">{ALERT_LABEL[a.kind] ?? titleCase(a.kind)}.</span>{' '}
                <span className="text-ink-700">{a.message}</span>
              </span>
            </div>
          ))}
        </section>
      )}

      <Card
        title="Key observations"
        sub={`${data.observations.length} from the rule table, most severe first`}
        bodyClass="divide-y divide-ink-100"
        className="mb-5"
        id="observations"
      >
        {data.observations.slice(0, 6).map((o) => (
          <div key={o.id} className="flex items-start gap-3 px-4 py-2.5 text-sm">
            <SeverityTag severity={o.severity} />
            <span className="min-w-0 text-ink-900">{o.message}</span>
          </div>
        ))}
        {data.observations.length > 6 && <div className="px-4 py-2 text-xs text-ink-500">{data.observations.length - 6} more on the property pages.</div>}
      </Card>

      <section aria-label="Headline figures" className="mb-5 grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-ink-100 shadow-card lg:grid-cols-5">
        <KpiTile
          label="Portfolio value"
          spark
          figure={m.total_value}
          trend={sumBy((r) => r.value_cents)}
          trendLabel="Projected portfolio value, next 10 years"
        />
        <KpiTile label="Total equity" spark figure={m.total_equity} trend={sumBy((r) => r.equity_cents)} trendLabel="Projected equity, next 10 years" />
        <KpiTile label="Total debt" spark figure={m.total_debt} trend={sumBy((r) => r.debt_cents)} trendLabel="Projected debt balance, next 10 years" />
        <KpiTile label="Net cash flow / yr" spark figure={m.net_cash_flow} signed trend={cfTrend} trendLabel="Projected net cash flow, next 10 years" />
        <div className="col-span-2 flex lg:col-span-1 [&>*]:flex-1">
          <KpiTile
            label="Exit tax if sold today"
            figure={m.exit_tax_total}
            sub={m.suspended_losses ? `${formatCentsCompact(m.suspended_losses.value_cents)} suspended losses release on a taxable sale` : undefined}
          />
        </div>
      </section>
      <p className="-mt-3 mb-5 text-[11px] text-ink-500">Sparklines: the next 10 years on each property's stored assumptions.</p>

      <div className="mb-5 grid gap-5 lg:grid-cols-[1.25fr_1fr]">
        <Card bodyClass="p-4">
          <ChartFrame
            testId="chart-equity-debt"
            title="Equity and debt by property"
            summary={`${cards.length} properties hold ${formatCents(m.total_value.value_cents)} of value against ${formatCents(m.total_value.value_cents - m.total_equity.value_cents)} of debt.`}
            legend={[
              { label: 'Equity', color: C.s1 },
              { label: 'Debt', color: C.muted },
            ]}
            height={Math.max(180, cards.length * 46 + 40)}
            table={{
              columns: [
                { key: 'name', label: 'Property' },
                { key: 'equity', label: 'Equity', money: true },
                { key: 'debt', label: 'Debt', money: true },
              ],
              rows: stack,
            }}
          >
            <ResponsiveContainer>
              <BarChart data={stack} layout="vertical" margin={{ top: 0, right: 12, left: 0, bottom: 0 }} barCategoryGap={12}>
                <CartesianGrid {...gridProps} horizontal={false} vertical />
                <XAxis type="number" tickFormatter={centsTick} {...xAxisProps} tickCount={narrow ? 3 : 5} />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={narrow ? 84 : 110}
                  tick={{ fontSize: 12, fill: 'var(--ink-700)' }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip cursor={{ fill: 'var(--ink-50)' }} content={(p) => <TooltipBody {...p} />} />
                <Bar dataKey="equity" name="Equity" stackId="s" fill={C.s1} stroke="var(--surface)" strokeWidth={2} maxBarSize={24} isAnimationActive={false} />
                <Bar
                  dataKey="debt"
                  name="Debt"
                  stackId="s"
                  fill={C.muted}
                  stroke="var(--surface)"
                  strokeWidth={2}
                  radius={[0, 4, 4, 0]}
                  maxBarSize={24}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </ChartFrame>
        </Card>
        <Card bodyClass="p-4">
          <ChartFrame
            testId="chart-concentration"
            title={netWorth ? 'Share of net worth' : 'Where the real-estate equity sits'}
            summary={
              top
                ? `${top.property.nickname} holds ${formatRate(topShare, 0)} of ${netWorth ? 'household net worth' : 'the real-estate equity'}${topShare > 0.4 ? ', above the 40% concentration line' : ''}.`
                : 'No properties.'
            }
            legend={donut.map((d) => ({ label: d.name, color: d.color, value: formatCentsCompact(d.value) }))}
            height={210}
            table={{
              columns: [
                { key: 'name', label: 'Slice' },
                { key: 'value', label: 'Equity', money: true },
                { key: 'share', label: 'Share', align: 'right' },
              ],
              rows: donut.map((d) => ({ ...d, share: formatRate(d.value / Math.max(1, netWorth ?? reEquity), 1) })),
            }}
          >
            <div className="relative h-full">
              <ResponsiveContainer>
                <PieChart>
                  <Pie
                    data={donut}
                    dataKey="value"
                    nameKey="name"
                    innerRadius="62%"
                    outerRadius="92%"
                    paddingAngle={1.5}
                    stroke="var(--surface)"
                    strokeWidth={2}
                    isAnimationActive={false}
                  >
                    {donut.map((d) => (
                      <Cell key={d.name} fill={d.color} />
                    ))}
                  </Pie>
                  <Tooltip content={(p) => <TooltipBody {...p} labelFmt={() => 'Equity'} />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
                <span className="num text-lg font-medium text-ink-950">{formatCentsCompact(reEquity)}</span>
                <span className="text-[11px] text-ink-500">real-estate equity</span>
              </div>
            </div>
          </ChartFrame>
        </Card>
      </div>

      <Card bodyClass="p-4" className="mb-5">
        <ChartFrame
          testId="chart-cashflow"
          title="Net cash flow by property, after debt service and reserves"
          summary={
            negCount
              ? `${negCount} of ${cards.length} properties run negative; the portfolio nets ${formatCents(m.net_cash_flow.value_cents)} a year.`
              : `Every property covers its own debt service; the portfolio nets ${formatCents(m.net_cash_flow.value_cents)} a year.`
          }
          height={cards.length * 32 + 4}
          fluid
          table={{
            columns: [
              { key: 'label', label: 'Property' },
              { key: 'value', label: 'Net cash flow / yr', money: true },
            ],
            rows: cards.map((c) => ({ label: c.property.nickname, value: c.net_cash_flow.value_cents })),
          }}
        >
          <DivergingBars
            rows={cards.map((c) => ({
              label: c.property.nickname,
              value: c.net_cash_flow.value_cents,
              figure: c.net_cash_flow,
              scope: { propertyId: c.property.id, householdId },
            }))}
          />
        </ChartFrame>
      </Card>

      <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
        <section aria-label="Properties" className="grid min-w-0 content-start gap-4 md:grid-cols-2">
          {cards.map((c) => (
            <PropertyCardView key={c.property.id} c={c} householdId={householdId} color={colorOf.get(c.property.id)!} />
          ))}
        </section>
        <aside className="space-y-5">
          <Card
            title="Narrative"
            actions={
              <span className="rounded bg-ink-100 px-1.5 py-0.5 font-mono text-[11px] text-ink-700" data-testid="narrative-provider">
                provider: {data.narrative.provider}
              </span>
            }
          >
            <p className="text-sm leading-relaxed text-ink-900">{data.narrative.text}</p>
            <p className="mt-3 text-[11px] leading-relaxed text-ink-500">
              {data.narrative.generated_at ? `Generated ${formatDateTime(data.narrative.generated_at)}. ` : ''}Every number is quoted from a computed figure;
              the narrative layer never computes or changes the math.
            </p>
          </Card>
          <Card title="Reconciliation">
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-ink-700">Open findings</span>
              <span className={`num text-xl font-medium ${data.findings_open ? 'text-blk-600' : 'text-ink-500'}`}>{data.findings_open}</span>
            </div>
            <p className="mt-1 text-xs text-ink-500">Figures touched by a blocking finding stay Blocked until it is resolved.</p>
            <Link to="/households/$householdId/documents" params={{ householdId }} hash="queue" className="btn btn-sm mt-3">
              Open the queue
            </Link>
          </Card>
          <Card title="Household inputs">
            <dl className="divide-y divide-ink-100 text-sm">
              {(
                [
                  ['Wages', formatCents(h.wages_cents)],
                  ['Other income', formatCents(h.other_income_cents)],
                  ['MAGI', formatCents(h.magi_cents)],
                  ['Active participation', h.active_participation ? 'Yes' : 'No'],
                  ['Real-estate professional', h.re_professional ? 'Yes' : 'No'],
                ] as const
              ).map(([k, v]) => (
                <div key={k} className="flex justify-between py-1.5">
                  <dt className="text-ink-500">{k}</dt>
                  <dd className="num">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </aside>
      </div>
    </TraceScope.Provider>
  );
}
