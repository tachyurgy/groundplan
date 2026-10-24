import { describe, expect, it } from 'vitest';
import { overridesOnly, propertySearch, strategiesSearch } from '../lib/search';
import { layout } from '../charts/Waterfall';

describe('typed URL state', () => {
  it('parses valid params and coerces strings from the URL', () => {
    expect(propertySearch.parse({ tab: 'exit', appreciation_rate: '0.05', horizon: '15' })).toEqual({ tab: 'exit', appreciation_rate: 0.05, horizon: 15 });
    expect(strategiesSearch.parse({ dst: 'true', load_rate: '0.09' })).toMatchObject({ dst: true, load_rate: 0.09 });
  });
  it('a hand-edited or hostile URL falls back to defaults instead of crashing', () => {
    expect(propertySearch.parse({ tab: 'nope', appreciation_rate: 'abc', horizon: '999', vacancy_rate: '-1' })).toEqual({});
    expect(strategiesSearch.parse({ dst: 'maybe', replacement_value_cents: '-5' })).toEqual({});
  });
  it('only real overrides are written to the URL', () => {
    expect(overridesOnly({ a: 0.03, b: 0.06, c: true }, { a: 0.03, b: 0.05, c: true })).toEqual({ b: 0.06 });
    expect(overridesOnly({ a: 0.1 + 0.2 }, { a: 0.3 })).toEqual({});
  });
});

describe('sale-proceeds waterfall layout', () => {
  it('steps float from the running level; totals reset it', () => {
    const rows = layout([
      { label: 'Sale price', value: 1000, kind: 'total' },
      { label: 'Costs', value: -60, kind: 'step' },
      { label: 'Loan', value: -400, kind: 'step' },
      { label: 'Tax', value: -90, kind: 'step' },
      { label: 'Net', value: 450, kind: 'total' },
    ]);
    expect(rows.map((r) => [r.from, r.to])).toEqual([
      [0, 1000],
      [1000, 940],
      [940, 540],
      [540, 450],
      [0, 450],
    ]);
  });
});
