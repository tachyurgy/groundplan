import { formatCentsCompact } from '../lib/money';

/** Shared Recharts styling: muted axes, tabular mono ticks, one ink + one accent per series family. */
export const SERIES = {
  hold: '#163a5f',
  sell: '#8a94a8',
  exchange: '#2f8f83',
  ink: '#111a2e',
  accent: '#2a6aa8',
  band: '#2a6aa8',
  pos: '#157347',
  neg: '#b42318',
  warm: '#c08a2d',
};

export const axisProps = {
  tick: { fontSize: 11, fill: '#5b6478', fontFamily: '"JetBrains Mono", ui-monospace, monospace' },
  tickLine: false,
  axisLine: { stroke: '#d6d9e0' },
} as const;

export const gridProps = { stroke: '#eceef2', vertical: false } as const;

export const centsTick = (v: number) => formatCentsCompact(v);

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
