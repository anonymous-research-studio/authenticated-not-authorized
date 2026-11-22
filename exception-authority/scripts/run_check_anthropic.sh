#!/usr/bin/env bash
# Check stage on the Anthropic models only (no OpenRouter key needed): Haiku and Sonnet, then Opus, then the
# implicit-arm check on all three. Each command runs under its own hard cap and asks for a typed "yes";
# it never passes --yes. The OpenRouter models follow later with scripts/run_check.sh, which skips the
# Anthropic items already done. Run only after the caps are approved.
# Usage: scripts/run_check_anthropic.sh CAP_HAIKU_SONNET_USD CAP_OPUS_USD CAP_IMPLICIT_USD
set -euo pipefail
CAP_HS="${1:?usage: scripts/run_check_anthropic.sh CAP_HAIKU_SONNET CAP_OPUS CAP_IMPLICIT}"
CAP_OPUS="${2:?usage: scripts/run_check_anthropic.sh CAP_HAIKU_SONNET CAP_OPUS CAP_IMPLICIT}"
CAP_IMP="${3:?usage: scripts/run_check_anthropic.sh CAP_HAIKU_SONNET CAP_OPUS CAP_IMPLICIT}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
cd "$ROOT"
HS=(--model claude-haiku-5-5 --model claude-sonnet-5-5)
"$PY" scripts/02_run_stage.py check "${HS[@]}" --model claude-opus-5-5 --dry-run
# Haiku first: if its prefilled requests are rejected (400), stop here and switch feed_protocol (PREREG section 2).
"$PY" scripts/02_run_stage.py check --model claude-haiku-5-5 --max-cost "$CAP_HS"
"$PY" scripts/04_health_check.py check --model claude-haiku-5-5
"$PY" scripts/02_run_stage.py check --model claude-sonnet-5-5 --max-cost "$CAP_HS"
"$PY" scripts/04_health_check.py check "${HS[@]}"
# One Opus item before the rest.
"$PY" scripts/02_run_stage.py check --model claude-opus-5-5 --limit 1 --max-cost "$CAP_OPUS"
"$PY" scripts/02_run_stage.py check --model claude-opus-5-5 --max-cost "$CAP_OPUS"
"$PY" scripts/04_health_check.py check "${HS[@]}" --model claude-opus-5-5
"$PY" scripts/02_run_stage.py check-implicit --max-cost "$CAP_IMP"
"$PY" scripts/04_health_check.py check-implicit
"$PY" scripts/02_run_stage.py main --model claude-haiku-5-5 --model claude-opus-5-5 --dry-run
echo "Anthropic check done: read about 10 replies, re-estimate from the logged tokens, decide Sonnet and the"
echo "effort level on cost and health only (PREREG changelog), then run the OpenRouter models' check."
