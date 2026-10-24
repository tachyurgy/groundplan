# Groundplan releases

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
