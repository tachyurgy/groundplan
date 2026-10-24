# gp_pipeline: Groundplan document pipeline

Python 3.12 · reportlab · pdfplumber (pdfium) · tesseract via pytesseract · numpy · pydantic. Zero network, zero paid APIs.

```
PDF bytes ─► text layer? ─ yes ─► pdfplumber words + bboxes ─┐
              │ no                                            ├─► classify (form + tax year) ─► form extractor ─► ExtractedField[]
              └─► pdfium raster 300 dpi ─► deskew ─► tesseract┘        (anchor lines / zonal re-OCR / key-value)
ExtractedField[] (all docs) ─► resolve.py (address normalize + fuzzy cluster) ─► reconcile.py (rules) ─► ReconciledHousehold + Finding[]
```

## Run it

```bash
make synth                    # python -m gp_pipeline.synth --out ../fixtures/documents   (~10 s, 26 docs x 2 variants, 4.1 MB)
make pipeline-eval            # python -m gp_pipeline.eval --docs ../fixtures/documents --out ../fixtures/documents/eval-latest.json
uv run python -m gp_pipeline.eval --docs ../fixtures/documents --noise   # add the harsher scan variant (temp files, deleted)
uv run gp-pipeline run ../fixtures/documents/2025_*.pdf --out /tmp/reconciled.json
make pipeline-service         # the internal HTTP service on :8090 (POST /extract, GET /health)
make test-pipeline            # pytest (OCR tests use the real tesseract; skipped if it is not installed)
```

## Layout

```
gp_pipeline/
  synth/        household.py (the Okafor-Lindqvist facts + planted mess), render.py (1040, Sch E, 4562, 8582, statements,
                closing statement, appraisal; real IRS line numbers + labels), scan.py (150 dpi, 0.7 deg, JPEG q60), generate.py
  extract/      text.py (pdfplumber), ocr.py (pdfium raster, projection-profile deskew, rule removal, tesseract psm 11),
                zones.py (zonal re-OCR of value cells), classify.py, layout.py, forms/*.py (one extractor per form),
                llm.py (Extractor protocol: RulesExtractor default, LLMExtractor + CrossCheckExtractor opt-in)
  address.py    hand-rolled usaddress-style normalization + token-set similarity with house-number/ZIP/unit vetoes
  resolve.py    entity resolution: greedy clustering, Schedule E as the spine, type code as tie-breaker
  reconcile.py  the rule table (below) -> ReconciledHousehold (maps 1:1 onto SPEC §1) + Finding[]
  run.py        orchestration; api.py = process_document() (what both backends call); service.py = the HTTP service
  eval/         scoring against gold.json; cli.py = `gp-pipeline run|synth|eval`
```

## One household, two consumers

`python -m gp_pipeline.synth` also writes `fixtures/seed/okafor-lindqvist.json` (`synth/seed_export.py`), the backend's
demo seed, from the same facts that render the PDFs: same normalized address keys (Maple's three spellings all
resolve to `1420 maple st, sacramento, ca 95838`), same tax years, same line values, same loans. The single planted
difference is the Maple 2025 rent roll ($1,600 under Schedule E line 3), which becomes the blocking conflict when the
2025 return is uploaded. `tests/test_seed_matches_documents.py` runs the pipeline over the documents and asserts it
reconciles onto the seed with only that gap. Six of the PDFs are copied to `web/public/samples/` (+ `index.json`) so
a visitor can try an upload.

## Reconciliation rules (reconcile.py)

| finding | kind | rule |
|---|---|---|
| `str:` | unsupported_structure | Schedule E line 1b type 3 (vacation / short-term rental): STR rules not modeled |
| `missing_latest:` | missing | property on an earlier Schedule E, absent from the latest: sold? converted? |
| `dep_outlier:` | outlier | line 18 vs MACRS 27.5 SL/MM allowable (Form 4562 line 19h basis + placed in service), > 5% |
| `dep_4562:` | conflict | Schedule E line 18 != Form 4562 line 22 for the same property-year |
| `missing_land_split:` | missing | closing statement shows the price but no land / improvement allocation |
| `conflict:..:mortgage_interest` | conflict | line 12 vs the sum of the lenders' YTD interest (only when every live loan has a statement), > $100 and > 1%; block above 10% |
| `conflict:..:loan_balance` | conflict | statement balance vs the amortization implied by its own terms, > 2% (fixed loans) |
| `low_conf:` | conflict (info) | an OCR money value whose form arithmetic failed (confidence < 0.6) |

Conflicts are never averaged: both candidates travel with the Finding and the backend keeps the figure blocked/flagged
until an advisor picks one.

## Eval (fixtures/documents/eval-latest.json, 2026-10-23, 26 documents, 419 gold fields)

| metric | text layer | scan (150 dpi, 0.7°, q60) | noise (100 dpi, 2°, q35) |
|---|---|---|---|
| field precision | 100.0% | 99.8% | 47.0% |
| field recall | 100.0% | 100.0% | 24.6% |
| document exact match | 100.0% | 100.0% | 0.0% |
| form classification | 100.0% | 100.0% | 80.8% (all 5 statements -> other) |
| entity resolution (address mentions) | 100.0% | 100.0% | 21.9% (10 clusters for 4 properties) |
| planted findings | 5/5 | 5/5 | 1/5 |
| extra non-info findings | 0 | 0 | 5 |
| wall time (M-series Mac) | 1.3 s | 73 s | 81 s |

**Read these numbers honestly.** The documents are synthetic and the extractors were developed against this renderer,
so the text-layer 100% says the anchors and arithmetic are right for this layout, not that the pipeline reads any
preparer's PDF. Real returns come from dozens of tax packages with different fonts, column positions and continuation
statements; expect the text-layer number to drop until each layout gets its anchors. The scan result (one spurious
field, 16 info-level low-confidence notes) is the more meaningful one: it shows deskew + zonal re-OCR + arithmetic
self-checks recovering clean scans. The noise variant is where it breaks: at 100 dpi tesseract misreads digits and
house numbers ("915 Dak Hollow"), resolution fragments, and the mortgage-statement classifier loses its "Loan Number"
anchor. Next steps there: per-form OCR at a higher upsample with a digit-only LSTM pass, fuzzy anchors in the
classifier, and the CrossCheckExtractor (LLM second opinion -> Findings, never silent overrides) on low-confidence docs.

## The HTTP service (SPEC §8)

`uvicorn gp_pipeline.service:app --port 8090`. `POST /extract` (multipart `file`, optional form `household_hint` JSON
with `property_keys`, `state`, `tax_year_latest`) returns `{document, extracted_fields, findings, properties_touched,
reconciled}`: SPEC §3's upload response minus DB ids. 15 MB cap (413), non-PDF 415, unreadable PDF 422. It has no
database and no public route; both API backends call it at `http://gp-pipeline:8090` (`GP_PIPELINE_URL`). The Python
API falls back to importing `gp_pipeline.api.process_document` in-process when the URL is unset. Bytes are processed
in memory and dropped; OCR rasters are released before the response is built.

Single-document semantics: an upload is reconciled on its own. Household facts a document cannot establish
(participation, goal, name) are never sent, an older return cannot roll `tax_year_latest` back, and a printed address
that matches one of the household's existing `property_keys` (similarity >= 0.85) is filed under that key. Cross-
document rules (missing-from-latest, line 12 vs statements) need the documents together: `gp-pipeline run` or
`import-reconciled`.

## Stubbed / not done

* `LLMExtractor` is wired (prompt + JSON schema in `extract/llm.py`) but off; nothing in tests or the deployed service
  calls a paid API. Enabling it needs `GP_LLM_EXTRACT=1` and a provider.
* Leases and other free-form documents are classified `other` and not extracted.
* Short-term-rental average stay is not on the return; the STR rule uses the type-3 code.
