/**
 * Static fixture service for VITE_MOCK=1. Same paths and shapes as SPEC §3 (`/api/v1/...`),
 * served from memory with the mock engine. Unknown routes return RFC 7807 problem+json.
 */
import type {
  Dashboard,
  HouseholdSummary,
  PropertyCard,
  Figure,
  Finding,
  UploadResponse,
  ScenarioAssumptions,
  FactSheetFormat,
  SimulationRequest,
  ExtractedField,
  Document,
  Narrative,
  Observation,
} from '../types';
import { db, docRefsFor } from './state';
import { analyzeProperty, strategies, simulate, factSheet, findFigure, DEFAULT_EXCHANGE, type EngineContext, type Overrides, fig } from './engine';
import { evalSummary } from './household';
import { rollupStatus } from '../../lib/status';
import { formatCents } from '../../lib/money';

export class MockHttpError extends Error {
  constructor(public status: number, public problem: { type: string; title: string; status: number; detail?: string }) {
    super(problem.title);
  }
}

const notFound = (detail: string) => new MockHttpError(404, { type: 'about:blank', title: 'Not Found', status: 404, detail });

function ctxFor(propertyId: string): EngineContext {
  const property = db.properties.find((p) => p.id === propertyId);
  if (!property) throw notFound(`property ${propertyId}`);
  const household = db.households.find((h) => h.id === property.household_id)!;
  const sl = db.suspended.filter((s) => s.household_id === household.id).sort((a, b) => b.tax_year - a.tax_year)[0];
  return {
    household,
    property,
    loans: db.loans,
    rentRolls: db.rentRolls,
    expenseYears: db.expenseYears,
    ledgers: db.ledgers,
    findings: db.findings,
    suspendedLossCents: sl?.carryforward_cents ?? 0,
    docRefs: docRefsFor(property),
  };
}

function num(q: URLSearchParams, k: string): number | undefined {
  const v = q.get(k);
  if (v === null || v === '') return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

function overridesFrom(q: URLSearchParams): Overrides {
  return {
    appreciation_rate: num(q, 'appreciation_rate'),
    rent_growth_rate: num(q, 'rent_growth') ?? num(q, 'rent_growth_rate'),
    expense_growth_rate: num(q, 'expense_growth') ?? num(q, 'expense_growth_rate'),
    vacancy_rate: num(q, 'vacancy_rate'),
    current_value_cents: num(q, 'current_value_cents'),
    land_pct: num(q, 'land_pct'),
    arm_index: num(q, 'arm_index'),
    selling_cost_rate: num(q, 'selling_cost_rate'),
    capex_reserve_rate: num(q, 'capex_reserve_rate'),
    reinvest_rate: num(q, 'reinvest_rate'),
  };
}

function propertyCards(hhId: string): PropertyCard[] {
  const hh = db.households.find((h) => h.id === hhId)!;
  return db.properties
    .filter((p) => p.household_id === hhId)
    .map((p) => {
      const a = analyzeProperty(ctxFor(p.id), hh.tax_year_latest, 10);
      const chips = [a.equity.value.status, a.cash_flow.net_cash_flow.status, a.exit_tax.exit_tax_total.status];
      return {
        property: p,
        value: a.equity.value,
        equity: a.equity.equity,
        net_cash_flow: a.cash_flow.net_cash_flow,
        exit_tax: a.exit_tax.exit_tax_total,
        roe: a.equity.roe,
        roe_rate: a.equity.roe_rate,
        status_chips: chips,
        open_findings: db.findings.filter((f) => f.property_id === p.id && f.status === 'open').length,
      };
    });
}

function sumFigure(key: string, label: string, figs: Figure[], formula: string): Figure {
  return {
    key,
    label,
    value_cents: figs.reduce((s, f) => s + f.value_cents, 0),
    status: rollupStatus(figs),
    inputs: figs.map((f, i) => ({ key: `${f.key}#${i}`, value: f.value_cents, source: { type: 'manual', ref: 'computed' }, figure: f, unit: 'cents', label: f.label })),
    formula,
    notes: [],
  };
}

function dashboard(hhId: string): Dashboard {
  const hh = db.households.find((h) => h.id === hhId);
  if (!hh) throw notFound(`household ${hhId}`);
  const cards = propertyCards(hhId);
  const labelled = (f: Figure, nick: string): Figure => ({ ...f, label: `${nick}: ${f.label ?? f.key}` });
  const metrics: Record<string, Figure> = {
    total_value: sumFigure('portfolio.total_value', 'Portfolio value', cards.map((c) => labelled(c.value, c.property.nickname)), 'Σ property values'),
    total_equity: sumFigure('portfolio.total_equity', 'Total equity', cards.map((c) => labelled(c.equity, c.property.nickname)), 'Σ (value − liens)'),
    net_cash_flow: sumFigure('portfolio.net_cash_flow', 'Net cash flow (annual)', cards.map((c) => labelled(c.net_cash_flow, c.property.nickname)), 'Σ property net cash flow'),
    total_debt: {
      key: 'portfolio.total_debt',
      label: 'Total debt',
      value_cents: cards.reduce((s, c) => s + c.value.value_cents - c.equity.value_cents, 0),
      status: rollupStatus(cards.flatMap((c) => [c.value, c.equity])),
      inputs: cards.map((c) => ({ key: `${c.property.id}.debt`, value: c.value.value_cents - c.equity.value_cents, source: { type: 'manual', ref: 'value − equity (lien balances)' }, unit: 'cents', label: c.property.nickname })),
      formula: 'Σ lien balances (value − equity per property)',
      notes: [],
    },
    exit_tax_total: sumFigure('portfolio.exit_tax', 'Embedded exit tax', cards.map((c) => labelled(c.exit_tax, c.property.nickname)), 'Σ exit tax if each property sold this year (each stacked separately)'),
  };
  const sl = db.suspended.filter((s) => s.household_id === hhId).sort((a, b) => b.tax_year - a.tax_year)[0];
  if (sl) {
    const doc = db.documents.find((d) => d.kind === 'form_8582' && d.tax_year === sl.tax_year && d.household_id === hhId);
    metrics.suspended_losses = fig(new Set(), 'household.suspended_losses', sl.carryforward_cents, [{ key: 'form_8582.carryforward', value: sl.carryforward_cents, source: doc ? { type: 'document', ref: `${doc.filename} · carryforward`, page: 1, document_id: doc.id, bbox: [470, 300, 580, 312] } : { type: 'manual', ref: 'entered' }, unit: 'cents' }], `Form 8582 carryforward (${sl.tax_year})`, ['Released in full on a fully taxable sale of the entire interest; not released by a 1031.'], 'Suspended passive losses');
  }
  const obs: Observation[] = [];
  const seen = new Set<string>();
  for (const c of cards) {
    for (const o of analyzeProperty(ctxFor(c.property.id), hh.tax_year_latest, 10).observations) {
      const k = ['suspended_losses', 'magi_phaseout'].includes(o.rule) ? o.rule : o.id;
      if (seen.has(k)) continue;
      seen.add(k);
      obs.push(['suspended_losses', 'magi_phaseout'].includes(o.rule) ? { ...o, property_id: null, id: `${hhId}:${o.rule}` } : o);
    }
  }
  const sevRank = { block: 0, warn: 1, info: 2 } as const;
  obs.sort((a, b) => sevRank[a.severity] - sevRank[b.severity]);
  return {
    household: hh,
    metrics,
    observations: obs,
    properties: cards,
    findings_open: db.findings.filter((f) => f.household_id === hhId && f.status === 'open').length,
    narrative: narrative(hh.goal, metrics, cards),
  };
}

function narrative(goal: string, m: Record<string, Figure>, cards: PropertyCard[]): Narrative {
  const neg = cards.filter((c) => c.net_cash_flow.value_cents < 0).map((c) => c.property.nickname);
  const blocked = cards.filter((c) => c.status_chips.includes('blocked')).map((c) => c.property.nickname);
  const top = [...cards].sort((a, b) => b.exit_tax.value_cents - a.exit_tax.value_cents)[0];
  const parts = [
    `Against the stated goal ("${goal}"), the portfolio holds ${formatCents(m.total_equity.value_cents)} of equity across ${cards.length} properties and produces ${formatCents(m.net_cash_flow.value_cents)} of net cash flow a year after debt service and reserves.`,
    neg.length ? `${neg.join(' and ')} ${neg.length > 1 ? 'run' : 'runs'} negative, so the portfolio's income is carried by the remaining properties.` : 'Every property covers its own debt service.',
    top ? `Selling everything this year would trigger an estimated ${formatCents(m.exit_tax_total.value_cents)} of combined exit tax; the largest single liability is ${top.property.nickname} at ${formatCents(top.exit_tax.value_cents)}, which grows with each year of depreciation.` : '',
    m.suspended_losses ? `${formatCents(m.suspended_losses.value_cents)} of suspended passive losses would be released by a fully taxable sale, but not by a 1031 exchange.` : '',
    blocked.length ? `Figures for ${blocked.join(', ')} are blocked until the open reconciliation items are resolved; nothing here averages conflicting sources.` : '',
  ].filter(Boolean);
  return { text: parts.join(' '), provider: 'template', generated_at: new Date().toISOString() };
}

function summaries(): HouseholdSummary[] {
  return db.households.map((h) => {
    const cards = propertyCards(h.id);
    return {
      id: h.id,
      name: h.name,
      state: h.state,
      filing_status: h.filing_status,
      property_count: cards.length,
      net_cash_flow_cents: cards.reduce((s, c) => s + c.net_cash_flow.value_cents, 0),
      total_equity_cents: cards.reduce((s, c) => s + c.equity.value_cents, 0),
      open_findings: db.findings.filter((f) => f.household_id === h.id && f.status === 'open').length,
      status: rollupStatus(cards.flatMap((c) => c.status_chips)),
    };
  });
}

function defaultAssumptions(propertyId: string, q: URLSearchParams): ScenarioAssumptions {
  const ctx = ctxFor(propertyId);
  const p = ctx.property;
  const debt = db.loans.filter((l) => l.property_id === p.id && !l.is_paid_off).reduce((s, l) => s + l.balance_cents, 0);
  const ex = DEFAULT_EXCHANGE(p, debt);
  const bool = (k: string) => (q.get(k) === null ? undefined : q.get(k) === 'true' || q.get(k) === '1');
  return {
    appreciation_rate: num(q, 'appreciation_rate') ?? p.appreciation_rate,
    rent_growth: num(q, 'rent_growth') ?? p.rent_growth_rate,
    expense_growth: num(q, 'expense_growth') ?? p.expense_growth_rate,
    reinvest_rate: num(q, 'reinvest_rate') ?? 0.06,
    sale_year: num(q, 'sale_year') ?? ctx.household.tax_year_latest + 1,
    exchange: {
      replacement_value_cents: num(q, 'replacement_value_cents') ?? ex.replacement_value_cents,
      replacement_debt_cents: num(q, 'replacement_debt_cents') ?? ex.replacement_debt_cents,
      dst: bool('dst') ?? ex.dst,
      load_rate: num(q, 'load_rate') ?? ex.load_rate,
      dst_yield: num(q, 'dst_yield') ?? ex.dst_yield,
      cash_taken_cents: num(q, 'cash_taken_cents') ?? ex.cash_taken_cents,
    },
  };
}

async function sha256Hex(buf: ArrayBuffer): Promise<string> {
  if (globalThis.crypto?.subtle) {
    const h = await crypto.subtle.digest('SHA-256', buf);
    return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, '0')).join('');
  }
  return 'sha256-unavailable';
}

function classify(name: string): { kind: Document['kind']; year: number | null } {
  const n = name.toLowerCase();
  const year = Number(n.match(/20\d\d/)?.[0]) || null;
  const kind: Document['kind'] = n.includes('schedule') || n.includes('sche')
    ? 'schedule_e'
    : n.includes('1040')
      ? 'form_1040'
      : n.includes('4562')
        ? 'form_4562'
        : n.includes('8582')
          ? 'form_8582'
          : n.includes('mortgage') || n.includes('statement')
            ? 'mortgage_statement'
            : n.includes('closing')
              ? 'closing_statement'
              : n.includes('apprais')
                ? 'appraisal'
                : 'other';
  return { kind, year };
}

async function upload(hhId: string, form: FormData): Promise<UploadResponse> {
  const file = form.get('file');
  if (!(file instanceof Blob)) throw new MockHttpError(422, { type: 'about:blank', title: 'Unprocessable', status: 422, detail: 'multipart field "file" required' });
  const name = (file as File).name ?? 'upload.pdf';
  const buf = await file.arrayBuffer();
  const sha = await sha256Hex(buf);
  const pageCount = Math.max(1, (new TextDecoder('latin1').decode(new Uint8Array(buf)).match(/\/Type\s*\/Page[^s]/g) ?? []).length);
  const { kind, year } = classify(name);
  const id = `doc_up_${sha.slice(0, 10)}_${Date.now() % 100000}`;
  const document: Document = { id, household_id: hhId, kind, tax_year: year, filename: name, sha256: sha, page_count: pageCount, uploaded_at: new Date().toISOString(), status: 'extracted', bytes_retained: false };
  // Mock extraction: mirror the fixture fields of the same kind/year if any, else a couple of synthetic ones.
  const twin = db.documents.find((d) => d.kind === kind && (year === null || d.tax_year === year) && !d.id.startsWith('doc_up_'));
  let fields: ExtractedField[] = twin
    ? db.fields.filter((f) => f.document_id === twin.id).map((f, i) => ({ ...f, id: `${id}_f${i}`, document_id: id, page: Math.min(f.page, pageCount) }))
    : [
        { id: `${id}_f0`, document_id: id, entity_hint: 'household', property_key: null, field: 'document.title', value: name, unit: 'text', page: 1, bbox: [40, 720, 400, 750], confidence: 0.6, extractor: 'rules', raw_text: name },
      ];
  fields = fields.slice(0, 40);
  db.documents.unshift(document);
  db.fields.push(...fields);
  const touched = [...new Set(fields.map((f) => f.property_key).filter(Boolean))] as string[];
  return { document, extracted_fields: fields, findings: [], properties_touched: touched };
}

type Handler = (m: RegExpMatchArray, q: URLSearchParams, body: unknown) => unknown | Promise<unknown>;
const routes: [string, RegExp, Handler][] = [
  ['GET', /^\/health$/, () => ({ status: 'ok', mode: 'mock' })],
  ['GET', /^\/households$/, () => summaries()],
  ['GET', /^\/households\/([^/]+)$/, (m) => db.households.find((h) => h.id === m[1]) ?? (() => { throw notFound(m[1]); })()],
  ['PATCH', /^\/households\/([^/]+)$/, (m, _q, b) => {
    const h = db.households.find((x) => x.id === m[1]);
    if (!h) throw notFound(m[1]);
    Object.assign(h, b);
    return h;
  }],
  ['GET', /^\/households\/([^/]+)\/dashboard$/, (m) => dashboard(m[1])],
  ['GET', /^\/households\/([^/]+)\/alerts$/, (m) => db.alerts.filter((a) => a.household_id === m[1])],
  ['GET', /^\/households\/([^/]+)\/findings$/, (m, q) => db.findings.filter((f) => f.household_id === m[1] && (!q.get('status') || f.status === q.get('status')))],
  ['POST', /^\/findings\/([^/]+)\/resolve$/, (m, _q, b) => {
    const f = db.findings.find((x) => x.id === m[1]);
    if (!f) throw notFound(m[1]);
    const body = (b ?? {}) as { value?: unknown; note?: string };
    f.status = 'resolved';
    f.resolution = { value: body.value ?? null, who: 'advisor@example.test', when: new Date().toISOString(), note: body.note ?? '' };
    applyResolution(f);
    return f;
  }],
  ['POST', /^\/findings\/([^/]+)\/dismiss$/, (m, _q, b) => {
    const f = db.findings.find((x) => x.id === m[1]);
    if (!f) throw notFound(m[1]);
    f.status = 'dismissed';
    f.resolution = { value: null, who: 'advisor@example.test', when: new Date().toISOString(), note: ((b ?? {}) as { note?: string }).note ?? '' };
    return f;
  }],
  ['GET', /^\/households\/([^/]+)\/documents$/, (m) => db.documents.filter((d) => d.household_id === m[1])],
  ['POST', /^\/households\/([^/]+)\/documents$/, (m, _q, b) => upload(m[1], b as FormData)],
  ['GET', /^\/documents\/([^/]+)$/, (m) => {
    const d = db.documents.find((x) => x.id === m[1]);
    if (!d) throw notFound(m[1]);
    return { document: d, fields: db.fields.filter((f) => f.document_id === d.id) };
  }],
  ['DELETE', /^\/documents\/([^/]+)$/, (m) => {
    db.documents = db.documents.filter((d) => d.id !== m[1]);
    db.fields = db.fields.filter((f) => f.document_id !== m[1]);
    return null;
  }],
  ['GET', /^\/households\/([^/]+)\/properties$/, (m) => db.properties.filter((p) => p.household_id === m[1])],
  ['GET', /^\/properties\/([^/]+)$/, (m) => ctxFor(m[1]).property],
  ['PATCH', /^\/properties\/([^/]+)$/, (m, _q, b) => Object.assign(ctxFor(m[1]).property, b)],
  ['GET', /^\/properties\/([^/]+)\/loans$/, (m) => db.loans.filter((l) => l.property_id === m[1])],
  ['GET', /^\/properties\/([^/]+)\/analysis$/, (m, q) => {
    const ctx = ctxFor(m[1]);
    return analyzeProperty(ctx, num(q, 'year') ?? ctx.household.tax_year_latest, num(q, 'horizon') ?? 10, overridesFrom(q));
  }],
  ['GET', /^\/properties\/([^/]+)\/figure\/(.+)$/, (m, q) => {
    const ctx = ctxFor(m[1]);
    const a = analyzeProperty(ctx, num(q, 'year') ?? ctx.household.tax_year_latest, num(q, 'horizon') ?? 10, overridesFrom(q));
    const f = findFigure(a, decodeURIComponent(m[2])) ?? findFigure(strategies(ctx, num(q, 'horizon') ?? 10, defaultAssumptions(m[1], q)), decodeURIComponent(m[2]));
    if (!f) throw notFound(`figure ${m[2]}`);
    return f;
  }],
  ['GET', /^\/properties\/([^/]+)\/strategies$/, (m, q) => strategies(ctxFor(m[1]), Math.max(1, Math.min(30, num(q, 'horizon') ?? 10)), defaultAssumptions(m[1], q), num(q, 'arm_index') ?? 0.04)],
  ['GET', /^\/properties\/([^/]+)\/factsheet$/, (m, q) => {
    const ctx = ctxFor(m[1]);
    const fmt = (q.get('format') ?? 'json') as FactSheetFormat;
    return factSheet(analyzeProperty(ctx, ctx.household.tax_year_latest, 10), fmt);
  }],
  ['POST', /^\/simulate$/, (_m, _q, b) => simulate(b as SimulationRequest)],
  ['GET', /^\/eval\/latest$/, () => evalSummary],
];

/** When a block finding is resolved with a chosen value, write it through so dependent figures unblock. */
function applyResolution(f: Finding) {
  if (f.field === 'rent_roll.gross_rent' && typeof f.resolution?.value === 'number' && f.property_id) {
    const hh = db.households.find((h) => h.id === f.household_id);
    const rr = db.rentRolls.find((r) => r.property_id === f.property_id && r.tax_year === hh?.tax_year_latest);
    if (rr) rr.gross_rent_cents = f.resolution.value;
  }
  if (f.field === 'property.status' && f.property_id && typeof f.resolution?.value === 'string') {
    const p = db.properties.find((x) => x.id === f.property_id);
    if (p && ['active', 'sold', 'converted'].includes(f.resolution.value)) p.status = f.resolution.value as typeof p.status;
  }
}

export async function mockFetch(method: string, path: string, body?: unknown): Promise<unknown> {
  const url = new URL(path, 'http://mock.local');
  const p = url.pathname.replace(/^\/api\/v1/, '');
  await new Promise((r) => setTimeout(r, import.meta.env.MODE === 'test' ? 0 : 120)); // feel like a network
  for (const [mth, re, h] of routes) {
    if (mth !== method) continue;
    const m = p.match(re);
    if (m) return h(m, url.searchParams, body);
  }
  throw new MockHttpError(404, { type: 'about:blank', title: 'Not Found', status: 404, detail: `${method} ${p} not mocked` });
}
