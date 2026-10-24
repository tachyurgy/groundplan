# Groundplan backend

Python 3.12+ (developed on 3.13) · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 17 · numpy · reportlab.
Package `groundplan`. Local only: nothing here is deployed, and no paid API is called by default.

## Run it

```bash
make db     # creates groundplan_dev + groundplan_test if missing, runs migrations, loads the demo household
make api    # uvicorn on :8000, OpenAPI at http://localhost:8000/docs
make test-backend   # ruff + pytest (engine goldens, unit tests, API tests against groundplan_test)
make fixtures       # regenerate ../fixtures/engine/*.json; fails if any hand-checked value drifts
```

Postgres runs on the `/tmp` socket as the current OS user. Override with `GP_DATABASE_URL`
(`postgresql+psycopg://@/groundplan_dev?host=/tmp` by default). Tests use `GP_TEST_DATABASE_URL` /
`groundplan_test`, rebuild its schema **by running the Alembic migrations**, and use no network.

## Layout

```
groundplan/
  engine/          pure functions, no I/O, Decimal math, integer cents out
    figure.py        Figure / Input / Source, the single rounding point, status derivation
    depreciation.py  MACRS 27.5 / 39 yr mid-month (Pub 946 A-6 / A-7a), simple mode, allowed-or-allowable, cost-seg 1245
    loans.py         monthly schedules: fixed, interest-only, ARM reset, HELOC, balloon; DSCR
    cashflow.py      NOI, net cash flow, the Schedule E bridge, projections
    equity.py        equity, lendable equity (70% LTV), ROE, CAGR, projected value, concentration
    passive.py       469(i) $25k allowance + phase-out, MFS, RE pro, carryforward, release on sale vs 1031
    tax_tables.py    2025 (+2026, verify) federal brackets, std deduction, LTCG, NIIT, and the stacking rule
    state_tax.py     table-driven from ../fixtures/engine/states.json; unsupported state -> Finding, never guessed
    exit_tax.py      every exit-tax component as its own Figure; Section 121 on a converted residence
    strategies.py    Hold / Sell now / 1031 (incl. DST) on identical assumptions + leads/trails/neutral matrix
    observations.py  ONE reviewable rule table (RULES) -> plain-English notes citing Figure keys
    narrative.py     TemplateNarrative (default) | LLMNarrative (opt-in) + number_guard
    simulate.py      buy/sell/exchange/refi over time, seeded Monte Carlo bands
    analysis.py      composes the above into the per-property analysis (the web client's PropertyAnalysis shape)
    golden.py        maps fixture JSON onto engine calls (the Go port implements the same `fn` names)
  db/              SQLAlchemy models (advisor_id on every table), session
  services/        portfolio (DB -> engine models, dashboard, alerts), ingest (import-reconciled, findings),
                   pipeline_adapter (lazy gp_pipeline), factsheet, report (PDF)
  api/             FastAPI app, routers, problem+json, request schemas
alembic/           migrations (0001 = full SPEC §1 model)
scripts/seed.py    the Okafor-Lindqvist demo household, loaded without the pipeline
scripts/gen_fixtures.py  golden case definitions; asserts hand-computed values, then writes the JSON
```

Request flow: router -> `Ctx` (session + advisor id) -> `services.portfolio` loads tenant-scoped rows and builds
plain engine dataclasses -> pure engine -> dicts shaped like `web/src/api/types.ts`. The engine never sees the ORM,
so the Go port (`engine-go/`) can replace it behind `GP_ENGINE=go` without touching the API (the setting exists;
the proxy is not wired yet).

## Figures and provenance

Every computed number is a `Figure`:

```json
{"key": "cash_flow.net_annual", "value_cents": 2097184, "status": "blocked",
 "inputs": [{"key": "cash_flow.noi", "value": 3502650, "status": "blocked",
             "source": {"type": "figure", "ref": "cash_flow.noi"},
             "figure": { ...the child Figure, recursively... }}],
 "formula": "NOI - debt service (principal + interest)", "notes": []}
```

* Leaf inputs carry a `source`: `document` (with `document_id`, `page`, `bbox` when the value came from an extracted
  field), `manual`, `public_data` or `default`. Computed inputs carry the child Figure, so
  `GET /properties/{id}/figure/{key}` returns the whole tree down to the source documents (`depth` param, default 12).
* Status follows SPEC §1: confirmed only if every leaf is document or manual; estimated if any leaf is public_data
  or default; blocked if an open `severity=block` Finding touches a leaf. It propagates upward through children.
  An estimated property value (`value_source=estimated`) is a `public_data` leaf; a default vacancy is `default`.
* Strategy figures inherit the base analysis status: a 1031 comparison built on an estimated value or a blocked
  rent figure can never show as confirmed.
* Conflicts are never averaged. A blocking conflict keeps the figure `blocked` until
  `POST /findings/{id}/resolve {value}`, which writes the chosen value back to the underlying row
  (`resolution.applied_to` says where), so the engine runs on the resolved value.
* Rounding: exact `Decimal` everywhere; round HALF-UP to the cent once, when a value becomes a Figure or a schedule
  row (`figure.cents`). The Go port uses the same rule; `fixtures/engine/*.json` holds both to the cent.

## The bracket-stacking rule (exit tax)

```
ordinary taxable = wages + other income - standard deduction - released suspended losses
1. ordinary taxable income fills the brackets first (that tax is not part of the exit tax)
2. Sec 1245 recapture (bonus / cost-seg) stacks next at full ordinary rates
3. unrecaptured Sec 1250 gain stacks on top at min(bracket rate, 25%)  -> can land in 12/22/24% brackets
4. remaining long-term gain stacks last at 0 / 15 / 20% by where it lands on total taxable income
NIIT = 3.8% x min(gain + rental NII, MAGI incl. gain - threshold);  state = marginal table tax on the gain
exit_tax_total = fed_1250 + fed_1245 + fed_ltcg + niit + state
```

Worked check (fixture `tax/exit_tax_wa_mfj_hand_checked`): MFJ, WA, wages $200,000, sale $1,000,000, 6% selling
costs, purchase $500,000, $150,000 accumulated depreciation. Gain = 940,000 - 350,000 = $590,000. Ordinary taxable
= $168,500. The 1250 gain ($150,000) fills 168,500 -> 318,500: 22% x 38,200 + 24% x 111,800 = **$35,236** (both
under the 25% cap). LTCG $440,000 from 318,500 -> 758,500: 15% x 281,550 + 20% x 158,450 = **$73,922.50**.
NIIT: 3.8% x min(590,000, 790,000 - 250,000) = **$20,520**. Total **$129,678.50**; net proceeds $810,321.50.

## Spec worked examples (all in `fixtures/engine/`)

| | inputs | result |
|---|---|---|
| (a) duplex | rents 48,000, opex 18,000, interest 9,000, dep 9,000, principal 6,000 | line 21 = 12,000; cash flow = 15,000; bridge delta 0 |
| (b) SFR | 30,000 / 12,000 / 14,000 / 12,000, principal 4,000 | line 21 = -8,000; cash flow = 0 |
| (c) phase-out | MAGI 130k / 140k / 150k | allowance 10,000 / 5,000 / 0 |
| (d) depreciation | $400k bought Oct 2011, basis 280k | simple: 10,181.82/yr, **145,090.93** accumulated through 2025 (exact, 14.25 yrs); table (default): first year 0.758% = 2,122.40, then 10,180.80/yr, **144,653.60** |

Table mode is the default because it is what the return should show; simple mode is the spec's "exact" check.

## "AI writes the narrative, never touches the math"

`engine/narrative.py`. The default `TemplateNarrative` is offline and composes observations and totals that are
already formatted from Figures. `LLMNarrative` is used only when `GP_LLM_PROVIDER=anthropic|bedrock` is set (the
SDKs are an optional `llm` extra, and tests never call it). Its prompt forbids arithmetic and gives it only
pre-formatted values (`FACTS`). `number_guard` then extracts every `$` amount and `%` in the output and checks each
against the set in the input. Any unknown number (or any provider error) discards the LLM text, falls back to
the template, and logs a `narrative_number_guard` event; the response's `narrative.guard` says what happened.
Tests prove an LLM that invents `$9,999,999` gets replaced.

## API (all under `/api/v1`, errors are `application/problem+json`)

`GET /health` · `GET|POST /households` · `GET|PATCH|DELETE /households/{id}` · `GET /households/{id}/dashboard` ·
`POST /households/{id}/properties` · `GET|PATCH|DELETE /properties/{id}` · `GET /properties/{id}/analysis` ·
`GET /properties/{id}/figure/{key}` · `POST /properties/{id}/loans` · `PATCH|DELETE /loans/{id}` ·
`PUT /properties/{id}/years/{tax_year}` · `GET /properties/{id}/strategies` · `GET|POST /properties/{id}/scenarios` ·
`GET /scenarios/{id}` · `POST|GET /households/{id}/documents` · `GET|DELETE /documents/{id}` ·
`GET /households/{id}/findings?status=` · `POST /findings/{id}/resolve` · `POST /findings/{id}/dismiss` ·
`GET /households/{id}/report.pdf` · `GET /properties/{id}/factsheet?format=emoney|rightcapital|mgp|json|csv` ·
`GET /households/{id}/alerts` · `POST /simulate` · `GET /eval/latest` · `POST /households/{id}/import-reconciled` ·
`GET /rules` (the observation rule table).

* Tenancy: optional `X-Advisor-Id` header (defaults to the dev advisor). Every query goes through
  `db.models.scoped(Model, advisor_id)`; another advisor's ids return 404 (`tests/test_api.py::test_tenant_isolation`).
* What-ifs as query params (the web client's names). `/analysis`: `appreciation_rate, rent_growth_rate,
  expense_growth_rate, vacancy_rate, capex_reserve_rate, selling_cost_rate, land_pct, current_value_cents, arm_index,
  year, horizon`. `/strategies`: `appreciation_rate, rent_growth, expense_growth, reinvest_rate, arm_index,
  replacement_value_cents, replacement_debt_cents, cash_taken_cents, dst, load_rate, dst_yield, replacement_state,
  horizon`.
* Uploads: the file is read into memory, hashed, passed to `gp_pipeline` and dropped; only sha256, the extracted
  fields and the findings persist (`bytes_retained` is always false). `gp_pipeline` is imported lazily. If it isn't
  installed, or exposes no `process_document(data, filename, context)`, the upload returns **501** with the sha256.
  In production this becomes an SQS-fed worker (API puts bytes on an encrypted in-memory queue item, worker
  extracts and writes fields, the client polls the document status); the synchronous path is for the demo.
* `import-reconciled` takes Agent B's `ReconciledHousehold` JSON and upserts it idempotently: properties by
  normalized address key, loans by lien position, years by tax year, documents by sha256, findings by stable key.
  A re-import never overwrites a finding the advisor already resolved or dismissed.
* Fact sheets: **best-effort** mappings onto the labels each platform uses for a real-estate asset ("Real Estate
  Asset: Market Value / Mortgage Liability / Net Rental Income", "Property: Current Value / Annual Rental Income /
  Mortgage", "Asset Type: Real Estate - Value / Debt / Income"). They are not official integrations and are labelled so.

## Deviations from SPEC

1. **land_pct semantics.** §1 says `land_pct 0.6..0.8 default 0.70`, but its own formula
   (basis = cost x (1 - land_pct)) and worked example (d) ($400k -> $280k basis) need land = 30%. I kept the
   formula and the example, so land_pct is the land share, bounded to **[0.20, 0.60], default 0.30**, with a note
   whenever the bound applies. The pipeline uses the same formula.
2. **Year 28 of the 27.5-year table** is computed as the exact remainder (e.g. Jan = 1.979%) with a flat 3.636% for
   years 2-27, as §2.1 specifies. The printed IRS table alternates 3.636/3.637 in years 10-27 and shows 1.970.
   Totals are identical; the year-by-year split differs by about 0.001% of basis.
3. **Observation severities** are `alert|warn|info` internally. The API maps them to the shared `Severity`
   (`alert` -> `warn`) and also returns `level` so alerts still sort first.
4. Response shapes follow `web/src/api/types.ts`, the client's reading of §3. Where that adds fields (nested
   `figure`, `document_id`/`bbox`, `label`, `roe_rate`, `dst_yield`), they are emitted. Source type `figure`
   marks a computed input.

## What is stubbed

* `GP_ENGINE=go` proxy to `engine-go` (setting exists; the Go service is Agent D's).
* Alerts are computed on the fly (`/alerts`), not persisted or scheduled. The `alerts` table exists.
* `LLMNarrative` and the pipeline's `LLMExtractor` are wired but off; no test or default path calls a paid API.
* Auth: a single dev advisor via header. Production would put Cognito/OIDC in front and derive `advisor_id`
  from the token (and add Postgres row-level security as a second wall).

## What I would do next

1. Postgres RLS policies keyed on `current_setting('app.advisor_id')`, so a missed `scoped()` cannot leak.
2. The async document worker (SQS + Fargate) with idempotency keys on sha256.
3. Wire the `GP_ENGINE=go` proxy and run both engines in shadow mode, diffing cents per request.
4. Persist alerts with a daily job; email/CRM hooks.
5. State tables: indexing updates per year, local taxes (NYC, MD counties), more partial-exclusion states.
6. Property-level tax modeling over the hold period (annual income tax on cash flow, passive-loss usage per year).

## Known limitations

* State tax ignores state deductions and exemptions and treats gains as ordinary income except AZ's 25% exclusion.
  WI's 30% exclusion and the MT/ND/SC partial exclusions are noted, not applied. 26 states plus no-tax states are
  in the table; the rest raise an `unsupported state` Finding.
* Hold/sell/1031 cash flows are pre-income-tax; only disposition taxes are modeled. The 1031 replacement
  uses the relinquished property's cap rate and a 30-yr fixed (DST: interest-only) loan at the weighted old rate.
* Each property's exit tax is stacked on the household's other income on its own. The dashboard's
  "exit tax if all sold" is the sum of those, not a single combined stack.
* Short-term rentals (average stay <= 7 days) are flagged and otherwise modeled as ordinary rentals.
* The Monte Carlo stochastic layer is float64 (a distribution, not a ledger); its taxes still come from the
  Decimal engine. Draws are i.i.d. normal per year and property, with no autocorrelation or regime model.
* 2026 federal tables are carried and marked verify. Anything past 2026 uses the 2026 tables.
* `infra/terraform` was written, not validated (terraform is not installed here), and is never applied.
