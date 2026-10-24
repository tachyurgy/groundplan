import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { FigureInput } from '../api/types';
import { deriveStatus, rollupStatus, blockingFieldsFrom } from '../lib/status';
import { StatusChip } from '../components/StatusChip';

const doc = (key: string): FigureInput => ({ key, value: 1, source: { type: 'document', ref: 'Schedule E', page: 1 } });
const man = (key: string): FigureInput => ({ key, value: 1, source: { type: 'manual', ref: 'advisor' } });
const def = (key: string): FigureInput => ({ key, value: 1, source: { type: 'default', ref: 'vacancy 5%' } });
const pub = (key: string): FigureInput => ({ key, value: 1, source: { type: 'public_data', ref: 'AVM' } });

describe('Confirmed / Estimated / Blocked (SPEC §1)', () => {
  it('confirmed only when every input is document or manual', () => {
    expect(deriveStatus([doc('a'), man('b')])).toBe('confirmed');
  });
  it('estimated when any input is public_data or default', () => {
    expect(deriveStatus([doc('a'), def('b')])).toBe('estimated');
    expect(deriveStatus([pub('a')])).toBe('estimated');
  });
  it('estimated propagates up from a nested figure', () => {
    const nested: FigureInput = { key: 'noi', value: 1, source: { type: 'manual', ref: 'computed' }, figure: { key: 'noi', value_cents: 1, status: 'estimated', inputs: [def('vac')], formula: '', notes: [] } };
    expect(deriveStatus([doc('rent'), nested])).toBe('estimated');
  });
  it('blocked when an open blocking finding touches any input, at any depth', () => {
    const blocking = blockingFieldsFrom([
      { id: 'f', household_id: 'h', property_id: 'p', kind: 'conflict', field: 'rent_roll.gross_rent', severity: 'block', message: '', candidates: [], status: 'open', resolution: null },
      { id: 'g', household_id: 'h', property_id: 'p', kind: 'conflict', field: 'x', severity: 'warn', message: '', candidates: [], status: 'open', resolution: null },
    ]);
    expect(blocking.has('x')).toBe(false); // warn findings never block
    const nested: FigureInput = { key: 'gross', value: 1, source: { type: 'manual', ref: 'computed' }, figure: { key: 'gross', value_cents: 1, status: 'confirmed', inputs: [doc('rent_roll.gross_rent')], formula: '', notes: [] } };
    expect(deriveStatus([man('a'), nested], blocking)).toBe('blocked');
    expect(deriveStatus([def('a'), doc('rent_roll.gross_rent')], blocking)).toBe('blocked');
  });
  it('rollup: blocked > estimated > confirmed', () => {
    expect(rollupStatus(['confirmed', 'estimated'])).toBe('estimated');
    expect(rollupStatus(['estimated', 'blocked', 'confirmed'])).toBe('blocked');
    expect(rollupStatus([])).toBe('confirmed');
  });
  it('chip renders the label and status', () => {
    render(
      <>
        <StatusChip status="confirmed" />
        <StatusChip status="estimated" />
        <StatusChip status="blocked" />
      </>,
    );
    const chips = screen.getAllByTestId('status-chip');
    expect(chips.map((c) => c.textContent)).toEqual(['Confirmed', 'Estimated', 'Blocked']);
    expect(chips[2]).toHaveAttribute('data-status', 'blocked');
    expect(chips[2].getAttribute('title')).toMatch(/blocking finding/);
  });
});
