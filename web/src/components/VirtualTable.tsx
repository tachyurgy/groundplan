import { useVirtualizer } from '@tanstack/react-virtual';
import { useRef, type ReactNode } from 'react';

export interface VCol<R> {
  key: string;
  label: string;
  right?: boolean;
  width?: string;
  render: (r: R) => ReactNode;
}

/**
 * Windowed table for long schedules (a 30-year loan is 360 monthly rows). Fixed row height means the
 * virtualizer never measures, the header stays sticky, and only ~20 rows are in the DOM at a time.
 * CSS grid rows instead of <table> because table rows cannot be absolutely positioned.
 */
export function VirtualTable<R>({
  rows,
  cols,
  height = 360,
  rowHeight = 32,
  label,
  rowClass,
  testId,
}: {
  rows: R[];
  cols: VCol<R>[];
  height?: number;
  rowHeight?: number;
  label: string;
  rowClass?: (r: R) => string;
  testId?: string;
}) {
  const parent = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual returns fresh functions each render by design; the compiler skips this component.
  const v = useVirtualizer({ count: rows.length, getScrollElement: () => parent.current, estimateSize: () => rowHeight, overscan: 8 });
  const template = cols.map((c) => c.width ?? 'minmax(0,1fr)').join(' ');
  return (
    <div
      ref={parent}
      className="relative overflow-auto rounded-md ring-1 ring-ink-100"
      style={{ height: Math.min(height, rows.length * rowHeight + 34) }}
      role="table"
      aria-label={label}
      aria-rowcount={rows.length + 1}
      data-testid={testId}
      tabIndex={0}
    >
      <div
        role="row"
        className="sticky top-0 z-10 grid border-b border-ink-200 bg-surface text-xs font-medium text-ink-500"
        style={{ gridTemplateColumns: template }}
      >
        {cols.map((c) => (
          <div role="columnheader" key={c.key} className={`px-2 py-2 whitespace-nowrap ${c.right ? 'text-right' : ''}`}>
            {c.label}
          </div>
        ))}
      </div>
      <div style={{ height: v.getTotalSize(), position: 'relative' }}>
        {v.getVirtualItems().map((vi) => {
          const r = rows[vi.index];
          return (
            <div
              role="row"
              aria-rowindex={vi.index + 2}
              key={vi.key}
              className={`absolute inset-x-0 grid items-center border-b border-ink-100 text-sm ${rowClass?.(r) ?? ''}`}
              style={{ height: rowHeight, transform: `translateY(${vi.start}px)`, gridTemplateColumns: template }}
            >
              {cols.map((c) => (
                <div role="cell" key={c.key} className={`truncate px-2 ${c.right ? 'num text-right' : ''}`}>
                  {c.render(r)}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
