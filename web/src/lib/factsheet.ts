import type { FactSheet } from '../api/types';

export function factSheetCsv(fs: FactSheet): string {
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const head = 'groundplan_key,platform_field,value_dollars,status,note';
  const rows = fs.rows.map((r) =>
    [r.groundplan_key, r.platform_field, r.value_cents === null ? '' : (r.value_cents / 100).toFixed(2), r.status, r.note ?? '']
      .map((x) => esc(String(x)))
      .join(','),
  );
  return [head, ...rows].join('\n');
}
