#!/usr/bin/env python3
"""Step 01. Generate the nine-cell scenarios into resources/scenarios.jsonl (all stages), or self-test.

Usage: python scripts/01_generate_scenarios.py [--selftest] [--out FILE]
Free. resources/scenarios.jsonl is part of the frozen protocol: regenerate only before the freeze.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # works without `pip install -e .`

from exception_authority import scenarios  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(scenarios.main(sys.argv[1:]))
