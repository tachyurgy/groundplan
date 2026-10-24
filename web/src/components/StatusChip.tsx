import type { FigureStatus } from '../api/types';

const STYLE: Record<FigureStatus, { cls: string; label: string; tip: string; glyph: string }> = {
  confirmed: { cls: 'bg-pos-100 text-pos-600 ring-pos-600/25', label: 'Confirmed', glyph: '✓', tip: 'Every input comes from a document or manual entry.' },
  estimated: { cls: 'bg-est-100 text-est-600 ring-est-600/30', label: 'Estimated', glyph: '~', tip: 'At least one input is public data or a default assumption.' },
  blocked: { cls: 'bg-blk-100 text-blk-600 ring-blk-600/30', label: 'Blocked', glyph: '!', tip: 'An open blocking finding touches an input. Resolve it in the reconciliation queue.' },
};

/** Confirmed / Estimated / Blocked. Glyph + word, never colour alone. */
export function StatusChip({ status, compact = false }: { status: FigureStatus; compact?: boolean }) {
  const s = STYLE[status] ?? STYLE.estimated;
  return (
    <span title={s.tip} data-testid="status-chip" data-status={status} className={`chip ${s.cls} ${compact ? 'px-1.5 text-[10.5px]' : ''}`}>
      <span aria-hidden className="font-mono text-[10px] leading-none font-semibold">
        {s.glyph}
      </span>
      {s.label}
    </span>
  );
}
