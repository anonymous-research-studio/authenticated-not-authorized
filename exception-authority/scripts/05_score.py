#!/usr/bin/env python3
"""Step 05. Score a stage: per-cell rates, the pilot go/no-go, the main effects.

Usage: python scripts/05_score.py summary|gonogo|effects STAGE   (or --selftest)
  summary  results/<stage>/summary.csv
  gonogo   PREREG section 5; never reads cell D; results/<stage>/gonogo.json
  effects  PREREG sections 1 and 4; results/<stage>/effects.json (input to steps 06-08)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # works without `pip install -e .`

from exception_authority import scoring  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(scoring.main(sys.argv[1:]))
