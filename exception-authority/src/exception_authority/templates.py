"""Post-hoc, descriptive: results per scenario template. Not part of the registered analysis (scoring.py,
frozen) and added after the main-stage data were read (18 Nov 2026; logged in results/logs/deviations.md).

Each base scenario belongs to one of six templates, one per domain and direction. Within a template the
20 base scenarios share the system prompt and every sentence except one noun (the product or item), so
the registered intervals and tests, which treat the 120 base scenarios as independent, are optimistic.
This module counts results per template instead. It reuses the scorer's own definitions of a valid reply
and of acceptance, reads sample 1 only (as the registered analysis does), and computes no statistic.

A template "accepts" a cell when a majority of its variants accept (more than half of the valid ones),
and "refuses" it when a minority do; exactly half is a split. An effect is flagged as single-template
when one template holds at least three quarters of the events that make it up (acceptances, discordant
pairs or rises), so the effect would largely vanish without that template.
"""
from collections import defaultdict
from pathlib import Path

from . import scoring as SC

SINGLE_SHARE = 0.75


def template_of(s: dict) -> tuple[str, str]:
    return (s["domain"], s["direction"])


def template_name(t: tuple[str, str]) -> str:
    return f"{t[0].replace('_', ' ')}, {t[1]}"


def scenarios_by_id(scenarios_path: Path) -> dict[str, dict]:
    return {s["id"]: s for s in SC.load_jsonl(scenarios_path)}


def templates(scen: dict[str, dict], stage: str) -> list[tuple[str, str]]:
    return sorted({template_of(s) for s in scen.values() if s["stage"] == stage})


def decisions(results_dir: Path, stage: str, model: str, scen: dict[str, dict]) -> dict[tuple[str, str], bool]:
    """(base, cell) -> accepted, for valid sample-1 replies."""
    path = results_dir / stage / f"{model}.jsonl"
    out = {}
    if not path.exists():
        return out
    for r in SC.load_jsonl(path):
        s = scen.get(r["id"])
        if s is None or r.get("sample", 1) != 1 or not SC.valid(r):
            continue
        out[(s["base"], s["cell"])] = SC.accepted(r, s)
    return out


def base_template(scen: dict[str, dict], stage: str) -> dict[str, tuple[str, str]]:
    return {s["base"]: template_of(s) for s in scen.values() if s["stage"] == stage}


def per_template(dec: dict, btpl: dict) -> dict[str, dict[tuple[str, str], list[int]]]:
    """cell -> template -> [accepted, valid]."""
    t = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for (base, cell), acc in dec.items():
        if base not in btpl:
            continue
        k = t[cell][btpl[base]]
        k[0] += acc
        k[1] += 1
    return t


def verdict(k: int, n: int) -> str:
    return "accept" if 2 * k > n else "refuse" if 2 * k < n else "split" if n else "none"


def count(per: dict, cell: str, want: str, tpls: list) -> int:
    return sum(verdict(*per[cell][t]) == want for t in tpls if per[cell][t][1])


def discordant(dec: dict, btpl: dict, first: str, second: str) -> dict[tuple[str, str], list[int]]:
    """template -> [pairs accepting only `first`, pairs accepting only `second`]."""
    out = defaultdict(lambda: [0, 0])
    for base, t in btpl.items():
        a, b = dec.get((base, first)), dec.get((base, second))
        if a is None or b is None:
            continue
        out[t][0] += a and not b
        out[t][1] += b and not a
    return out


def rises(dec_explicit: dict, dec_implicit: dict, btpl: dict, cell: str) -> dict[tuple[str, str], list[int]]:
    """template -> [base scenarios accepted only without the rule, only with it] for one cell."""
    out = defaultdict(lambda: [0, 0])
    for base, t in btpl.items():
        e, i = dec_explicit.get((base, cell)), dec_implicit.get((base, cell))
        if e is None or i is None:
            continue
        out[t][0] += i and not e
        out[t][1] += e and not i
    return out


def leave_one_out(dec: dict, btpl: dict, first: str, second: str) -> dict[tuple[str, str], tuple[int, int]]:
    """Omitted template -> (net discordant pairs first minus second, pairs left) over the base scenarios with
    valid replies in both cells of the other templates. The paired difference is net / pairs left."""
    d = discordant(dec, btpl, first, second)
    n = defaultdict(int)
    for base, t in btpl.items():
        if dec.get((base, first)) is not None and dec.get((base, second)) is not None:
            n[t] += 1
    tpls = sorted(set(btpl.values()))
    net = {t: d[t][0] - d[t][1] for t in tpls}
    return {t: (sum(net.values()) - net[t], sum(n.values()) - n[t]) for t in tpls}


def concentration(events: dict[tuple[str, str], int]) -> tuple[int, tuple[str, str] | None, bool]:
    """(total events, template with the most, whether that template holds >= SINGLE_SHARE of them)."""
    total = sum(events.values())
    if not total:
        return 0, None, False
    top = max(events, key=lambda t: events[t])
    return total, top, events[top] >= SINGLE_SHARE * total
