"""``gp-pipeline run <pdf...> --out reconciled.json`` | ``gp-pipeline synth`` | ``gp-pipeline eval`` (SPEC §4.6)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "synth":
        from gp_pipeline.synth.generate import main as synth_main

        return synth_main(rest)
    if cmd == "eval":
        from gp_pipeline.eval.__main__ import main as eval_main

        return eval_main(rest)
    if cmd == "run":
        ap = argparse.ArgumentParser(prog="gp-pipeline run")
        ap.add_argument("pdfs", nargs="+", type=Path)
        ap.add_argument("--out", type=Path, default=None)
        ap.add_argument("--ocr", action="store_true", help="force OCR even when a text layer exists")
        a = ap.parse_args(rest)
        from gp_pipeline.run import run_files

        rec = run_files(a.pdfs, force_ocr=a.ocr)
        text = json.dumps(rec.model_dump(mode="json"), indent=2)
        if a.out:
            a.out.write_text(text + "\n")
            print(f"{len(rec.properties)} properties, {len(rec.extracted_fields)} fields, {len(rec.findings)} findings -> {a.out}")
        else:
            print(text)
        return 0
    print(f"unknown command {cmd!r}\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
