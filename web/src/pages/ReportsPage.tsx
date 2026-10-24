import { useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { getRouteApi } from '@tanstack/react-router';
import { useState } from 'react';
import { api, downloadBinary, qs } from '../api/client';
import { dashboardQuery, factSheetQuery } from '../api/queries';
import type { FactSheet } from '../api/types';
import { FigureValue } from '../components/FigureValue';
import { HouseholdNav } from '../components/HouseholdNav';
import { StatusChip } from '../components/StatusChip';
import { Card, PageHeader, SeverityTag, TabPanel, Tabs } from '../components/ui';
import { householdTitle, FILING_LABEL, PROPERTY_TYPE_LABEL } from '../lib/format';
import { formatCents, formatRate } from '../lib/money';
import { rollupStatus } from '../lib/status';
import { TraceScope } from '../lib/traceScope';

const route = getRouteApi('/households/$householdId/reports');
type Platform = 'emoney' | 'rightcapital' | 'mgp';
const PLATFORMS: { id: Platform; label: string }[] = [
  { id: 'emoney', label: 'eMoney' },
  { id: 'rightcapital', label: 'RightCapital' },
  { id: 'mgp', label: 'MoneyGuidePro' },
];

function saveText(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function ReportsPage() {
  const { householdId } = route.useParams();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const d = useSuspenseQuery(dashboardQuery(householdId)).data;
  const platform = search.platform ?? 'emoney';
  const pid = search.property ?? d.properties[0]?.property.id ?? null;
  const fs = useQuery({ ...factSheetQuery(pid ?? '', platform), enabled: !!pid });
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (what: string, fn: () => Promise<unknown>) => {
    setBusy(what);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };
  const slug =
    d.properties
      .find((c) => c.property.id === pid)
      ?.property.nickname.toLowerCase()
      .replace(/[^a-z0-9]+/g, '-') ?? 'property';
  return (
    <TraceScope.Provider value={{ householdId }}>
      <PageHeader
        title="Reports and fact sheets"
        actions={
          <button
            type="button"
            className="btn btn-primary"
            data-testid="report-pdf"
            disabled={busy === 'pdf'}
            onClick={() => run('pdf', () => downloadBinary(`/households/${householdId}/report.pdf`, 'groundplan-portfolio-report.pdf'))}
          >
            {busy === 'pdf' ? 'Generating…' : 'Download report (PDF)'}
          </button>
        }
      >
        A client-ready review generated on the fly and never stored, plus the field-by-field mapping into the planning software the advisor already uses.
      </PageHeader>
      <HouseholdNav householdId={householdId} />
      <div className="grid gap-5 xl:grid-cols-[1.1fr_1fr]">
        <Card title="Report preview" sub="What the PDF contains, on screen">
          <div className="mx-auto max-w-[680px] rounded-sm bg-surface px-1 py-2 sm:px-4 sm:py-4" data-testid="report-preview">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b-2 border-ink-950 pb-2">
              <div>
                <div className="label">Real estate portfolio review</div>
                <div className="text-xl font-semibold tracking-tight">{householdTitle(d.household.name)}</div>
              </div>
              <div className="text-right text-xs text-ink-500">
                {FILING_LABEL[d.household.filing_status]}, {d.household.state}
                <br />
                Tax year {d.household.tax_year_latest}
              </div>
            </div>
            <p className="mt-3 text-sm text-ink-700">Goal: {d.household.goal}</p>
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {(
                [
                  ['Value', d.metrics.total_value, false],
                  ['Equity', d.metrics.total_equity, false],
                  ['Net cash flow', d.metrics.net_cash_flow, true],
                  ['Exit tax today', d.metrics.exit_tax_total, false],
                ] as const
              ).map(([k, f, signed]) => (
                <div key={k}>
                  <div className="label">{k}</div>
                  <div className="mt-0.5 font-medium">
                    <FigureValue figure={f} signed={signed} />
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-5 -mx-1 overflow-x-auto px-1" tabIndex={0} role="region" aria-label="Properties in the report">
              <table className="tbl min-w-[460px]">
                <thead>
                  <tr>
                    <th>Property</th>
                    <th className="r">Value</th>
                    <th className="r">Equity</th>
                    <th className="r">Cash flow</th>
                    <th className="r">ROE</th>
                    <th>Figures</th>
                  </tr>
                </thead>
                <tbody>
                  {d.properties.map((c) => (
                    <tr key={c.property.id}>
                      <td>
                        <div className="font-medium">{c.property.nickname}</div>
                        <div className="text-[11px] text-ink-500">{PROPERTY_TYPE_LABEL[c.property.property_type] ?? c.property.property_type}</div>
                      </td>
                      <td className="r num">{formatCents(c.value.value_cents)}</td>
                      <td className="r num">{formatCents(c.equity.value_cents)}</td>
                      <td className="r">
                        <TraceScope.Provider value={{ householdId, propertyId: c.property.id }}>
                          <FigureValue figure={c.net_cash_flow} signed />
                        </TraceScope.Provider>
                      </td>
                      <td className="r num">{formatRate(c.roe_rate, 1)}</td>
                      <td>
                        <StatusChip status={rollupStatus(c.status_chips)} compact />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3 className="mt-5">Observations</h3>
            <ul className="mt-2 space-y-1.5">
              {d.observations.slice(0, 6).map((o) => (
                <li key={o.id} className="flex items-start gap-2 text-xs leading-relaxed">
                  <SeverityTag severity={o.severity} />
                  <span className="min-w-0">{o.message}</span>
                </li>
              ))}
            </ul>
            <h3 className="mt-5">Summary</h3>
            <p className="mt-1 text-sm leading-relaxed">{d.narrative.text}</p>
            <p className="mt-5 border-t border-ink-200 pt-2 text-[11px] text-ink-500">
              Estimated figures rely on public data or default assumptions. Blocked figures await reconciliation. This review describes trade-offs and is not
              tax or legal advice; verify with the client’s CPA.
            </p>
          </div>
        </Card>

        <Card
          title="Fact sheets"
          sub="Paste field for field into the planning platform"
          actions={
            <div className="flex gap-2">
              <button
                type="button"
                className="btn btn-sm"
                data-testid="export-json"
                disabled={!pid || busy === 'json'}
                onClick={() =>
                  run('json', async () =>
                    saveText(
                      `${slug}-factsheet.json`,
                      JSON.stringify(await api<FactSheet>('GET', `/properties/${pid}/factsheet${qs({ format: 'json' })}`), null, 2),
                      'application/json',
                    ),
                  )
                }
              >
                JSON
              </button>
              <button
                type="button"
                className="btn btn-sm"
                data-testid="export-csv"
                disabled={!pid || busy === 'csv'}
                onClick={() => run('csv', () => downloadBinary(`/properties/${pid}/factsheet${qs({ format: 'csv' })}`, `${slug}-factsheet.csv`))}
              >
                CSV
              </button>
            </div>
          }
        >
          <label className="mb-3 flex flex-col gap-1 text-sm sm:flex-row sm:items-center sm:gap-3">
            <span className="label">Property</span>
            <select
              className="input sm:max-w-xs"
              value={pid ?? ''}
              onChange={(e) => navigate({ search: (s) => ({ ...s, property: e.target.value }), replace: true, resetScroll: false })}
              data-testid="factsheet-property"
            >
              {d.properties.map((c) => (
                <option key={c.property.id} value={c.property.id}>
                  {c.property.nickname}
                </option>
              ))}
            </select>
          </label>
          <Tabs
            label="Planning platform"
            tabs={PLATFORMS}
            value={platform}
            onChange={(p) => navigate({ search: (s) => ({ ...s, platform: p === 'emoney' ? undefined : p }), replace: true, resetScroll: false })}
          >
            {PLATFORMS.map((pl) => (
              <TabPanel key={pl.id} value={pl.id} className="mt-3">
                {fs.isPending ? (
                  <div className="skeleton h-[360px]" />
                ) : fs.error ? (
                  <p className="text-sm text-neg-600">{fs.error.message}</p>
                ) : fs.data ? (
                  <>
                    <ul className="divide-y divide-ink-100" data-testid="factsheet">
                      {fs.data.rows.map((r) => (
                        <li key={r.groundplan_key} className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 py-2">
                          <span className="min-w-0 text-[13px] text-ink-950">{r.platform_field}</span>
                          <span className="num text-right text-[13px]">{r.value_cents === null ? (r.value_text ?? '—') : formatCents(r.value_cents)}</span>
                          <span className="min-w-0 font-mono text-[11px] break-all text-ink-500">
                            {r.groundplan_key}
                            {r.note ? <span className="font-sans"> · {r.note}</span> : null}
                          </span>
                          <span className="text-right">
                            <StatusChip status={r.status} compact />
                          </span>
                        </li>
                      ))}
                    </ul>
                    <p className="mt-2 text-[11px] text-ink-500">
                      As of {fs.data.as_of ?? '—'}. {fs.data.platform_label}. Estimated rows should be confirmed before they drive a plan.
                    </p>
                  </>
                ) : null}
              </TabPanel>
            ))}
          </Tabs>
        </Card>
      </div>
    </TraceScope.Provider>
  );
}
