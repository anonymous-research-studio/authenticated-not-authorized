#!/usr/bin/env python3
"""Step 07. Figure: acceptance per cell and model with Wilson 95% intervals (from summary.csv), into
../manuscript/figures/cells.pdf. Needs matplotlib (pip install -e ".[figures]") and a scored stage.

Usage: python scripts/07_make_figures.py [--stage main] [--outdir ../manuscript/figures]
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
    ap.add_argument("--outdir", type=Path, default=d["manuscript"] / "figures")
    args = ap.parse_args(argv)
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        print('matplotlib is not installed: pip install -e ".[figures]"')
        return 1
    path = outputs.write_figure(args.stage, args.results_dir, args.outdir)
    if path:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
