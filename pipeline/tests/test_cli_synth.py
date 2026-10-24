import json

from gp_pipeline.cli import main
from gp_pipeline.synth.generate import generate


def test_cli_run(docs, tmp_path):
    out = tmp_path / "rec.json"
    assert main(["run", str(docs / "2025_schedule_e.pdf"), str(docs / "appraisal_1.pdf"), "--out", str(out)]) == 0
    rec = json.loads(out.read_text())
    assert len(rec["properties"]) == 3 and rec["documents"][0]["kind"] == "schedule_e"


def test_synth_text_layer_is_deterministic(gold, tmp_path):
    g = generate(tmp_path, seed=gold["seed"], scans=False)
    assert {d["file"]: d["sha256"] for d in g["documents"]} == {d["file"]: d["sha256"] for d in gold["documents"]}
    assert len(g["planted"]) == len(gold["planted"])
