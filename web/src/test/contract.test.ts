import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { api, ApiError, ContractError } from '../api/client';
import { AnalysisSchema, DashboardSchema, StrategiesSchema } from '../api/schemas';
import { server } from './server';

const HH = 'hh_okafor_lindqvist';
const PROPS = ['p1_maple', 'p2_tahoe', 'p3_elm', 'p4_oak'];

describe('API contract (Zod at the boundary)', () => {
  it('the fixture backend satisfies the dashboard, analysis and strategies schemas', async () => {
    const d = await api('GET', `/households/${HH}/dashboard`, { schema: DashboardSchema });
    expect(d.properties).toHaveLength(4);
    expect(d.metrics.exit_tax_total.value_cents).toBeGreaterThan(0);
    for (const id of PROPS) {
      const a = await api('GET', `/properties/${id}/analysis`, { schema: AnalysisSchema });
      expect(Number.isInteger(a.cash_flow.net_cash_flow.value_cents)).toBe(true);
      expect(a.exit_tax.layers_1250).toBeDefined();
      const s = await api('GET', `/properties/${id}/strategies?horizon=12`, { schema: StrategiesSchema });
      expect(s.paths.map((p) => p.path)).toEqual(['hold', 'sell', 'exchange']);
      expect(s.paths[0].series).toHaveLength(12);
    }
  });

  it('coerces Decimal-as-string rates from the Python API once, at the boundary', async () => {
    const real = await api<Record<string, unknown>>('GET', `/properties/p1_maple/analysis`);
    const asStrings = JSON.parse(JSON.stringify(real)) as { property: Record<string, unknown> };
    asStrings.property.vacancy_rate = '0.050000';
    const parsed = AnalysisSchema.parse(asStrings);
    expect(parsed.property.vacancy_rate).toBe(0.05);
  });

  it('a renamed field is a ContractError naming the path, never NaN on screen', async () => {
    server.use(
      http.get('*/api/v1/households/:id/dashboard', () =>
        HttpResponse.json({ household: {}, metrics: { total_value: { key: 'x', value_cents: 'oops', status: 'confirmed' } }, observations: [], properties: [], findings_open: 0, narrative: { text: '', provider: 't' } }),
      ),
    );
    const err = await api('GET', `/households/${HH}/dashboard`, { schema: DashboardSchema }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ContractError);
    expect((err as ContractError).issues.map((i) => i.path)).toEqual(expect.arrayContaining(['metrics.total_value.value_cents', 'household.name']));
  });

  it('problem+json errors become ApiError with the detail as the message', async () => {
    const err = await api('GET', '/properties/nope/analysis').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).message).toMatch(/nope/);
  });

  it('a network failure is ApiError(0) so the shell can show the backend-down banner', async () => {
    server.use(http.get('*/api/v1/households', () => HttpResponse.error()));
    const err = (await api('GET', '/households').catch((e: unknown) => e)) as ApiError;
    expect(err.isNetwork).toBe(true);
  });

  it('every request carries a UUIDv4 X-Workspace-Id', async () => {
    let seen = '';
    server.use(
      http.get('*/api/v1/meta', ({ request }) => {
        seen = request.headers.get('x-workspace-id') ?? '';
        return HttpResponse.json({ backend: 'test' });
      }),
    );
    await api('GET', '/meta');
    expect(seen).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
});
