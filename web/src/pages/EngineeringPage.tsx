import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { IS_MOCK, STACK } from '../api/client';
import { metaQuery } from '../api/queries';
import { Card, PageHeader } from '../components/ui';
import summary from '../generated/e2e-summary.json';
import { formatDateTime } from '../lib/format';
import { useVitals } from '../lib/vitals';

interface Summary {
  generated_at: string | null;
  unit: { files: number; tests: number; passed: number } | null;
  runs: { project: string; target: string; passed: number; failed: number; skipped: number; flaky?: number }[];
  axe: { pages: number; serious: number; critical: number } | null;
  bundle: { initial_gzip_kb: number; budget_kb: number } | null;
}
const S = summary as unknown as Summary;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-10">
      <h2 className="mb-3 text-lg">{title}</h2>
      <div className="space-y-3 text-[15px] leading-relaxed text-ink-700 [&_code]:rounded [&_code]:bg-ink-100 [&_code]:px-1 [&_code]:font-mono [&_code]:text-[13px] [&_strong]:font-semibold [&_strong]:text-ink-950">{children}</div>
    </section>
  );
}

/** The request path, drawn as a plain left-to-right diagram. Colours are theme tokens. */
function Architecture() {
  const box = (x: number, y: number, w: number, title: string, sub: string, accent = false) => (
    <g>
      <rect x={x} y={y} width={w} height={58} rx={8} fill={accent ? 'var(--brand-50)' : 'var(--surface)'} stroke={accent ? 'var(--brand-500)' : 'var(--ink-200)'} />
      <text x={x + w / 2} y={y + 25} textAnchor="middle" fontSize={13} fontWeight={600} fill="var(--ink-950)">
        {title}
      </text>
      <text x={x + w / 2} y={y + 43} textAnchor="middle" fontSize={11} fill="var(--ink-500)">
        {sub}
      </text>
    </g>
  );
  const arrow = (x1: number, y1: number, x2: number, y2: number, label?: string) => (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--ink-400)" strokeWidth={1.5} markerEnd="url(#arr)" />
      {label && (
        <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 6} textAnchor="middle" fontSize={10.5} fill="var(--ink-500)">
          {label}
        </text>
      )}
    </g>
  );
  return (
    <div className="overflow-x-auto rounded-lg bg-surface-2 p-3 ring-1 ring-ink-100" tabIndex={0} role="region" aria-label="Architecture diagram, scrolls sideways">
      <svg viewBox="0 0 900 250" className="min-w-[700px]" role="img" aria-label="Browser (React) calls a Cloudflare Pages Function at /api, which proxies to the Python or Go API on the server; both APIs use Postgres and call the internal Python document pipeline.">
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--ink-400)" />
          </marker>
        </defs>
        {box(10, 96, 150, 'Browser', 'React 19 SPA', true)}
        {box(205, 96, 170, 'Pages Function', '/api/* same-origin proxy')}
        {box(425, 40, 170, 'Python API', 'FastAPI, SQLAlchemy')}
        {box(425, 152, 170, 'Go API', 'net/http, same contract')}
        {box(650, 40, 230, 'Postgres 17', 'groundplan_py / groundplan_go')}
        {box(650, 152, 230, 'Document pipeline', 'Python, OCR + rules, internal')}
        {arrow(160, 125, 205, 125, 'fetch')}
        {arrow(375, 115, 425, 72, 'gp-python')}
        {arrow(375, 135, 425, 180, 'gp-go')}
        {arrow(595, 69, 650, 69)}
        {arrow(595, 181, 650, 96)}
        {arrow(595, 104, 650, 172)}
        {arrow(595, 190, 650, 190)}
        <text x={10} y={20} fontSize={11} fill="var(--ink-500)">
          X-Workspace-Id travels on every request: it is the tenant id the API filters every query by.
        </text>
      </svg>
    </div>
  );
}

function Lib({ name, why }: { name: string; why: ReactNode }) {
  return (
    <div className="grid gap-1 border-b border-ink-100 py-3 sm:grid-cols-[200px_1fr] sm:gap-4">
      <div className="font-medium text-ink-950">{name}</div>
      <div className="text-[14px] leading-relaxed text-ink-700">{why}</div>
    </div>
  );
}

export function EngineeringPage() {
  const meta = useQuery(metaQuery());
  const vitals = useVitals((s) => s.vitals);
  const runs = S.runs ?? [];
  const totals = runs.reduce((a, r) => ({ p: a.p + r.passed, f: a.f + r.failed }), { p: 0, f: 0 });
  return (
    <article className="mx-auto max-w-[860px]">
      <PageHeader title="Engineering notes">
        How this front end is built and tested, and why. Written for an engineer reviewing the code; every claim here points at something in the repository.
      </PageHeader>

      <Card className="mb-10" title="This deployment">
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div className="flex justify-between gap-3">
            <dt className="text-ink-500">Front end build</dt>
            <dd className="num">{IS_MOCK ? 'mock (MSW)' : `VITE_STACK=${STACK}`}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-ink-500">Backend answering</dt>
            <dd className="num" data-testid="eng-backend">
              {meta.data ? `${meta.data.backend} ${meta.data.version ? String(meta.data.version).slice(0, 7) : ''}` : meta.isError ? 'unreachable' : '…'}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-ink-500">Runtime</dt>
            <dd className="num">{meta.data?.runtime ?? '—'}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-ink-500">Database</dt>
            <dd className="num">{meta.data?.db ?? '—'}</dd>
          </div>
          {['LCP', 'INP', 'CLS', 'FCP', 'TTFB'].map((k) => (
            <div key={k} className="flex justify-between gap-3">
              <dt className="text-ink-500">{k} (this visit)</dt>
              <dd className="num">{vitals[k] ? `${k === 'CLS' ? vitals[k].value.toFixed(3) : `${Math.round(vitals[k].value)} ms`} · ${vitals[k].rating}` : 'not yet measured'}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <Section title="Architecture">
        <Architecture />
        <p>
          The same React build is deployed twice on Cloudflare Pages, once per backend. The browser only ever calls its own origin at <code>/api/v1</code>. A Pages Function (<code>functions/api/[[path]].ts</code>) proxies that path to the stack's API, whose
          origin is an environment variable set per Pages project. Same-origin means no CORS preflight on every request, cookies are never involved, and the API host can move without a front-end rebuild. The function forwards the method, body (multipart
          uploads stream through untouched), <code>Content-Type</code>, <code>X-Workspace-Id</code>, and the client IP as <code>X-Forwarded-For</code> so the API's per-IP abuse limits see the real visitor.
        </p>
        <p>
          There are no logins. On first load the app creates a random UUID, keeps it in <code>localStorage</code> (falling back to <code>sessionStorage</code>, then memory, because storage can throw in private modes), and sends it as{' '}
          <code>X-Workspace-Id</code>. The API provisions and seeds a workspace for an unknown id; that id is the tenant every query is filtered by. Two browsers never see each other's data.
        </p>
        <p>
          The twin link in the footer opens the same view on the other stack. Ids differ per backend and per workspace, so the link carries names (household, property nickname) plus the current URL search; a small <code>/twin</code> route on the other
          side maps the names back to its own ids and keeps every assumption in the URL.
        </p>
      </Section>

      <Section title="Three kinds of state, three homes">
        <p>
          <strong>Server state</strong> lives in TanStack Query and nowhere else. Query keys come from one factory and are hierarchical (<code>['gp','household',id,…]</code>, <code>['gp','property',id,'analysis',params]</code>), so “everything derived
          from this household” is one invalidation. The assumption overrides are part of the key: an edit is a new query, the previous result stays on screen (<code>placeholderData: keepPreviousData</code>) while the recompute runs, and dragging a value
          back hits the cache.
        </p>
        <p>
          <strong>URL state</strong> is anything a colleague should be able to open from a link: every assumption, the horizon, the active tab, the DST toggle, the selected document and page, the fact-sheet platform. TanStack Router validates each
          route's search params with Zod; an invalid or out-of-range value falls back to the stored default instead of crashing, and only overrides are written, so a pristine view has a clean URL. Back and forward walk through assumption changes.
        </p>
        <p>
          <strong>UI state</strong> is the small remainder: the theme preference, which figure the traceability drawer is showing, connectivity. That is one Zustand store of a few fields. Form drafts stay inside the forms.
        </p>
      </Section>

      <Section title="Why each library">
        <div>
          <Lib name="React 19 + React Compiler" why="Actions and useActionState for the forms, useDeferredValue on the horizon slider so dragging never blocks input, useTransition for URL writes. The compiler memoizes components and values automatically, so the code has no hand-placed useMemo / useCallback; the eslint react-hooks rules flag code the compiler cannot optimize." />
          <Lib name="TanStack Router" why="Typed, Zod-validated search params per route (the URL is the assumptions store), loaders that call queryClient.ensureQueryData so data starts loading in parallel with the lazy route chunk and on link hover, per-route error and pending components. React Router 7 data mode would also work; its search params are untyped strings." />
          <Lib name="TanStack Query v5" why="queryOptions shared by loaders, useSuspenseQuery and useQueries; keepPreviousData for live recompute; optimistic resolve/dismiss in the reconciliation queue with rollback; 25 cached strategy queries power the sensitivity grid. Retries only on network or 5xx: a 4xx or a contract error never improves by retrying." />
          <Lib name="Zod 4" why="Runtime validation at the API boundary for the payloads that drive the headline numbers (dashboard, analysis, strategies). The backends describe these responses as untyped dicts in OpenAPI, and two different backends serve them; a renamed field produces a named contract error instead of $0 or NaN on screen. Python Decimals arrive as strings and are coerced once, here. The same library validates search params and form input." />
          <Lib name="OpenAPI types" why={<>Request types can be generated from <code>backend/openapi.json</code> with openapi-typescript (<code>npm run gen:api</code>). Response bodies are untyped in that document today, so the Zod schemas are the response contract and the TypeScript types are inferred from them.</>} />
          <Lib name="Tailwind CSS v4" why="Design tokens are CSS variables with a light and a dark value; utilities resolve to the variables, so one class is correct in both themes and charts use the same tokens. The theme is resolved before first paint (no flash): an explicit choice wins, otherwise the OS setting." />
          <Lib name="Radix UI primitives" why="Dialog (traceability drawer, edit property, reset confirmation), Tabs, Slider and AlertDialog bring focus trapping, focus return, roving tab index and ARIA wiring that are easy to get subtly wrong by hand." />
          <Lib name="Recharts 3 + hand-built SVG" why="Recharts for standard line, area and bar charts. The waterfall, bracket-fill, sensitivity grid, diverging bars and sparklines are small SVG or HTML components because they need exact control (labels that never collide on a 360px phone, every bar opening its source figure). One wrapper gives every chart a text summary, a legend for two or more series and a data-table toggle." />
          <Lib name="TanStack Virtual" why="The monthly amortization schedule (up to 360 rows) and the per-field evaluation table render only the rows in view, with fixed row heights so nothing is measured or shifts." />
          <Lib name="MSW" why="One set of request handlers serves the in-browser demo (`--mode mock`, a service worker), Vitest (msw/node) and the Playwright mock run. The app's real fetch client, headers and error handling all run; only the server is fake, with a separate in-memory database per workspace id, like the real APIs." />
          <Lib name="pdf.js" why="Loaded only when a page image is drawn. Uploaded files are never stored server-side, so page images come from the copy in the browser tab; after a reload the viewer draws a schematic page with the bounding boxes and says the bytes were not retained." />
        </div>
      </Section>

      <Section title="Testing">
        <p>
          <strong>Unit and component tests</strong> (Vitest + Testing Library, MSW on the network) cover money formatting and rounding, the confirmed / estimated / blocked rule, the contract schemas against the mock backend, the URL search
          schemas, the assumptions form (an edit changes the request; invalid input never reaches the API), optimistic resolve with rollback, workspace-id persistence and fallbacks, and the twin-link name mapping.
        </p>
        <p>
          <strong>End-to-end tests</strong> (Playwright, its own Chromium) run the user journeys at four viewports (iPhone 390×844, Android 360×800, tablet 768×1024, desktop 1440×900) against the mock build and against each live stack: households to
          dashboard to property; every analysis tab renders non-empty charts with real numbers; clicking a number opens the drawer and Escape returns focus; an assumption edit changes the figure, the URL, and survives a reload; strategies with the
          horizon slider, DST toggle, waterfall and heatmap; upload a synthetic PDF, see fields and boxes, resolve a finding and watch the figure leave Blocked; PDF and CSV downloads; the simulator; two browser contexts with separate workspaces and a
          reset. Every page is scanned with axe, checked for console errors and for horizontal scroll at 360px. One test opens the same property on both live stacks and asserts the headline figures are identical.
        </p>
        {runs.length > 0 ? (
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="End-to-end results">
            <table className="tbl" data-testid="e2e-summary">
              <thead>
                <tr>
                  <th>Playwright project</th>
                  <th>Target</th>
                  <th className="r">Passed</th>
                  <th className="r">Failed</th>
                  <th className="r">Skipped</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={`${r.project}-${r.target}`}>
                    <td>{r.project}</td>
                    <td className="font-mono text-xs">{r.target}</td>
                    <td className="r num">{r.passed}</td>
                    <td className={`r num ${r.failed ? 'text-neg-600' : ''}`}>{r.failed}</td>
                    <td className="r num">{r.skipped}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-ink-500">
              Last full run {S.generated_at ? formatDateTime(S.generated_at) : '—'}: {totals.p} passed, {totals.f} failed{S.unit ? `; ${S.unit.passed}/${S.unit.tests} unit tests in ${S.unit.files} files` : ''}
              {S.axe ? `; axe found ${S.axe.serious} serious and ${S.axe.critical} critical issues across ${S.axe.pages} page scans` : ''}.
            </p>
          </div>
        ) : (
          <p className="text-sm text-ink-500">No end-to-end results have been recorded in this build yet.</p>
        )}
      </Section>

      <Section title="Budgets">
        <p>
          <strong>JavaScript:</strong> the initial load must stay under 200 KB gzipped; <code>size-limit</code> enforces it in CI{S.bundle ? ` (currently ${S.bundle.initial_gzip_kb.toFixed(1)} KB)` : ''}. Every route is a lazy chunk; Recharts, pdf.js and the
          drawer load only when used.
        </p>
        <p>
          <strong>Layout shift:</strong> skeletons have the size of what replaces them, charts have fixed heights, sparkline space is reserved, and numbers use tabular figures so a recompute never moves a column. Web Vitals are reported to the console in
          development and shown above for this visit.
        </p>
        <p>
          <strong>Accessibility:</strong> landmarks and a skip link, keyboard-operable tabs, slider, dialogs and drawer (focus returns to the number that opened it), visible focus rings, AA contrast in both themes, status shown with a glyph and a word
          (never colour alone), and every chart has a text summary plus a table view. axe runs on every page in the end-to-end suite with zero serious or critical findings allowed.
        </p>
        <p>
          <strong>Phones:</strong> a bottom tab bar within thumb reach, tables that become stacked rows under 640px, key figures pinned while scrolling the property tabs, 44px touch targets, charts that drop tick density, and no horizontal page scroll at
          360px (asserted in the tests).
        </p>
      </Section>

      <Section title="Product rules the UI enforces">
        <p>
          Every number on screen is a button that opens its calculation: formula, inputs as a tree, and the source of each leaf (document page with the extraction box highlighted, manual entry, public data or a default). Every figure carries
          Confirmed, Estimated or Blocked. Green and red only ever mean the sign of money. Conflicting sources are never averaged: a blocked figure stays blocked until a person picks a value in the reconciliation queue. The strategy comparison
          describes trade-offs measure by measure and never names a winner.
        </p>
      </Section>
    </article>
  );
}
