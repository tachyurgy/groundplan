import type { FigureStatus } from '../api/types';
import { STATUS_CLASS, STATUS_LABEL } from '../lib/status';

const DOT: Record<FigureStatus, string> = { confirmed: 'bg-pos-600', estimated: 'bg-est-600', blocked: 'bg-blk-600' };

export function StatusChip({ status, compact = false, title }: { status: FigureStatus; compact?: boolean; title?: string }) {
  const tip =
    title ??
    (status === 'confirmed'
      ? 'Every input comes from a document or manual entry.'
      : status === 'estimated'
        ? 'At least one input is public data or a default assumption.'
        : 'An open blocking finding touches an input. Resolve it in the reconciliation queue.');
  return (
    <span
      title={tip}
      data-testid="status-chip"
      data-status={status}
      className={`inline-flex shrink-0 items-center gap-1 rounded-full ${compact ? 'px-1.5 text-[9.5px]' : 'px-2 text-[10.5px]'} py-px font-semibold uppercase tracking-wide ring-1 ring-inset ${STATUS_CLASS[status]}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${DOT[status]}`} aria-hidden />
      {STATUS_LABEL[status]}
    </span>
  );
}
