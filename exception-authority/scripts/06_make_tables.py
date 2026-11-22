#!/usr/bin/env python3
"""Step 06. LaTeX tables into ../manuscript/tables/: design.tex (the nine cells, with the exact wording
from resources/scenarios.jsonl), rates.tex (from results/<stage>/effects.json, with the paired exploratory
stage, main-implicit for main, as a lower block) and summary.tex (two panels: the two-sided summary with
paired accuracy, and the contrasts). ?? until the stage is scored. Free.

Usage: python scripts/06_make_tables.py [--stage main] [--outdir ../manuscript/tables]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # works without `pip install -e .`

from exception_authority import outputs  # noqa: E402


def main(argv):
    d = outputs.defaults()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", default="main", help="results stage to read (default main)")
    ap.add_argument("--results-dir", type=Path, default=d["results_dir"])
    ap.add_argument("--scenarios", type=Path, default=d["scenarios"])
    ap.add_argument("--outdir", type=Path, default=d["manuscript"] / "tables")
    args = ap.parse_args(argv)
    for path in outputs.write_tables(args.stage, args.results_dir, args.scenarios, args.outdir):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
