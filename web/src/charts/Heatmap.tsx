import { formatRate } from '../lib/money';
import { PATH_COLOR } from './kit';

export type PathId = 'hold' | 'sell' | 'exchange';
export interface HeatCell {
  rate: number;
  horizon: number;
  leader: PathId | null;
  /** lead over the runner-up, as a share of the runner-up's terminal wealth */
  margin: number;
  wealth: Record<PathId, number>;
}

const SHORT: Record<PathId, string> = { hold: 'Hold', sell: 'Sell', exchange: '1031' };

/**
 * Which path ends with the most after-tax wealth, for every (appreciation × horizon) pair.
 * Hue = which path leads (categorical); opacity = by how much (a near-tie fades toward the surface).
 * Text in each cell (path name + margin) so the grid reads without colour.
 */
export function Heatmap({
  rates,
  horizons,
  cells,
  current,
}: {
  rates: number[];
  horizons: number[];
  cells: Map<string, HeatCell | undefined>;
  current?: { rate: number; horizon: number };
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-[3px] text-xs" data-testid="heatmap">
        <caption className="sr-only">Leading path by appreciation rate (rows) and horizon in years (columns)</caption>
        <thead>
          <tr>
            <th scope="col" className="px-1 py-1 text-left font-medium text-ink-500">
              Appr. \ yrs
            </th>
            {horizons.map((h) => (
              <th key={h} scope="col" className="num px-1 py-1 text-center font-medium text-ink-500">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rates.map((r) => (
            <tr key={r}>
              <th scope="row" className="num px-1 text-left font-medium whitespace-nowrap text-ink-700">
                {formatRate(r, 1)}
              </th>
              {horizons.map((h) => {
                const c = cells.get(`${r}|${h}`);
                const isCur = current && Math.abs(current.rate - r) < 1e-6 && current.horizon === h;
                if (!c)
                  return (
                    <td key={h} className="h-11 min-w-[52px] rounded-md bg-ink-100">
                      <span className="sr-only">loading</span>
                      <span aria-hidden className="block h-full w-full animate-pulse rounded-md" />
                    </td>
                  );
                const alpha = c.leader ? Math.min(0.85, 0.2 + Math.min(c.margin, 0.25) * 2.6) : 0;
                const label = c.leader ? `${SHORT[c.leader]} leads by ${(c.margin * 100).toFixed(1)}%` : 'Within 1%';
                return (
                  <td
                    key={h}
                    data-testid="heat-cell"
                    data-leader={c.leader ?? 'tie'}
                    title={`${formatRate(r, 1)} appreciation, ${h} years: ${label}`}
                    className={`relative h-11 min-w-[52px] rounded-md text-center align-middle ${isCur ? 'ring-2 ring-ink-950 ring-offset-1 ring-offset-surface' : ''}`}
                    style={{
                      background: c.leader ? `color-mix(in oklab, ${PATH_COLOR[c.leader]} ${Math.round(alpha * 100)}%, var(--surface))` : 'var(--ink-100)',
                    }}
                  >
                    <span className={`block leading-tight font-semibold text-ink-950`}>{c.leader ? SHORT[c.leader] : 'Tie'}</span>
                    <span className={`num block text-[10.5px] leading-tight text-ink-900`}>
                      {c.leader ? `+${(c.margin * 100).toFixed(c.margin < 0.1 ? 1 : 0)}%` : '±1%'}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
