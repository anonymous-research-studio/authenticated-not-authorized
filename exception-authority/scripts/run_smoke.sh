#!/usr/bin/env bash
# Free gate: self-tests, unit tests, the scripted smoke stage and its health check. No API calls.
# Usage: scripts/run_smoke.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
cd "$ROOT"
"$PY" scripts/01_generate_scenarios.py --selftest
"$PY" scripts/05_score.py --selftest
"$PY" -m unittest discover -s tests -t . -q
"$PY" scripts/02_run_stage.py smoke
# scripted-garbage is meant to fail as unparsed; every other scripted model must be clean
"$PY" scripts/04_health_check.py smoke --model scripted-gold --model scripted-accept --model scripted-never
echo "smoke gate passed (no API calls were made)"
