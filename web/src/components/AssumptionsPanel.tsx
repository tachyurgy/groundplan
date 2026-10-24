import { useEffect, useState } from 'react';
import { formatRate, parseDollarsToCents } from '../lib/money';

export type AssumptionKind = 'rate' | 'cents' | 'bool' | 'int';

export interface AssumptionField {
  key: string;
  label: string;
  kind: AssumptionKind;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  hidden?: boolean;
}

export type AssumptionValues = Record<string, number | boolean>;

function toText(kind: AssumptionKind, v: number | boolean | undefined): string {
  if (v === undefined) return '';
  if (kind === 'rate') return ((v as number) * 100).toFixed(2).replace(/\.?0+$/, '') || '0';
  if (kind === 'cents') return Math.round((v as number) / 100).toLocaleString('en-US');
  return String(v);
}

function fromText(kind: AssumptionKind, s: string): number | null {
  if (kind === 'rate') {
    const n = Number(s.replace('%', '').trim());
    return Number.isFinite(n) ? n / 100 : null;
  }
  if (kind === 'cents') return parseDollarsToCents(s);
  const n = Number(s);
  return Number.isFinite(n) ? Math.round(n) : null;
}

function Field({ f, value, defaultValue, onCommit }: { f: AssumptionField; value: number | boolean | undefined; defaultValue?: number | boolean; onCommit: (v: number | boolean) => void }) {
  const [text, setText] = useState(toText(f.kind, value));
  useEffect(() => setText(toText(f.kind, value)), [value, f.kind]);
  const changed = defaultValue !== undefined && value !== undefined && value !== defaultValue;
  if (f.kind === 'bool') {
    return (
      <label className="flex items-center justify-between gap-3 py-1 text-sm">
        <span className="text-ink-700">{f.label}</span>
        <input type="checkbox" aria-label={f.label} checked={!!value} onChange={(e) => onCommit(e.target.checked)} className="h-4 w-4 accent-brand-600" />
      </label>
    );
  }
  const commit = () => {
    const n = fromText(f.kind, text);
    if (n === null) return setText(toText(f.kind, value));
    const bounded = Math.min(f.max ?? Infinity, Math.max(f.min ?? -Infinity, n));
    if (bounded !== value) onCommit(bounded);
    else setText(toText(f.kind, value));
  };
  return (
    <label className="grid grid-cols-[1fr_7.5rem] items-center gap-2 py-1 text-sm">
      <span className="flex min-w-0 items-center gap-1.5 text-ink-700" title={f.hint}>
        <span className="truncate">{f.label}</span>
        {changed && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand-500" title={`default ${f.kind === 'rate' ? formatRate(defaultValue as number) : String(defaultValue)}`} />}
      </span>
      <span className="relative">
        {f.kind === 'cents' && <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-xs text-ink-400">$</span>}
        <input
          aria-label={f.label}
          inputMode="decimal"
          className={`input-num ${f.kind === 'rate' ? 'pr-6' : ''} ${f.kind === 'cents' ? 'pl-5' : ''}`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
          }}
        />
        {f.kind === 'rate' && <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-ink-400">%</span>}
      </span>
    </label>
  );
}

/**
 * Shared assumptions. Each committed edit (blur / Enter / toggle) calls onChange with the full new set;
 * the page puts these into the query key, so TanStack Query re-requests and every figure recomputes.
 */
export function AssumptionsPanel({
  title = 'Assumptions',
  fields,
  values,
  defaults,
  onChange,
  onReset,
  busy,
}: {
  title?: string;
  fields: AssumptionField[];
  values: AssumptionValues;
  defaults?: AssumptionValues;
  onChange: (v: AssumptionValues) => void;
  onReset?: () => void;
  busy?: boolean;
}) {
  return (
    <section className="card" data-testid="assumptions-panel">
      <div className="card-head">
        <h2 className="flex items-center gap-2">
          {title}
          {busy && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500" title="recomputing" />}
        </h2>
        {onReset && (
          <button type="button" className="text-xs font-medium text-brand-600 hover:underline" onClick={onReset}>
            Reset
          </button>
        )}
      </div>
      <div className="card-body divide-y divide-ink-100 py-1">
        {fields
          .filter((f) => !f.hidden)
          .map((f) => (
            <Field key={f.key} f={f} value={values[f.key]} defaultValue={defaults?.[f.key]} onCommit={(v) => onChange({ ...values, [f.key]: v })} />
          ))}
      </div>
    </section>
  );
}
