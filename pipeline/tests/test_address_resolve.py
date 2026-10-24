from gp_pipeline.address import key, normalize, similarity
from gp_pipeline.models import ExtractedField
from gp_pipeline.resolve import resolve


def test_three_spellings_one_key():
    ks = {key(a) for a in ("1420 Maple St, Sacramento, CA 95838", "1420 MAPLE STREET UNIT A/B, SACRAMENTO, CA 95838",
                           "1420 Maple St., Sacramento, CA 95838")}
    assert ks == {"1420 maple st, sacramento, ca 95838"}


def test_single_unit_is_kept_and_vetoes():
    a, b = normalize("915 Oak Hollow Way Unit 204, Elk Grove, CA 95758"), normalize("915 Oak Hollow Way Unit 205, Elk Grove, CA 95758")
    assert a.key() == "915 oak hollow way unit 204, elk grove, ca 95758"
    assert similarity(a, b) == 0.0
    assert similarity(normalize("12 Elm Ct, Roseville, CA 95661"), normalize("14 Elm Ct, Roseville, CA 95661")) == 0.0


def _f(addr, kind="schedule_e", year=2025, doc="d.pdf"):
    return ExtractedField(document_key=doc, document_kind=kind, tax_year=year, entity_hint="property", property_key=key(addr),
                          address_raw=addr, field="schedule_e.line1a.address", value=addr, unit="text", page=1, confidence=1,
                          extractor="rules")


def test_resolution_clusters_variants_across_documents():
    fields = [_f("1420 Maple St, Sacramento, CA 95838", year=2023, doc="a"), _f("1420 MAPLE STREET UNIT A/B, SACRAMENTO, CA 95838", year=2024, doc="b"),
              _f("1420 Maple Street, Sacramento, CA 95838", kind="appraisal", doc="c"), _f("2875 Elm Ct, Roseville, CA 95661", doc="d")]
    matches, canon = resolve(fields)
    assert len(canon) == 2
    assert len({m.property_key for m in matches.values() if "maple" in m.raw_address.lower()}) == 1
