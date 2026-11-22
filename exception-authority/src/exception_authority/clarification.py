"""The clarification flag, per model and cell (PREREG section 4, items 2 and 6: reported separately per model
and cell, exploratory). Decisions are scored on `decision` alone; this module only counts how often a valid
sample-1 reply also set `clarification_required`, and how often it did so while accepting the exception.

It reuses the scorer's own definitions of a valid reply and of acceptance (scoring.py, frozen) and computes
no statistic. Not part of the frozen protocol; added 19 Nov 2026 (logged in results/logs/deviations.md).

  results/main/clarification.csv           registered stage (exploratory item)
  results/main-implicit/clarification.csv  exploratory implicit-rule arm (PREREG section 4b)
"""
from __future__ import annotations

import csv
from pathlib import Path

from . import scenarios as S
from . import scoring as SC

COLUMNS = ["stage", "analysis", "model", "panel", "cell", "valid", "flagged", "accepted", "accepted_and_flagged"]
ANALYSIS = {"main": "exploratory item of the registered analysis (PREREG section 4, items 2 and 6)",
            "main-implicit": "exploratory implicit-rule arm (PREREG section 4b)"}


def counts(results_dir: Path, stage: str, model: str, scen: dict[str, dict]) -> dict[str, dict[str, int]]:
    """cell -> {valid, flagged, accepted, accepted_and_flagged}, over valid sample-1 replies."""
    out = {c: {"valid": 0, "flagged": 0, "accepted": 0, "accepted_and_flagged": 0} for c in S.CELLS}
    path = results_dir / stage / f"{model}.jsonl"
    if not path.exists():
        return out
    for r in SC.load_jsonl(path):
        s = scen.get(r["id"])
        if s is None or r.get("sample", 1) != 1 or not SC.valid(r):
            continue
        k = out[s["cell"]]
        acc, flag = bool(SC.accepted(r, s)), bool(r.get("clarification_required"))
        k["valid"] += 1
        k["flagged"] += flag
        k["accepted"] += acc
        k["accepted_and_flagged"] += acc and flag
    return out


def rows(results_dir: Path, stage: str, models: list[str], outside: list[str], scen: dict[str, dict]) -> list[dict]:
    out = []
    for m in models:
        for cell, k in counts(results_dir, stage, m, scen).items():
            out.append({"stage": stage, "analysis": ANALYSIS.get(stage, "exploratory"), "model": m,
                        "panel": "outside panel" if m in outside else "panel", "cell": cell, **k})
    return out


def write_csv(table: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(table)
    return path
