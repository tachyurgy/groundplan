/**
 * Shared chart chrome. Every chart on the site goes through ChartFrame, which gives it:
 *  - a fixed-height plot area (no layout shift while data loads),
 *  - a one-sentence text summary (the text alternative screen readers get, also visible),
 *  - a legend whenever there are two or more series (identity is never colour alone),
 *  - a "Table" toggle that swaps the plot for the underlying numbers.
 * Colours are CSS variables (--series-n, --grid, --ink-*), so the same SVG is right in both themes.
 */
import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react';
import { formatCents, formatCentsCompact } from '../lib/money';

export const C = {
  s1: 'var(--series-1)',
  s2: 'var(--series-2)',
  s3: 'var(--series-3)',
  s4: 'var(--series-4)',
  s5: 'var(--series-5)',
  muted: 'var(--series-muted)',
  pos: 'var(--pos-600)',
  neg: 'var(--neg-600)',
  grid: 'var(--grid)',
  axis: 'var(--axis)',
  ink: 'var(--ink-900)',
  ink5: 'var(--ink-500)',
  surface: 'var(--surface)',
};

export const PATH_COLOR = { hold: C.s1, sell: C.s2, exchange: C.s3 } as const;

export const axisTick = { fontSize: 11, fill: 'var(--ink-500)', fontFamily: 'var(--font-mono)' };
export const xAxisProps = { tick: axisTick, tickLine: false, axisLine: { stroke: 'var(--axis)' } } as const;
export const yAxisProps = { tick: axisTick, tickLine: false, axisLine: false, width: 52 } as const;
export const gridProps = { stroke: 'var(--grid)', vertical: false } as const;
export const centsTick = (v: number) => formatCentsCompact(v);

const narrowQuery = '(max-width: 639px)';
function subscribeNarrow(cb: () => void) {
  const m = window.matchMedia(narrowQuery);
  m.addEventListener('change', cb);
  return () => m.removeEventListener('change', cb);
}
/** True on phones: charts drop tick density, legends wrap below, labels shorten. */
export function useNarrow(): boolean {
  return useSyncExternalStore(
    subscribeNarrow,
    () => window.matchMedia(narrowQuery).matches,
    () => false,
  );
}

/** Width of a container, for the hand-built SVG charts. A callback ref, so it works for elements that mount late. */
export function useMeasure<T extends HTMLElement>(): [(el: T | null) => void, number] {
  const [el, setEl] = useState<T | null>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, w];
}

export interface LegendItem {
  label: string;
  color: string;
  value?: string;
  dashed?: boolean;
}

export function Legend({ items }: { items: LegendItem[] }) {
  if (items.length < 2) return null;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-700" aria-label="Legend">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          <svg width="14" height="8" aria-hidden>
            {i.dashed ? <line x1="0" y1="4" x2="14" y2="4" stroke={i.color} strokeWidth="2" strokeDasharray="3 2" /> : <rect x="0" y="0" width="14" height="8" rx="2" fill={i.color} />}
          </svg>
          {i.label}
          {i.value && <span className="num text-ink-950">{i.value}</span>}
        </li>
      ))}
    </ul>
  );
}

export interface TableSpec {
  columns: { key: string; label: string; money?: boolean; align?: 'left' | 'right' }[];
  rows: Record<string, unknown>[];
}

export function ChartFrame({
  title,
  summary,
  legend,
  height,
  table,
  children,
  actions,
  testId,
}: {
  title: ReactNode;
  summary: string;
  legend?: LegendItem[];
  height: number;
  table: TableSpec;
  children: ReactNode;
  actions?: ReactNode;
  testId?: string;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <figure className="min-w-0" data-testid={testId}>
      <div className="mb-2 flex items-start justify-between gap-3">
        <figcaption className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-ink-950">{title}</div>
          <p className="mt-0.5 text-xs leading-relaxed text-ink-500" data-testid="chart-summary">
            {summary}
          </p>
        </figcaption>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          <button type="button" className="btn btn-sm btn-ghost text-ink-500" aria-pressed={showTable} onClick={() => setShowTable(!showTable)}>
            {showTable ? 'Chart' : 'Table'}
          </button>
        </div>
      </div>
      {legend && legend.length > 1 && (
        <div className="mb-2">
          <Legend items={legend} />
        </div>
      )}
      {showTable ? (
        <div className="overflow-auto rounded-md ring-1 ring-ink-100" style={{ maxHeight: Math.max(height, 220) }}>
          <table className="tbl">
            <thead className="sticky top-0 bg-surface">
              <tr>
                {table.columns.map((c) => (
                  <th key={c.key} className={c.money || c.align === 'right' ? 'r' : ''}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i}>
                  {table.columns.map((c) => (
                    <td key={c.key} className={`${c.money || c.align === 'right' ? 'r num' : ''}`}>
                      {c.money && typeof r[c.key] === 'number' ? formatCents(r[c.key] as number) : (r[c.key] as ReactNode) ?? '—'}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ height }} className="min-w-0">
          {children}
        </div>
      )}
    </figure>
  );
}

/** Recharts tooltip body in the app's style. */
export function TooltipBody({ active, payload, label, fmt = (v: number) => formatCents(v), labelFmt }: { active?: boolean; payload?: readonly { name?: string | number; value?: unknown; color?: string; dataKey?: unknown }[]; label?: unknown; fmt?: (v: number) => string; labelFmt?: (l: unknown) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md bg-surface px-3 py-2 text-xs shadow-pop">
      <div className="num mb-1 font-medium text-ink-950">{labelFmt ? labelFmt(label) : String(label)}</div>
      {payload
        .filter((p) => typeof p.value === 'number' || Array.isArray(p.value))
        .map((p, i) => (
          <div key={`${String(p.name)}-${i}`} className="flex items-center justify-between gap-5">
            <span className="flex items-center gap-1.5 text-ink-700">
              <span className="h-2 w-2 rounded-sm" style={{ background: p.color }} />
              {p.name}
            </span>
            <span className="num text-ink-950">{Array.isArray(p.value) ? `${fmt(p.value[0] as number)} – ${fmt(p.value[1] as number)}` : fmt(p.value as number)}</span>
          </div>
        ))}
    </div>
  );
}
