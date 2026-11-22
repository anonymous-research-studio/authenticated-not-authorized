#!/usr/bin/env python3
"""Step 03. Fingerprint the protocol into FROZEN.json, after the check stage and the review of PREREG.md.

The pilot and main stages refuse to run if any frozen file changed since: the generator, the label check
(derive.py), the scenarios, the runner, the guard, the scorer, resources/config.json and ../PREREG.md. Record the freeze in
PREREG.md's changelog (which itself changes PREREG.md, so freeze again after writing that line).

Usage: python scripts/03_freeze_protocol.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # works without `pip install -e .`

from exception_authority import runner  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(runner.main(["freeze"]))
