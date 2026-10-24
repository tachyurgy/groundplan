import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AssumptionsForm, type FieldDef } from '../components/AssumptionsForm';

const FIELDS: FieldDef[] = [
  { key: 'appreciation_rate', label: 'Appreciation', kind: 'rate', min: -0.2, max: 0.3 },
  { key: 'current_value_cents', label: 'Current value', kind: 'cents', min: 0 },
  { key: 'dst', label: 'Exchange into a DST', kind: 'bool' },
];
const VALUES = { appreciation_rate: 0.035, current_value_cents: 62_000_000, dst: false };

describe('assumptions form (React 19 action + Zod)', () => {
  it('shows form units and commits API units: % -> decimal, $ -> cents', async () => {
    const onCommit = vi.fn();
    render(<AssumptionsForm title="Assumptions" fields={FIELDS} values={VALUES} onCommit={onCommit} />);
    const appr = screen.getByLabelText('Appreciation');
    expect(appr).toHaveValue('3.5');
    expect(screen.getByLabelText('Current value')).toHaveValue('620,000');
    fireEvent.change(appr, { target: { value: '5' } });
    fireEvent.blur(appr);
    await waitFor(() => expect(onCommit).toHaveBeenCalledTimes(1));
    expect(onCommit.mock.calls[0][0]).toEqual({ appreciation_rate: 0.05, current_value_cents: 62_000_000, dst: false });

    const val = screen.getByLabelText('Current value');
    fireEvent.change(val, { target: { value: '$700,000' } });
    fireEvent.blur(val);
    await waitFor(() => expect(onCommit).toHaveBeenCalledTimes(2));
    expect(onCommit.mock.calls[1][0].current_value_cents).toBe(70_000_000);
  });

  it('a toggle commits immediately', async () => {
    const onCommit = vi.fn();
    render(<AssumptionsForm title="A" fields={FIELDS} values={VALUES} onCommit={onCommit} />);
    fireEvent.click(screen.getByLabelText('Exchange into a DST'));
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith(expect.objectContaining({ dst: true })));
  });

  it('invalid or out-of-range input shows an inline error, keeps what was typed, and never commits', async () => {
    const onCommit = vi.fn();
    render(<AssumptionsForm title="A" fields={FIELDS} values={VALUES} onCommit={onCommit} />);
    const appr = screen.getByLabelText('Appreciation');
    fireEvent.change(appr, { target: { value: 'abc' } });
    fireEvent.blur(appr);
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a number');
    expect(appr).toHaveValue('abc');
    expect(appr).toHaveAttribute('aria-invalid', 'true');
    fireEvent.change(appr, { target: { value: '45' } });
    fireEvent.blur(appr);
    expect(await screen.findByRole('alert')).toHaveTextContent('Between −20.0% and 30.0%');
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('an unchanged value does not commit (no needless refetch)', async () => {
    const onCommit = vi.fn();
    render(<AssumptionsForm title="A" fields={FIELDS} values={VALUES} onCommit={onCommit} />);
    const appr = screen.getByLabelText('Appreciation');
    fireEvent.blur(appr);
    await new Promise((r) => setTimeout(r, 20));
    expect(onCommit).not.toHaveBeenCalled();
  });
});
