# engine-go: the Go twin of the Groundplan backend

A complete Go backend that is a drop-in replacement for the FastAPI app in `backend/`: same paths under `/api/v1`,
same JSON, same cents. The React front end runs against either. Live at **https://gp-go-api.levelbrook.com**
(its Python twin is https://gp-python-api.levelbrook.com).

```
go test ./...                                  # 63 golden fixtures + unit + handler + Postgres integration tests
go run ./cmd/gp-api                            # :8080, DATABASE_URL=postgres:///groundplan_go_test?host=/tmp by default
python3 ../scripts/parity.py http://localhost:8000 http://localhost:8080
./deploy.sh                                    # cross-compile, build the image on Box B, run, register with kamal-proxy
make sync                                      # re-copy the shared contracts (states.json, migrations.sql, seed JSON)
```

## Architecture

```
cmd/gp-api            main: env config, schema guard, sweep goroutine, graceful shutdown, -healthcheck for distroless
internal/api          net/http (Go 1.22 pattern routing), middleware, problem+json, pydantic-style validation, handlers
internal/service      port of backend/groundplan/services: portfolio (analyze, dashboard, summary, alerts, strategies,
                      serializers), ingest (import_reconciled, persist_documents, upsert_findings, resolve), factsheet,
                      workspace (provision + seed in one tx, limits, reset, sweep), seed
internal/store        pgx/v5: tenant-scoped loads of a household tree, row writes, the Alembic schema guard
internal/report       report.pdf with go-pdf/fpdf (same sections, rows and wording as services/report.py)
migrations            backend/migrations.sql (alembic upgrade head --sql), embedded verbatim
engine/...            the deterministic engine, one package per Python module
dec                   decimal arithmetic with Python's default decimal context
jsonx                 insertion-ordered JSON object + an encoder that writes what Starlette writes
```

**Why stdlib `net/http` and not chi:** Go 1.22's `ServeMux` has method + wildcard patterns (`GET /properties/{id}`,
`{key...}` for figure keys containing dots), which covers all 40 routes. Middleware is one `ServeHTTP` (request id,
recover, access log, CORS, body limit, timeout), so a router dependency would add nothing. Unknown paths and wrong
methods are answered with the same problem+json bodies Starlette produces (404 "Not Found", 405 "Method Not Allowed").

**Tenancy:** `X-Workspace-Id` (any UUID form Python's `uuid.UUID` accepts, canonicalized) is the `advisor_id`; every
query in `internal/store` filters by it. First use provisions the advisor row and seeds the demo household in one
transaction; concurrent first requests race on `INSERT ... ON CONFLICT (id) DO NOTHING RETURNING id` and the loser
rolls back its per-IP counter bump (an integration test fires 16 concurrent first requests and checks one household
and one counted provision). Limits: 30 new workspaces per IP per day, 20 households and 50 documents per workspace,
15 MB upload, 20 MB body; idle workspaces are swept after 14 days.

**Schema:** Alembic is the single source of truth. `migrations/alembic_head.sql` is `backend/migrations.sql` copied
byte for byte (test-enforced). On start the server applies it to an empty database and refuses to start if
`alembic_version` is anything but the embedded head (0002).

**Upload conflicts:** a document value that differs from a stored non-zero rent/expense value is never written; it
raises a block-severity conflict Finding `conflict:<property_key>:<column>:<year>` with both candidates (the upload is
candidate 0). Resolving writes the chosen value back; a decided conflict never reopens; uploads never rename an
existing property. The upload response carries `import {properties_created, properties_updated, conflicts_raised}`
and lists `properties_touched` in property order (nickname, then key) on both stacks.

**Documents:** `POST /households/{id}/documents` streams the multipart `file` into memory (15 MB cap), hashes it, sends
it to `GP_PIPELINE_URL/extract` with the `household_hint` JSON, drops the bytes, then persists exactly like
`services/ingest.py` (import the reconciled household, documents by sha256, fields replaced, findings by stable key).
4xx from the pipeline = 422/413 "Document rejected", unreachable or 5xx = 503 "Document pipeline unavailable".

## File-by-file map to the Python engine

| Python (`backend/groundplan/engine/`) | Go (`engine-go/engine/`) |
|---|---|
| figure.py (Figure, Input, Source, money, ratio, derive_status) | figure/figure.go |
| depreciation.py | depreciation/depreciation.go |
| loans.py | loans/loans.go |
| cashflow.py | cashflow/cashflow.go |
| equity.py | equity/equity.go |
| passive.py | passive/passive.go |
| tax_tables.py | taxtables/taxtables.go |
| state_tax.py (+ fixtures/engine/states.json, embedded) | statetax/statetax.go |
| exit_tax.py | exittax/exittax.go |
| models.py | models/models.go |
| analysis.py | analysis/analysis.go |
| strategies.py (compare_strategies, present; no `recommended`) | strategies/strategies.go |
| observations.py (the RULES table) | observations/observations.go |
| narrative.py (TemplateNarrative, number_guard) | narrative/narrative.go |
| simulate.py | simulate/simulate.go |
| golden.py | golden/golden.go (+ golden_test.go runs ../fixtures/engine/*.json) |
| wire.py (engine wire format) | internal/api/engine.go |

## The rounding rule (identical to Python)

Python computes with `decimal.Decimal` under the default context: **28 significant digits, ROUND_HALF_EVEN on every
intermediate operation**, and rounds a money value **HALF_UP to the cent exactly once**, when it becomes a Figure or a
schedule row. `dec` reproduces this on `cockroachdb/apd` (the same General Decimal Arithmetic spec libmpdec implements):
add/sub/mul/quo at 28 digits half-even, integer powers computed exactly then rounded once, exact quotients given the
ideal exponent, `Cents()` = quantize(1, HALF_UP), `String()` = GDA to-scientific-string (byte-identical to
`str(Decimal)`, so rates, layer rates and Input values print the same). Python-specific formatting is ported too:
`repr(float)` for every JSON float, `format(Decimal, ".1f")` half-even, `{x:,.0f}` on floats, `{days:g}`.
`dec/testdata/python_vectors.json` holds CPython outputs the tests compare against.

The simulator is float64 like Python's: every product feeding an addition is wrapped in `float64()` so the Go
compiler cannot fuse it into an FMA on arm64, and `x**n` is a correctly rounded power (what glibc returns).

## Migration plan (strangler)

1. **Golden fixtures are the contract**: `fixtures/engine/*.json` run unchanged in pytest and `go test` (63 cases).
2. **Wire API**: `POST /engine/analyze` and `/engine/strategies` take `backend/groundplan/engine/wire.py` JSON;
   Python serves the same endpoints as the reference (16/16 demo-household calls byte-identical).
3. **GP_ENGINE=go** on gp-python-api forwards pure engine calls to `http://gp-go-api:8080` with fallback, a 30 s
   breaker and an `engine_go_diff` shadow comparison log.
4. **Parity**: `scripts/parity.py` walks every GET for a fresh workspace on both stacks, applies identical mutations
   and diffs normalized JSON (182 checks).
5. **Cutover**: point the front end at gp-go-api (it already runs against either), keep Python for the document
   pipeline, retire the Python API once the shadow diff log stays empty.

## Measured (2026-10-23, Box B, fresh workspace, Maple duplex)

| | Python (gp-python-api) | Go (gp-go-api) |
|---|---|---|
| `GET /strategies` from the box (via kamal-proxy, 50 sequential, 2 runs) | p50 48-51 ms, p95 63-67 ms | p50 22-24 ms, p95 27-28 ms |
| `GET /strategies` from a laptop in WA (network dominated) | p50 173-197 ms, p95 271-301 ms | p50 146-148 ms, p95 226-228 ms |
| RSS (`docker stats --no-stream`, idle) | 106 MiB (256 MiB cap) | 7.8 MiB (96 MiB cap) |
| Image | Python 3.12 slim | 25 MB distroless static |

Parity (live gp-python-api vs gp-go-api, run from Box B): `scripts/parity.py` **182/182**, and
`scripts/parity_upload.py` **24/24** with 0 invariant failures: the 2025 Schedule E (text layer and OCR `.scan.pdf`)
through gp-pipeline -> 0 new properties, 3 updated, 1 blocking rent conflict -> resolve with the document's value ->
Maple confirmed with document provenance -> re-upload updates in place (one document, the decided conflict stays closed).

## Honest list of differences

- **Monte Carlo bands** (`/simulate` with sigma > 0): Go draws from `math/rand/v2` PCG seeded by the request seed,
  numpy uses PCG64; both are reproducible per seed but the bands differ. With sigma = 0 every number matches.
- **Validation error texts** (422 `errors[].msg`) follow pydantic's wording for the common cases (missing, int/float/
  bool parsing, literal, bounds, extra fields); exotic inputs can word a message differently. Status, type and loc match.
- **Timestamps** render in the database session time zone like psycopg, but values are per-request anyway.
- **LLM narrative**: not wired in Go (the template provider is the default on both; Python only uses an LLM when
  `GP_LLM_PROVIDER` is set). `narrative.NumberGuard` is ported for when it is.
- **CORS preflight** replies are Starlette-shaped but not header-for-header identical.
- **Seed**: both load `fixtures/seed/okafor-lindqvist.json` (embedded in Go, drift-tested). `deploy.sh` still honours an
  optional `/root/groundplan/go-seed.json` override (GP_SEED_PATH); it is not present in production.
