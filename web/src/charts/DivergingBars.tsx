import type { FigureT } from '../api/schemas';
import { formatCents, formatCentsCompact } from '../lib/money';
import { useUi } from '../lib/theme';
import { useTraceScope } from '../lib/traceScope';
import { C, useMeasure, useNarrow } from './kit';

export interface DivergingRow {
  label: string;
  value: number;
  figure?: FigureT;
  scope?: { propertyId?: string; householdId?: string };
}

/** Bars left/right of zero; green and red encode the sign and nothing else. */
export function DivergingBars({ rows }: { rows: DivergingRow[] }) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const narrow = useNarrow();
  const openTrace = useUi((s) => s.openTrace);
  const scope = useTraceScope();
  const labelW = narrow ? 96 : 130;
  const valueW = narrow ? 64 : 84;
  const track = Math.max(60, width - labelW - valueW * 2);
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.value)));
  const hasNeg = rows.some((r) => r.value < 0);
  const hasPos = rows.some((r) => r.value > 0);
  const zero = labelW + valueW + (hasNeg && hasPos ? track / 2 : hasNeg ? track : 0);
  const half = hasNeg && hasPos ? track / 2 : track;
  const rowH = 32;
  const h = rows.length * rowH;
  return (
    <div ref={ref} className="w-full">
      {width > 0 && (
        <svg width={width} height={h}>
          <line x1={zero} x2={zero} y1={0} y2={h} stroke={C.axis} />
          {rows.map((r, i) => {
            const y = i * rowH + 9;
            const len = (Math.abs(r.value) / maxAbs) * (half - 4);
            const x0 = r.value >= 0 ? zero : zero - len;
            const valX = r.value >= 0 ? zero + len + 6 : zero - len - 6;
            const fig = r.figure;
            return (
              <g key={r.label}>
                <text x={0} y={y + 7} dominantBaseline="central" fontSize={12} fill="var(--ink-700)">
                  {r.label.length > (narrow ? 13 : 20) ? `${r.label.slice(0, narrow ? 12 : 19)}…` : r.label}
                </text>
                <rect x={x0} y={y} width={Math.max(2, len)} height={14} rx={3} fill={r.value >= 0 ? C.pos : C.neg} />
                <foreignObject x={r.value >= 0 ? valX : valX - valueW} y={y - 4} width={valueW} height={22} style={{ overflow: 'visible' }}>
                  <button
                    type="button"
                    data-testid="figure"
                    data-key={fig?.key}
                    disabled={!fig}
                    onClick={(e) => fig && openTrace({ figure: fig, ...scope, ...r.scope, returnFocus: e.currentTarget })}
                    className={`figure-btn block w-full text-[12px] ${r.value >= 0 ? 'text-left text-pos-600' : 'text-right text-neg-600'}`}
                    aria-label={`${r.label} net cash flow ${formatCents(r.value)}`}
                  >
                    {formatCentsCompact(r.value)}
                  </button>
                </foreignObject>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
