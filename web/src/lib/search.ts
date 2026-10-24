/**
 * Typed URL state. Every assumption, the horizon, the active tab and the DST toggle are search params,
 * validated with Zod by the router (validateSearch). Invalid or out-of-range values fall back to
 * "unset" (= the property's stored value) instead of crashing, so a hand-edited URL is always safe.
 * Only overrides are written: a pristine view has a clean URL.
 */
import { z } from 'zod';

const rateIn = (min: number, max: number) => z.coerce.number().min(min).max(max).optional().catch(undefined);
const centsIn = z.coerce.number().int().min(0).max(10_000_000_000).optional().catch(undefined);
const bool = z
  .union([z.boolean(), z.enum(['true', 'false', '1', '0'])])
  .transform((v) => v === true || v === 'true' || v === '1')
  .optional()
  .catch(undefined);

export const PROPERTY_TABS = ['cash', 'equity', 'appreciation', 'depreciation', 'exit', 'loans'] as const;
export type PropertyTab = (typeof PROPERTY_TABS)[number];

export const propertySearch = z.object({
  tab: z.enum(PROPERTY_TABS).optional().catch(undefined),
  horizon: z.coerce.number().int().min(1).max(30).optional().catch(undefined),
  current_value_cents: centsIn,
  appreciation_rate: rateIn(-0.2, 0.3),
  rent_growth_rate: rateIn(-0.2, 0.3),
  expense_growth_rate: rateIn(-0.2, 0.3),
  vacancy_rate: rateIn(0, 0.9),
  capex_reserve_rate: rateIn(0, 0.5),
  selling_cost_rate: rateIn(0, 0.2),
  land_pct: rateIn(0, 1),
  arm_index: rateIn(0, 0.2),
});
export type PropertySearch = z.infer<typeof propertySearch>;

export const strategiesSearch = z.object({
  horizon: z.coerce.number().int().min(1).max(30).optional().catch(undefined),
  appreciation_rate: rateIn(-0.2, 0.3),
  rent_growth: rateIn(-0.2, 0.3),
  expense_growth: rateIn(-0.2, 0.3),
  reinvest_rate: rateIn(-0.1, 0.2),
  arm_index: rateIn(0, 0.2),
  replacement_value_cents: centsIn,
  replacement_debt_cents: centsIn,
  cash_taken_cents: centsIn,
  dst: bool,
  load_rate: rateIn(0, 0.25),
  dst_yield: rateIn(0, 0.15),
});
export type StrategiesSearch = z.infer<typeof strategiesSearch>;

export const documentsSearch = z.object({
  doc: z.string().optional().catch(undefined),
  page: z.coerce.number().int().min(1).max(500).optional().catch(undefined),
});

export const reportsSearch = z.object({
  property: z.string().optional().catch(undefined),
  platform: z.enum(['emoney', 'rightcapital', 'mgp']).optional().catch(undefined),
});

export const simulateSearch = z.object({
  years: z.coerce.number().int().min(3).max(30).optional().catch(undefined),
  runs: z.coerce.number().int().min(10).max(2000).optional().catch(undefined),
});

/** Strip keys equal to the base value (so the URL only carries real overrides). */
export function overridesOnly<T extends Record<string, unknown>>(next: T, base: Partial<Record<keyof T, unknown>>): Partial<T> {
  const out: Partial<T> = {};
  for (const [k, v] of Object.entries(next)) {
    if (v === undefined) continue;
    const b = base[k as keyof T];
    if (typeof v === 'number' && typeof b === 'number' && Math.abs(v - b) < 1e-9) continue;
    if (v === b) continue;
    out[k as keyof T] = v as T[keyof T];
  }
  return out;
}

export const twinSearch = z.object({
  to: z.string().max(2000).optional().catch(undefined),
  hh: z.string().max(200).optional().catch(undefined),
  prop: z.string().max(200).optional().catch(undefined),
});
