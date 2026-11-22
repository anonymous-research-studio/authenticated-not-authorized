#!/usr/bin/env python3
"""Step 08. LaTeX macros for every number the paper cites, with meanings and sources, into
../manuscript/numbers.tex and numbers.md. Design numbers come from the generator and the config;
results from results/<stage>/effects.json, results/pilot/gonogo.json and results/spend-ledger.jsonl.
A result that does not exist yet is a bold ?? in the PDF. Regenerate after every scored stage; never
edit the outputs by hand. Free. Also writes results/<stage>/clarification.csv and, for the paired implicit
stage, results/<stage>-implicit/clarification.csv: the clarification flag per model and cell (PREREG section 4,
items 2 and 6; exploratory), from the sample-1 replies with the scorer's definitions.

Usage: python scripts/08_make_numbers.py [--stage main] [--outdir ../manuscript]
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
    ap.add_argument("--outdir", type=Path, default=d["manuscript"])
    args = ap.parse_args(argv)
    cfg = outputs.config()
    rows = outputs.collect(args.stage, args.results_dir, args.scenarios, cfg)
    tex, md, missing = outputs.write_numbers(rows, args.outdir)
    print(f"wrote {tex} and {md}: {len(rows)} macros, {missing} still missing")
    for p in outputs.write_clarification(args.stage, args.results_dir, args.scenarios, cfg):
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
