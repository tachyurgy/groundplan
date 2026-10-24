import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useDashboard, useFactSheet } from '../api/hooks';
import { IS_MOCK, api, qs, rawUrl } from '../api/client';
import type { FactSheet, FactSheetFormat } from '../api/types';
import { HouseholdNav } from '../components/Layout';
import { FigureValue } from '../components/FigureValue';
import { StatusChip } from '../components/StatusChip';
import { TraceScope } from '../lib/traceContext';
import { Card, ErrorBox, Loading, PageHeader, SeverityTag, Tabs } from '../components/ui';
import { FILING_LABEL, PROPERTY_TYPE_LABEL } from '../lib/format';
import { formatCents, formatRate } from '../lib/money';
import { factSheetCsv } from '../lib/factsheet';

type Platform = 'emoney' | 'rightcapital' | 'mgp';
const PLATFORMS: { id: Platform; label: string }[] = [
  { id: 'emoney', label: 'eMoney' },
  { id: 'rightcapital', label: 'RightCapital' },
  { id: 'mgp', label: 'MoneyGuidePro' },
];


function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ReportsPage() {
  const { id = '' } = useParams();
  const dash = useDashboard(id);
  const [platform, setPlatform] = useState<Platform>('emoney');
  const [propId, setPropId] = useState<string | null>(null);
  const pid = propId ?? dash.data?.properties[0]?.property.id ?? null;
  const fs = useFactSheet(pid, platform);
  if (dash.isLoading) return <Loading />;
  if (dash.error || !dash.data) return <ErrorBox error={dash.error ?? 'not found'} />;
  const d = dash.data;
  const exportAs = async (fmt: 'json' | 'csv') => {
    if (!pid) return;
    if (!IS_MOCK) {
      window.open(rawUrl(`/properties/${pid}/factsheet${qs({ format: fmt })}`), '_blank');
      return;
    }
    const sheet = await api<FactSheet>('GET', `/properties/${pid}/factsheet${qs({ format: fmt as FactSheetFormat })}`);
    if (fmt === 'json') download(`factsheet-${pid}.json`, JSON.stringify(sheet, null, 2), 'application/json');
    else download(`factsheet-${pid}.csv`, factSheetCsv(sheet), 'text/csv');
  };
  return (
    <TraceScope.Provider value={{ householdId: id }}>
      <PageHeader
        eyebrow="Household"
        title="Reports & fact sheets"
        actions={
          IS_MOCK ? (
            <button type="button" className="btn btn-primary" onClick={() => window.print()} title="Mock mode: prints this preview. Live mode streams report.pdf from the API.">
              Print preview
            </button>
          ) : (
            <a className="btn btn-primary" href={rawUrl(`/households/${id}/report.pdf`)} target="_blank" rel="noreferrer">
              Generate report (PDF)
            </a>
          )
        }
      />
      <HouseholdNav id={id} />
      <div className="grid gap-5 xl:grid-cols-[1.1fr_1fr]">
        <Card title="Report preview" actions={<span className="text-xs text-ink-500">client-ready; generated on the fly, not stored</span>}>
          <div className="mx-auto max-w-[680px] rounded-sm bg-white px-6 py-6 ring-1 ring-ink-200">
            <div className="flex items-baseline justify-between border-b-2 border-ink-950 pb-2">
              <div>
                <div className="label">Real estate portfolio review</div>
                <div className="text-xl font-semibold tracking-tight">{d.household.name} household</div>
              </div>
              <div className="text-right text-xs text-ink-500">
                {FILING_LABEL[d.household.filing_status]} · {d.household.state}
                <br />
                Tax year {d.household.tax_year_latest}
              </div>
            </div>
            <p className="mt-3 text-sm italic text-ink-700">Goal: {d.household.goal}</p>
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {(
                [
                  ['Value', d.metrics.total_value],
                  ['Equity', d.metrics.total_equity],
                  ['Net cash flow', d.metrics.net_cash_flow],
                  ['Exit tax today', d.metrics.exit_tax],
                ] as const
              ).map(([k, f]) => (
                <div key={k}>
                  <div className="label">{k}</div>
                  <div className="mt-0.5 font-semibold">
                    <FigureValue figure={f} signed={k === 'Net cash flow'} />
                  </div>
                </div>
              ))}
            </div>
            <table className="tbl mt-5">
              <thead>
                <tr>
                  <th>Property</th>
                  <th className="r">Value</th>
                  <th className="r">Equity</th>
                  <th className="r">Cash flow</th>
                  <th className="r">ROE</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {d.properties.map((c) => (
                  <tr key={c.property.id}>
                    <td>
                      <div className="font-medium">{c.property.nickname}</div>
                      <div className="text-[11px] text-ink-500">{PROPERTY_TYPE_LABEL[c.property.property_type]}</div>
                    </td>
                    <td className="r num">{formatCents(c.value.value_cents)}</td>
                    <td className="r num">{formatCents(c.equity.value_cents)}</td>
                    <td className="r">
                      <FigureValue figure={c.net_cash_flow} signed />
                    </td>
                    <td className="r num">{formatRate(c.roe_rate, 1)}</td>
                    <td>
                      <StatusChip status={c.status_chips.includes('blocked') ? 'blocked' : c.status_chips.includes('estimated') ? 'estimated' : 'confirmed'} compact />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3 className="mt-5">Observations</h3>
            <ul className="mt-1 space-y-1">
              {d.observations.slice(0, 6).map((o) => (
                <li key={o.id} className="flex gap-2 text-xs">
                  <SeverityTag severity={o.severity} />
                  {o.message}
                </li>
              ))}
            </ul>
            <h3 className="mt-5">Summary</h3>
            <p className="mt-1 text-sm leading-relaxed">{d.narrative.text}</p>
            <p className="mt-5 border-t border-ink-200 pt-2 text-[10px] text-ink-400">
              Estimated figures rely on public data or default assumptions. Blocked figures await reconciliation. This review describes trade-offs and is not tax or legal advice; verify with the client’s CPA.
            </p>
          </div>
        </Card>

        <Card
          title="Fact sheets"
          actions={
            <div className="flex gap-2">
              <button type="button" className="btn btn-sm" onClick={() => exportAs('json')}>
                Export JSON
              </button>
              <button type="button" className="btn btn-sm" onClick={() => exportAs('csv')}>
                Export CSV
              </button>
            </div>
          }
        >
          <label className="mb-3 flex items-center gap-2 text-sm">
            <span className="label">Property</span>
            <select className="input h-8 max-w-xs" value={pid ?? ''} onChange={(e) => setPropId(e.target.value)}>
              {d.properties.map((c) => (
                <option key={c.property.id} value={c.property.id}>
                  {c.property.nickname}
                </option>
              ))}
            </select>
          </label>
          <Tabs tabs={PLATFORMS} value={platform} onChange={setPlatform} />
          {fs.isLoading && <Loading />}
          {fs.data && (
            <div className="mt-3 overflow-x-auto">
              <table className="tbl" data-testid="factsheet">
                <thead>
                  <tr>
                    <th>{fs.data.platform_label} field</th>
                    <th>Groundplan key</th>
                    <th className="r">Value</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {fs.data.rows.map((r) => (
                    <tr key={r.groundplan_key}>
                      <td>
                        <div className="text-[13px] text-ink-950">{r.platform_field}</div>
                        {r.note && <div className="text-[11px] text-ink-500">{r.note}</div>}
                      </td>
                      <td className="font-mono text-[11px] text-ink-500">{r.groundplan_key}</td>
                      <td className="r num">{r.value_cents === null ? r.value_text ?? '—' : formatCents(r.value_cents)}</td>
                      <td>
                        <StatusChip status={r.status} compact />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-[11px] text-ink-500">As of {fs.data.as_of}. Paste field-for-field into {fs.data.platform_label}; Estimated rows should be confirmed before they drive a plan.</p>
            </div>
          )}
        </Card>
      </div>
    </TraceScope.Provider>
  );
}
