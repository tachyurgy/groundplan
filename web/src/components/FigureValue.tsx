import type { Figure } from '../api/types';
import { formatCents, formatCentsCompact, signClass } from '../lib/money';
import { StatusChip } from './StatusChip';
import { useTrace, useTraceScope } from '../lib/traceContext';

interface Props {
  figure: Figure | null | undefined;
  /** colour by sign (green/red). Off for values where sign is not meaning (e.g. property value). */
  signed?: boolean;
  compact?: boolean;
  chip?: boolean;
  className?: string;
  /** override display (e.g. a rate derived from the figure) while still tracing the figure */
  display?: string;
}

/** Any number on screen. Click = Traceability drawer. Blocked figures render the value struck through. */
export function FigureValue({ figure, signed = false, compact = false, chip = false, className = '', display }: Props) {
  const { open } = useTrace();
  const scope = useTraceScope();
  if (!figure) return <span className="num text-ink-300">—</span>;
  const blocked = figure.status === 'blocked';
  const text = display ?? (compact ? formatCentsCompact(figure.value_cents) : formatCents(figure.value_cents));
  return (
    <span className={`inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5 ${className}`}>
      <button
        type="button"
        data-testid="figure"
        data-key={figure.key}
        onClick={() => open({ figure, ...scope })}
        title={`${figure.label ?? figure.key} · click to trace`}
        className={`figure-btn ${signed ? signClass(figure.value_cents) : 'text-ink-950'} ${blocked ? 'line-through decoration-blk-600 decoration-solid' : ''}`}
      >
        {text}
      </button>
      {chip && <StatusChip status={figure.status} compact />}
    </span>
  );
}

/** Label / value row used in dense figure lists. */
export function FigureRow({ label, figure, signed, strong, indent, display }: { label: string; figure: Figure | null | undefined; signed?: boolean; strong?: boolean; indent?: boolean; display?: string }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 py-1 ${strong ? 'border-t border-ink-200 pt-1.5 font-semibold' : ''}`}>
      <span className={`min-w-0 text-sm ${indent ? 'pl-3 text-ink-500' : 'text-ink-700'}`}>{label}</span>
      <span className="flex shrink-0 items-center gap-2">
        {figure && <StatusChip status={figure.status} compact />}
        <FigureValue figure={figure} signed={signed} display={display} />
      </span>
    </div>
  );
}
