import { Link } from 'react-router-dom';
import { useHouseholds } from '../api/hooks';
import { formatCents, signClass } from '../lib/money';
import { FILING_LABEL } from '../lib/format';
import { StatusChip } from '../components/StatusChip';
import { ErrorBox, Loading, PageHeader } from '../components/ui';

export function HouseholdsPage() {
  const { data, isLoading, error } = useHouseholds();
  const totals = data?.reduce((a, h) => ({ eq: a.eq + h.total_equity_cents, cf: a.cf + h.net_cash_flow_cents, f: a.f + h.open_findings, p: a.p + h.property_count }), { eq: 0, cf: 0, f: 0, p: 0 });
  return (
    <div>
      <PageHeader eyebrow="Book of business" title="Households">
        Rental real estate held by each client household, reconciled from their returns and statements.
      </PageHeader>
      {isLoading && <Loading />}
      {!!error && <ErrorBox error={error} />}
      {data && totals && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-px overflow-hidden rounded-md bg-ink-200 shadow-card sm:grid-cols-4">
            {[
              ['Households', String(data.length)],
              ['Properties', String(totals.p)],
              ['Total real-estate equity', formatCents(totals.eq)],
              ['Open findings', String(totals.f)],
            ].map(([k, v]) => (
              <div key={k} className="bg-white px-4 py-3">
                <div className="label">{k}</div>
                <div className="num mt-1 text-lg font-semibold text-ink-950">{v}</div>
              </div>
            ))}
          </div>
          <div className="card overflow-x-auto">
            <table className="tbl min-w-[720px]">
              <thead>
                <tr>
                  <th>Household</th>
                  <th>State</th>
                  <th>Filing</th>
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
                      <Link to={`/households/${h.id}`} className="font-semibold text-ink-950 hover:text-brand-600">
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
                        <Link to={`/households/${h.id}/documents#queue`} className="num inline-flex min-w-[1.75rem] justify-center rounded-full bg-blk-100 px-2 py-px text-xs font-semibold text-blk-600 ring-1 ring-inset ring-blk-600/20" data-testid="findings-badge">
                          {h.open_findings}
                        </Link>
                      ) : (
                        <span className="num text-ink-300">0</span>
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
        </>
      )}
    </div>
  );
}
