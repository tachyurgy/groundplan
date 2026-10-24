import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { StrategyMatrix } from '../components/Matrix';
import type { MatrixMeasure, MatrixVerdict, StrategyPath } from '../api/types';

const matrix: Record<MatrixMeasure, Record<StrategyPath, MatrixVerdict>> = {
  terminal_wealth: { hold: 'neutral', sell: 'trails', exchange: 'leads' },
  cumulative_cash_flow: { hold: 'leads', sell: 'trails', exchange: 'neutral' },
  tax_paid_now: { hold: 'leads', sell: 'trails', exchange: 'neutral' },
  liquidity: { hold: 'neutral', sell: 'leads', exchange: 'trails' },
  management_burden: { hold: 'trails', sell: 'leads', exchange: 'leads' },
  concentration: { hold: 'trails', sell: 'leads', exchange: 'neutral' },
};
const paths = [
  { path: 'hold' as const, label: 'Hold' },
  { path: 'sell' as const, label: 'Sell now (taxable)' },
  { path: 'exchange' as const, label: '1031 exchange' },
];

describe('leads / trails / neutral matrix', () => {
  it('renders 6 measures × 3 paths with the verdict in each cell', () => {
    render(<StrategyMatrix matrix={matrix} paths={paths} />);
    const table = screen.getByTestId('strategy-matrix');
    expect(within(table).getAllByRole('row')).toHaveLength(7);
    expect(screen.getByTestId('cell-terminal_wealth-exchange')).toHaveAttribute('data-verdict', 'leads');
    expect(screen.getByTestId('cell-liquidity-exchange')).toHaveTextContent(/trails/i);
    expect(screen.getByTestId('cell-terminal_wealth-hold')).toHaveTextContent(/neutral/i);
    expect(screen.getByText('Sell now (taxable)')).toBeInTheDocument();
  });
  it('never says "recommended"', () => {
    const { container } = render(<StrategyMatrix matrix={matrix} paths={paths} />);
    expect(container.textContent?.toLowerCase()).not.toContain('recommend');
  });
});
