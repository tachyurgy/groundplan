import type { Figure } from '../api/types';
import { FigureValue } from './FigureValue';
import { StatusChip } from './StatusChip';

export function Metric({ label, figure, signed, sub, display }: { label: string; figure: Figure | null | undefined; signed?: boolean; sub?: string; display?: string }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <span className="label">{label}</span>
        {figure && <StatusChip status={figure.status} compact />}
      </div>
      <div className="mt-1 text-xl font-semibold leading-tight">
        <FigureValue figure={figure} signed={signed} display={display} />
      </div>
      {sub && <div className="mt-0.5 text-xs text-ink-500">{sub}</div>}
    </div>
  );
}
