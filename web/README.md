# Groundplan web

The advisor-facing front end. One codebase, deployed twice on Cloudflare Pages, each wired to one backend:

| Site                             | Pages project | API (through the same-origin `/api` proxy)     |
| -------------------------------- | ------------- | ---------------------------------------------- |
| https://gp-python.levelbrook.com | `gp-python`   | https://gp-python-api.levelbrook.com (FastAPI) |
| https://gp-go.levelbrook.com     | `gp-go`       | https://gp-go-api.levelbrook.com (Go)          |

No logins: each browser gets a workspace id (UUIDv4 in `localStorage["gp.workspace"]`) sent as `X-Workspace-Id`.
The `/engineering` page in the app explains the architecture, state split and library choices for a reviewer.

## Stack

React 19 + React Compiler, TypeScript (strict), Vite 8, Tailwind CSS 4 (CSS-variable tokens, light and dark),
TanStack Router (Zod-validated search params), TanStack Query 5, Zod 4 at the API boundary, Radix UI primitives,
Recharts 3 plus hand-built SVG charts, TanStack Virtual, pdf.js, Zustand (UI state only), MSW (mock backend),
Vitest + Testing Library, Playwright + axe.

## Run

```bash
npm ci
npm run dev              # :5173, proxies /api to API_ORIGIN (default http://localhost:8000)
npm run dev:mock         # :5173 with the MSW fixture backend in a service worker, no API needed
API_ORIGIN=https://gp-python-api.levelbrook.com npm run dev   # local UI against a live API
npm run typecheck && npm run lint && npm test
npm run build && npm run size                                  # bundle budget: initial JS < 200 KB gzip
npm run e2e                                                    # Playwright, mock build, 4 viewports
E2E_LIVE_ONLY=1 E2E_PYTHON_URL=https://gp-python.levelbrook.com E2E_GO_URL=https://gp-go.levelbrook.com npx playwright test
npm run gen:api          # regenerate src/api/openapi.gen.ts from ../backend/openapi.json
```

## Layout

```
src/
  main.tsx            QueryClient (retry policy, connectivity), router, MSW in --mode mock only
  router.tsx          route tree: lazy pages, loaders (ensureQueryData), validateSearch, error/pending per route
  api/
    client.ts         fetch wrapper: X-Workspace-Id, problem+json -> ApiError, Zod -> ContractError, binary downloads
    schemas.ts        Zod schemas for dashboard / analysis / strategies (+ Decimal-string and ratio normalization)
    contract.ts       request types from openapi.gen.ts (generated from the backend's OpenAPI)
    queries.ts        query-key factory, queryOptions, mutations (optimistic resolve/dismiss with rollback)
    mock/             fixture household, TypeScript mock engine, MSW handlers (per workspace, persisted)
  lib/                search-param schemas, workspace id, theme/UI store, money/rate formatting, status rule
  components/         app shell, traceability drawer, assumptions form (useActionState), figures, tables
  charts/             chart frame (summary + legend + table toggle), waterfall, heatmap, bracket fill, ...
  pages/              one file per route, including /engineering and /twin
functions/api/[[path]].ts   Pages Function: /api/* proxy to API_ORIGIN (+ visitor IP, proxy key)
e2e/                  Playwright specs; screenshots and results are gitignored
scripts/              deploy-pages.sh, check-bundle.mjs, summarize-e2e.mjs, contact-sheet.py
```

## Deploy

```bash
export CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=...
scripts/deploy-pages.sh python      # builds with VITE_STACK=python, checks the budget, adds lbtrack, deploys gp-python
scripts/deploy-pages.sh go
```

Each Pages project has two secrets: `API_ORIGIN` (its API) and `PROXY_KEY` (lets the API trust the forwarded
visitor IP; Cloudflare rewrites `CF-Connecting-IP` on the proxy's subrequest to its own egress address).

## E2E and the workspace limit

The APIs allow 30 new workspaces per client IP per day. Live runs therefore use a persistent pool
(`e2e/.ws-pool/`): read-only journeys share one workspace per stack, reset once in global setup; tests that change
data have their own slot and call `POST /workspace/reset` first. After the first run, a full run provisions nothing.

## Known gaps

- The mock engine is a TypeScript approximation of the Python engine for offline demos; its numbers differ from the
  live stacks. The live stacks are checked against each other (parity spec), not against the mock.
- Response bodies are untyped in the backend's OpenAPI document, so Zod schemas (not generated types) describe them.
