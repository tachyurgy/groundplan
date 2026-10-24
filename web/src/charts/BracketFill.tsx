import type { TaxLayerT } from '../api/schemas';
import { formatCents, formatCentsCompact, formatRate } from '../lib/money';
import { C, useMeasure, useNarrow } from './kit';

/**
 * The bracket-stacking picture: taxable income laid out left to right from $0. Ordinary income fills
 * the brackets first, §1245 next at full ordinary rates, unrecaptured §1250 on top at min(bracket, 25%),
 * then long-term gain at 0/15/20% by where it lands. Each slice is labelled with its rate when it fits.
 */
export function BracketFill({ ordinary, l1245, l1250, ltcg }: { ordinary: number; l1245: TaxLayerT[]; l1250: TaxLayerT[]; ltcg: TaxLayerT[] }) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const narrow = useNarrow();
  const top = Math.max(ordinary, ...[...l1245, ...l1250, ...ltcg].map((l) => l.upper_cents), 1);
  const x = (v: number) => (v / top) * width;
  type Slice = { from: number; to: number; color: string; label: string; rate?: number; tax?: number };
  const slices: Slice[] = [
    { from: 0, to: ordinary, color: 'var(--ink-300)', label: 'Other ordinary income' },
    ...l1245.map((l) => ({ from: l.lower_cents, to: l.upper_cents, color: C.s2, label: '§1245', rate: l.rate, tax: l.tax_cents })),
    ...l1250.map((l) => ({ from: l.lower_cents, to: l.upper_cents, color: C.s1, label: '§1250', rate: l.rate, tax: l.tax_cents })),
    ...ltcg.map((l) => ({ from: l.lower_cents, to: l.upper_cents, color: C.s3, label: 'LTCG', rate: l.rate, tax: l.tax_cents })),
  ].filter((s) => s.to > s.from);
  const ticks = [...new Set(slices.flatMap((s) => [s.from, s.to]))].sort((a, b) => a - b);
  const barY = 18;
  const barH = 30;
  return (
    <div ref={ref} className="w-full" data-testid="bracket-fill">
      {width > 0 && (
        <svg width={width} height={barY + barH + 34} aria-hidden>
          {slices.map((s, i) => {
            const x0 = x(s.from);
            const w = Math.max(1, x(s.to) - x0 - 2);
            const fits = w > (narrow ? 34 : 44);
            return (
              <g key={i}>
                <rect x={x0} y={barY} width={w} height={barH} rx={i === 0 ? 4 : 2} fill={s.color} />
                {fits && s.rate !== undefined && (
                  <text
                    x={x0 + w / 2}
                    y={barY + barH / 2}
                    textAnchor="middle"
                    dominantBaseline="central"
                    fontSize={11}
                    fontFamily="var(--font-mono)"
                    fill="#fff"
                    fontWeight={600}
                  >
                    {formatRate(s.rate, 0)}
                  </text>
                )}
                {fits && s.rate === undefined && w > 120 && (
                  <text x={x0 + 8} y={barY + barH / 2} dominantBaseline="central" fontSize={11} fill="var(--ink-950)">
                    ordinary income
                  </text>
                )}
              </g>
            );
          })}
          {ticks.map((t, i) => {
            const tx = x(t);
            const show = i === 0 || i === ticks.length - 1 || !narrow;
            const prev = ticks[i - 1];
            if (!show || (prev !== undefined && x(t) - x(prev) < 44 && i !== ticks.length - 1))
              return <line key={t} x1={tx} x2={tx} y1={barY + barH} y2={barY + barH + 4} stroke={C.axis} />;
            return (
              <g key={t}>
                <line x1={tx} x2={tx} y1={barY - 4} y2={barY + barH + 4} stroke={C.axis} />
                <text
                  x={Math.min(Math.max(tx, 18), width - 18)}
                  y={barY + barH + 16}
                  textAnchor="middle"
                  fontSize={10.5}
                  fontFamily="var(--font-mono)"
                  fill="var(--ink-500)"
                >
                  {formatCentsCompact(t)}
                </text>
              </g>
            );
          })}
          <text x={0} y={10} fontSize={11} fill="var(--ink-500)">
            Taxable income, stacked from $0 →
          </text>
        </svg>
      )}
      <ul className="mt-2 mb-1 grid gap-x-6 gap-y-1 text-xs text-ink-700 sm:grid-cols-2">
        {slices
          .filter((s) => s.rate !== undefined)
          .map((s, i) => (
            <li key={i} className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm" style={{ background: s.color }} />
                {s.label} at {formatRate(s.rate!, 0)}
                <span className="text-ink-500">on {formatCentsCompact(s.to - s.from)}</span>
              </span>
              <span className="num text-ink-950">{formatCents(s.tax ?? 0)}</span>
            </li>
          ))}
      </ul>
    </div>
  );
}
