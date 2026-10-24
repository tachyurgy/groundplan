import { startTransition, useActionState, useRef } from 'react';
import { z } from 'zod';
import { formatCents, formatRate, parseDollarsToCents } from '../lib/money';
import { Pulse } from './ui';

export type FieldKind = 'rate' | 'cents' | 'int' | 'bool';
export interface FieldDef {
  key: string;
  label: string;
  kind: FieldKind;
  min?: number;
  max?: number;
  hint?: string;
}
export type Values = Record<string, number | boolean>;

function toText(kind: FieldKind, v: number | boolean | undefined): string {
  if (v === undefined) return '';
  if (kind === 'rate') return String(Number(((v as number) * 100).toFixed(3)));
  if (kind === 'cents') return Math.round((v as number) / 100).toLocaleString('en-US');
  return String(v);
}

function fmtBound(kind: FieldKind, v: number) {
  return kind === 'rate' ? formatRate(v, 1) : kind === 'cents' ? formatCents(v) : String(v);
}

/** Zod schema for one field: text in the form's units (%, $, years) -> the API's units (decimal, cents, int). */
function fieldSchema(f: FieldDef) {
  const num = z
    .string()
    .trim()
    .min(1, 'Required')
    .transform((s, ctx) => {
      const n = f.kind === 'cents' ? parseDollarsToCents(s) : Number(s.replace(/[%,\s]/g, ''));
      if (n === null || !Number.isFinite(n)) {
        ctx.addIssue({ code: 'custom', message: 'Enter a number' });
        return z.NEVER;
      }
      return f.kind === 'rate' ? n / 100 : f.kind === 'int' ? Math.round(n) : n;
    });
  return num.refine((n) => (f.min === undefined || n >= f.min - 1e-9) && (f.max === undefined || n <= f.max + 1e-9), {
    message:
      f.min !== undefined && f.max !== undefined
        ? `Between ${fmtBound(f.kind, f.min)} and ${fmtBound(f.kind, f.max)}`
        : f.min !== undefined
          ? `At least ${fmtBound(f.kind, f.min)}`
          : `At most ${fmtBound(f.kind, f.max!)}`,
  });
}

/**
 * Assumptions as a React 19 form action. Each field commits on blur / Enter / toggle by submitting the
 * form; the action validates every field with Zod and, if valid, hands the full set to onCommit (which
 * writes the URL search params, so the query key changes and every figure recomputes). Invalid input
 * shows an inline message and never reaches the API.
 */
export function AssumptionsForm({
  title,
  fields,
  values,
  defaults,
  onCommit,
  onReset,
  busy,
  testId = 'assumptions-panel',
}: {
  title: string;
  fields: FieldDef[];
  values: Values;
  defaults?: Values;
  onCommit: (v: Values) => void;
  onReset?: () => void;
  busy?: boolean;
  testId?: string;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [state, action] = useActionState(
    (_prev: { errors: Record<string, string> }, fd: FormData) => {
      const errors: Record<string, string> = {};
      const out: Values = {};
      for (const f of fields) {
        if (f.kind === 'bool') {
          out[f.key] = fd.get(f.key) === 'on';
          continue;
        }
        const r = fieldSchema(f).safeParse(String(fd.get(f.key) ?? ''));
        if (r.success) out[f.key] = r.data;
        else errors[f.key] = r.error.issues[0]?.message ?? 'Invalid';
      }
      if (Object.keys(errors).length) return { errors };
      const changed = fields.some((f) => out[f.key] !== values[f.key]);
      if (changed) onCommit(out);
      return { errors: {} };
    },
    { errors: {} },
  );
  const submit = () => formRef.current?.requestSubmit();
  const dirty = defaults ? fields.some((f) => defaults[f.key] !== undefined && values[f.key] !== defaults[f.key]) : false;
  return (
    // onSubmit + startTransition (not <form action>) so React does not reset the inputs after a
    // failed validation: the user keeps what they typed next to the error.
    <form
      ref={formRef}
      onSubmit={(e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        startTransition(() => action(fd));
      }}
      className="card"
      data-testid={testId}
      noValidate
    >
      <div className="card-head">
        <h2 className="flex items-center gap-2">{title}</h2>
        <div className="flex items-center gap-2">
          <Pulse on={!!busy} />
          {onReset && dirty && (
            <button type="button" className="cursor-pointer text-xs font-medium text-brand-600 hover:underline" onClick={onReset}>
              Reset
            </button>
          )}
        </div>
      </div>
      <div className="divide-y divide-ink-100 px-4 py-1">
        {fields.map((f) => {
          const v = values[f.key];
          const changed = defaults?.[f.key] !== undefined && v !== defaults[f.key];
          const err = state.errors[f.key];
          const id = `${testId}-${f.key}`;
          if (f.kind === 'bool')
            return (
              <label key={f.key} htmlFor={id} className="flex min-h-11 cursor-pointer items-center justify-between gap-3 py-1.5 text-sm sm:min-h-9">
                <span className="text-ink-700">{f.label}</span>
                <input
                  key={String(v)}
                  id={id}
                  name={f.key}
                  type="checkbox"
                  defaultChecked={!!v}
                  onChange={submit}
                  className="h-5 w-5 accent-brand-600 sm:h-4 sm:w-4"
                />
              </label>
            );
          return (
            <div key={f.key} className="py-1.5">
              <div className="grid grid-cols-[1fr_8rem] items-center gap-3">
                <label htmlFor={id} className="flex min-w-0 items-center gap-1.5 text-sm text-ink-700">
                  <span className="truncate" title={f.hint}>
                    {f.label}
                  </span>
                  {changed && (
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand-500" title={`Stored value: ${toText(f.kind, defaults?.[f.key])}`}>
                      <span className="sr-only">(changed)</span>
                    </span>
                  )}
                </label>
                <span className="relative">
                  {f.kind === 'cents' && <span className="pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-xs text-ink-500">$</span>}
                  <input
                    key={`${f.key}:${String(v)}`}
                    id={id}
                    name={f.key}
                    inputMode={f.kind === 'int' ? 'numeric' : 'decimal'}
                    autoComplete="off"
                    defaultValue={toText(f.kind, v)}
                    aria-invalid={!!err}
                    aria-describedby={err ? `${id}-err` : f.hint ? `${id}-hint` : undefined}
                    onBlur={(e) => e.currentTarget.value !== toText(f.kind, v) && submit()}
                    className={`input-num ${f.kind === 'rate' ? 'pr-6' : ''} ${f.kind === 'cents' ? 'pl-5' : ''} ${err ? 'border-neg-600' : ''}`}
                  />
                  {f.kind === 'rate' && <span className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 text-xs text-ink-500">%</span>}
                </span>
              </div>
              {err && (
                <p id={`${id}-err`} role="alert" className="mt-1 text-right text-xs text-neg-600">
                  {err}
                </p>
              )}
              {f.hint && !err && (
                <p id={`${id}-hint`} className="sr-only">
                  {f.hint}
                </p>
              )}
            </div>
          );
        })}
      </div>
      <button type="submit" className="sr-only" tabIndex={-1}>
        Apply
      </button>
    </form>
  );
}
