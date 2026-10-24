/** Mutable in-memory store behind the mock router (resets on reload). */
import * as fx from './household';
import type { Document, ExtractedField, Finding, FigureSource, Household, Property } from '../types';

export interface MockDb {
  households: Household[];
  properties: Property[];
  loans: typeof fx.loans;
  rentRolls: typeof fx.rentRolls;
  expenseYears: typeof fx.expenseYears;
  ledgers: typeof fx.depreciationLedgers;
  suspended: typeof fx.suspendedLosses;
  documents: Document[];
  fields: ExtractedField[];
  findings: Finding[];
  alerts: typeof fx.alerts;
}

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

export function freshDb(): MockDb {
  return {
    households: clone([fx.household, fx.household2]),
    properties: clone([...fx.properties, ...fx.properties2]),
    loans: clone(fx.loans),
    rentRolls: clone(fx.rentRolls),
    expenseYears: clone(fx.expenseYears),
    ledgers: clone(fx.depreciationLedgers),
    suspended: clone(fx.suspendedLosses),
    documents: clone(fx.documents),
    fields: clone(fx.extractedFields),
    findings: clone(fx.findings),
    alerts: clone(fx.alerts),
  };
}

export let db: MockDb = freshDb();
export function resetDb() {
  db = freshDb();
}

/** Provenance refs for a property: latest-year document field per field name. */
export function docRefsFor(p: Property): Record<string, FigureSource> {
  const key = normalizeAddr(`${p.address_line1} ${p.city} ${p.state} ${p.zip}`);
  const out: Record<string, FigureSource> = {};
  const docsById = new Map(db.documents.map((d) => [d.id, d]));
  const rows = db.fields
    .filter((f) => f.property_key === null || f.property_key === key)
    .sort((a, b) => (docsById.get(b.document_id)?.tax_year ?? 0) - (docsById.get(a.document_id)?.tax_year ?? 0));
  for (const f of rows) {
    if (out[f.field]) continue;
    const d = docsById.get(f.document_id);
    out[f.field] = { type: 'document', ref: `${d?.filename ?? f.document_id} · ${f.field}`, page: f.page, document_id: f.document_id, bbox: f.bbox };
  }
  // map mortgage statements onto loans by property
  for (const l of db.loans.filter((x) => x.property_id === p.id)) {
    const bal = rows.find((f) => f.field === 'mortgage.principal_balance' && Math.abs(Number(f.value) - l.balance_cents) < 100);
    if (bal) {
      const d = docsById.get(bal.document_id);
      out[`mortgage.${l.id}`] = { type: 'document', ref: `${d?.filename} · principal balance`, page: bal.page, document_id: bal.document_id, bbox: bal.bbox };
    }
  }
  return out;
}

export function normalizeAddr(s: string): string {
  return s
    .toLowerCase()
    .replace(/[.,#]/g, ' ')
    .replace(/\bstreet\b/g, 'st')
    .replace(/\broad\b/g, 'rd')
    .replace(/\bcourt\b/g, 'ct')
    .replace(/\s+/g, ' ')
    .trim();
}
