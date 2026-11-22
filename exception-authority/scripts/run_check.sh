#!/usr/bin/env bash
# Check stage (paid), cheapest models first and Opus last, each command under its own hard cap.
# Asks for a typed "yes" before each paid command; it never passes --yes. Run only after the caps are approved.
# Usage: scripts/run_check.sh CAP_CHEAP_USD CAP_OPUS_USD [CAP_IMPLICIT_USD]
# With a third cap it also runs check-implicit (Haiku and Opus, the exploratory implicit-rule arm).
set -euo pipefail
CAP_CHEAP="${1:?usage: scripts/run_check.sh CAP_CHEAP_USD CAP_OPUS_USD}"
CAP_OPUS="${2:?usage: scripts/run_check.sh CAP_CHEAP_USD CAP_OPUS_USD}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
cd "$ROOT"
CHEAP=(--model llama-3.3-70b --model qwen3.8-flash --model claude-haiku-5-5 --model gemini-3.5-flash-lite --model gpt-4.1-mini)
"$PY" scripts/02_run_stage.py check --dry-run
"$PY" scripts/02_run_stage.py check "${CHEAP[@]}" --max-cost "$CAP_CHEAP"
"$PY" scripts/04_health_check.py check "${CHEAP[@]}"
"$PY" scripts/02_run_stage.py check --model claude-opus-5-5 --max-cost "$CAP_OPUS"
"$PY" scripts/04_health_check.py check
if [ -n "${3:-}" ]; then
  "$PY" scripts/02_run_stage.py check-implicit --max-cost "$3"
  "$PY" scripts/04_health_check.py check-implicit
fi
echo "check stage done: read about 10 replies in results/check/*.jsonl, pin the Gemini and Qwen hosts, then freeze"
