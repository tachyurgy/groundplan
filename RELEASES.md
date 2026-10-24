# Groundplan releases

## 2026-10-23 (later) — Demo seed now = the synthetic documents' household (SEED CHANGED)
- **Seed changed:** `backend/scripts/seed.py` now loads `fixtures/seed/okafor-lindqvist.json`, generated from
  `pipeline/gp_pipeline/synth/household.py` (new addresses, purchase prices, loans, values, years). Go port: load the
  same JSON. Open findings at seed time: 4 (STR, Elm 2024 depreciation outlier, Oak missing from 2025, Tahoe line 12
  vs lender interest), none blocking; the household is not blocked until the 2025 Schedule E is uploaded.
- **What deployed:** gp-python-api + gp-pipeline rebuilt (see below for verification).
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
