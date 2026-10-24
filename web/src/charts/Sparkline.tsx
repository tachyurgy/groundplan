/** Word-sized trend line for KPI tiles: no axes, 1.5px line, end dot. The tile's number carries the value. */
export function Sparkline({ values, color = 'var(--series-1)', label }: { values: number[]; color?: string; label: string }) {
  if (values.length < 2) return <div className="h-8" aria-hidden />;
  const w = 120;
  const h = 32;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (w - 4) + 2, h - 3 - ((v - min) / span) * (h - 6)] as const);
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const [ex, ey] = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-8 w-full" preserveAspectRatio="none" role="img" aria-label={label} data-testid="sparkline">
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={ex} cy={ey} r={2.5} fill={color} stroke="var(--surface)" strokeWidth={1} />
    </svg>
  );
}
