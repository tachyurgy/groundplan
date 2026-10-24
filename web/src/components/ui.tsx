import type { ReactNode } from 'react';
import type { Severity } from '../api/types';

export function Card({ title, actions, children, className = '', bodyClass = 'card-body', id }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string; id?: string }) {
  return (
    <section id={id} className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          {typeof title === 'string' ? <h2>{title}</h2> : title}
          {actions}
        </div>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

const SEV: Record<Severity, string> = {
  block: 'bg-blk-100 text-blk-600 ring-blk-600/25',
  warn: 'bg-est-100 text-est-600 ring-est-600/20',
  info: 'bg-ink-100 text-ink-700 ring-ink-500/20',
};

export function SeverityTag({ severity }: { severity: Severity }) {
  return <span className={`inline-flex rounded px-1.5 py-px text-[10.5px] font-semibold uppercase tracking-wide ring-1 ring-inset ${SEV[severity]}`}>{severity}</span>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-ink-200" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${value === t.id ? 'border-brand-600 text-ink-950' : 'border-transparent text-ink-500 hover:text-ink-900'}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-sm text-ink-500">
      <span className="h-2 w-2 animate-pulse rounded-full bg-brand-500" />
      {label}…
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded border border-neg-600/30 bg-neg-100 px-3 py-2 text-sm text-neg-600">
      <strong className="font-semibold">Request failed.</strong> {msg}
      <div className="mt-1 text-xs text-ink-700">Live mode expects the API at http://localhost:8000/api/v1. Run with VITE_MOCK=1 for the fixture household.</div>
    </div>
  );
}

export function PageHeader({ eyebrow, title, children, actions }: { eyebrow?: ReactNode; title: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && <div className="label mb-1">{eyebrow}</div>}
        <h1>{title}</h1>
        {children && <div className="mt-1 text-sm text-ink-500">{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
