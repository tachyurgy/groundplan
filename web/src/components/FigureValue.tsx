import type { ReactNode } from 'react';
import type { FigureT } from '../api/schemas';
import { formatCents, formatCentsCompact, signClass } from '../lib/money';
import { useUi } from '../lib/theme';
import { useTraceScope } from '../lib/traceScope';
import { StatusChip } from './StatusChip';

interface Props {
  figure: FigureT | null | undefined;
  /** colour by sign (green/red). Off where sign carries no meaning (e.g. property value). */
  signed?: boolean;
  compact?: boolean;
  chip?: boolean;
  className?: string;
  /** override display (e.g. a rate derived from the figure) while still tracing the figure */
  display?: string;
}

/** Any number on screen. Click (or Enter) opens the traceability drawer. Blocked values render struck through. */
export function FigureValue({ figure, signed = false, compact = false, chip = false, className = '', display }: Props) {
  const openTrace = useUi((s) => s.openTrace);
  const scope = useTraceScope();
  if (!figure) return <span className="num text-ink-400">—</span>;
  const blocked = figure.status === 'blocked';
  const text = display ?? (compact ? formatCentsCompact(figure.value_cents) : formatCents(figure.value_cents));
  const label = figure.label ?? figure.key;
  return (
    <span className={`inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5 ${className}`}>
      <button
        type="button"
        data-testid="figure"
        data-key={figure.key}
        data-status={figure.status}
        onClick={(e) => openTrace({ figure, ...scope, returnFocus: e.currentTarget })}
        aria-label={`${label}: ${text}, ${figure.status}. Show how this is calculated`}
        className={`figure-btn ${signed ? signClass(figure.value_cents) : 'text-ink-950'} ${blocked ? 'line-through decoration-blk-600' : ''}`}
      >
        {text}
      </button>
      {chip && <StatusChip status={figure.status} compact />}
    </span>
  );
}

/** Label / value row for dense statements (cash-flow waterfall lists, exit-tax breakdowns). */
export function FigureRow({ label, figure, signed, strong, indent, display, hint }: { label: ReactNode; figure: FigureT | null | undefined; signed?: boolean; strong?: boolean; indent?: boolean; display?: string; hint?: ReactNode }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 py-1.5 ${strong ? 'mt-0.5 border-t border-ink-200 pt-2 font-semibold' : ''}`}>
      <span className={`min-w-0 text-sm ${indent ? 'pl-3 text-ink-500' : 'text-ink-700'}`}>
        {label}
        {hint && <span className="block text-[11px] font-normal text-ink-500">{hint}</span>}
      </span>
      <span className="flex shrink-0 items-center gap-2">
        {figure && <StatusChip status={figure.status} compact />}
        <FigureValue figure={figure} signed={signed} display={display} />
      </span>
    </div>
  );
}
