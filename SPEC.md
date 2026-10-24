# Groundplan — real estate planning engine for financial advisors

Groundplan is a faithful functional clone of a real-estate-planning SaaS for financial advisors.
Originally local-only; §8 (2026-10-23) adds a public no-login deploy. Goal: a candidate can demo and defend every layer in a technical working session.
Stack mirrors the target company exactly: **Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 17**,
**React 18 + TypeScript + Vite + Tailwind + Recharts**, AWS-shaped packaging (Dockerfile per service,
docker-compose, an `infra/` folder with an ECS/Fargate task definition + Terraform sketch that is NOT applied),
plus a **Go 1.26 port of the deterministic engine** sharing the same golden fixtures.

Identity rules: no personal names of the author anywhere in code, docs or commits. Commits are authored as
`Levelbrook Consulting <levelbrookteam@gmail.com>`. Never name the target company in the product (the product is
"Groundplan"); the README may say "inspired by the advisor real-estate-planning category".
No paid APIs are ever called by default. Every LLM/cloud call sits behind an interface whose default
implementation is local/offline. Tests must pass with no network.

## 0. Repo layout (fixed; three agents build in parallel, each owns one top-level dir)

```
groundplan/
  SPEC.md                 this file (contract for all agents)
  README.md               how to run everything locally (coordinator writes at the end; agents write their own dir README)
  Makefile                top-level: make db, make api, make web, make pipeline-eval, make test, make go-test
  backend/                [AGENT A] FastAPI app + engine + DB + seed      (python package `groundplan`)
  pipeline/               [AGENT B] document pipeline + synthetic docs + eval harness (python package `gp_pipeline`)
  web/                    [AGENT C] React/TS/Vite frontend
  engine-go/              [AGENT D, later] Go port of backend/groundplan/engine with the same golden fixtures
  fixtures/               SHARED golden fixtures (JSON). Agent A creates `fixtures/engine/*.json`; Agent B creates
                          `fixtures/documents/*` (synthetic PDFs + gold labels). Agent C may add `fixtures/web/`.
  infra/                  Dockerfiles, docker-compose.yml, ecs-task-def.json, terraform/ sketch (Agent A, not applied)
```

Python tooling: `uv` (installed), one `pyproject.toml` per package, `pytest`, `ruff`. Node: npm, Node 25.
Local Postgres 17 is running on localhost:5432 (socket /tmp), superuser = current OS user, no password.
Databases to use: `groundplan_dev` and `groundplan_test` (create with `createdb`). Never touch other DBs.

## 1. Domain model (canonical; both Python packages and the TS types follow these names)

All money is integer **cents** in storage and API (`int`), rendered as dollars in the UI. Rates are decimals
(`0.035` = 3.5%). Dates ISO `YYYY-MM-DD`. Every analytic figure carries **provenance**.

```
Advisor        id, firm_name, name, email           (single tenant locally; `advisor_id` on every row anyway,
                                                     row-level isolation enforced in queries = "tenant isolation at the DB layer")
Household      id, advisor_id, name, filing_status (single|mfj|mfs|hoh), state (2-letter), tax_year_latest,
               wages_cents, other_income_cents, magi_cents, active_participation (bool), re_professional (bool),
               goal (text, e.g. "retire in 7 years, stop managing property"), notes
Property       id, household_id, nickname, address_line1, city, state, zip, property_type
               (sfr|multifamily|vacation_str|commercial|land|self_rental|other), units,
               purchase_date, purchase_price_cents, placed_in_service_date, land_pct (LAND share, bounded 0.20..0.40 = improvements 60-80%, default 0.30),
               improvements_cents (capital improvements added to basis), cost_seg_study (bool),
               current_value_cents, value_source (estimated|confirmed), value_as_of,
               appreciation_rate, rent_growth_rate, expense_growth_rate, vacancy_rate, mgmt_fee_rate,
               capex_reserve_rate, selling_cost_rate (default 0.06), status (active|sold|converted)
Loan           id, property_id, lender, loan_type (fixed|arm|interest_only|heloc|balloon), original_cents,
               balance_cents, balance_as_of, rate, term_months, io_months (0 if none), arm_reset_date,
               arm_index_margin, monthly_payment_cents, maturity_date, lien_position (1..n), is_paid_off
RentRoll       id, property_id, tax_year, gross_rent_cents, other_income_cents
ExpenseYear    id, property_id, tax_year, taxes_cents, insurance_cents, repairs_cents, mgmt_cents,
               utilities_cents, hoa_cents, other_cents, mortgage_interest_cents, depreciation_cents  (= Schedule E lines)
DepreciationLedger id, property_id, tax_year, allowed_cents, allowable_cents, method (sl_27_5|sl_39|cost_seg|bonus), note
SuspendedLoss  id, household_id, tax_year, carryforward_cents            (Form 8582)
Document       id, household_id, kind (form_1040|schedule_e|form_4562|form_8582|mortgage_statement|closing_statement|
               lease|appraisal|other), tax_year, filename, sha256, page_count, uploaded_at, status
               (queued|extracted|reconciled|discarded), bytes_retained (always false; file is processed in memory and
               dropped; only sha256 + extracted fields persist)
ExtractedField id, document_id, entity_hint (household|property), property_key (normalized address or column id),
               field (e.g. "schedule_e.line3.rents"), value (json), unit (cents|date|text|bool|rate), page, bbox [x0,y0,x1,y1],
               confidence (0..1), extractor (rules|ocr|llm), raw_text
Finding        id, household_id, property_id (nullable), kind (conflict|missing|outlier|stale|unsupported_structure),
               field, severity (info|warn|block), message, candidates (json list of {source, value, document_id, page}),
               status (open|resolved|dismissed), resolution (json: chosen value + who + when + note)
Figure (not a table; the API shape for any computed number):
               { "key": "cash_flow.net_annual", "value_cents": 1500000, "status": "confirmed|estimated|blocked",
                 "inputs": [ {"key": "...", "value": ..., "source": {"type":"document|manual|public_data|default", "ref": "...", "page": 3}} ],
                 "formula": "line21 + depreciation - principal_paid - capex_paid",
                 "notes": ["..."] }
Scenario       id, property_id, name, horizon_years (default 10), assumptions (json: appreciation_rate, rent_growth,
               expense_growth, reinvest_rate (default 0.06), sale_year, exchange {replacement_value_cents,
               replacement_debt_cents, dst (bool), load_rate (default 0.085 for DST), cash_taken_cents}), results (json cache)
Alert (monitoring, roadmap item, stub): id, household_id, property_id, kind (arm_reset|io_period_ending|cash_flow_negative|
               value_drift|loan_maturity|roe_below_threshold), due_date, message, status
```

"Confirmed vs estimated": a figure is **confirmed** only if every input is from a document or manual entry;
**estimated** if any input is public_data or default; **blocked** if an open Finding with severity=block touches an input.
The engine never averages conflicting sources; it runs on the resolved value or returns `blocked`.

## 2. Deterministic engine (backend/groundplan/engine/, pure functions, no I/O, Decimal math, integer cents out)

Implement each as a pure function taking plain dataclasses/pydantic models and returning `Figure`s. Round half-up to
the cent only at the end of each figure. Every function has golden tests in `fixtures/engine/<name>.json`
(list of {input, expected}) so the Go port can reuse them byte-for-byte.

2.1 **Depreciation** (`depreciation.py`): residential rental = 27.5-yr straight line, **mid-month convention**
(IRS Pub 946 Table A-6). First-year percentage by month placed in service: Jan 3.485, Feb 3.182, Mar 2.879, Apr 2.576,
May 2.273, Jun 1.970, Jul 1.667, Aug 1.364, Sep 1.061, Oct 0.758, Nov 0.455, Dec 0.152 (%); years 2-27 = 3.636%;
year 28 = remainder (table: 1.970 for Jan ... ). Implement from the table, and also a "simple" mode (basis/27.5 full
years) with a flag, defaulting to the table. Nonresidential = 39-yr mid-month (first-year by month: Jan 2.461, Feb 2.247,
Mar 2.033, Apr 1.819, May 1.605, Jun 1.391, Jul 1.177, Aug 0.963, Sep 0.749, Oct 0.535, Nov 0.321, Dec 0.107; then 2.564%).
Depreciable basis = (purchase_price + improvements) × (1 - land_pct), land_pct (land share) bounded to [0.20, 0.40] with a note when
bounded; default 0.70. Accumulated depreciation through end of year Y-1 for sale in Y. "Allowed or allowable": if a ledger
says less was claimed than allowable, recapture still uses allowable (flag it as a Finding kind=outlier).
Cost-seg / bonus: if `cost_seg_study` or ledger method=bonus, the ledger amounts override the table and the bonus
portion is tagged Sec 1245 (ordinary rates, no 25% cap).

2.2 **Loan amortization** (`loans.py`): monthly schedule; fixed; interest_only for io_months then amortizing over the
remaining term; ARM: fixed rate until arm_reset_date then rate = index+margin (assumption input) — produce a schedule and
annual principal/interest splits; HELOC: treat as interest-only revolving at `rate` on `balance`; balloon: amortize on
`term_months` schedule, remaining balance due at maturity. Also `principal_paid_in_year(year)` and
`interest_paid_in_year(year)` and `balance_at(date)`. Multiple liens per property are summed; a paid-off lien contributes 0
but still appears in the trace. DSCR = NOI / annual debt service.

2.3 **Cash flow** (`cashflow.py`): per property per year:
`NOI = gross_rent×(1-vacancy) + other_income − (taxes+insurance+repairs+mgmt+utilities+hoa+other) − capex_reserve`
`net_cash_flow = NOI − debt_service(principal+interest)`. Also the **Schedule E reconciliation view**:
`cash_flow_from_return = line21 + line18_depreciation − principal_paid − capital_improvements_paid` (and never subtract
interest twice). Expose both and the delta between them as a Figure. Projections: grow rent by rent_growth, expenses by
expense_growth, each year of horizon.

2.4 **Equity** (`equity.py`): equity = value − Σ balances; lendable_equity = max(0, value×0.70 − Σ balances);
ROE = (net_cash_flow + principal_paydown + appreciation_this_year) / equity_begin_of_year; also CAGR of value from
purchase; projected value = value×(1+appr)^n; concentration = property value / (household net worth input) if given.

2.5 **Passive losses** (`passive.py`): net all rentals in the household. If net ≤ 0 and not re_professional: allowance =
25,000 − 0.5×max(0, MAGI − 100,000), floored at 0, only if active_participation; MFS living together = 0; deductible this
year = min(loss, allowance); remainder carried forward (adds to SuspendedLoss). Suspended losses release in full on a
**fully taxable** sale of the entire interest; a 1031 does NOT release them (carry forward). STR with avg stay ≤ 7 days:
flag Finding kind=unsupported_structure "short-term rental rules apply; not modeled".

2.6 **Federal tax tables** (`tax_tables.py`), tax year 2025 (also carry 2026 if you know them; mark source):
Ordinary brackets 2025 — Single: 10% to 11,925; 12% to 48,475; 22% to 103,350; 24% to 197,300; 32% to 250,525;
35% to 626,350; 37% above. MFJ: 23,850 / 96,950 / 206,700 / 394,600 / 501,050 / 751,600. HOH: 17,000 / 64,850 / 103,350 /
197,300 / 250,500 / 626,350. MFS = single brackets except 37% starts at 375,800.
Standard deduction 2025 (post-OBBBA): Single 15,750; MFJ 31,500; HOH 23,625; MFS 15,750.
LTCG 2025: 0% up to Single 48,350 / MFJ 96,700 / HOH 64,750; 15% up to Single 533,400 / MFJ 600,050 / HOH 566,700; 20% above.
NIIT: 3.8% on min(net investment income, MAGI − threshold), threshold Single/HOH 200,000; MFJ 250,000; MFS 125,000.
Unrecaptured §1250 gain: taxed at ordinary rates **capped at 25%**, stacked ON TOP of ordinary taxable income and
BELOW the LTCG layer (order: ordinary income → §1250 gain fills remaining brackets at min(bracket,25%) → remaining LTCG at
0/15/20 by where it lands). §1245 (bonus/cost-seg recapture) is ordinary income with no cap.

2.7 **State tax** (`state_tax.py`): table-driven `fixtures/engine/states.json`. Include at least: no-tax states
(WA, TX, FL, NV, SD, WY, AK, TN, NH[interest/dividends only → treat 0 for RE gains]); flat states AZ 2.5%, CO 4.4%,
GA 5.39%, IL 4.95%, IN 3.0%, KY 4.0%, MI 4.25%, NC 4.25%, PA 3.07%, UT 4.5%, MS 4.4%, ID 5.695%; bracket states CA (2025:
1/2/4/6/8/9.3/10.3/11.3/12.3 + 1% MHS tax over $1M), NY (4 to 10.9), NJ (1.4 to 10.75), OR (4.75/6.75/8.75/9.9),
MA (5% + 4% surtax over ~$1,083,150), MN (5.35/6.8/7.85/9.85), VA (2/3/5/5.75), MD (2..5.75 + ~3.2% local note),
OH (0/2.75/3.5), WI (3.5/4.4/5.3/7.65). Treat capital gains as ordinary income in every taxing state unless the table
says otherwise (note: AZ 25% LTCG exclusion, ND/SC/MT partial exclusions, WA 7% excise on gains >$270k applies to
*securities* not real estate → 0). Mark every row `"verify": true` with a `source` string; this is an interview demo,
accuracy of the shape matters more than the last decimal, but do not invent brackets you don't know — put fewer states
with a clear "unsupported state" Finding rather than fake numbers. Also a `clawback_states: [CA, OR, MA, MT]` flag for
1031 out-of-state replacement (informational Finding only).

2.8 **Exit tax on a taxable sale** (`exit_tax.py`): sale_price − selling_costs (rate) − loan payoffs = net before tax;
adjusted_basis = purchase + improvements − accumulated_depreciation(allowed/allowable); total_gain = amount realized −
adjusted_basis; unrecaptured_1250 = min(total_gain, accumulated_depreciation_SL); sec1245 = bonus/cost-seg portion;
ltcg = total_gain − 1250 − 1245; federal via stacking on the household's other taxable income (wages + other − std
deduction + released suspended losses as an ordinary deduction); NIIT on the gain (+ rental NII) above threshold; state
per table; **exit_tax_total = fed_1250 + fed_1245 + fed_ltcg + niit + state**; net_proceeds = net before tax − exit_tax_total.
Output every component as its own Figure with inputs and the stacking explanation in `notes`. Section 121 (converted
former residence): if `former_residence_until` is set and within the 2-of-5 rule window → exclude up to 250k/500k of the
non-depreciation gain, with a Finding warn "verify with CPA (nonqualified use)".

2.9 **Strategy comparison** (`strategies.py`): three paths over `horizon_years` on IDENTICAL assumptions:
- **Hold**: yearly net cash flow (grown), principal paydown, appreciation; ending equity; the *growing* deferred exit
  tax if sold at horizon end; terminal after-tax wealth = ending equity − exit tax at horizon + Σ cash flows reinvested
  at reinvest_rate.
- **Sell now (taxable)**: net proceeds after exit tax today, invested at reinvest_rate for the horizon; terminal wealth;
  suspended losses released (reduce the tax).
- **1031 exchange (incl. DST)**: deferred gain carried into replacement at reduced basis; boot = cash_taken +
  max(0, old_debt_paid_off − replacement_debt) (mortgage boot); boot taxed now via the same exit-tax stack (gain recognized
  = min(boot, total_gain)); DST: load_rate reduces working equity; distributions at `dst_yield` (default 0.05) on net
  invested; replacement depreciation continues on carryover basis (+ any new basis); terminal wealth includes the
  deferred liability shown explicitly (not hidden); suspended losses NOT released.
Output per path: yearly series (cash_flow, equity, value, debt, cumulative_tax_deferred, wealth) and terminal figures,
plus a **leads/trails/neutral** matrix per measure (terminal_wealth, cumulative_cash_flow, tax_paid_now, liquidity,
management_burden, concentration) — NEVER a "recommended" label. Add `caveats[]` per path (DST illiquidity, no control,
sponsor risk, fees; hold = concentration and growing recapture; sell = tax now and reinvestment assumption).

2.10 **Observations** (`observations.py`): deterministic rule engine producing short plain-English notes with severity
and the Figures they cite, e.g. cash-flow negative; DSCR < 1.2; ROE < reinvest_rate; recapture > 15% of equity;
IO period ends within 24 months; ARM resets within 24 months; loan matures within 36 months; land_pct was bounded;
depreciation on return differs from allowable by >5%; value_source estimated; concentration > 40% of net worth;
suspended losses present (sale would release them); MAGI phase-out eating the allowance; STR flagged. Keep the rule
list in one table so it is reviewable.

2.11 **Narrative** (`narrative.py`): `NarrativeProvider` protocol: `TemplateNarrative` (default, offline; composes the
observations + strategy matrix into 2-4 paragraphs against `household.goal`, with every number pulled from Figures) and
`LLMNarrative` (optional; `GP_LLM_PROVIDER=anthropic|bedrock`, reads `ANTHROPIC_API_KEY` or boto3 creds; never called in
tests; prompt forbids computing or altering numbers — it may only cite Figure values passed in; a post-check asserts every
dollar amount in the output appears in the input set, else falls back to the template and logs a `narrative_number_guard`
event). This is the "AI writes the narrative, never touches the math" rule, enforced in code.

## 3. API (FastAPI, `/api/v1`, JSON; OpenAPI served at /docs). Agent A implements; Agent C consumes.

```
GET  /health
GET  /households                               -> [HouseholdSummary {id,name,state,filing_status,property_count,
                                                   net_cash_flow_cents,total_equity_cents,open_findings,status}]
POST /households  / GET,PATCH,DELETE /households/{id}
GET  /households/{id}/dashboard                -> {household, metrics:{...Figures}, observations:[...], properties:[PropertyCard],
                                                   findings_open: n, narrative:{text, provider, generated_at}}
POST /households/{id}/properties  / GET,PATCH,DELETE /properties/{id}
GET  /properties/{id}/analysis?year=&horizon=  -> {cash_flow:{...Figures, schedule_e_bridge}, equity:{...}, appreciation:{...},
                                                   depreciation:{schedule:[{year,amount_cents}], accumulated_cents, ...},
                                                   exit_tax:{components...,net_proceeds}, loans:[{schedule summary}], observations:[...]}
GET  /properties/{id}/figure/{key}             -> Figure with full inputs tree (traceability drawer)
POST /properties/{id}/loans  / PATCH,DELETE /loans/{id}
PUT  /properties/{id}/years/{tax_year}         -> upsert RentRoll + ExpenseYear + DepreciationLedger for that year
GET  /properties/{id}/strategies?horizon=10&...assumption overrides   -> StrategyComparison (three paths, series, matrix, caveats)
POST /properties/{id}/scenarios  / GET /scenarios/{id}  (saved assumption sets)
POST /households/{id}/documents   multipart upload -> runs pipeline in-process (sync for the demo; design note on SQS/worker
                                                   in README), returns {document, extracted_fields:[...], findings:[...], properties_touched:[...]}.
                                                   The file bytes are NOT persisted; only sha256 + fields. A `GP_RETAIN_UPLOADS_SECONDS`
                                                   setting (default 0) exists only to prove the point.
GET  /households/{id}/documents   / GET /documents/{id}  (fields + page/bbox)  / DELETE
GET  /households/{id}/findings?status=open   / POST /findings/{id}/resolve {value, note} / POST /findings/{id}/dismiss
GET  /households/{id}/report.pdf              -> client-ready portfolio report (WeasyPrint or reportlab; generated on the fly, not stored)
GET  /properties/{id}/factsheet?format=emoney|rightcapital|mgp|json|csv  -> the per-property Fact Sheet mapping
                                                   (field names each platform uses for property value, equity, net rental income, mortgage liability)
GET  /households/{id}/alerts                  -> monitoring stubs computed from loans/values (roadmap item)
POST /simulate                                -> the "buy/sell over time" simulation engine: body {start_year, years, properties:[...],
                                                   events:[{year, type: buy|sell|exchange|refi, ...}], assumptions, monte_carlo:{runs, appr_sigma, rent_sigma}}
                                                   -> yearly series + percentile bands (p10/p50/p90) for net worth, cash flow, taxes paid
GET  /eval/latest                             -> last pipeline eval summary (reads fixtures/documents/eval-latest.json if present)
```
Errors: RFC 7807 problem+json. Pagination not needed. Auth: a single dev advisor; `X-Advisor-Id` header optional;
every query filters by advisor_id (demonstrate tenant isolation with a test).

## 4. Document pipeline (Agent B, package `gp_pipeline`, zero network, zero paid APIs)

4.1 **Synthetic document generator** (`gp_pipeline/synth/`): `python -m gp_pipeline.synth --out fixtures/documents`
creates a realistic demo household, **"the Okafor-Lindqvist household"** (MFJ, California, MAGI ~$186k, goal: "retire in
7 years, stop managing property") with 3 tax years (2023, 2024, 2025) and these properties, each with deliberate
real-world mess:
  P1 "Maple duplex" (multifamily, 2 units, Sacramento): bought 2012, fixed 30-yr loan, solid cash flow, big accumulated
     depreciation. Address printed THREE different ways across years ("1420 Maple St", "1420 MAPLE STREET UNIT A/B", "1420 Maple St.").
  P2 "Tahoe cabin" (vacation_str, avg stay 4 nights): personal-use days on line 2; triggers the STR unsupported finding.
  P3 "Elm SFR" (sfr, Roseville): interest-only 7/1 ARM resetting 2027; depreciation on the 2024 return is 12% LOWER than
     allowable (preparer error) -> outlier finding; appears first in 2024 (bought Jun 2024, partial-year depreciation).
  P4 "Oak condo" (sfr/condo): present in 2023 and 2024, ABSENT in 2025 -> finding "property missing from latest return: sold?
     converted?"; also carries a HELOC second lien and a paid-off first.
  Household: Form 8582 shows a $14,200 suspended loss carryforward in 2025.
Documents per year: Form 1040 pages 1-2 (filing status, wages line 1a, line 11 AGI, line 15 taxable income — rest filled
with plausible numbers), Schedule E Part I (full line structure 1a..26 with columns A/B/C and a second page when >3
properties), Form 4562 Part III (MACRS, 27.5 SL/MM lines), Form 8582 Part I/II. Plus non-tax docs: one mortgage statement
per active loan (lender name, balance, rate, payment, next reset for the ARM, IO period end), one closing statement for P3
(purchase price, closing costs, land/improvement split absent), one appraisal letter for P1. Render with reportlab in a
layout that resembles the IRS forms (line numbers on the left, labels, values right-aligned in boxes) — it need not be
pixel-identical, but the *line numbers and labels must be the real ones* from the 2024/2025 IRS forms. Produce each PDF
in two variants: `*.pdf` (text layer) and `*.scan.pdf` (rasterized at 150 dpi via pdftoppm, rotated 0.7°, JPEG q=60,
re-wrapped as PDF) to exercise OCR. Write `gold.json` with every field value, page and property key.

4.2 **Extraction** (`gp_pipeline/extract/`):
  - `classify.py`: form-type + tax-year classifier (regex/anchor based on text; OCR text when no text layer).
  - `text.py`: pdfplumber words with coordinates; fallback `ocr.py` via `pytesseract` (tesseract is installed at
    /opt/homebrew/bin/tesseract; poppler's pdftoppm also installed) returning words with bboxes.
  - `forms/schedule_e.py`, `forms/form_1040.py`, `forms/form_4562.py`, `forms/form_8582.py`, `forms/mortgage_statement.py`,
    `forms/closing_statement.py`: anchor/layout extractors producing `ExtractedField`s with page+bbox+confidence.
  - `llm.py`: `Extractor` protocol; `RulesExtractor` (default). `LLMExtractor` (optional; same interface; provider
    `anthropic` or `bedrock` via env; off by default; never used in tests) and `CrossCheckExtractor` that runs both and
    turns disagreements into Findings. Document the prompt and the JSON schema it must return.
4.3 **Entity resolution** (`resolve.py`): normalize addresses (usaddress-style normalization implemented by hand: case,
  punctuation, street suffix abbreviations, unit tokens), fuzzy match (token set ratio ≥ 0.85) across years/documents, with
  property_type code as a tiebreaker; emit a `PropertyMatch` with confidence and the alternative candidates.
4.4 **Reconciliation** (`reconcile.py`): for every (property, field) across sources: agree → confirmed; conflict →
  Finding(conflict) with candidates (never averaged); missing in latest year → Finding; depreciation vs allowable → outlier;
  loan balance on statement vs implied by amortization → conflict if > 2%; STR → unsupported_structure. Output a
  `ReconciledHousehold` JSON that maps 1:1 onto the §1 domain model so Agent A's import endpoint can load it.
4.5 **Eval harness** (`gp_pipeline/eval/`): `python -m gp_pipeline.eval --docs fixtures/documents --out fixtures/documents/eval-latest.json`
  computes per-form, per-field precision/recall/exact-match for text-layer and scan variants, entity-resolution accuracy,
  finding recall (did we raise the 4 planted findings?), and a confusion table; prints a markdown table and writes JSON.
  Include a `--noise` option (dpi 100, rotation 2°, jpeg 35) to show degradation. The README states the numbers honestly.
4.6 CLI: `gp-pipeline run <pdf...> --out reconciled.json`, `gp-pipeline synth`, `gp-pipeline eval`.

## 5. Frontend (Agent C, `web/`): React 18 + TS + Vite + Tailwind + Recharts + react-router + TanStack Query.
Look: calm fintech, light theme, dense tables, monospace numbers, green/red only for sign, a visible **Confirmed /
Estimated / Blocked** chip on every figure, no "recommended" anywhere. Phone-usable but desktop-first. Pages:
  1. `/` Households list (metrics, open findings badge).
  2. `/households/:id` Portfolio dashboard: key observations first, then top metrics, then one card per property
     (value, equity, net cash flow, exit tax, ROE, status chips), narrative panel (shows provider = template/llm),
     "Generate report (PDF)" button, Alerts strip.
  3. `/properties/:id` Property analysis: assumptions panel (every edit re-queries and recomputes live), tabs Cash flow
     (with the Schedule E → cash-flow bridge), Equity & lendable equity, Appreciation, Depreciation (schedule table + chart),
     Exit tax (stacked bar of 1250 / LTCG / NIIT / state with the bracket-stacking explanation), Loans (schedule, IO/ARM
     markers). Clicking ANY number opens the **Traceability drawer** (Figure → inputs tree → source document/page/bbox or
     manual/default; formula text).
  4. `/properties/:id/strategies` Hold vs Sell vs 1031: three columns, horizon slider, shared assumptions (one edit
     updates all three), charts (wealth over time, cumulative cash flow, deferred tax growing), the leads/trails/neutral
     matrix, caveats, DST toggle with load and yield, boot calculator (cash + mortgage boot), "what the proceeds do".
  5. `/households/:id/documents` Upload (drag/drop PDFs), per-document extracted fields with page thumbnails + bbox
     overlays (render PDF pages client-side with pdf.js from the upload buffer only; server never returns the file),
     **Reconciliation queue**: open findings with candidates side by side, Resolve/Dismiss, and the rule that blocked
     figures stay blocked until resolved.
  6. `/households/:id/reports` Report preview + Fact Sheets (eMoney / RightCapital / MoneyGuidePro tabs showing the
     exact field mapping), JSON/CSV export.
  7. `/simulate` Simulation playground (the "buy/sell over time with visualization" ask): timeline editor of buy/sell/
     exchange/refi events, assumptions, Monte Carlo bands chart, taxes-paid chart, equity vs debt area chart.
  8. `/eval` Pipeline eval dashboard reading /eval/latest (precision/recall tables, scan vs text).
Use the exact TS types from §1/§3 in `web/src/api/types.ts`. Mock server (msw or a static JSON mode `VITE_MOCK=1`) so the
UI runs before the API exists; switch to live API by default. Vitest + a few component tests. `npm run dev` on :5173
proxying `/api` to :8000.

## 6. Go port (Agent D, later, `engine-go/`): `module groundplan/engine`, packages mirroring §2.1-2.9, `go test ./...`
loads `../fixtures/engine/*.json` and asserts byte-equal cents. Use `math/big` or `shopspring/decimal`-free integer-cents
arithmetic with explicit rounding identical to Python's (document the rounding rule in both). Provide a tiny HTTP
service (`cmd/engine-server`, stdlib net/http) exposing POST /analyze and POST /strategies with the same JSON as §3 so
the FastAPI app can proxy to it behind a flag `GP_ENGINE=go|python` — the Python-to-Go migration path, demonstrated.

## 7. Quality bar
- `make test` green (pytest for both packages, vitest, go test). Golden fixtures cover: depreciation table by month
  (12 cases + year 28), IO/ARM/HELOC/balloon schedules, cash flow bridge, passive-loss phaseout at MAGI 100k/130k/140k/150k,
  exit tax stacking at 3 income levels (one where 1250 lands under 25%), NIIT threshold edge, 1031 with full/partial
  mortgage boot, DST load, suspended loss release vs not, Section 121 on a converted residence.
- Worked examples from the target company's public docs must reproduce: (a) duplex: rents 48,000; opex 18,000;
  interest 9,000; depreciation 9,000 → line21 12,000; principal 6,000 → cash flow 15,000. (b) SFR: 30,000 / 12,000 /
  14,000 / 12,000 → line21 −8,000; principal 4,000 → cash flow 0. (c) MAGI 130k → allowance 10,000; 140k → 5,000;
  150k → 0. (d) $400k bought 2011, basis 280k → ≈$10,180/yr, ≈$145k accumulated by end 2025 (table mode gets close;
  simple mode exact: 280000/27.5 = 10181.82 × 14.25 ≈ 145k — document which).
- README per package: how to run, how it is structured, the trade-offs, what is stubbed, what you would do next.
- No secrets in the repo. No network in tests. `ruff` clean. Commit early and often as `Levelbrook Consulting`.

## 8. Public twin deploy (added 2026-10-23): one product, two backends, two front ends, no logins

Goal: the same product running twice, end to end, so a reviewer can click both and see identical numbers:
- **Python stack**: React front end at `https://gp-python.levelbrook.com` (Cloudflare Pages project `gp-python`)
  → API `https://gp-python-api.levelbrook.com` (FastAPI container `gp-python-api` on Box B).
- **Go stack**: React front end at `https://gp-go.levelbrook.com` (Pages project `gp-go`)
  → API `https://gp-go-api.levelbrook.com` (Go container `gp-go-api` on Box B).
- **Document pipeline** stays Python (OCR/ML lives in Python at most shops that move the core API to Go): internal
  container `gp-pipeline` on the docker network `kamal`, no public route, `POST http://gp-pipeline:8090/extract`
  (multipart `file`, form `household_hint` optional) → `{document, extracted_fields, findings, properties_touched, reconciled}`
  exactly the shape §3 `POST /households/{id}/documents` returns minus DB ids. Both APIs call it over HTTP
  (`GP_PIPELINE_URL`); locally the Python API falls back to calling `gp_pipeline` in-process when the URL is unset.
- Same Postgres 17 server (`lb-postgres`), separate databases `groundplan_py` and `groundplan_go`, role `groundplan`.
  **Alembic is the single schema source of truth**: the Go service ships the Alembic-generated SQL (`engine-go/migrations/*.sql`,
  produced with `alembic upgrade head --sql`) and refuses to start if `alembic_version` does not match.

### 8.1 Tenancy without logins: workspaces
- The front end creates a random UUIDv4 on first load, stores it in `localStorage["gp.workspace"]`, and sends it on every
  request as header **`X-Workspace-Id`**. The workspace id IS the tenant (`advisor_id`); every query is filtered by it
  (that is the "tenant isolation at the DB layer" story, now load-bearing).
- First request with an unknown workspace id → the API provisions an advisor row (firm "Demo workspace") and **seeds the demo
  household(s)** for it (same seed as `scripts.seed`), in one transaction, idempotent under concurrent first requests
  (unique constraint + ON CONFLICT). Missing/invalid header → 400 problem+json (except `/health`, `/meta`, `/eval/latest`).
- Abuse guards: max 30 new workspaces per client IP per day (IP from `X-Forwarded-For` first hop / `CF-Connecting-IP`),
  max 20 households and 50 documents per workspace, upload max 15 MB, request body max 20 MB. 429 problem+json when exceeded.
- `POST /api/v1/workspace/reset` → deletes the workspace's data and re-seeds. `GET /api/v1/workspace` →
  `{id, created_at, households, documents}`.
- Housekeeping: workspaces idle > 14 days are deleted by a startup + every-6-hours sweep (`last_seen_at` column).
- CORS: allow origins `https://gp-python.levelbrook.com`, `https://gp-go.levelbrook.com`, `http://localhost:5173`,
  `http://localhost:4173`, any `https://*.gp-python.pages.dev` / `*.gp-go.pages.dev`; allow header `X-Workspace-Id`, `Content-Type`.
  (The front ends also proxy `/api/*` same-origin through a Pages Function, so CORS is the fallback, not the main path.)

### 8.2 `GET /api/v1/meta` (both backends, no workspace needed)
`{"backend": "python"|"go", "version": "<git sha>", "engine": "python"|"go", "runtime": "CPython 3.12.x"|"go1.26.x",
  "started_at": ISO8601, "db": "postgres 17"}`. The front end shows this in a footer badge and links to the twin stack.

### 8.3 Parity contract
- The FastAPI OpenAPI document (`backend/openapi.json`, regenerated by `make openapi`) is THE contract. The Go server must
  serve every path in it with JSON that validates against it; `scripts/parity.py <base_a> <base_b>` walks every GET for a fresh
  workspace on both, runs the same mutations, and diffs the JSON (ignoring ids/timestamps). Cents must be byte-identical.
- No field named `recommended` anywhere in any response (test asserts it on both backends).
