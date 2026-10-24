import { describe, expect, it } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { findingsQuery, qk, useResolveFinding } from '../api/queries';
import type { Finding } from '../api/types';
import { server } from './server';

const HH = 'hh_okafor_lindqvist';

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  return { qc, wrapper };
}

describe('resolve finding: optimistic with rollback', () => {
  it('leaves the open queue immediately and stays resolved after the server agrees', async () => {
    const { qc, wrapper } = setup();
    const before = await qc.fetchQuery(findingsQuery(HH));
    const target = before.find((f) => f.status === 'open')!;
    const { result } = renderHook(() => useResolveFinding(), { wrapper });
    act(() => result.current.mutate({ id: target.id, householdId: HH, value: 4_800_000, note: 'leases' }));
    await waitFor(() => expect(qc.getQueryData<Finding[]>(qk.findings(HH))!.find((f) => f.id === target.id)!.status).toBe('resolved'));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const after = await qc.fetchQuery({ ...findingsQuery(HH), staleTime: 0 });
    expect(after.find((f) => f.id === target.id)!.status).toBe('resolved');
  });

  it('rolls back when the server refuses', async () => {
    const { qc, wrapper } = setup();
    const before = await qc.fetchQuery(findingsQuery(HH));
    const target = before.find((f) => f.status === 'open')!;
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    server.use(
      http.post('*/api/v1/findings/:id/resolve', async () => {
        await gate;
        return HttpResponse.json({ type: 'about:blank', title: 'Conflict', status: 409, detail: 'finding changed' }, { status: 409 });
      }),
    );
    const { result } = renderHook(() => useResolveFinding(), { wrapper });
    act(() => result.current.mutate({ id: target.id, householdId: HH, value: 1, note: '' }));
    await waitFor(() => expect(qc.getQueryData<Finding[]>(qk.findings(HH))!.find((f) => f.id === target.id)!.status).toBe('resolved'));
    release();
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error!.message).toBe('finding changed');
    await waitFor(() => expect(qc.getQueryData<Finding[]>(qk.findings(HH))!.find((f) => f.id === target.id)!.status).toBe('open'));
  });
});
