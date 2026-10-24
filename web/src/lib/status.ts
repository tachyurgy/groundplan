import type { FigureStatus, Finding, FigureInput, SourceType } from '../api/types';

/**
 * SPEC §1 rule: confirmed only if every input is document|manual; estimated if any input is
 * public_data|default; blocked if an open Finding with severity=block touches an input.
 * The API already returns `status`; this derives it client-side for display consistency and tests.
 */
export function deriveStatus(inputs: FigureInput[], openBlockingFields: Set<string> = new Set()): FigureStatus {
  if (inputs.some((i) => openBlockingFields.has(i.key))) return 'blocked';
  const walk = (list: FigureInput[]): FigureStatus => {
    let st: FigureStatus = 'confirmed';
    for (const i of list) {
      if (i.figure) {
        const nested = walk(i.figure.inputs);
        if (nested === 'blocked') return 'blocked';
        if (nested === 'estimated') st = 'estimated';
      }
      if (openBlockingFields.has(i.key)) return 'blocked';
      if (!isHardSource(i.source.type)) st = 'estimated';
    }
    return st;
  };
  return walk(inputs);
}

export function isHardSource(t: SourceType): boolean {
  return t === 'document' || t === 'manual';
}

/** Roll several figures up to one status: blocked > estimated > confirmed. */
export function rollupStatus(figs: ({ status: FigureStatus } | FigureStatus | null | undefined)[]): FigureStatus {
  let st: FigureStatus = 'confirmed';
  for (const f of figs) {
    if (!f) continue;
    const s = typeof f === 'string' ? f : f.status;
    if (s === 'blocked') return 'blocked';
    if (s === 'estimated') st = 'estimated';
  }
  return st;
}

export function blockingFieldsFrom(findings: Finding[]): Set<string> {
  return new Set(findings.filter((f) => f.status === 'open' && f.severity === 'block').map((f) => f.field));
}

export const STATUS_LABEL: Record<FigureStatus, string> = {
  confirmed: 'Confirmed',
  estimated: 'Estimated',
  blocked: 'Blocked',
};

export const STATUS_CLASS: Record<FigureStatus, string> = {
  confirmed: 'bg-pos-100 text-pos-600 ring-pos-600/20',
  estimated: 'bg-est-100 text-est-600 ring-est-600/20',
  blocked: 'bg-blk-100 text-blk-600 ring-blk-600/25',
};

export const SOURCE_LABEL: Record<SourceType, string> = {
  document: 'Document',
  manual: 'Manual entry',
  public_data: 'Public data',
  default: 'Default',
};
