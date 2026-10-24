import { Link, useParams } from 'react-router-dom';
import { useAlerts, useDashboard } from '../api/hooks';
import { IS_MOCK, rawUrl } from '../api/client';
import type { PropertyCard } from '../api/types';
import { FigureValue } from '../components/FigureValue';
import { Metric } from '../components/Metric';
import { StatusChip } from '../components/StatusChip';
import { TraceScope } from '../lib/traceContext';
import { HouseholdNav } from '../components/Layout';
import { Card, ErrorBox, Loading, PageHeader, SeverityTag } from '../components/ui';
import { FILING_LABEL, PROPERTY_TYPE_LABEL, formatDate, formatDateTime, titleCase } from '../lib/format';
import { formatCents, formatRate, signClass } from '../lib/money';
import { rollupStatus } from '../lib/status';

function PropertyCardView({ c, householdId }: { c: PropertyCard; householdId: string }) {
  const p = c.property;
  return (
    <TraceScope.Provider value={{ propertyId: p.id, householdId }}>
      <article className="card flex flex-col" data-testid="property-card">
        <div className="card-head items-start">
          <div className="min-w-0">
            <Link to={`/properties/${p.id}`} className="block truncate font-semibold text-ink-950 hover:text-brand-600">
              {p.nickname}
            </Link>
            <div className="truncate text-xs text-ink-500">
              {p.address_line1}, {p.city} · {PROPERTY_TYPE_LABEL[p.property_type]}
              {p.units > 1 ? ` · ${p.units} units` : ''}
            </div>
          </div>
          <StatusChip status={rollupStatus(c.status_chips)} />
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 px-4 py-3 text-sm">
          {(
            [
              ['Value', <FigureValue key="v" figure={c.value} chip />],
              ['Equity', <FigureValue key="e" figure={c.equity} chip />],
              ['Net cash flow', <FigureValue key="n" figure={c.net_cash_flow} signed chip />],
              ['Exit tax today', <FigureValue key="x" figure={c.exit_tax} chip />],
              ['ROE', <FigureValue key="r" figure={c.roe} display={formatRate(c.roe_rate, 1)} chip />],
              ['Open findings', <span key="f" className={`num ${c.open_findings ? 'font-semibold text-blk-600' : 'text-ink-400'}`}>{c.open_findings}</span>],
            ] as const
          ).map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="label">{k}</dt>
              <dd className="mt-0.5">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-auto flex gap-3 border-t border-ink-100 px-4 py-2 text-xs font-medium">
          <Link to={`/properties/${p.id}`} className="text-brand-600 hover:underline">
            Analysis
          </Link>
          <Link to={`/properties/${p.id}/strategies`} className="text-brand-600 hover:underline">
            Hold / Sell / 1031
          </Link>
          <span className="ml-auto text-ink-400">value {p.value_source} {formatDate(p.value_as_of)}</span>
        </div>
      </article>
    </TraceScope.Provider>
  );
}

export function DashboardPage() {
  const { id = '' } = useParams();
  const { data, isLoading, error } = useDashboard(id);
  const alerts = useAlerts(id);
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? 'not found'} />;
  const h = data.household;
  const m = data.metrics;
  const reportHref = IS_MOCK ? undefined : rawUrl(`/households/${id}/report.pdf`);
  return (
    <TraceScope.Provider value={{ householdId: id }}>
      <PageHeader
        eyebrow={`${FILING_LABEL[h.filing_status]} · ${h.state} · tax year ${h.tax_year_latest}`}
        title={`${h.name} household`}
        actions={
          reportHref ? (
            <a className="btn btn-primary" href={reportHref} target="_blank" rel="noreferrer">
              Generate report (PDF)
            </a>
          ) : (
            <Link className="btn btn-primary" to={`/households/${id}/reports`} title="Mock mode has no PDF renderer; opens the report preview">
              Generate report (PDF)
            </Link>
          )
        }
      >
        Goal: <span className="text-ink-900">{h.goal}</span>
      </PageHeader>
      <HouseholdNav id={id} />

      {alerts.data && alerts.data.length > 0 && (
        <div className="mb-5 flex gap-2 overflow-x-auto pb-1" data-testid="alerts-strip">
          <span className="label shrink-0 self-center pr-1">Monitoring</span>
          {alerts.data.map((a) => (
            <div key={a.id} className="flex min-w-[260px] max-w-[340px] shrink-0 items-start gap-2 rounded border border-ink-200 bg-white px-3 py-2 text-xs shadow-sm">
              <span className="num mt-px shrink-0 rounded bg-ink-100 px-1.5 py-px text-[10.5px] font-semibold text-ink-700">{formatDate(a.due_date)}</span>
              <span>
                <span className="font-semibold text-ink-900">{titleCase(a.kind)}.</span> <span className="text-ink-700">{a.message}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <div className="min-w-0 space-y-5">
          <Card title="Key observations" actions={<span className="text-xs text-ink-500">{data.observations.length} from the rule table</span>} bodyClass="divide-y divide-ink-100">
            {data.observations.slice(0, 8).map((o) => (
              <div key={o.id} className="flex items-start gap-3 px-4 py-2 text-sm">
                <SeverityTag severity={o.severity} />
                <span className="text-ink-900">{o.message}</span>
              </div>
            ))}
            {data.observations.length > 8 && <div className="px-4 py-2 text-xs text-ink-500">+{data.observations.length - 8} more on the property pages</div>}
          </Card>

          <section className="card grid grid-cols-2 gap-x-6 gap-y-4 px-4 py-4 md:grid-cols-5">
            <Metric label="Portfolio value" figure={m.total_value} />
            <Metric label="Total equity" figure={m.total_equity} />
            <Metric label="Net cash flow / yr" figure={m.net_cash_flow} signed />
            <Metric label="Exit tax if sold today" figure={m.exit_tax} />
            <Metric label="Suspended losses" figure={m.suspended_losses} sub="Form 8582 carryforward" />
          </section>

          <div className="grid gap-4 md:grid-cols-2">
            {data.properties.map((c) => (
              <PropertyCardView key={c.property.id} c={c} householdId={id} />
            ))}
          </div>
        </div>

        <aside className="space-y-5">
          <Card
            title="Narrative"
            actions={
              <span className="rounded bg-ink-100 px-1.5 py-px font-mono text-[10.5px] text-ink-700" data-testid="narrative-provider">
                provider: {data.narrative.provider}
              </span>
            }
          >
            <p className="text-sm leading-relaxed text-ink-900">{data.narrative.text}</p>
            <p className="mt-3 text-[11px] text-ink-500">
              Generated {formatDateTime(data.narrative.generated_at)}. Every number is pulled from a Figure; the narrative layer never computes or alters math.
            </p>
          </Card>
          <Card title="Reconciliation">
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-ink-700">Open findings</span>
              <span className={`num text-xl font-semibold ${data.findings_open ? 'text-blk-600' : 'text-ink-400'}`}>{data.findings_open}</span>
            </div>
            <p className="mt-1 text-xs text-ink-500">Figures touched by a blocking finding stay Blocked until it is resolved.</p>
            <Link to={`/households/${id}/documents#queue`} className="btn btn-sm mt-3">
              Open the queue
            </Link>
          </Card>
          <Card title="Household inputs">
            <dl className="space-y-1 text-sm">
              {(
                [
                  ['Wages', formatCents(h.wages_cents)],
                  ['Other income', formatCents(h.other_income_cents)],
                  ['MAGI', formatCents(h.magi_cents)],
                  ['Active participation', h.active_participation ? 'Yes' : 'No'],
                  ['RE professional', h.re_professional ? 'Yes' : 'No'],
                ] as const
              ).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <dt className="text-ink-500">{k}</dt>
                  <dd className={`num ${k === 'Wages' ? signClass(0) : ''}`}>{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </aside>
      </div>
    </TraceScope.Provider>
  );
}
