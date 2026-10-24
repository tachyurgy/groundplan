import type { FigureT } from '../api/schemas';
import { Sparkline } from '../charts/Sparkline';
import { FigureValue } from './FigureValue';
import { StatusChip } from './StatusChip';

/**
 * Headline figure: label, the traceable number with its status, and (optionally) a 10-year trend.
 * `spark` reserves the sparkline's height up front so the tile does not grow when the trend arrives.
 */
export function KpiTile({
  label,
  figure,
  signed,
  sub,
  trend,
  spark = false,
  trendLabel,
  display,
}: {
  label: string;
  figure: FigureT | null | undefined;
  signed?: boolean;
  sub?: string;
  trend?: number[];
  spark?: boolean;
  trendLabel?: string;
  display?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col bg-surface px-4 py-3" data-testid="kpi">
      <span className="label truncate">{label}</span>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-xl leading-tight font-medium sm:text-[1.35rem]">
          <FigureValue figure={figure} signed={signed} display={display} />
        </span>
        {figure && <StatusChip status={figure.status} compact />}
      </div>
      {(spark || sub) && (
        <div className="mt-auto pt-1.5">
          {spark &&
            (trend ? (
              <Sparkline
                values={trend}
                label={trendLabel ?? `${label} trend`}
                color={signed && trend[trend.length - 1] < 0 ? 'var(--neg-600)' : 'var(--series-1)'}
              />
            ) : (
              <div className="h-8" />
            ))}
          {sub && <div className="text-[11px] leading-snug text-ink-500">{sub}</div>}
        </div>
      )}
    </div>
  );
}
