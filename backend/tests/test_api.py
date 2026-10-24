import hashlib
import json
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from groundplan.db import base
from groundplan.db.base import Base
from tests.conftest import OTHER_ADVISOR

API = "/api/v1"
OTHER = {"X-Workspace-Id": OTHER_ADVISOR}


def _hid(client):
    return client.get(f"{API}/households").json()[0]["id"]


def _prop(client, hid, nickname):
    d = client.get(f"{API}/households/{hid}/dashboard").json()
    for c in d["properties"]:
        if c["property"]["nickname"] == nickname:
            return c
    raise AssertionError(nickname)


def test_migration_matches_models(db_session_factory):
    with base.engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_health_and_openapi(client):
    assert client.get(f"{API}/health").json()["status"] == "ok"
    assert "/api/v1/properties/{property_id}/strategies" in client.get("/openapi.json").json()["paths"]


def test_households_list_shape(client):
    rows = client.get(f"{API}/households").json()
    assert len(rows) == 1
    h = rows[0]
    assert h["name"] == "Okafor-Lindqvist household" and h["property_count"] == 4
    assert set(h) >= {"id", "name", "state", "filing_status", "property_count", "net_cash_flow_cents", "total_equity_cents",
                      "open_findings", "status"}
    assert h["status"] == "estimated"  # nothing blocks until a document disagrees (see test_upload::test_money_moment)


def test_tenant_isolation(client):
    hid = _hid(client)
    pid = _prop(client, hid, "Maple duplex")["property"]["id"]
    assert client.get(f"{API}/households", headers=OTHER).json() == []
    for url in (f"/households/{hid}", f"/households/{hid}/dashboard", f"/properties/{pid}", f"/properties/{pid}/analysis",
                f"/properties/{pid}/strategies", f"/households/{hid}/findings", f"/households/{hid}/report.pdf"):
        r = client.get(API + url, headers=OTHER)
        assert r.status_code == 404, url
        assert r.headers["content-type"].startswith("application/problem+json")
    assert client.patch(f"{API}/households/{hid}", json={"name": "pwned"}, headers=OTHER).status_code == 404
    assert client.delete(f"{API}/properties/{pid}", headers=OTHER).status_code == 404
    assert client.get(f"{API}/households/{hid}").json()["name"] == "Okafor-Lindqvist household"


def test_dashboard(client):
    d = client.get(f"{API}/households/{_hid(client)}/dashboard").json()
    assert d["findings_open"] == 4
    assert d["narrative"]["provider"] == "template"
    assert {"total_value", "total_equity", "net_cash_flow", "exit_tax_total"} <= set(d["metrics"])
    rules = {o["rule"] for o in d["observations"]}
    assert {"str_flagged", "arm_reset", "io_ending", "depreciation_gap", "suspended_losses", "magi_phaseout"} <= rules
    assert "recommend" not in json.dumps(d).lower()


def test_analysis_overrides_and_trace(client):
    hid = _hid(client)
    pid = _prop(client, hid, "Elm SFR")["property"]["id"]
    base_an = client.get(f"{API}/properties/{pid}/analysis").json()
    assert base_an["depreciation"]["outlier"] is True
    assert {"cash_flow", "equity", "appreciation", "depreciation", "exit_tax", "loans", "observations", "property"} <= set(base_an)
    hi = client.get(f"{API}/properties/{pid}/analysis", params={"current_value_cents": 70_000_000, "arm_index": "0.06"}).json()
    assert hi["equity"]["value"]["value_cents"] == 70_000_000
    assert hi["exit_tax"]["exit_tax_total"]["value_cents"] > base_an["exit_tax"]["exit_tax_total"]["value_cents"]
    fig = client.get(f"{API}/properties/{pid}/figure/exit_tax.total").json()
    assert fig["key"] == "exit_tax.total"
    # the full inputs tree reaches the leaves
    def depth(f):
        kids = [i["figure"] for i in f["inputs"] if "figure" in i]
        return 1 + max((depth(k) for k in kids), default=0)
    assert depth(fig) >= 4
    assert client.get(f"{API}/properties/{pid}/analysis", params={"appreciation_rate": "abc"}).status_code == 422


def test_blocked_until_resolved_then_value_written_back(client):
    """A document that disagrees with the rent roll on file raises a blocking conflict (never averaged, never
    overwritten); resolving it writes the chosen value back and the figure is no longer blocked."""
    hid = _hid(client)
    maple = _prop(client, hid, "Maple duplex")
    pid, key = maple["property"]["id"], maple["property"]["property_key"]
    assert maple["net_cash_flow"]["status"] == "confirmed"
    on_file = client.get(f"{API}/properties/{pid}/analysis").json()["cash_flow"]["gross_rent"]["value_cents"]
    payload = {"schema_version": "1.0", "generated_at": "2026-01-15T00:00:00Z", "household": {"name": ""},
               "properties": [{"key": key, "nickname": "1420 Maple St", "years_seen": [2025],
                               "rent_rolls": [{"tax_year": 2025, "gross_rent_cents": on_file + 160_000}]}]}
    r = client.post(f"{API}/households/{hid}/import-reconciled", json=payload).json()
    assert r["stats"]["properties_created"] == 0 and r["stats"]["conflicts_raised"] == 1
    after = _prop(client, hid, "Maple duplex")
    assert after["property"]["nickname"] == "Maple duplex"  # a document never renames a property
    assert after["net_cash_flow"]["status"] == "blocked"
    strat = client.get(f"{API}/properties/{pid}/strategies").json()
    assert all(p["terminal"]["terminal_wealth"]["status"] == "blocked" for p in strat["paths"])
    f = next(x for x in client.get(f"{API}/households/{hid}/findings", params={"status": "open"}).json() if x["severity"] == "block")
    assert {c["value"] for c in f["candidates"]} == {on_file, on_file + 160_000}
    # the rent roll value is untouched until the advisor decides
    assert client.get(f"{API}/properties/{pid}/analysis").json()["cash_flow"]["gross_rent"]["value_cents"] == on_file
    r = client.post(f"{API}/findings/{f['id']}/resolve", json={"value": on_file + 160_000, "note": "the return is right"})
    assert r.status_code == 200 and r.json()["resolution"]["applied_to"] == "rent_rolls[2025].gross_rent_cents"
    assert _prop(client, hid, "Maple duplex")["net_cash_flow"]["status"] == "confirmed"
    an = client.get(f"{API}/properties/{pid}/analysis").json()
    assert an["cash_flow"]["gross_rent"]["value_cents"] == on_file + 160_000
    # re-importing the same document does not re-open the decided conflict
    r = client.post(f"{API}/households/{hid}/import-reconciled", json=payload).json()
    assert r["stats"]["conflicts_raised"] == 0


def test_strategies_shape_and_dst(client):
    pid = _prop(client, _hid(client), "Oak condo")["property"]["id"]
    r = client.get(f"{API}/properties/{pid}/strategies", params={"horizon": 7, "dst": "true", "load_rate": "0.085",
                                                                  "replacement_debt_cents": 0, "cash_taken_cents": 1_000_000}).json()
    assert [p["path"] for p in r["paths"]] == ["hold", "sell", "exchange"]
    assert all(len(p["series"]) == 7 for p in r["paths"])
    ex = r["paths"][2]
    assert ex["boot"]["mortgage_boot"]["value_cents"] > 0  # HELOC paid off, no replacement debt
    assert ex["terminal"]["deferred_liability"]["value_cents"] > 0
    assert "recommended" not in r and set(r["caveats"]) == {"hold", "sell", "exchange"}
    # estimated value -> no strategy figure may claim confirmed
    assert all(p["terminal"]["terminal_wealth"]["status"] != "confirmed" for p in r["paths"])


def test_crud_property_loan_year_scenario(client):
    hid = _hid(client)
    p = client.post(f"{API}/households/{hid}/properties", json={"nickname": "Test fourplex", "property_type": "multifamily", "units": 4,
                                                               "purchase_date": "2020-02-01", "purchase_price_cents": 90_000_000,
                                                               "current_value_cents": 105_000_000, "land_pct": 0.3}).json()
    ln = client.post(f"{API}/properties/{p['id']}/loans", json={"lender": "Bank", "balance_cents": 60_000_000,
                                                               "balance_as_of": "2025-12-31", "rate": 0.055, "term_months": 300}).json()
    assert client.patch(f"{API}/loans/{ln['id']}", json={"rate": 0.06}).json()["rate"] == 0.06
    y = client.put(f"{API}/properties/{p['id']}/years/2025", json={"gross_rent_cents": 9_600_000, "taxes_cents": 1_100_000,
                                                                   "mortgage_interest_cents": 3_300_000}).json()
    assert y["gross_rent_cents"] == 9_600_000
    an = client.get(f"{API}/properties/{p['id']}/analysis").json()
    assert an["cash_flow"]["gross_rent"]["value_cents"] == 9_600_000
    sc = client.post(f"{API}/properties/{p['id']}/scenarios", json={"name": "base", "horizon_years": 5, "assumptions": {"reinvest_rate": 0.05}})
    assert sc.status_code == 201 and sc.json()["results"]["horizon_years"] == 5
    assert client.get(f"{API}/scenarios/{sc.json()['id']}").status_code == 200
    assert client.patch(f"{API}/properties/{p['id']}", json={"bogus": 1}).status_code == 422
    assert client.delete(f"{API}/loans/{ln['id']}").status_code == 204
    assert client.delete(f"{API}/properties/{p['id']}").status_code == 204
    assert client.get(f"{API}/properties/{p['id']}").status_code == 404


def test_upload_without_pipeline_is_503_and_nothing_stored(client, monkeypatch):
    from groundplan.api.routers import documents
    from groundplan.services.pipeline_adapter import PipelineUnavailable

    def unavailable():
        raise PipelineUnavailable("no pipeline in this test")

    monkeypatch.setattr(documents, "load_processor", unavailable)
    hid = _hid(client)
    r = client.post(f"{API}/households/{hid}/documents", files={"file": ("sched_e.pdf", b"%PDF-1.7 fake", "application/pdf")})
    assert r.status_code == 503
    body = r.json()
    assert body["sha256"] == hashlib.sha256(b"%PDF-1.7 fake").hexdigest()
    assert body["bytes_retained"] is False
    assert client.get(f"{API}/households/{hid}/documents").json() == []


def test_import_reconciled_idempotent(client):
    hid = _hid(client)
    payload = {
        "schema_version": "1.0", "generated_at": "2026-01-15T00:00:00Z",
        "household": {"name": "x", "filing_status": "mfj", "state": "CA", "tax_year_latest": 2025, "wages_cents": 17_180_000,
                      "magi_cents": 18_640_000},
        "properties": [{"key": "1420 maple st sacramento ca 95816", "nickname": "Maple duplex", "address_line1": "1420 Maple St",
                        "city": "Sacramento", "state": "CA", "zip": "95816", "property_type": "multifamily", "units": 2,
                        "rent_rolls": [{"tax_year": 2025, "gross_rent_cents": 5_160_000}],
                        "expense_years": [{"tax_year": 2025, "taxes_cents": 393_000, "depreciation_cents": 860_400}]},
                       {"key": "9 new rd woodland ca 95695", "nickname": "Woodland SFR", "address_line1": "9 New Rd", "city": "Woodland",
                        "state": "CA", "zip": "95695", "property_type": "sfr", "purchase_date": "2021-04-01",
                        "purchase_price_cents": 55_000_000, "depreciable_basis_cents": 38_500_000, "current_value_cents": 60_000_000,
                        "loans": [{"key": "l1", "lender": "Chase", "loan_type": "fixed", "balance_cents": 40_000_000,
                                   "balance_as_of": "2025-12-31", "rate": 0.031, "maturity_date": "2051-05-01", "lien_position": 1}]}],
        "suspended_losses": [{"tax_year": 2025, "carryforward_cents": 1_420_000}],
        "documents": [{"key": "2025_schedule_e.pdf", "kind": "schedule_e", "tax_year": 2025, "filename": "2025_schedule_e.pdf",
                       "sha256": "ab" * 32, "page_count": 2}],
        "extracted_fields": [{"document_key": "2025_schedule_e.pdf", "entity_hint": "property",
                              "property_key": "1420 maple st sacramento ca 95816", "field": "schedule_e.line3.rents",
                              "value": 5_160_000, "unit": "cents", "page": 1, "bbox": [400, 500, 480, 512], "confidence": 0.98,
                              "extractor": "rules", "raw_text": "51,600"}],
        "findings": [{"key": "missing:woodland", "kind": "missing", "field": "form_1098", "severity": "info", "message": "no 1098",
                      "property_key": "9 new rd woodland ca 95695", "candidates": [{"source": "x", "value": None,
                                                                                 "document_key": "2025_schedule_e.pdf", "page": 1}]}],
    }
    r1 = client.post(f"{API}/households/{hid}/import-reconciled", json=payload)
    assert r1.status_code == 200, r1.text
    assert r1.json()["stats"]["properties_created"] == 1
    r2 = client.post(f"{API}/households/{hid}/import-reconciled", json=payload).json()
    assert r2["stats"]["properties_created"] == 0 and r2["stats"]["findings_created"] == 0
    assert len([p for p in r2["properties"] if p["nickname"] == "Woodland SFR"]) == 1
    wl = next(p for p in r2["properties"] if p["nickname"] == "Woodland SFR")
    assert abs(wl["land_pct"] - 0.3) < 1e-6
    docs = client.get(f"{API}/households/{hid}/documents").json()
    assert len(docs) == 1 and docs[0]["bytes_retained"] is False
    # document provenance flows into the Figure source
    maple = _prop(client, hid, "Maple duplex")["property"]["id"]
    an = client.get(f"{API}/properties/{maple}/analysis").json()
    src = an["cash_flow"]["gross_rent"]["inputs"][0]["source"]
    assert src["type"] == "document" and src["document_id"] == docs[0]["id"] and src["page"] == 1 and src["bbox"] == [400, 500, 480, 512]
    assert client.post(f"{API}/households/{hid}/import-reconciled", json={"nope": 1}).status_code == 422


def test_report_factsheet_alerts_simulate(client):
    hid = _hid(client)
    pdf = client.get(f"{API}/households/{hid}/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-" and len(pdf.content) > 5000
    pid = _prop(client, hid, "Maple duplex")["property"]["id"]
    for fmt, label in (("emoney", "Real Estate Asset: Market Value"), ("rightcapital", "Property: Current Value"),
                       ("mgp", "Asset Type: Real Estate - Value")):
        sheet = client.get(f"{API}/properties/{pid}/factsheet", params={"format": fmt}).json()
        assert label in [r["platform_field"] for r in sheet["rows"]]
        assert "best-effort" in sheet["platform_label"]
    csv = client.get(f"{API}/properties/{pid}/factsheet", params={"format": "csv"})
    assert csv.headers["content-type"].startswith("text/csv") and "groundplan_key" in csv.text
    kinds = {a["kind"] for a in client.get(f"{API}/households/{hid}/alerts").json()}
    assert {"arm_reset", "io_period_ending", "value_drift"} <= kinds
    body = {"household_id": hid, "start_year": 2026, "years": 6,
            "events": [{"year": 2027, "type": "sell", "property_ref": "Tahoe cabin"},
                       {"year": 2028, "type": "buy", "property_ref": "New SFR", "amount_cents": 60_000_000, "debt_cents": 42_000_000}],
            "monte_carlo": {"runs": 60, "appr_sigma": 0.06, "rent_sigma": 0.02, "seed": 11}}
    a = client.post(f"{API}/simulate", json=body).json()
    b = client.post(f"{API}/simulate", json=body).json()
    assert a == b and a["runs"] == 60 and len(a["series"]) == 6
    s0 = a["series"][1]
    assert s0["net_worth"]["p10"] <= s0["net_worth"]["p50"] <= s0["net_worth"]["p90"]
    assert a["series"][1]["taxes_paid"]["p50"] > 0
    assert a["terminal"]["cumulative_taxes"]["p50"] > 0


def test_eval_latest_404_problem_when_missing(client):
    p = Path(__file__).resolve().parents[2] / "fixtures" / "documents" / "eval-latest.json"
    r = client.get(f"{API}/eval/latest")
    assert r.status_code == (200 if p.exists() else 404)
