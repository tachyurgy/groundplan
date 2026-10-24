import { describe, it, expect } from 'vitest';
import { mockFetch } from '../api/mock/router';
import { resetDb } from '../api/mock/state';
import type { Dashboard, PropertyAnalysis, StrategyComparison } from '../api/types';

describe('mock fixture service', () => {
  it('serves the Okafor-Lindqvist dashboard with integer cents and SPEC §1 statuses', async () => {
    resetDb();
    const d = (await mockFetch('GET', '/api/v1/households/hh_okafor_lindqvist/dashboard')) as Dashboard;
    expect(d.properties).toHaveLength(4);
    for (const c of d.properties) expect(Number.isInteger(c.net_cash_flow.value_cents)).toBe(true);
    const oak = d.properties.find((c) => c.property.nickname === 'Oak condo')!;
    expect(oak.status_chips.every((s) => s === 'blocked')).toBe(true); // missing-from-2025 block finding
    const maple = d.properties.find((c) => c.property.nickname === 'Maple duplex')!;
    expect(maple.value.status).toBe('confirmed'); // appraisal-backed
    expect(maple.net_cash_flow.status).toBe('blocked'); // rent conflict
    expect(d.narrative.provider).toBe('template');
  });

  it('every property yields three strategy paths and a full matrix', async () => {
    for (const id of ['p1_maple', 'p2_tahoe', 'p3_elm', 'p4_oak']) {
      const a = (await mockFetch('GET', `/api/v1/properties/${id}/analysis`)) as PropertyAnalysis;
      expect(a.exit_tax.stacking_notes.length).toBeGreaterThan(3);
      const s = (await mockFetch('GET', `/api/v1/properties/${id}/strategies?horizon=10`)) as StrategyComparison;
      expect(s.paths.map((p) => p.path)).toEqual(['hold', 'sell', 'exchange']);
      expect(Object.keys(s.matrix)).toHaveLength(6);
      expect(s.paths[0].series).toHaveLength(10);
    }
  });

  it('resolving the rent conflict unblocks Maple cash flow', async () => {
    resetDb();
    await mockFetch('POST', '/api/v1/findings/fnd_maple_rent_conflict/resolve', { value: 4_800_000, note: 'leases' });
    const a = (await mockFetch('GET', '/api/v1/properties/p1_maple/analysis')) as PropertyAnalysis;
    expect(a.cash_flow.net_cash_flow.status).not.toBe('blocked');
    expect(a.cash_flow.gross_rent.value_cents).toBe(4_800_000);
    resetDb();
  });
});
