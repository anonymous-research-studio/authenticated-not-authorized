#!/usr/bin/env python3
"""Step 04. Protocol health of a stage's results, with no outcome rates. Run after every paid step.

Usage: python scripts/04_health_check.py STAGE [--model M ...] [--allow-missing]
Exit 0 if clean, 1 if any problem.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # works without `pip install -e .`

from exception_authority import health  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(health.main(sys.argv[1:]))
