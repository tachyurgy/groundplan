import { useSuspenseQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { householdsQuery } from '../api/queries';
import { StatusChip } from '../components/StatusChip';
import { PageHeader } from '../components/ui';
import { FILING_LABEL } from '../lib/format';
import { formatCents, signClass } from '../lib/money';

export function HouseholdsPage() {
  const { data } = useSuspenseQuery(householdsQuery());
  const totals = data.reduce((a, h) => ({ eq: a.eq + h.total_equity_cents, cf: a.cf + h.net_cash_flow_cents, f: a.f + h.open_findings, p: a.p + h.property_count }), { eq: 0, cf: 0, f: 0, p: 0 });
  return (
    <div>
      <PageHeader title="Households">Rental real estate held by each client household, reconciled from their tax returns and loan statements. Open one to see the portfolio, the reconciliation queue and the hold, sell or exchange comparison.</PageHeader>

      <dl className="mb-5 grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-ink-100 shadow-card md:grid-cols-4">
        {(
          [
            ['Households', String(data.length), ''],
            ['Properties', String(totals.p), ''],
            ['Real-estate equity', formatCents(totals.eq), ''],
            ['Net cash flow / yr', formatCents(totals.cf), signClass(totals.cf)],
          ] as const
        ).map(([k, v, cls]) => (
          <div key={k} className="bg-surface px-4 py-3">
            <dt className="label">{k}</dt>
            <dd className={`num mt-1 text-lg font-medium text-ink-950 ${cls}`}>{v}</dd>
          </div>
        ))}
      </dl>

      {data.length === 0 && (
        <div className="card card-body text-sm text-ink-700">
          This workspace has no households. Use “Reset demo data” in the footer to seed the demo household again.
        </div>
      )}

      {/* phones: stacked cards */}
      <ul className="space-y-3 sm:hidden" data-testid="households-cards">
        {data.map((h) => (
          <li key={h.id} className="card">
            <Link to="/households/$householdId" params={{ householdId: h.id }} className="block px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-semibold text-ink-950">{h.name}</div>
                  <div className="text-xs text-ink-500">
                    {h.state}, {FILING_LABEL[h.filing_status]}, {h.property_count} properties
                  </div>
                </div>
                <StatusChip status={h.status} compact />
              </div>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
                <div>
                  <dt className="label">Equity</dt>
                  <dd className="num">{formatCents(h.total_equity_cents)}</dd>
                </div>
                <div>
                  <dt className="label">Cash flow</dt>
                  <dd className={`num ${signClass(h.net_cash_flow_cents)}`}>{formatCents(h.net_cash_flow_cents)}</dd>
                </div>
                <div>
                  <dt className="label">Findings</dt>
                  <dd className={`num ${h.open_findings ? 'font-semibold text-blk-600' : 'text-ink-500'}`}>{h.open_findings} open</dd>
                </div>
              </dl>
            </Link>
          </li>
        ))}
      </ul>

      <div className="card hidden overflow-x-auto sm:block">
        <table className="tbl" data-testid="households-table">
          <thead>
            <tr>
              <th>Household</th>
              <th>State</th>
              <th>Filing status</th>
              <th className="r">Properties</th>
              <th className="r">Total equity</th>
              <th className="r">Net cash flow / yr</th>
              <th className="r">Open findings</th>
              <th>Figures</th>
            </tr>
          </thead>
          <tbody>
            {data.map((h) => (
              <tr key={h.id}>
                <td>
                  <Link to="/households/$householdId" params={{ householdId: h.id }} className="font-semibold text-ink-950 hover:text-brand-600 hover:underline">
                    {h.name}
                  </Link>
                </td>
                <td className="num">{h.state}</td>
                <td className="text-ink-700">{FILING_LABEL[h.filing_status]}</td>
                <td className="r num">{h.property_count}</td>
                <td className="r num">{formatCents(h.total_equity_cents)}</td>
                <td className={`r num ${signClass(h.net_cash_flow_cents)}`}>{formatCents(h.net_cash_flow_cents)}</td>
                <td className="r">
                  {h.open_findings > 0 ? (
                    <Link to="/households/$householdId/documents" params={{ householdId: h.id }} hash="queue" className="num inline-flex min-w-7 justify-center rounded-full bg-blk-100 px-2 py-px text-xs font-semibold text-blk-600 ring-1 ring-blk-600/25 ring-inset" data-testid="findings-badge" aria-label={`${h.open_findings} open findings`}>
                      {h.open_findings}
                    </Link>
                  ) : (
                    <span className="num text-ink-500">0</span>
                  )}
                </td>
                <td>
                  <StatusChip status={h.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
