export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return iso;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export function pct(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return `${(n * 100).toFixed(digits)}%`;
}

export function titleCase(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export const PROPERTY_TYPE_LABEL: Record<string, string> = {
  sfr: 'Single-family',
  multifamily: 'Multifamily',
  vacation_str: 'Short-term rental',
  commercial: 'Commercial',
  land: 'Land',
  self_rental: 'Self-rental',
  other: 'Other',
};

export const LOAN_TYPE_LABEL: Record<string, string> = {
  fixed: 'Fixed',
  arm: 'ARM',
  interest_only: 'Interest-only',
  heloc: 'HELOC',
  balloon: 'Balloon',
};

export const FILING_LABEL: Record<string, string> = {
  single: 'Single',
  mfj: 'Married filing jointly',
  mfs: 'Married filing separately',
  hoh: 'Head of household',
};

export const DOC_KIND_LABEL: Record<string, string> = {
  form_1040: 'Form 1040',
  schedule_e: 'Schedule E',
  form_4562: 'Form 4562',
  form_8582: 'Form 8582',
  mortgage_statement: 'Mortgage statement',
  closing_statement: 'Closing statement',
  lease: 'Lease',
  appraisal: 'Appraisal',
  other: 'Other',
};

/** "Okafor-Lindqvist" and "Okafor-Lindqvist household" both render as "Okafor-Lindqvist household". */
export function householdTitle(name: string): string {
  return /\bhousehold$/i.test(name.trim()) ? name.trim() : `${name.trim()} household`;
}
