# Groundplan releases

## 2026-10-23 (night) — Go engine port of the three fixes + one findings order (gp-go-api 1f0a3f7, gp-python-api 1f0a3f70a5d7)
- **What deployed:** gp-go-api (engine fixes from f56b36c, findings order 1f0a3f7) and gp-python-api 1f0a3f70a5d7 on Box B.
- **Changed:** Go mirrors Python 0dd3906 (loans back-fill balance, 1031 cash after tax invested, exit_tax.released_loss_benefit);
  findings lists ordered severity, property nickname (none first), kind, key, field, id on both stacks; parity.py adds two
  non-DST cash_taken strategy variants and reports SKIP separately.
- **How:** `engine-go/deploy.sh`; Python image built on the box from backend/ pipeline/ fixtures/ infra/ with GP_GIT_SHA.
- **Verified:** go test green (68 golden cases), go vet clean; pytest 131 passed, ruff clean; from Box B, parity twice in a
  row: 197/197 + 1 SKIP (resolve-blocking: no open block finding left on either side), upload 24/24, 0 invariant failures.

## 2026-10-23 (late) — Python engine: three calculation fixes (gp-python-api 0dd3906b9b7a)
- **What deployed:** gp-python-api on Box B (https://gp-python-api.levelbrook.com), image built from commit 0dd3906.
- **Changed:** loans table back-filled year no longer doubles the year-end balance (Maple 2025 row $294,074.78 ->
  $147,037.39 = equity total debt); 1031 cash boot after the tax on boot is invested at the reinvest rate and counted in
  terminal wealth, default replacement value = rolled equity + replacement debt (Maple 10y, $50k cash out: $587,141.31 ->
  $568,582.50, now below the no-cash $580,602.21); released suspended losses credit the ordinary tax they save
  (new Figure `exit_tax.released_loss_benefit`; Maple sell-now tax $96,600.26 -> $92,155.66). New golden cases (GOLDEN commit);
  /meta now reports the git sha instead of 0.1.0. The Go engine is not ported yet, so Python/Go parity diverges on these
  figures until it is.
- **How:** tar backend/ pipeline/ fixtures/ infra/ -> /root/groundplan/src-py, `docker build -f infra/Dockerfile.api
  --build-arg GP_GIT_SHA=<sha>`, `docker run` on the kamal network (256m), builder prune.
- **Verified:** pytest 130 passed, ruff clean; live /meta version 0dd3906b9b7a; fresh workspace Maple loans row, sell tax and
  1031 terminal wealth with `cash_taken_cents=5000000` show the numbers above.

## 2026-10-23 (night) — Front ends live: gp-python.levelbrook.com and gp-go.levelbrook.com
- **What deployed:** Cloudflare Pages projects `gp-python` and `gp-go`, the same React build twice (VITE_STACK), each
  proxying `/api/*` to its backend through a Pages Function. Live: https://gp-python.levelbrook.com,
  https://gp-go.levelbrook.com.
- **Changed:** web rebuilt on React 19 + React Compiler, Vite 8, Tailwind 4, TanStack Router (typed URL state) +
  Query, Zod at the API boundary, Radix primitives, Recharts 3 + hand-built SVG charts (waterfall, sensitivity
  heatmap, bracket fill, diverging bars, sparklines), TanStack Virtual, MSW mock backend; no-login workspaces;
  stack badge + twin link; upload summary for the Schedule E demo flow; `/engineering` page; CI workflow.
- **How:** `cd web && scripts/deploy-pages.sh python` and `... go` (wrangler pages deploy of dist + functions, lbtrack
  installed, `_routes.json`), secrets `API_ORIGIN` + `PROXY_KEY` per project, custom domains via the Pages API +
  proxied CNAMEs.
- **Verified:** Vitest 40/40; Playwright mock 50 passed (4 viewports), live 107 passed across Python and Go at 4
  viewports plus the Python-vs-Go parity walk (headline figures identical for all 4 properties via the twin link);
  axe 0 serious / 0 critical across 180 page scans (light + dark); initial JS 158.6 KB gzip (budget 200); a
  workspace created through each proxy records the visitor IP on both backends.

## 2026-10-23 — gp-go-api upload-conflict semantics, JSON seed unpinned; gp-python-api properties_touched order
- **What deployed:** gp-go-api `707bcbf` and gp-python-api `707bcbf73185` (Box B).
- **Changed:** Go ports the new ingest rules (blocking conflict instead of overwrite, decided conflicts stay closed, no
  renames, upload `import` counts); Go now seeds from `fixtures/seed/okafor-lindqvist.json` (the legacy-seed pin
  `/root/groundplan/go-seed.json` was removed). Python: one-line change in `routers/documents.py` so
  `properties_touched` is listed in property order (nickname, key) instead of by random uuid, matching Go.
  New `scripts/parity_upload.py` (upload -> block -> resolve -> confirmed -> re-upload, text + scan).
- **How:** `engine-go/deploy.sh`; Python: patched file into `/root/groundplan/src-py`, `flock .build.lock docker build -f
  infra/Dockerfile.api --build-arg GP_GIT_SHA=707bcbf73185`, container recreated with the same run args.
- **Verified:** from Box B against both live APIs: `scripts/parity.py` 182/182, `scripts/parity_upload.py` 24/24 with 0
  invariant failures; both `/meta` report sha 707bcbf.

## 2026-10-23 (later) — Demo seed now = the synthetic documents' household (SEED CHANGED)
- **Seed changed:** `backend/scripts/seed.py` now loads `fixtures/seed/okafor-lindqvist.json`, generated from
  `pipeline/gp_pipeline/synth/household.py` (new addresses, purchase prices, loans, values, years). Go port: load the
  same JSON. Open findings at seed time: 4 (STR, Elm 2024 depreciation outlier, Oak missing from 2025, Tahoe line 12
  vs lender interest), none blocking; the household is not blocked until the 2025 Schedule E is uploaded.
- **What deployed:** gp-python-api + gp-pipeline rebuilt from 0587cc2 (same hosts, caps, routes).
- **How:** same raw pattern as below (tar -> scp -> flock docker build on Box B -> docker run -> kamal-proxy deploy).
- **Verified:** live, fresh workspaces: `2025_schedule_e.pdf` and `.scan.pdf` each -> `import {properties_created: 0,
  properties_updated: 3, conflicts_raised: 1}`, touched ids all pre-existing, Maple cash flow blocked -> resolve 200 ->
  confirmed. `scripts/parity.py http://localhost:8000 https://gp-python-api.levelbrook.com` 182/182. Backend 117 tests,
  pipeline 14, ruff clean, `make fixtures` no diff.
- **Changed:** upload/import raises a blocking conflict instead of overwriting when a document disagrees with a stored
  rent-roll/expense value; never renames an existing property; upload response gains `import` counts. Synth: Elm IO
  period now ends 2027-06-30 with the ARM reset. `web/public/samples/` holds 6 sample PDFs + index.json.

## 2026-10-23 — Go twin API (gp-go-api) on Box B
- **What deployed:** `https://gp-go-api.levelbrook.com` (container `gp-go-api`, static Go binary on distroless, 96 MB cap,
  ~8 MB resident). Postgres db `groundplan_go` on `lb-postgres`. Uploads go to the internal `gp-pipeline`. Binary git sha `4ea1089`.
- **Changed:** `engine-go/`: the full engine port (63/63 golden fixtures byte-equal), every `/api/v1` path of
  `backend/openapi.json`, `/engine/analyze` + `/engine/strategies` on the wire format, workspaces + limits + sweep,
  embedded Alembic SQL with a revision guard, seed from `fixtures/seed/okafor-lindqvist.json`, fpdf report.
- **How:** `engine-go/deploy.sh`: cross-compile linux/amd64 on the Mac, scp, `flock /root/groundplan/.build.lock docker build`
  on the box, `docker run --network kamal --memory 96m --env-file /root/groundplan/go-api.env`, `kamal-proxy deploy gp-go-api
  --tls --health-check-path /health`. DNS A record DNS-only -> 5.78.227.227.
- **Verified:** from outside: `/api/v1/meta` (backend go, go1.26.5, postgres 17), no header -> 400 problem+json,
  report.pdf `application/pdf`, text + scan Schedule E uploads (61 fields each), `scripts/parity.py` live Python vs live
  Go 182/182. Pinned to a JSON export of the legacy seed (`/root/groundplan/go-seed.json`) because the live Python API
  still runs it; remove the file and redeploy once gp-python-api ships the JSON seed.

## 2026-10-23 — Python twin API + internal document pipeline on Box B
- **What deployed:** `https://gp-python-api.levelbrook.com` (container `gp-python-api`, FastAPI, 256 MB cap) and the
  internal `gp-pipeline` service (`http://gp-pipeline:8090` on the docker network, tesseract + poppler, 384 MB cap, no
  public route). Postgres db `groundplan_py` on the shared `lb-postgres`. Image git sha `ff40be2a05e4`.
- **Changed:** no-login workspaces (`X-Workspace-Id`, auto-provision + demo seed, per-IP and per-workspace caps, reset,
  14-day idle sweep), `GET /meta`, CORS for the twin front ends, `recommended` removed everywhere, document upload
  through the pipeline service (text layer and OCR scans), `GP_ENGINE=go` forwarding with Python fallback (deployed with
  `GP_ENGINE=python` until gp-go-api is live), `/engine/analyze` + `/engine/strategies` wire API, `scripts/parity.py`.
- **How:** tar of backend/ + pipeline/ + fixtures/engine + eval-latest.json -> scp to `/root/groundplan/src-py` ->
  `flock /root/groundplan/.build.lock docker build -f infra/Dockerfile.{pipeline,api}` on the box -> `docker run -d
  --restart unless-stopped --network kamal --memory {384,256}m` (env `/root/groundplan/python-api.env`) ->
  `kamal-proxy deploy gp-python-api --target gp-python-api:8000 --host gp-python-api.levelbrook.com --tls
  --health-check-path /api/v1/health` -> `docker builder prune -f`. DNS A record DNS-only -> 5.78.227.227.
- **Verified:** from outside: `/api/v1/meta` 200 (CPython 3.12.15, postgres 17, alembic 0002), no header -> 400,
  fresh-workspace dashboard 200 (4 properties, 4 open findings), real multipart uploads of the synthetic 2025 Schedule E
  (text 0.5 s, 61 fields, extractor rules) and its `.scan.pdf` (8.3 s, 61 fields, extractor ocr, identical rents),
  CORS preflight for gp-go.levelbrook.com, `/eval/latest`, `python3 scripts/parity.py http://localhost:8000
  https://gp-python-api.levelbrook.com` 182/182. Not verified: the Go twin (not deployed yet) and the front ends.
