import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { TraceProvider } from '../components/trace';
import { TraceDrawer } from '../components/TraceDrawer';
import { FigureValue } from '../components/FigureValue';
import type { Figure } from '../api/types';

vi.mock('../api/client', () => ({ api: vi.fn(async () => null), qs: () => '', IS_MOCK: true }));

const fig: Figure = {
  key: 'cash_flow.net_annual',
  label: 'Net cash flow',
  value_cents: 1_500_000,
  status: 'estimated',
  formula: 'line21 + depreciation - principal_paid - capex_paid',
  notes: ['Worked example (a) from SPEC §7.'],
  inputs: [
    { key: 'schedule_e.line21', value: 1_200_000, unit: 'cents', source: { type: 'document', ref: 'f1040-2025-scheduleE.pdf · line 21', page: 1, document_id: 'd1' } },
    { key: 'property.vacancy_rate', value: 0.05, unit: 'rate', source: { type: 'default', ref: 'vacancy 5%' } },
  ],
};

describe('traceability drawer', () => {
  it('clicking a number opens the drawer with formula, inputs and sources', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <TraceProvider>
            <FigureValue figure={fig} signed />
            <TraceDrawer />
          </TraceProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.queryByTestId('trace-drawer')).toBeNull();
    fireEvent.click(screen.getByTestId('figure'));
    const drawer = screen.getByTestId('trace-drawer');
    expect(drawer).toHaveTextContent('$15,000.00');
    expect(drawer).toHaveTextContent('line21 + depreciation - principal_paid - capex_paid');
    expect(drawer).toHaveTextContent('Document · p1');
    expect(drawer).toHaveTextContent('Default');
    expect(drawer).toHaveTextContent('Estimated');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByTestId('trace-drawer')).toBeNull();
  });
});
