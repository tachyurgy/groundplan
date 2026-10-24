import { describe, expect, it } from 'vitest';
import { formatCents, formatCentsCompact, formatRate, parseDollarsToCents, signClass } from '../lib/money';
import { factSheetCsv } from '../lib/factsheet';

describe('money formatting (integer cents in, dollars out)', () => {
  it('formats whole dollars with half-up rounding and a true minus sign', () => {
    expect(formatCents(1_500_000)).toBe('$15,000');
    expect(formatCents(149)).toBe('$1');
    expect(formatCents(150)).toBe('$2');
    expect(formatCents(-800_000)).toBe('−$8,000');
    expect(formatCents(0)).toBe('$0');
    expect(formatCents(null)).toBe('—');
  });
  it('exact mode keeps cents; sign mode prefixes positives', () => {
    expect(formatCents(1_018_182, { exact: true })).toBe('$10,181.82');
    expect(formatCents(1_200_000, { sign: true })).toBe('+$12,000');
  });
  it('compact', () => {
    expect(formatCentsCompact(123_456_700)).toBe('$1.23M');
    expect(formatCentsCompact(4_560_000)).toBe('$46k');
    expect(formatCentsCompact(-250_000)).toBe('−$2.5k');
  });
  it('rates are decimals', () => {
    expect(formatRate(0.035)).toBe('3.50%');
    expect(formatRate(0.03875, 3)).toBe('3.875%');
  });
  it('parses user dollars to integer cents', () => {
    expect(parseDollarsToCents('$1,234.56')).toBe(123_456);
    expect(parseDollarsToCents('620000')).toBe(62_000_000);
    expect(parseDollarsToCents('−12')).toBe(-1_200);
    expect(parseDollarsToCents('abc')).toBeNull();
    expect(parseDollarsToCents('')).toBeNull();
  });
  it('green/red only for sign', () => {
    expect(signClass(1)).toContain('pos');
    expect(signClass(-1)).toContain('neg');
    expect(signClass(0)).not.toMatch(/pos|neg/);
  });
  it('fact sheet CSV exports dollars and escapes', () => {
    const csv = factSheetCsv({ property_id: 'p', format: 'csv', platform_label: 'x', as_of: '2025-12-31', rows: [{ groundplan_key: 'value', platform_field: 'Assets, Real Estate', value_cents: 62_000_000, value_text: null, status: 'confirmed', note: null }] });
    expect(csv.split('\n')[1]).toBe('value,"Assets, Real Estate",620000.00,confirmed,');
  });
});
