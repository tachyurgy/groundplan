import type { MatrixMeasure, MatrixVerdict, StrategyPath } from '../api/types';

export const MEASURE_LABEL: Record<MatrixMeasure, string> = {
  terminal_wealth: 'Terminal after-tax wealth',
  cumulative_cash_flow: 'Cumulative cash flow',
  tax_paid_now: 'Tax paid now',
  liquidity: 'Liquidity',
  management_burden: 'Management burden',
  concentration: 'Concentration',
};

const VERDICT_STYLE: Record<MatrixVerdict, string> = {
  leads: 'bg-ink-950 text-white',
  trails: 'bg-white text-ink-500 ring-1 ring-inset ring-ink-200',
  neutral: 'bg-ink-100 text-ink-700',
};

const VERDICT_GLYPH: Record<MatrixVerdict, string> = { leads: '▲', trails: '▼', neutral: '●' };

/**
 * Leads / trails / neutral per measure and path. Descriptive only: the matrix never ranks paths overall
 * and there is no "best" column (SPEC §2.9).
 */
export function StrategyMatrix({
  matrix,
  paths,
}: {
  matrix: Record<MatrixMeasure, Record<StrategyPath, MatrixVerdict>>;
  paths: { path: StrategyPath; label: string }[];
}) {
  const measures = Object.keys(MEASURE_LABEL) as MatrixMeasure[];
  return (
    <div className="overflow-x-auto">
      <table className="tbl" data-testid="strategy-matrix">
        <thead>
          <tr>
            <th>Measure</th>
            {paths.map((p) => (
              <th key={p.path} className="text-center">
                {p.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {measures
            .filter((m) => matrix[m])
            .map((m) => (
              <tr key={m}>
                <td className="whitespace-nowrap text-ink-700">{MEASURE_LABEL[m]}</td>
                {paths.map((p) => {
                  const v = matrix[m][p.path] ?? 'neutral';
                  return (
                    <td key={p.path} className="text-center">
                      <span data-testid={`cell-${m}-${p.path}`} data-verdict={v} className={`inline-flex min-w-[5.5rem] items-center justify-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${VERDICT_STYLE[v]}`}>
                        <span aria-hidden className="text-[9px]">
                          {VERDICT_GLYPH[v]}
                        </span>
                        {v}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-ink-500">Each row compares the three paths on one measure only. Qualitative rows (liquidity, burden, concentration) are rule-based. No row, and no combination of rows, is an instruction to choose a path.</p>
    </div>
  );
}
