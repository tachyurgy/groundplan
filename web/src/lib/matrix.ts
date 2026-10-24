import type { MatrixMeasure } from '../api/types';

export const MEASURE_LABEL: Record<MatrixMeasure, string> = {
  terminal_wealth: 'Terminal after-tax wealth',
  cumulative_cash_flow: 'Cumulative cash flow',
  tax_paid_now: 'Tax paid now',
  liquidity: 'Liquidity',
  management_burden: 'Management burden',
  concentration: 'Concentration',
};
