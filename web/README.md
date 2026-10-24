# Groundplan web

React 18 + TypeScript + Vite + Tailwind + Recharts + react-router + TanStack Query. It is the advisor-facing
front end for the Groundplan API (`/api/v1`, SPEC §3). Everything runs locally and nothing is deployed.

## Run

```bash
npm i
npm run dev            # live mode: http://localhost:5173, proxies /api -> http://localhost:8000
npm run dev:mock       # same as VITE_MOCK=1 npm run dev: in-memory fixture household, no API needed
npm run build          # tsc -b (zero errors) + vite build
npm run lint           # eslint, zero warnings
npm test               # vitest + React Testing Library (jsdom)
```

**Mock vs live.** `src/api/client.ts` reads `import.meta.env.VITE_MOCK`. If it is `1` (or `true`), every
`api(method, path)` call is routed into `src/api/mock/router.ts` (lazy-imported, so it is not in the live
bundle's critical path). Otherwise the call goes through `fetch('/api/v1' + path)` and Vite's proxy forwards it
to the FastAPI app on :8000. Both modes use the same paths and the same response shapes. A "Mock data" badge
in the header shows which mode is running. Errors from either side surface as RFC 7807 problem details.

## Pages and routes

| Route | Page |
|---|---|
| `/` | Households list: equity, net cash flow, open-findings badge, rolled-up figure status |
| `/households/:id` | Portfolio dashboard: alerts strip, key observations first, then top metrics, one card per property (value, equity, net cash flow, exit tax, ROE, status chips), narrative panel with `provider`, "Generate report (PDF)" |
| `/properties/:id` | Property analysis: assumptions panel (each edit re-queries `/analysis`), tabs Cash flow (+ Schedule E → cash-flow bridge), Equity & lendable equity, Appreciation, Depreciation (table + chart), Exit tax (stacked §1250 / §1245 / LTCG / NIIT / state bar + the bracket-stacking explanation), Loans (schedule, IO-end and ARM-reset markers, DSCR) |
| `/properties/:id/strategies` | Hold / Sell now / 1031 in three columns: horizon slider, shared assumptions (one edit updates all three paths), 1031 replacement inputs, DST toggle with load and yield, wealth / cumulative cash flow / deferred-tax charts, leads/trails/neutral matrix, caveats, boot calculator, "what the proceeds do" |
| `/households/:id/documents` | Drag-and-drop PDF upload, document list by tax year, per-document extracted fields beside the page render with bbox overlays, and the reconciliation queue (`#queue`): candidates side by side, Use this value / Dismiss, with a note for the audit trail |
| `/households/:id/reports` | Report preview, fact sheets (eMoney / RightCapital / MoneyGuidePro tabs with the exact field mapping), JSON and CSV export |
| `/simulate` | Simulation playground: timeline editor of buy/sell/exchange/refi events, assumptions, Monte Carlo net-worth bands (p10/p50/p90), taxes paid, equity vs debt |
| `/eval` | Pipeline eval: text vs scan precision/recall/exact match per form and per field, entity resolution, planted-finding recall, classification confusion matrix |

The word "recommended" appears nowhere in the UI. The matrix is per-measure only, with no overall ranking.

## Structure

```
src/
  api/
    types.ts         TS mirror of SPEC §1 + §3 (integer cents, Figure {key,value_cents,status,inputs,formula,notes})
    client.ts        api() with the mock/live switch, qs(), ApiError (problem+json)
    hooks.ts         TanStack Query hooks + query keys; mutations invalidate everything derived
    mock/
      household.ts   Okafor-Lindqvist fixture (SPEC §4.1): 4 properties, 6 loans, 3 tax years, 19 documents,
                     extracted fields with page+bbox, 5 findings (4 open), alerts, eval summary; plus a 2nd household
      engine.ts      deterministic mock of SPEC §2 (depreciation Table A-6, loans incl. IO/ARM/HELOC, cash flow +
                     Schedule E bridge, equity/ROE, 2025 bracket stacking for exit tax, strategies, matrix,
                     observations rule table, Monte Carlo simulate, fact sheets)
      state.ts       mutable in-memory store (resolve/dismiss/upload mutate it; reload resets)
      router.ts      path -> handler table mirroring §3
  components/        StatusChip, FigureValue/FigureRow, Metric, TraceDrawer, PdfPage, AssumptionsPanel,
                     Matrix, Layout, charts, ui primitives, fileStore
  lib/               money/rate formatting, status rule, chart theme, trace context, fact-sheet CSV
  pages/             one file per route
  test/              vitest suites
```

## State and data fetching

* **Server state = TanStack Query, and only that.** No global store. Query keys hold the full parameter object,
  e.g. `['analysis', id, {appreciation_rate: 0.05}]`, so an assumption edit *is* a new query. `placeholderData:
  keepPreviousData` keeps the old numbers on screen while the recompute runs (a pulsing dot in the panel header).
* **Assumptions are local UI state** on the page (only the overrides that differ from the property's stored values),
  debounced 150 ms before they go into the query key. Inputs commit on blur, Enter or toggle, never per keystroke.
* **Mutations** (resolve, dismiss, upload) call `invalidateQueries()` with no filter. Resolving one finding can
  unblock figures on any page, so everything derived is refetched. That is simple, and correct at this data size.
* **URL state**: selected document and page live in the query string (`?doc=&page=`), so the traceability drawer
  can deep-link into the documents page.

## Traceability drawer

Every number on screen is a `FigureValue`, a button showing the Figure's value. Clicking it calls `useTrace().open(...)`
with the Figure plus the page's `TraceScope` (property id, household id, current assumption params). The drawer:

1. renders the Figure that is already in hand (value, Confirmed / Estimated / Blocked chip, formula text, notes);
2. fetches `GET /properties/{id}/figure/{key}?<same params>` and switches to that version if it carries a fuller
   inputs tree, so the live API can return lightweight Figures in `/analysis`;
3. shows the inputs as a collapsible tree. A computed input carries a nested `figure` and expands to its own
   formula and inputs. A leaf shows its source chip (Document · p3 / Manual entry / Public data / Default);
4. for a document source, opens a source preview: `GET /documents/{id}` for the fields, then `PdfPage` with the
   source bbox outlined in red, plus a deep link to the documents page;
5. for a Blocked figure, explains why and links to the reconciliation queue.

Status chips follow SPEC §1 exactly (`lib/status.ts`, tested): confirmed only if every input is document or manual,
estimated if any is public_data or default, blocked if an open `severity=block` finding touches an input at any depth.
Blocked values render struck through. Green and red are used only for the sign of money.

## PDF rendering (no bytes from the server)

`Document.bytes_retained` is always false, and the API never returns file bytes. On upload, the browser keeps the `File`
in an in-memory map keyed by the returned `document.id` (`components/fileStore.ts`). `PdfPage` lazy-loads pdf.js
and its worker, renders the page from that buffer to a canvas, and maps each `ExtractedField.bbox` (PDF points,
origin bottom-left) through `viewport.convertToViewportRectangle`. Clicking a box highlights its row. For documents
this tab never held (fixtures, or after a reload) it draws a schematic page with the boxes and raw text and
labels it "file bytes not retained". That is the privacy property made visible.

## What is stubbed / deviations

* **Mock engine is not the engine of record.** It reproduces the shapes and the main rules so the UI is demoable.
  Numbers will differ from the Python engine. In particular the 1031 deferred-liability projection and the
  simulation's tax model are simplified, and only CA and the no-tax and flat states have state tables.
* **Assumption overrides as query params.** SPEC §3 lists `?year=&horizon=` for `/analysis` and "assumption overrides"
  for `/strategies`. The UI sends override keys as query params on both: `appreciation_rate, rent_growth_rate,
  expense_growth_rate, vacancy_rate, capex_reserve_rate, selling_cost_rate, land_pct, current_value_cents, arm_index,
  horizon` (analysis) and `appreciation_rate, rent_growth, expense_growth, reinvest_rate, arm_index,
  replacement_value_cents, replacement_debt_cents, cash_taken_cents, dst, load_rate, dst_yield, horizon` (strategies).
  The API should accept (or ignore) these names.
* **Shape additions beyond §1/§3** (all optional, documented in `types.ts`): `FigureInput.figure` (nested Figure for the
  inputs tree), `FigureInput.unit/label`, `FigureSource.document_id/bbox` (so the drawer can open the page),
  `Figure.label`, `PropertyCard.roe_rate`, `ExchangeAssumptions.dst_yield`. The detailed analysis, strategy, fact-sheet,
  simulation and eval response types are this app's reading of §3. If Agent A's OpenAPI differs, `types.ts` is the one
  place to reconcile.
* **Report PDF** is a real link to `/households/{id}/report.pdf` in live mode. Mock mode has no PDF renderer, so the
  button opens the on-screen report preview, which has a Print action.
* **Simulate** seeds the Okafor-Lindqvist properties client-side instead of loading them from the API.
* Upload in mock mode hashes the file client-side (SubtleCrypto) and returns fixture fields of the same form/year.
  No real extraction happens. Alerts are read-only.

## Next

Generate `types.ts` from the FastAPI OpenAPI schema and diff it in CI; Playwright smoke over the 8 routes at 1360
and 390 px (done by hand for this build: no console errors, no horizontal overflow at 390 px); virtualize the
per-field eval table if the eval grows.
