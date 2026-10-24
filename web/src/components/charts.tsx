import { formatCentsCompact } from '../lib/money';

export function ChartTooltip({ active, payload, label, fmt = formatCentsCompact }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string | number; fmt?: (v: number) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-ink-200 bg-white px-2.5 py-1.5 text-xs shadow-card">
      <div className="mb-1 font-semibold text-ink-900">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-ink-700">
            <span className="h-2 w-2 rounded-sm" style={{ background: p.color }} />
            {p.name}
          </span>
          <span className="num text-ink-950">{fmt(p.value)}</span>
        </div>
      ))}
    </div>
  );
}
