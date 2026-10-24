import { Tabs as RTabs } from 'radix-ui';
import type { ReactNode } from 'react';
import type { Severity } from '../api/types';

export function Card({
  title,
  actions,
  children,
  className = '',
  bodyClass = 'card-body',
  id,
  sub,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
  id?: string;
  sub?: ReactNode;
}) {
  return (
    <section id={id} className={`card ${className}`} aria-labelledby={id && title ? `${id}-title` : undefined}>
      {(title || actions) && (
        <div className="card-head">
          <div className="min-w-0">
            {typeof title === 'string' ? <h2 id={id ? `${id}-title` : undefined}>{title}</h2> : title}
            {sub && <div className="mt-0.5 text-xs text-ink-500">{sub}</div>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      {/* a body that scrolls sideways must be reachable by keyboard (axe: scrollable-region-focusable) */}
      {/overflow-(x-)?auto/.test(bodyClass) ? (
        <div className={bodyClass} tabIndex={0} role="region" aria-label={typeof title === 'string' ? title : 'Scrollable content'}>
          {children}
        </div>
      ) : (
        <div className={bodyClass}>{children}</div>
      )}
    </section>
  );
}

const SEV: Record<Severity, { cls: string; label: string; icon: string }> = {
  block: { cls: 'bg-blk-100 text-blk-600 ring-blk-600/30', label: 'Blocking', icon: '■' },
  warn: { cls: 'bg-est-100 text-est-600 ring-est-600/30', label: 'Warning', icon: '▲' },
  info: { cls: 'bg-ink-100 text-ink-700 ring-ink-300', label: 'Info', icon: '●' },
};

export function SeverityTag({ severity }: { severity: Severity }) {
  const s = SEV[severity] ?? SEV.info;
  return (
    <span className={`chip ${s.cls}`}>
      <span aria-hidden className="text-[8px]">
        {s.icon}
      </span>
      {s.label}
    </span>
  );
}

/** Accessible tabs (Radix: roving focus, arrow keys, aria wiring). Controlled, so the value can live in the URL. */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
  children,
}: {
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (t: T) => void;
  label: string;
  children?: ReactNode;
}) {
  return (
    <RTabs.Root value={value} onValueChange={(v) => onChange(v as T)} activationMode="manual">
      <RTabs.List aria-label={label} className="-mx-1 flex gap-0.5 overflow-x-auto border-b border-ink-100 px-1 [scrollbar-width:none]">
        {tabs.map((t) => (
          <RTabs.Trigger
            key={t.id}
            value={t.id}
            className="-mb-px h-11 shrink-0 cursor-pointer border-b-2 border-transparent px-3 text-sm font-medium whitespace-nowrap text-ink-500 transition-colors hover:text-ink-900 data-[state=active]:border-brand-600 data-[state=active]:text-ink-950 sm:h-10"
          >
            {t.label}
          </RTabs.Trigger>
        ))}
      </RTabs.List>
      {children}
    </RTabs.Root>
  );
}
export const TabPanel = RTabs.Content;

export function PageHeader({ back, title, children, actions }: { back?: ReactNode; title: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between sm:gap-x-4">
      <div className="min-w-0 flex-1">
        {back && <div className="mb-1.5 text-sm">{back}</div>}
        <h1 className="break-words">{title}</h1>
        {children && <div className="mt-1.5 max-w-[72ch] text-sm leading-relaxed text-ink-500">{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 [&>*]:flex-1 sm:[&>*]:flex-none">{actions}</div>}
    </div>
  );
}

export function Banner({ tone = 'info', children, action }: { tone?: 'info' | 'warn' | 'error'; children: ReactNode; action?: ReactNode }) {
  const cls =
    tone === 'error'
      ? 'border-neg-600/30 bg-neg-100 text-neg-600'
      : tone === 'warn'
        ? 'border-est-600/30 bg-est-100 text-est-600'
        : 'border-brand-500/25 bg-brand-50 text-brand-700';
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2 text-sm ${cls}`}>
      <div className="min-w-0 flex-1">{children}</div>
      {action}
    </div>
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="divide-y divide-ink-100 text-sm">
      {items.map(([k, v], i) => (
        <div key={i} className="flex items-baseline justify-between gap-3 py-1.5">
          <dt className="text-ink-500">{k}</dt>
          <dd className="num text-right text-ink-900">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Pulse({ on, label = 'Recomputing' }: { on: boolean; label?: string }) {
  return (
    <span aria-live="polite" className="inline-flex h-4 items-center">
      {on && (
        <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-500">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500" />
          {label}
        </span>
      )}
    </span>
  );
}
