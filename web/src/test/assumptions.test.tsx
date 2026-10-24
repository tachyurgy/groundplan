import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AssumptionsPanel, type AssumptionValues } from '../components/AssumptionsPanel';

const apiSpy = vi.fn(async (_method: string, path: string) => ({ path }));
vi.mock('../api/client', () => ({
  api: (m: string, p: string) => apiSpy(m, p),
  qs: (o: Record<string, unknown>) => {
    const u = new URLSearchParams();
    for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== '') u.set(k, String(v));
    const s = u.toString();
    return s ? `?${s}` : '';
  },
  IS_MOCK: false,
}));

// imported after the mock so the hook uses the spy
const { useStrategies } = await import('../api/hooks');

function Harness() {
  const [v, setV] = useState<AssumptionValues>({ appreciation_rate: 0.035, reinvest_rate: 0.06, dst: false });
  const q = useStrategies('p1_maple', v as Record<string, number | boolean>);
  return (
    <>
      <AssumptionsPanel
        fields={[
          { key: 'appreciation_rate', label: 'Appreciation', kind: 'rate' },
          { key: 'reinvest_rate', label: 'Reinvestment return', kind: 'rate' },
          { key: 'dst', label: 'Exchange into a DST', kind: 'bool' },
        ]}
        values={v}
        onChange={setV}
      />
      <output data-testid="last">{(q.data as unknown as { path: string } | undefined)?.path}</output>
    </>
  );
}

function renderHarness() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Harness />
    </QueryClientProvider>,
  );
}

describe('assumptions panel', () => {
  beforeEach(() => apiSpy.mockClear());

  it('one edit re-queries the strategies endpoint with the new assumption', async () => {
    renderHarness();
    await waitFor(() => expect(apiSpy).toHaveBeenCalledTimes(1));
    expect(apiSpy.mock.calls[0][1]).toContain('appreciation_rate=0.035');

    const input = screen.getByLabelText('Appreciation');
    expect(input).toHaveValue('3.5');
    fireEvent.change(input, { target: { value: '5' } });
    fireEvent.blur(input);

    await waitFor(() => expect(apiSpy).toHaveBeenCalledTimes(2));
    const path = apiSpy.mock.calls[1][1];
    expect(path).toMatch(/^\/properties\/p1_maple\/strategies\?/);
    expect(path).toContain('appreciation_rate=0.05');
    expect(path).toContain('reinvest_rate=0.06'); // other shared assumptions travel with it
    await waitFor(() => expect(screen.getByTestId('last')).toHaveTextContent('appreciation_rate=0.05'));
  });

  it('toggles refetch too; unchanged or invalid input does not', async () => {
    renderHarness();
    await waitFor(() => expect(apiSpy).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByLabelText('Exchange into a DST'));
    await waitFor(() => expect(apiSpy).toHaveBeenCalledTimes(2));
    expect(apiSpy.mock.calls[1][1]).toContain('dst=true');

    const input = screen.getByLabelText('Reinvestment return');
    fireEvent.change(input, { target: { value: 'abc' } });
    fireEvent.blur(input);
    fireEvent.change(input, { target: { value: '6' } });
    fireEvent.blur(input);
    await new Promise((r) => setTimeout(r, 30));
    expect(apiSpy).toHaveBeenCalledTimes(2);
  });
});
