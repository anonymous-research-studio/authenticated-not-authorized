#!/usr/bin/env python3
"""Step 02. Run one stage (smoke, check, pilot, main) and record every decision.

Usage: python scripts/02_run_stage.py STAGE [--model M ...] [--dry-run [--show N]] [--max-cost USD] [--yes]
       [--limit N] [--workers 4] [--scenarios FILE] [--results-dir DIR]
smoke is free (scripted models). Every other stage calls paid APIs: always --dry-run first, then run only
with an approved --max-cost. --yes skips the typed confirmation; use it only after the run is approved.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # works without `pip install -e .`

from exception_authority import runner  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(runner.main(sys.argv[1:]))
