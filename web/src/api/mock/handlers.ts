/**
 * MSW request handlers: the fixture backend for `--mode mock` (browser, service worker) and for
 * Vitest (msw/node). Network-level mocking means the app's real fetch client, headers and error
 * handling all run; only the server is fake. Each X-Workspace-Id gets its own in-memory database,
 * the same tenancy rule as the real APIs.
 */
import { http, HttpResponse } from 'msw';
import { MockHttpError, mockFetch } from './router';
import { db, resetDb, selectWorkspace } from './state';
import { factSheetCsv } from '../../lib/factsheet';
import type { FactSheet } from '../types';

const STARTED = new Date().toISOString();
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const problem = (status: number, title: string, detail: string) => HttpResponse.json({ type: 'about:blank', title, status, detail }, { status, headers: { 'Content-Type': 'application/problem+json' } });

/** A real, minimal one-page PDF so "download returns application/pdf" is testable in mock mode too. */
export function tinyPdf(lines: string[]): Uint8Array {
  const esc = (s: string) => s.replace(/[\\()]/g, (c) => `\\${c}`).replace(/[^\x20-\x7e]/g, '-');
  const text = lines.map((l, i) => `BT /F1 ${i === 0 ? 18 : 11} Tf 56 ${740 - i * 22} Td (${esc(l)}) Tj ET`).join('\n');
  const objs = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${text.length} >>\nstream\n${text}\nendstream`,
  ];
  let out = '%PDF-1.4\n';
  const offsets: number[] = [];
  objs.forEach((o, i) => {
    offsets.push(out.length);
    out += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}`;
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return new TextEncoder().encode(out);
}

async function readBody(request: Request): Promise<unknown> {
  if (request.method === 'GET' || request.method === 'HEAD') return undefined;
  const ct = request.headers.get('content-type') ?? '';
  if (ct.includes('multipart/form-data')) return request.formData();
  const t = await request.text();
  return t ? JSON.parse(t) : undefined;
}

export const handlers = [
  http.get('*/api/v1/meta', () => HttpResponse.json({ backend: 'mock', version: 'msw', engine: 'mock (TypeScript)', runtime: 'browser', started_at: STARTED, db: 'in-memory' })),
  http.get('*/api/v1/health', () => HttpResponse.json({ status: 'ok', mode: 'mock' })),

  http.all('*/api/v1/*', async ({ request }) => {
    const url = new URL(request.url);
    const path = url.pathname.replace(/^.*\/api\/v1/, '');
    const ws = request.headers.get('x-workspace-id') ?? '';
    if (path !== '/eval/latest' && !UUID_RE.test(ws)) return problem(400, 'Workspace required', 'Send a UUIDv4 in the X-Workspace-Id header.');
    const w = selectWorkspace(ws || 'anon');

    if (path === '/workspace' && request.method === 'GET') return HttpResponse.json({ id: ws, created_at: w.created_at, households: db.households.length, documents: db.documents.length });
    if (path === '/workspace/reset' && request.method === 'POST') {
      resetDb();
      return HttpResponse.json({ id: ws, created_at: w.created_at, households: db.households.length, documents: db.documents.length });
    }
    const report = path.match(/^\/households\/([^/]+)\/report\.pdf$/);
    if (report && request.method === 'GET') {
      const hh = db.households.find((h) => h.id === report[1]);
      if (!hh) return problem(404, 'Not Found', `household ${report[1]}`);
      return new HttpResponse(tinyPdf([`${hh.name}: real estate portfolio review`, 'Groundplan mock report (MSW fixture backend).', `Tax year ${hh.tax_year_latest}, ${hh.state}.`]), {
        headers: { 'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename="report.pdf"' },
      });
    }
    const scen = path.match(/^\/properties\/([^/]+)\/scenarios$/);
    if (scen && request.method === 'POST') {
      const body = (await readBody(request)) as { name: string };
      return HttpResponse.json({ id: `scn_${Date.now()}`, property_id: scen[1], ...body }, { status: 201 });
    }
    if (scen && request.method === 'GET') return HttpResponse.json([]);

    try {
      const body = await readBody(request);
      const res = await mockFetch(request.method, url.pathname.replace(/^.*\/api\/v1/, '/api/v1') + url.search, body);
      if (/\/factsheet$/.test(path) && url.searchParams.get('format') === 'csv') {
        return new HttpResponse(factSheetCsv(res as FactSheet), { headers: { 'Content-Type': 'text/csv; charset=utf-8' } });
      }
      return HttpResponse.json(res === undefined ? null : (JSON.parse(JSON.stringify(res)) as never));
    } catch (e) {
      if (e instanceof MockHttpError) return problem(e.status, e.problem.title, e.problem.detail ?? e.problem.title);
      return problem(500, 'Mock server error', e instanceof Error ? e.message : String(e));
    }
  }),
];
