"""Eval harness (SPEC §4.5): run the pipeline over the synthetic set and score it against gold.json.

``python -m gp_pipeline.eval --docs fixtures/documents --out fixtures/documents/eval-latest.json [--noise]``

Variants: ``text`` (the text-layer PDFs), ``scan`` (the committed ``*.scan.pdf``: 150 dpi, 0.7 deg, JPEG q60) and, with
``--noise``, ``noise`` (re-degraded on the fly at 100 dpi, 2 deg, JPEG q35, in a temp dir that is deleted).

Scoring, per variant:
* field level: a gold field is matched to the extracted field with the same name in the same document (if a form has
  several properties, the extracted field whose printed address is most similar to the gold one). ``correct`` = value
  equal after normalisation (cents exact, text case/space-insensitive, rates within 1e-6). precision = correct /
  extracted (extracted fields whose name exists in the gold vocabulary for that form), recall = correct / gold,
  doc exact-match = share of documents with every gold field correct.
* classification: form kind and tax year per document, plus the confusion table.
* entity resolution: every gold address mention is mapped to the cluster it landed in; accuracy = mentions whose cluster
  is the one holding the majority of that property's mentions, and the property count.
* finding recall: each planted finding is found when a Finding with the same kind, the same property (through the
  resolved cluster) and tax year exists. ``unplanted`` lists the extra findings (precision signal).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from gp_pipeline import __version__
from gp_pipeline.address import key as address_key
from gp_pipeline.address import normalize, similarity
from gp_pipeline.models import ExtractedField, ParsedDocument
from gp_pipeline.run import extract_bytes, run_parsed

VARIANTS = ("text", "scan")


def _norm(v, unit: str):
    if v is None:
        return None
    if unit == "text":
        return " ".join(str(v).lower().replace(",", " ").replace(".", " ").replace(" - ", " ").split())
    if unit == "rate":
        return round(float(v), 6)
    if unit == "bool":
        return bool(v)
    if unit in ("cents", "int"):
        try:
            return int(v)
        except (TypeError, ValueError):
            return v
    return str(v)


def _match(gold: list[dict], got: list[ExtractedField]) -> list[tuple[dict, ExtractedField | None]]:
    by_field: dict[str, list[ExtractedField]] = defaultdict(list)
    for f in got:
        by_field[f.field].append(f)
    used: set[int] = set()
    pairs = []
    for g in gold:
        cands = [f for f in by_field.get(g["field"], []) if id(f) not in used]
        if not cands:
            pairs.append((g, None))
            continue
        if len(cands) > 1 and g.get("address_printed"):
            ga = normalize(g["address_printed"])
            cands.sort(key=lambda f: -(similarity(ga, normalize(f.address_raw)) if f.address_raw else 0))
        pick = cands[0]
        used.add(id(pick))
        pairs.append((g, pick))
    return pairs


def _prf(c: Counter) -> dict:
    p = c["correct"] / c["extracted"] if c["extracted"] else None
    r = c["correct"] / c["gold"] if c["gold"] else None
    return {"gold": c["gold"], "extracted": c["extracted"], "correct": c["correct"],
            "precision": round(p, 4) if p is not None else None, "recall": round(r, 4) if r is not None else None}


def eval_variant(docs_dir: Path, gold: dict, variant: str, files: dict[str, Path]) -> dict:
    t0 = time.time()
    per_form: dict[str, Counter] = defaultdict(Counter)
    per_field: dict[str, Counter] = defaultdict(Counter)
    confusion: Counter = Counter()
    year_ok, doc_exact, errors = 0, 0, []
    parsed: list[ParsedDocument] = []
    all_fields: list[ExtractedField] = []
    gold_by_file = {}
    for d in gold["documents"]:
        path = files[d["file"]]
        doc, fields, _ = extract_bytes(path.read_bytes(), path.name, force_ocr=variant != "text")
        parsed.append(doc)
        all_fields += fields
        gold_by_file[path.name] = d
        confusion[(d["kind"], doc.kind)] += 1
        year_ok += int(doc.tax_year == d.get("tax_year"))
        vocab = {g["field"] for g in d["fields"]}
        pairs = _match(d["fields"], fields)
        ok_all = True
        for g, f in pairs:
            fam = g["field"].split(".")[0]
            per_form[d["kind"]]["gold"] += 1
            per_field[g["field"]]["gold"] += 1
            good = f is not None and _norm(f.value, g["unit"]) == _norm(g["value"], g["unit"])
            if good:
                per_form[d["kind"]]["correct"] += 1
                per_field[g["field"]]["correct"] += 1
            else:
                ok_all = False
                if len(errors) < 60:
                    errors.append({"file": path.name, "field": g["field"], "gold": g["value"],
                                   "got": None if f is None else f.value, "raw": None if f is None else f.raw_text,
                                   "family": fam})
        for f in fields:
            if f.field in vocab:
                per_form[d["kind"]]["extracted"] += 1
                per_field[f.field]["extracted"] += 1
        doc_exact += int(ok_all)
    rec = run_parsed(parsed, all_fields)
    er = _entity_resolution(gold, gold_by_file, all_fields, rec)
    fr = _finding_recall(gold, rec, er["cluster_of_gold"])
    total = Counter()
    for c in per_form.values():
        total.update(c)
    n = len(gold["documents"])
    return {
        "variant": variant,
        "seconds": round(time.time() - t0, 1),
        "documents": n,
        "overall": _prf(total) | {"doc_exact_match": round(doc_exact / n, 4)},
        "classification": {"kind_accuracy": round(sum(v for (a, b), v in confusion.items() if a == b) / n, 4),
                           "tax_year_accuracy": round(year_ok / n, 4),
                           "confusion": [{"gold": a, "predicted": b, "count": v} for (a, b), v in sorted(confusion.items())]},
        "per_form": {k: _prf(v) for k, v in sorted(per_form.items())},
        "per_field": {k: _prf(v) for k, v in sorted(per_field.items())},
        "entity_resolution": {k: v for k, v in er.items() if k != "cluster_of_gold"},
        "findings": fr,
        "errors_sample": errors,
    }


def _entity_resolution(gold: dict, gold_by_file: dict, fields: list[ExtractedField], rec) -> dict:
    """Map each gold address mention to the canonical key its extracted twin resolved to."""
    mentions = []  # (gold property key, resolved key or None)
    for fname, d in gold_by_file.items():
        gold_addr = {}
        for g in d["fields"]:
            if g.get("address_printed") and g.get("property_key"):
                gold_addr[g["address_printed"]] = g["property_key"]
        got = [f for f in fields if f.document_key == fname and f.address_raw]
        for printed, gpk in gold_addr.items():
            ga = normalize(printed)
            best = max(got, key=lambda f: similarity(ga, normalize(f.address_raw)), default=None)
            ok = best is not None and similarity(ga, normalize(best.address_raw)) >= 0.6
            mentions.append((gpk, best.property_key if ok else None, fname, printed))
    by_gold: dict[str, Counter] = defaultdict(Counter)
    for gpk, rk, _, _ in mentions:
        by_gold[gpk][rk] += 1
    cluster_of_gold = {gpk: c.most_common(1)[0][0] for gpk, c in by_gold.items()}
    correct = sum(1 for gpk, rk, _, _ in mentions if rk is not None and rk == cluster_of_gold[gpk]
                  and list(cluster_of_gold.values()).count(rk) == 1)
    wrong = [{"file": f, "printed": p, "gold": g, "resolved": r} for g, r, f, p in mentions
             if r is None or r != cluster_of_gold[g]]
    planted = [p for p in gold["planted"] if p["check"] == "entity_resolution"]
    planted_ok = []
    for p in planted:
        keys = {rk for gpk, rk, _, printed in mentions if gpk == p["property_key"] and printed in p["variants"]}
        planted_ok.append({"id": p["id"], "found": len(keys) == 1 and None not in keys})
    return {"mentions": len(mentions), "correct": correct, "accuracy": round(correct / len(mentions), 4) if mentions else None,
            "gold_properties": len(gold["household"]["properties"]), "resolved_properties": len(rec.properties),
            "planted": planted_ok, "misplaced": wrong[:20], "cluster_of_gold": cluster_of_gold}


def _finding_recall(gold: dict, rec, cluster_of_gold: dict) -> dict:
    planted = [p for p in gold["planted"] if p["check"] == "finding"]
    rows, matched_keys = [], set()
    for p in planted:
        pk = cluster_of_gold.get(p["property_key"])
        hit = next((f for f in rec.findings if f.kind == p["kind"] and f.property_key == pk and pk is not None
                    and (p.get("tax_year") is None or f.tax_year == p["tax_year"])), None)
        if hit:
            matched_keys.add(hit.key)
        rows.append({"id": p["id"], "kind": p["kind"], "found": hit is not None, "finding_key": hit.key if hit else None})
    extra = [{"key": f.key, "kind": f.kind, "severity": f.severity, "message": f.message} for f in rec.findings
             if f.key not in matched_keys]
    found = sum(r["found"] for r in rows)
    return {"planted": len(rows), "found": found, "recall": round(found / len(rows), 4) if rows else None, "rows": rows,
            "unplanted": extra, "unplanted_count": len(extra),
            "unplanted_non_info": sum(1 for f in extra if f["severity"] != "info")}


def run(docs_dir: Path, out: Path | None = None, noise: bool = False, variants: tuple[str, ...] = VARIANTS) -> dict:
    gold = json.loads((docs_dir / "gold.json").read_text())
    result = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "pipeline_version": __version__,
              "gold_schema": gold["schema"], "seed": gold["seed"], "variants": {}}
    for v in variants:
        files = {d["file"]: docs_dir / (d["file"] if v == "text" else d["scan_file"]) for d in gold["documents"]}
        result["variants"][v] = eval_variant(docs_dir, gold, v, files)
    if noise:
        from gp_pipeline.synth.scan import NOISE, degrade

        td = Path(tempfile.mkdtemp(prefix="gp-noise-"))
        try:
            files = {}
            for d in gold["documents"]:
                files[d["file"]] = degrade(docs_dir / d["file"], td / (d["file"][:-4] + ".noise.pdf"), **NOISE)
            result["variants"]["noise"] = eval_variant(docs_dir, gold, "noise", files) | {"params": NOISE}
        finally:
            shutil.rmtree(td, ignore_errors=True)
    result["summary"] = {v: {"precision": r["overall"]["precision"], "recall": r["overall"]["recall"],
                             "doc_exact_match": r["overall"]["doc_exact_match"],
                             "kind_accuracy": r["classification"]["kind_accuracy"],
                             "entity_resolution_accuracy": r["entity_resolution"]["accuracy"],
                             "finding_recall": r["findings"]["recall"]} for v, r in result["variants"].items()}
    if out:
        out.write_text(json.dumps(result, indent=2, default=str) + "\n")
    return result


def markdown(result: dict) -> str:
    vs = list(result["variants"])
    lines = ["| metric | " + " | ".join(vs) + " |", "|---|" + "---|" * len(vs)]

    def row(label, fn):
        lines.append(f"| {label} | " + " | ".join(fn(result["variants"][v]) for v in vs) + " |")

    pct = lambda x: "-" if x is None else f"{x:.1%}"  # noqa: E731
    row("field precision", lambda r: pct(r["overall"]["precision"]))
    row("field recall", lambda r: pct(r["overall"]["recall"]))
    row("document exact match", lambda r: pct(r["overall"]["doc_exact_match"]))
    row("form classification", lambda r: pct(r["classification"]["kind_accuracy"]))
    row("tax year", lambda r: pct(r["classification"]["tax_year_accuracy"]))
    row("entity resolution", lambda r: pct(r["entity_resolution"]["accuracy"]))
    row("properties (gold 4)", lambda r: str(r["entity_resolution"]["resolved_properties"]))
    row("planted findings", lambda r: f"{r['findings']['found']}/{r['findings']['planted']}")
    row("extra non-info findings", lambda r: str(r["findings"]["unplanted_non_info"]))
    row("seconds", lambda r: str(r["seconds"]))
    forms = sorted({k for r in result["variants"].values() for k in r["per_form"]})
    lines += ["", "| form (P / R) | " + " | ".join(vs) + " |", "|---|" + "---|" * len(vs)]
    for k in forms:
        lines.append(f"| {k} | " + " | ".join(
            f"{pct(result['variants'][v]['per_form'].get(k, {}).get('precision'))} / "
            f"{pct(result['variants'][v]['per_form'].get(k, {}).get('recall'))}" for v in vs) + " |")
    return "\n".join(lines)


__all__ = ["run", "markdown", "address_key"]
