"""Protocol health of a stage's results, with no outcome rates.
Run it after every paid step and before the next, more expensive one.

Per model, and per cell where it matters: items planned, done, missing, errors, refusals, replies cut
off at max_tokens, unparsed replies, replies from a different model than requested, mixed settings,
tokens and cost, and (per model only) how often clarification_required is true. It never prints acceptance or accuracy, so checking the protocol cannot become a
look at the effect.

Usage:
  python scripts/04_health_check.py check            # exit 0 if clean, 1 if any problem
  python scripts/04_health_check.py pilot --model claude-haiku-5-5
  python scripts/04_health_check.py check --allow-missing   # after a deliberate --limit run
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from . import runner
from .paths import RESULTS, SCENARIOS
from .runner import load_jsonl


def host_key(name) -> str:
    """Host names without case, spaces or hyphens, so a pinned slug ("google-ai-studio") matches the host
    OpenRouter reports ("Google AI Studio")."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())

# A stage is clean when, per model, these stay at or under the limits (shares of planned items).
LIMITS = {"missing": 0.0, "refusal": 0.02, "truncated": 0.0, "unparsed": 0.02, "served_mismatch": 0.0,
          "host_mismatch": 0.0, "no_lookup": 0.02}


CACHE_HIT_MIN = 0.90  # samples 2+ that read the prompt cache, in a stage with caching on


def check(stage: str, model: str, items: list[dict], stage_dir: Path,
          allow_missing: bool = False, samples: int = 1, cache: bool = False) -> tuple[list[str], list[str]]:
    rows = load_jsonl(stage_dir / f"{model}.jsonl")
    errs = load_jsonl(stage_dir / f"{model}.errors.jsonl")
    planned = {it["id"]: it for it in items}
    rows = [r for r in rows if r["id"] in planned and r.get("sample", 1) <= samples]
    done = {(r["id"], r.get("sample", 1)) for r in rows}
    n = len(planned) * samples
    counts = Counter()
    by_cell: dict[str, Counter] = {}
    for r in rows:
        bad = []
        if r.get("stop_reason") == "refusal":
            bad.append("refusal")
        elif r.get("stop_reason") == "max_tokens":
            bad.append("truncated")
        elif r.get("protocol_deviation") == "no_lookup":
            bad.append("no_lookup")
        elif not r.get("parse_ok"):
            bad.append("unparsed")
        if r.get("model_id") and r.get("served_model") and not str(r["served_model"]).startswith(r["model_id"]):
            bad.append("served_mismatch")
        if r.get("pinned_host") and r.get("served_by") and not host_key(r["served_by"]).startswith(host_key(r["pinned_host"])):
            bad.append("host_mismatch")
        for b in bad:
            counts[b] += 1
            by_cell.setdefault(r["cell"], Counter())[b] += 1
    counts["missing"] = n - len(done)
    dupes = len(rows) - len(done)
    settings = {r.get("settings_hash") for r in rows}
    out_tokens = [r["usage"]["output_tokens"] for r in rows if r.get("usage")]
    in_tokens = [r["usage"]["input_tokens"] + r["usage"].get("cache_creation_input_tokens", 0)
                 + r["usage"].get("cache_read_input_tokens", 0) for r in rows if r.get("usage")]
    cost = sum(r.get("cost_usd", 0.0) for r in rows)

    lines = [f"{model}: {len(done)}/{n} done, {len(errs)} error lines logged, ${cost:.4f}"]
    if out_tokens:
        lines.append(f"  tokens in: median {statistics.median(in_tokens):.0f}, max {max(in_tokens)}; "
                     f"out: median {statistics.median(out_tokens):.0f}, max {max(out_tokens)}")
    served = Counter(r.get("served_model") for r in rows)
    if served:
        lines.append("  served model(s): " + ", ".join(f"{k} ({v})" for k, v in served.items()))
    lines.append("  " + ", ".join(f"{k} {counts[k]}" for k in LIMITS))
    # Model-level only: a per-cell split could show an effect. Near-100% would make scoring awkward.
    clar = sum(1 for r in rows if r.get("clarification_required") is True)
    lines.append(f"  clarification_required true: {clar}/{len(rows)}")
    if samples > 1:  # determinism (temperature 0) or reliability: a share of items, never a direction
        dec: dict[str, set] = {}
        for r in rows:
            if r.get("parse_ok") and r.get("stop_reason") not in ("refusal", "max_tokens"):
                dec.setdefault(r["id"], set()).add(r["decision"])
        multi = [i for i, d in dec.items() if sum(1 for r in rows if r["id"] == i and r.get("parse_ok")) >= 2]
        differ = sum(len(dec[i]) > 1 for i in multi)
        lines.append(f"  decision differs between samples: {differ}/{len(multi)} items ({samples} samples per item)")
    cache_problem = None
    if cache:
        repeats = [r for r in rows if r.get("sample", 1) >= 2]
        writes = sum(1 for r in rows if r.get("sample", 1) == 1 and r["usage"].get("cache_creation_input_tokens", 0) > 0)
        hits = sum(1 for r in repeats if r["usage"].get("cache_read_input_tokens", 0) > 0)
        rate = hits / len(repeats) if repeats else None
        lines.append(f"  prompt cache: sample 1 wrote it on {writes}/{sum(1 for r in rows if r.get('sample', 1) == 1)}; "
                     f"samples 2+ read it on {hits}/{len(repeats)}" + (f" ({rate:.0%})" if rate is not None else ""))
        if rate is not None and rate < CACHE_HIT_MIN:
            cache_problem = f"{model}: cache hit rate {rate:.0%} on samples 2+ (limit {CACHE_HIT_MIN:.0%})"
    calls = Counter(r.get("calls", 1) for r in rows)
    if set(calls) - {1}:
        lines.append("  calls per item: " + ", ".join(f"{k} ({v})" for k, v in sorted(calls.items())))
    for cell, c in sorted(by_cell.items()):
        lines.append(f"    cell {cell}: " + ", ".join(f"{k} {v}" for k, v in c.items()))
    refusal_cats = Counter(r.get("refusal_category") for r in rows if r.get("stop_reason") == "refusal")
    if refusal_cats:
        lines.append("  refusal categories: " + ", ".join(f"{k} ({v})" for k, v in refusal_cats.items()))

    problems = [f"{model}: {k} {counts[k]}/{n} (limit {lim:.0%})" for k, lim in LIMITS.items()
                if n and counts[k] / n > lim and not (k == "missing" and allow_missing)]
    if dupes:
        problems.append(f"{model}: {dupes} duplicate rows")
    if cache_problem:
        problems.append(cache_problem)
    if len(settings) > 1:
        problems.append(f"{model}: rows from {len(settings)} different settings")
    if fatal := [e for e in errs if e.get("fatal")]:
        problems.append(f"{model}: {len(fatal)} account/request errors logged (e.g. {fatal[-1].get('fatal')})")
    return lines, problems


def main(argv: list[str]) -> int:
    cfg = json.loads(runner.CONFIG.read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=list(cfg["stages"]))
    ap.add_argument("--model", action="append")
    ap.add_argument("--allow-missing", action="store_true", help="after a deliberate --limit run")
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    ap.add_argument("--results-dir", type=Path, default=RESULTS)
    args = ap.parse_args(argv)
    stage_cfg = cfg["stages"][args.stage]
    items = [it for it in load_jsonl(args.scenarios) if it["stage"] == stage_cfg["scenarios"]]
    problems: list[str] = []
    for model in args.model or stage_cfg["models"]:
        samples = int(stage_cfg.get("samples", {}).get(model, 1))
        mcfg = cfg["models"].get(model, {})
        cache = runner.caches(mcfg, stage_cfg)
        lines, p = check(args.stage, model, items, args.results_dir / args.stage, args.allow_missing, samples, cache)
        print("\n".join(lines))
        problems += p
    if problems:
        print("PROBLEMS:\n  " + "\n  ".join(problems))
        return 1
    print(f"CLEAN: stage {args.stage} has no protocol problems.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
