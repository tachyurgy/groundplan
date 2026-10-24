import type { Cents, Rate } from '../api/types';

const usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const usd2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Integer cents -> "$1,234,567" (whole dollars, half-up on the cents). */
export function formatCents(cents: Cents | null | undefined, opts: { exact?: boolean; sign?: boolean } = {}): string {
  if (cents === null || cents === undefined || Number.isNaN(cents)) return '—';
  const dollars = cents / 100;
  const s = opts.exact ? usd2.format(Math.abs(dollars)) : usd0.format(Math.abs(Math.round(dollars)));
  if (cents < 0) return `−${s}`; // U+2212 minus, reads better than hyphen in tabular columns
  if (opts.sign && cents > 0) return `+${s}`;
  return s;
}

/** Compact: 1_234_567_00 -> "$1.23M"; 45_600_00 -> "$45.6k". */
export function formatCentsCompact(cents: Cents | null | undefined): string {
  if (cents === null || cents === undefined) return '—';
  const abs = Math.abs(cents) / 100;
  const neg = cents < 0 ? '−' : '';
  if (abs >= 1_000_000) return `${neg}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 10_000) return `${neg}$${(abs / 1_000).toFixed(0)}k`;
  if (abs >= 1_000) return `${neg}$${(abs / 1_000).toFixed(1)}k`;
  return `${neg}$${abs.toFixed(0)}`;
}

/** 0.0375 -> "3.75%" */
export function formatRate(rate: Rate | null | undefined, digits = 2): string {
  if (rate === null || rate === undefined || Number.isNaN(rate)) return '—';
  return `${(rate * 100).toFixed(digits)}%`;
}

/** Parse a user-entered dollar string ("$1,234.56", "1234", "-12") into integer cents. */
export function parseDollarsToCents(input: string): Cents | null {
  const cleaned = input.replace(/[$,\s]/g, '').replace('−', '-');
  if (cleaned === '' || cleaned === '-') return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return null;
  return Math.round(n * 100);
}

/** Sign class for a cents value: green only for positive, red only for negative, neutral for zero. */
export function signClass(cents: Cents | null | undefined): string {
  if (cents === null || cents === undefined || cents === 0) return 'text-ink-900';
  return cents > 0 ? 'text-pos-600' : 'text-neg-600';
}

export function dollars(cents: Cents): number {
  return cents / 100;
}
