import argparse
import sys
from pathlib import Path

from gp_pipeline.eval import markdown, run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gp-pipeline eval", description="Score the pipeline against fixtures/documents/gold.json")
    ap.add_argument("--docs", default="../fixtures/documents", type=Path)
    ap.add_argument("--out", default=None, type=Path, help="write the JSON result here (eval-latest.json)")
    ap.add_argument("--noise", action="store_true", help="also score a harsher scan (100 dpi, 2 deg, JPEG q35)")
    ap.add_argument("--variants", default="text,scan", help="comma list of text,scan")
    args = ap.parse_args(argv)
    res = run(args.docs, args.out, noise=args.noise, variants=tuple(v for v in args.variants.split(",") if v))
    print(markdown(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
