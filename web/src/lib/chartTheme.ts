import { formatCentsCompact } from './money';

/** Shared Recharts styling: muted axes, tabular mono ticks, one ink + one accent per series family. */
export const SERIES = {
  hold: '#163a5f',
  sell: '#8a94a8',
  exchange: '#2f8f83',
  ink: '#111a2e',
  accent: '#2a6aa8',
  band: '#2a6aa8',
  pos: '#157347',
  neg: '#b42318',
  warm: '#c08a2d',
};

export const axisProps = {
  tick: { fontSize: 11, fill: '#5b6478', fontFamily: '"JetBrains Mono", ui-monospace, monospace' },
  tickLine: false,
  axisLine: { stroke: '#d6d9e0' },
} as const;

export const gridProps = { stroke: '#eceef2', vertical: false } as const;

export const centsTick = (v: number) => formatCentsCompact(v);

