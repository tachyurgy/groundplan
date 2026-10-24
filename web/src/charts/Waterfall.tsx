import type { FigureT } from '../api/schemas';
import { formatCents, formatCentsCompact } from '../lib/money';
import { useUi } from '../lib/theme';
import { useTraceScope } from '../lib/traceScope';
import { C, useMeasure, useNarrow } from './kit';

export interface WaterfallStep {
  label: string;
  /** signed amount in cents: totals are levels, steps are deltas */
  value: number;
  kind: 'total' | 'step';
  color?: string;
  figure?: FigureT;
}

/** Running totals: totals reset the level, steps float from the previous level. Pure, outside render. */
export function layout(steps: WaterfallStep[]) {
  return steps.reduce<(WaterfallStep & { from: number; to: number })[]>((out, s) => {
    const level = out.length ? out[out.length - 1].to : 0;
    out.push(s.kind === 'total' ? { ...s, from: 0, to: s.value } : { ...s, from: level, to: level + s.value });
    return out;
  }, []);
}

/**
 * Horizontal waterfall: each row floats from the running total. Horizontal so it reads the same on a
 * phone (labels never collide) as on a desktop. Every row opens the traceability drawer for its figure.
 */
export function Waterfall({ steps }: { steps: WaterfallStep[] }) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const narrow = useNarrow();
  const openTrace = useUi((s) => s.openTrace);
  const scope = useTraceScope();
  const rows = layout(steps);
  const max = Math.max(1, ...rows.map((r) => Math.max(r.from, r.to)));
  const min = Math.min(0, ...rows.map((r) => Math.min(r.from, r.to)));
  const labelW = narrow ? 108 : 168;
  const valueW = narrow ? 70 : 92;
  const track = Math.max(40, width - labelW - valueW - 16);
  const x = (v: number) => ((v - min) / (max - min)) * track;
  const rowH = narrow ? 30 : 28;
  const barH = 14;
  const h = rows.length * rowH + 4;
  return (
    <div ref={ref} className="w-full">
      {width > 0 && (
        <svg width={width} height={h} role="list" aria-label="Sale proceeds waterfall">
          {/* zero line */}
          <line x1={labelW + x(0)} x2={labelW + x(0)} y1={0} y2={h} stroke={C.axis} strokeWidth={1} />
          {rows.map((r, i) => {
            const y = i * rowH + (rowH - barH) / 2;
            const x0 = labelW + x(Math.min(r.from, r.to));
            const w = Math.max(2, Math.abs(x(r.to) - x(r.from)));
            const fill = r.color ?? (r.kind === 'total' ? 'var(--ink-700)' : r.value < 0 ? C.muted : C.pos);
            const next = rows[i + 1];
            return (
              <g key={r.label} role="listitem" aria-label={`${r.label}: ${formatCents(r.value)}`}>
                <text x={0} y={y + barH / 2} dominantBaseline="central" fontSize={12} fill={r.kind === 'total' ? 'var(--ink-950)' : 'var(--ink-700)'} fontWeight={r.kind === 'total' ? 600 : 400}>
                  {r.label}
                </text>
                <rect x={x0} y={y} width={w} height={barH} rx={3} fill={fill} />
                {next && next.kind === 'step' && <line x1={labelW + x(r.to)} x2={labelW + x(r.to)} y1={y + barH} y2={y + rowH} stroke={C.axis} strokeDasharray="2 2" />}
                <foreignObject x={labelW + track + 8} y={y - 4} width={valueW + 8} height={barH + 8}>
                  {r.figure ? (
                    <button
                      type="button"
                      data-testid="figure"
                      data-key={r.figure.key}
                      onClick={(e) => openTrace({ figure: r.figure!, ...scope, returnFocus: e.currentTarget })}
                      className="figure-btn block w-full text-right text-[12px] text-ink-950"
                      aria-label={`${r.label}: ${narrow ? formatCentsCompact(r.value) : formatCents(r.value)}. Show how this is calculated`}
                    >
                      {narrow ? formatCentsCompact(r.value) : formatCents(r.value)}
                    </button>
                  ) : (
                    <span className="num block text-right text-[12px] text-ink-950">{formatCents(r.value)}</span>
                  )}
                </foreignObject>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
