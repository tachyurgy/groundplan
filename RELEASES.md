# Groundplan releases

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
