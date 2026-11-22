"""Manuscript outputs generated from the protocol and the results: LaTeX number macros, tables and the
per-cell figure. Nothing here changes what is sent to a model or how it is scored, so this module is
not part of the frozen protocol.

In the paper, write \\accOpusCno{} instead of typing a number, so the text cannot drift from the
results. A result that does not exist yet (no results/<stage>/effects.json) is still defined, as a bold
"??", so the draft always compiles; numbers.md lists every macro with its meaning and source, and says
which ones are still missing.

  numbers   ../manuscript/numbers.tex and numbers.md        (scripts/08_make_numbers.py)
  tables    ../manuscript/tables/{design,rates,summary}.tex (scripts/06_make_tables.py)
  figure    ../manuscript/figures/cells.pdf                  (scripts/07_make_figures.py, needs matplotlib)
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from . import scenarios as S
from . import scoring as SC
from .paths import MANUSCRIPT, RESULTS, SCENARIOS

MISSING = r"\missing{}"
# Macro-safe names (letters only). Unknown models fall back to their letters, capitalized.
MODEL_MACRO = {"claude-haiku-5-5": "Haiku", "claude-opus-5-5": "Opus", "claude-sonnet-5-5": "Sonnet",
               "gpt-4.1-mini": "Gptmini", "gemini-3.5-flash-lite": "Gemini", "qwen3.8-flash": "Qwen",
               "llama-3.3-70b": "Llama"}
MODEL_LABEL = {"claude-haiku-5-5": "Claude Haiku 5.5", "claude-opus-5-5": "Claude Opus 5.5",
               "claude-sonnet-5-5": "Claude Sonnet 5.5", "gpt-4.1-mini": "GPT-4.1 mini",
               "gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite", "qwen3.8-flash": "Qwen3.8 Flash",
               "llama-3.3-70b": "Llama 3.3 70B"}
CELL_MACRO = {"A": "A", "D": "D", "B-in": "Bin", "B-out": "Bout", "R": "R", "R-ctl": "Rctl",
              "C-ok": "Cok", "C-no": "Cno", "C-ctl": "Cctl"}
CONTRAST_MACRO = {"C-ctl - C-no": "pri", "R-ctl - R": "secRctlR", "B-in - B-out": "secBinBout",
                  "D - A": "secDA", "C-ok - C-no": "secCokCno", "C-ok - C-ctl": "ctlCokCctl",
                  "B-in - R-ctl": "ctlBinRctl"}
# Paired accuracy (descriptive): macro stems for scoring.PAIRED.
PAIR_MACRO = {"C-no / C-ctl": "CnoCctl", "C-no / C-ok": "CnoCok", "R / R-ctl": "RRctl", "B-out / B-in": "BoutBin"}
DIR_MACRO = {"permissive": "Perm", "restrictive": "Restr"}
# Exploratory implicit-rule arm (PREREG section 4b): the label-free pairs only.
IMPLICIT_MACRO = {"C-ctl - C-no": "impPri", "R-ctl - R": "impRctlR", "B-in - B-out": "impBinBout"}


def model_macro(name: str) -> str:
    return MODEL_MACRO.get(name) or re.sub(r"[^A-Za-z]", "", name).capitalize()


def model_label(name: str) -> str:
    return MODEL_LABEL.get(name, name)


def half_up(x: float, places: int) -> str:
    """Round half up on the decimal value (0.125 -> 0.13), not on the binary float."""
    q = Decimal(1).scaleb(-places)
    return str(Decimal(repr(round(float(x), 9))).quantize(q, rounding=ROUND_HALF_UP))


def pct(x: float) -> str:
    """A proportion as a whole percentage, without the % sign."""
    return MISSING if x is None or math.isnan(x) else half_up(100 * x, 0)


def pts(x: float) -> str:
    """A difference of proportions in signed percentage points."""
    if x is None or math.isnan(x):
        return MISSING
    v = half_up(100 * x, 0)
    if v in ("0", "-0"):
        return "0"
    return "$-$" + v[1:] if v.startswith("-") else "+" + v  # a true minus sign, not a hyphen


def pval(p: float, relation: bool = False) -> str:
    """Tables print the bare value ("< 0.001", "0.031"); text macros (relation=True) carry the relation,
    so "$p$ \\macro" reads "p < 0.001" or "p = 0.031"."""
    if p is None or math.isnan(p):
        return MISSING
    if p < 0.001:
        return "< 0.001"
    return ("= " if relation else "") + half_up(p, 3)


def load_json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def config() -> dict:
    from . import runner  # read at call time, so tests can point it elsewhere
    return json.loads(runner.CONFIG.read_text(encoding="utf-8"))


def load_rows(path: Path) -> list[dict]:
    return SC.load_jsonl(path)


def implicit_stage(stage: str, cfg: dict) -> str | None:
    """The exploratory stage that pairs with this one (main -> main-implicit), if any."""
    return next((s for s, c in cfg["stages"].items() if c.get("pairs_with") == stage), None)


def cache_hit_rate(rows: list[dict]) -> float | None:
    """Share of samples 2+ whose request read the prompt cache (the health report's measure)."""
    repeats = [r for r in rows if r.get("sample", 1) >= 2 and r.get("usage")]
    if not repeats:
        return None
    return sum((r["usage"].get("cache_read_input_tokens") or 0) > 0 for r in repeats) / len(repeats)


# --- numbers ----------------------------------------------------------------------------------------

def collect(stage: str, results_dir: Path, scenarios_path: Path, cfg: dict) -> list[tuple[str, str, str, str]]:
    """(macro, value, meaning, source) for every number the paper may cite."""
    out: list[tuple[str, str, str, str]] = []

    def add(macro, value, meaning, source):
        out.append((macro, str(value), meaning, source))

    items = [json.loads(l) for l in scenarios_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_stage = Counter(i["stage"] for i in items)
    bases = {st: len({i["base"] for i in items if i["stage"] == st}) for st in S.STAGES}
    run_models = cfg["stages"]["main"]["models"]          # every model the main stage runs
    outside = cfg["stages"]["main"].get("outside_panel", [])
    panel = [m for m in run_models if m not in outside]   # H1's Holm family and prediction F
    vendors = {cfg["models"][m]["model_id"].split("/")[0] if "/" in cfg["models"][m]["model_id"] else "anthropic"
               for m in panel}
    src_s, src_c = "resources/scenarios.jsonl", "resources/config.json"
    add("nCells", len(S.CELLS), "cells per base scenario", "src/exception_authority/scenarios.py")
    add("nDomains", len({d for d, _ in S.DOMAINS}), "domains", "src/exception_authority/scenarios.py")
    add("nDirections", len({r for _, r in S.DOMAINS}), "directions (permissive, restrictive)", "src/exception_authority/scenarios.py")
    for st, name in (("check", "Check"), ("pilot", "Pilot"), ("main", "Main")):
        add(f"nBase{name}", bases[st], f"base scenarios in the {st} stage", src_s)
        add(f"nItems{name}", by_stage[st], f"items per model in the {st} stage", src_s)
    add("nModels", len(panel), "models in the main panel (H1's Holm family and prediction F)", src_c)
    add("nOutsidePanel", len(outside), "models run in main but reported outside H1's Holm family and prediction F", src_c)
    add("nVendors", len(vendors), "vendors in the main panel", src_c)
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
    add("nModelsWord", words[len(panel)] if len(panel) < len(words) else str(len(panel)), "models in the main panel, as a word", src_c)
    add("nVendorsWord", words[len(vendors)] if len(vendors) < len(words) else str(len(vendors)), "vendors in the main panel, as a word", src_c)
    add("nItemsMainAll", by_stage["main"] * len(panel), "main-stage items over all models", src_s + ", " + src_c)
    add("todayDate", S.TODAY, "date stated in every prompt", "src/exception_authority/scenarios.py")
    add("issuedDate", S.ISSUED, "issue date of every feed entry", "src/exception_authority/scenarios.py")
    add("revokedDate", S.REVOKED, "revocation date in R (review date in R-ctl)", "src/exception_authority/scenarios.py")
    add("goMinValid", pct(SC.GO_MIN_VALID), "P1: minimum valid share per cell, percent", "src/exception_authority/scoring.py")
    add("floorBreakLo", pct(SC.FLOOR_BREAK_LO), "prediction F: Wilson lower bound to exceed, percent", "src/exception_authority/scoring.py")
    add("floorBreakConf", f"{100 * (1 - SC.FLOOR_BREAK_ALPHA):.2f}",
        "prediction F: confidence level of the Wilson bound, Bonferroni over the three unauthorized cells (D, R, C-no), percent",
        "src/exception_authority/scoring.py")
    add("ceilingAcc", pct(SC.CEILING_ACCURACY), "outcome C: minimum accuracy per cell, percent", "src/exception_authority/scoring.py")
    add("nBootstrap", f"{SC.BOOTSTRAP:,}", "bootstrap resamples", "src/exception_authority/scoring.py")
    n_main = bases["main"]
    k_floor = next((k for k in range(n_main + 1) if SC.floor_lower_bound(k / n_main, n_main) > SC.FLOOR_BREAK_LO), None)
    add("floorBreakK", k_floor if k_floor is not None else MISSING,
        f"prediction F: fewest acceptances out of {n_main} that clear the bound", "src/exception_authority/scoring.py")
    claude_samples = {int(v) for m, v in cfg["stages"]["main"].get("samples", {}).items() if m.startswith("claude-")}
    add("nSamplesClaude", claude_samples.pop() if len(claude_samples) == 1 else MISSING,
        "samples per main item for each Claude model (sample 1 confirmatory)", src_c)
    max_tok = {cfg["models"][m].get("max_tokens") for m in panel}
    add("maxTokens", f"{max_tok.pop():,}" if len(max_tok) == 1 else MISSING, "max_tokens for every panel model", src_c)

    eff_path = results_dir / stage / "effects.json"
    eff = load_json(eff_path)
    src_e = f"results/{stage}/effects.json"
    models = (eff or {}).get("models", {})
    for m in run_models if not models else list(models):
        M, res = model_macro(m), models.get(m)
        rates = (res or {}).get("rates", {})
        for cell in S.CELLS:
            r = rates.get(cell)
            add(f"acc{M}{CELL_MACRO[cell]}", pct(r[0]) if r else MISSING,
                f"{model_label(m)}: acceptance in {cell}, percent", src_e)
            # 100 minus the rounded acceptance, so text and the rates table always sum to 100
            add(f"rej{M}{CELL_MACRO[cell]}", str(100 - int(pct(r[0]))) if r else MISSING,
                f"{model_label(m)}: share of {cell} items not accepted, percent (100 minus acc)", src_e)
        con = (res or {}).get("contrasts", {})
        for name, stem in CONTRAST_MACRO.items():
            c = con.get(name)
            est = c["estimate"] if c else [None, None, None]
            add(f"{stem}Est{M}", pts(est[0]), f"{model_label(m)}: {name}, percentage points", src_e)
            add(f"{stem}Lo{M}", pts(est[1]), f"{model_label(m)}: {name}, 95% bootstrap lower bound", src_e)
            add(f"{stem}Hi{M}", pts(est[2]), f"{model_label(m)}: {name}, 95% bootstrap upper bound", src_e)
            if name in SC.PRIMARY or name in SC.SECONDARY:
                add(f"{stem}Holm{M}", pval(c.get("holm_p"), relation=True) if c else MISSING,
                    f"{model_label(m)}: {name}, Holm-adjusted p ({'primary' if name in SC.PRIMARY else 'secondary'} family)", src_e)
            if name in SC.PRIMARY:
                add(f"{stem}First{M}", c["only_first"] if c else MISSING, f"{model_label(m)}: discordant pairs favouring {name.split(' - ')[0]}", src_e)
                add(f"{stem}Second{M}", c["only_second"] if c else MISSING, f"{model_label(m)}: discordant pairs favouring {name.split(' - ')[1]}", src_e)
        for stem, key, what in (("fa", SC.FALSE_KEY, "false acceptance (D, R, C-no)"),
                                ("appl", SC.APPLIC_KEY, "applicability errors: acceptance in B-out"),
                                ("ret", SC.RETAIN_KEY, "genuine retention (B-in, R-ctl, C-ok, C-ctl)")):
            v = (res or {}).get(key)
            add(f"{stem}{M}", pct(v[0]) if v else MISSING, f"{model_label(m)}: {what}, percent", src_e)
            for d, D in DIR_MACRO.items():  # descriptive, by direction
                v = ((res or {}).get("by_direction", {}).get(d) or {}).get(key)
                add(f"{stem}{D}{M}", pct(v[0]) if v else MISSING, f"{model_label(m)}: {what}, {d} direction, percent", src_e)
        for name, P in PAIR_MACRO.items():  # descriptive: both members of the pair right
            v = (res or {}).get("paired_accuracy", {}).get(name)
            add(f"pair{P}{M}", pct(v[0]) if v else MISSING, f"{model_label(m)}: paired accuracy {name} (both right), percent", src_e)
            add(f"pair{P}Lo{M}", pct(v[1]) if v else MISSING, f"{model_label(m)}: paired accuracy {name}, Wilson 95% lower bound", src_e)
            add(f"pair{P}Hi{M}", pct(v[2]) if v else MISSING, f"{model_label(m)}: paired accuracy {name}, Wilson 95% upper bound", src_e)
        o = (eff or {}).get("outcomes", {})
        add(f"floorBreak{M}", ("yes" if o["floor_break"][m] else "no") if m in o.get("floor_break", {})
            else "outside panel" if m in outside else MISSING,
            f"{model_label(m)}: prediction F holds", src_e)
        add(f"minAcc{M}", pct(o["min_cell_accuracy"][m]) if m in o.get("min_cell_accuracy", {})
            else "outside panel" if m in outside else MISSING,
            f"{model_label(m)}: lowest accuracy in any cell, percent", src_e)
        planned = by_stage[cfg["stages"].get(stage, {}).get("scenarios", stage)]
        add(f"invalid{M}", planned - sum(r[3] for r in rates.values()) if rates else MISSING,
            f"{model_label(m)}: invalid replies (sample 1) out of {planned} planned items", src_e)

    # Claude models: run-to-run reliability over samples 1-3 and the prompt-cache hit rate (exploratory
    # and infrastructure; neither enters a test).
    stage_dir = results_dir / stage
    rel = (eff or {}).get("reliability", {})
    for m in [m for m in (list(models) or run_models) if m.startswith("claude-")]:
        M = model_macro(m)
        r = rel.get(m)
        add(f"flip{M}", pct(r["flip_rate"]) if r and r.get("flip_rate") is not None else MISSING,
            f"{model_label(m)}: items whose decision differs between samples 1-3, percent (exploratory)", src_e)
        hit = cache_hit_rate(load_rows(stage_dir / f"{m}.jsonl"))
        add(f"cacheHit{M}", pct(hit) if hit is not None else MISSING,
            f"{model_label(m)}: samples 2-3 that read the prompt cache, percent", f"results/{stage}/{m}.jsonl")

    # OpenRouter models: does temperature 0 repeat? The check stage runs their items twice.
    check_cfg = cfg["stages"].get("check", {})
    by_id = {i["id"]: i for i in items}
    for m, k in check_cfg.get("samples", {}).items():
        if int(k) < 2 or m not in run_models:
            continue
        rows = [r for r in load_rows(results_dir / "check" / f"{m}.jsonl") if r["id"] in by_id]
        r = SC.reliability(rows, by_id) if rows else None
        add(f"checkDiffer{model_macro(m)}", pct(r["flip_rate"]) if r and r.get("flip_rate") is not None else MISSING,
            f"{model_label(m)}: check items whose decision differs between the two runs at temperature 0, percent",
            f"results/check/{m}.jsonl")

    # Exploratory implicit-rule arm (PREREG section 4b): label-free paired differences, unadjusted.
    imp_stage = implicit_stage(stage, cfg)
    if imp_stage:
        imp = load_json(results_dir / imp_stage / "effects.json")
        src_i = f"results/{imp_stage}/effects.json"
        imodels = (imp or {}).get("models", {})
        for m in list(imodels) or cfg["stages"][imp_stage]["models"]:
            M, res = model_macro(m), imodels.get(m) or {}
            for name, stem in IMPLICIT_MACRO.items():
                c = res.get("contrasts", {}).get(name)
                est = c["estimate"] if c else [None, None, None]
                add(f"{stem}Est{M}", pts(est[0]), f"{model_label(m)}, implicit arm: {name}, percentage points", src_i)
                add(f"{stem}Lo{M}", pts(est[1]), f"{model_label(m)}, implicit arm: {name}, 95% bootstrap lower bound", src_i)
                add(f"{stem}Hi{M}", pts(est[2]), f"{model_label(m)}, implicit arm: {name}, 95% bootstrap upper bound", src_i)
            for name, P in PAIR_MACRO.items():
                pat = res.get("paired_patterns", {}).get(name)
                exc = name.split(" / ")[1]
                add(f"impOnly{P}{M}", pct(pat[f"accept {exc} only"] / pat["n"]) if pat and pat["n"] else MISSING,
                    f"{model_label(m)}, implicit arm: base scenarios accepting only {exc} of the pair {name}, percent (acceptance pattern, no correctness)", src_i)
            for cell in S.CELLS:
                r = res.get("rates", {}).get(cell)
                add(f"impAcc{M}{CELL_MACRO[cell]}", pct(r[0]) if r else MISSING,
                    f"{model_label(m)}, implicit arm: acceptance in {cell}, percent (no correctness)", src_i)
                c = res.get("explicit_minus_implicit", {}).get(cell)
                add(f"impDiff{CELL_MACRO[cell]}{M}", pts(c["estimate"][0]) if c else MISSING,
                    f"{model_label(m)}: explicit minus implicit acceptance in {cell}, percentage points, paired by base scenario", src_i)
                add(f"impDiff{CELL_MACRO[cell]}Lo{M}", pts(c["estimate"][1]) if c else MISSING,
                    f"{model_label(m)}: explicit minus implicit in {cell}, paired bootstrap 95% lower bound", src_i)
                add(f"impDiff{CELL_MACRO[cell]}Hi{M}", pts(c["estimate"][2]) if c else MISSING,
                    f"{model_label(m)}: explicit minus implicit in {cell}, paired bootstrap 95% upper bound", src_i)
            r = res.get("reliability")
            add(f"impFlip{M}", pct(r["flip_rate"]) if r and r.get("flip_rate") is not None else MISSING,
                f"{model_label(m)}, implicit arm: items whose decision differs between samples 1-3, percent", src_i)
        ests = [c["estimate"][0] for res in imodels.values() for name in IMPLICIT_MACRO
                if (c := res.get("contrasts", {}).get(name))]
        add("impContrastMin", pts(min(ests)) if ests else MISSING,
            "implicit arm: smallest of the three label-free contrasts over all models, percentage points", src_i)
    o = (eff or {}).get("outcomes")
    add("ceilingHolds", ("yes" if o["ceiling"] else "no") if o else MISSING, "outcome C holds for the whole panel", src_e)
    claude = [m for m in (o or {}).get("floor_break", {}) if m.startswith("claude-")]
    add("nFloorBreakClaude", sum(o["floor_break"][m] for m in claude) if o else MISSING,
        "Claude models for which prediction F holds", src_e)
    add("nClaude", len(claude) if o else len([m for m in panel if m.startswith("claude-")]), "Claude models in the panel", src_e if o else src_c)
    other = [m for m in (o or {}).get("floor_break", {}) if not m.startswith("claude-")]
    add("nFloorBreakOther", sum(o["floor_break"][m] for m in other) if o else MISSING,
        "non-Claude panel models for which prediction F holds (descriptive; clarification 1)", src_e)

    def h1_holds(m):  # clarification 2: Holm-adjusted p < 0.05 and estimate > 0
        c = models.get(m, {}).get("contrasts", {}).get(SC.PRIMARY[0])
        return bool(c) and c.get("holm_p") is not None and c["holm_p"] < 0.05 and c["estimate"][0] > 0
    add("nHOneHolds", sum(h1_holds(m) for m in panel) if models else MISSING,
        "panel models for which H1 holds (Holm-adjusted p < 0.05 and estimate > 0; clarification 2)", src_e)
    every_claude = [m for m in models if m.startswith("claude-")]  # all three, Sonnet included
    add("faClaudeMax", half_up(100 * max(models[m][SC.FALSE_KEY][0] for m in every_claude), 1) if every_claude else MISSING,
        "highest false acceptance among the three Claude models, percent, one decimal", src_e)
    add("retClaudeMin", half_up(100 * min(models[m][SC.RETAIN_KEY][0] for m in every_claude), 1) if every_claude else MISSING,
        "lowest genuine retention among the three Claude models, percent, one decimal", src_e)

    # Post hoc, descriptive (18 Nov 2026): counts per scenario template (templates.py). The registered
    # analysis treats the 120 base scenarios as independent; these count templates instead.
    from . import templates as T
    scen = T.scenarios_by_id(scenarios_path)
    scen_stage = cfg["stages"].get(stage, {}).get("scenarios", stage)   # e.g. a test stage reusing main items
    tpls = T.templates(scen, scen_stage)
    btpl = T.base_template(scen, scen_stage)
    src_t = f"results/{stage}/<model>.jsonl via templates.py (post hoc)"
    add("nTemplates", len(tpls), "scenario templates (one per domain and direction)", src_s)
    add("nVariants", (len(btpl) // len(tpls)) if tpls else MISSING, "base scenarios (noun variants) per template", src_s)
    tcounts = {}
    for m in (list(models) or run_models):
        M = model_macro(m)
        dec = T.decisions(results_dir, stage, m, scen)
        per = T.per_template(dec, btpl)
        c = {"DAcc": T.count(per, "D", "accept", tpls), "DRef": T.count(per, "D", "refuse", tpls),
             "BoutRej": T.count(per, "B-out", "refuse", tpls), "BoutAcc": T.count(per, "B-out", "accept", tpls),
             "AAcc": T.count(per, "A", "accept", tpls)}
        h1 = T.discordant(dec, btpl, "C-ctl", "C-no")
        ctl = T.discordant(dec, btpl, "C-ok", "C-ctl")
        c["HOneDisc"] = sum(h1[x][0] > 0 for x in tpls)
        c["CtlGap"] = sum(ctl[x][0] > 0 for x in tpls)
        tcounts[m] = c
        # leave one template out of H1 (post hoc, descriptive; the registered H1 and its Holm p are unchanged)
        loo = T.leave_one_out(dec, btpl, "C-ctl", "C-no")
        diffs = [net / n for net, n in loo.values() if n]
        add(f"looHOneMin{M}", pts(min(diffs)) if diffs else MISSING,
            f"{model_label(m)}: H1 (C-ctl - C-no) with one template omitted, smallest over the omitted templates, points (post hoc)", src_t)
        add(f"looHOneMax{M}", pts(max(diffs)) if diffs else MISSING,
            f"{model_label(m)}: H1 (C-ctl - C-no) with one template omitted, largest over the omitted templates, points (post hoc)", src_t)
        top_t = max(tpls, key=lambda x: h1[x][0] + h1[x][1]) if tpls else None
        net, n_left = loo[top_t] if top_t else (None, None)
        add(f"looHOneTopNet{M}", net if top_t else MISSING,
            f"{model_label(m)}: net H1 discordant pairs (C-ctl only minus C-no only) without the template holding most of them (post hoc)", src_t)
        add(f"looHOneTopN{M}", n_left if top_t else MISSING,
            f"{model_label(m)}: base scenarios left without that template (post hoc)", src_t)
        for key, what in (("DAcc", "templates where most variants accept D"), ("DRef", "templates where most variants refuse D"),
                          ("BoutRej", "templates where most variants reject B-out"), ("BoutAcc", "templates where most variants accept B-out"),
                          ("AAcc", "templates where most variants accept A"),
                          ("HOneDisc", "templates holding at least one H1 discordant pair favouring C-ctl"),
                          ("CtlGap", "templates holding at least one pair accepting C-ok but not C-ctl")):
            add(f"tpl{key}{M}", c[key], f"{model_label(m)}: {what} (post hoc)", src_t)
        bout = {x: per["B-out"][x][0] for x in tpls}
        total, top, _ = T.concentration(bout)
        add(f"tplBoutTop{M}", bout[top] if top else 0, f"{model_label(m)}: B-out acceptances in its most frequent template (post hoc)", src_t)
        add(f"tplBoutTotal{M}", total, f"{model_label(m)}: B-out acceptances, all templates (post hoc)", src_t)
    # clarification flag (PREREG section 4, items 2 and 6: per model and cell, exploratory); valid sample-1 replies
    from . import clarification as CL
    src_cl = f"results/{stage}/clarification.csv (clarification.py)"
    clar = {m: CL.counts(results_dir, stage, m, scen) for m in (list(models) or run_models)}
    for m, cc in clar.items():
        M = model_macro(m)
        for cell, k in cc.items():
            add(f"clar{M}{CELL_MACRO[cell]}", k["flagged"] if k["valid"] else MISSING,
                f"{model_label(m)}: valid sample-1 replies in {cell} that set clarification_required (exploratory)", src_cl)
            add(f"clarN{M}{CELL_MACRO[cell]}", k["valid"] if k["valid"] else MISSING,
                f"{model_label(m)}: valid sample-1 replies in {cell}", src_cl)
    others = [m for m in clar if not m.startswith("claude-") and m in panel]
    tot = {key: sum(clar[m][c][key] for m in others for c in SC.UNAUTHORIZED_CELLS)
           for key in ("valid", "accepted", "accepted_and_flagged")}
    have = bool(others) and tot["valid"] > 0
    add("clarOtherValidDRC", tot["valid"] if have else MISSING,
        "non-Claude panel models: valid sample-1 replies in D, R and C-no, summed", src_cl)
    add("clarOtherAccDRC", tot["accepted"] if have else MISSING,
        "non-Claude panel models: of those, replies accepting the exception (false acceptance), summed", src_cl)
    add("clarOtherAccFlagDRC", tot["accepted_and_flagged"] if have else MISSING,
        "non-Claude panel models: of those acceptances, replies that also set clarification_required (exploratory)", src_cl)
    inv = []
    for m in (list(models) or run_models):
        rates = ((models.get(m) or {}).get("rates") or {})
        planned = by_stage[cfg["stages"].get(stage, {}).get("scenarios", stage)]
        inv.append(planned - sum(r[3] for r in rates.values()) if rates else None)
    add("invalidSummary", (f"none of the {by_stage[cfg['stages'].get(stage, {}).get('scenarios', stage)]} sample-1 replies of any model was invalid"
                           if inv and all(v == 0 for v in inv) else f"invalid sample-1 replies per model ranged from {min(v for v in inv if v is not None)} to {max(v for v in inv if v is not None)}")
        if inv and any(v is not None for v in inv) else MISSING, "invalid replies over all main-stage models, as a phrase", src_e)
    other = [m for m in tcounts if not m.startswith("claude-") and m in panel]
    claude_all = [m for m in tcounts if m.startswith("claude-")]
    add("tplDAccOtherMin", min(tcounts[m]["DAcc"] for m in other) if other else MISSING,
        "fewest templates in which a non-Claude panel model accepts D (post hoc)", src_t)
    add("tplDRefClaudeMin", min(tcounts[m]["DRef"] for m in claude_all) if claude_all else MISSING,
        "fewest templates in which a Claude model refuses D (post hoc)", src_t)
    short = {m: model_label(m).split()[0] if not m.startswith("claude-") else model_label(m).split()[1] for m in tcounts}
    short.update({"gpt-4.1-mini": "GPT-4.1 mini"})
    exc = [short[m] for m in tcounts if tcounts[m]["BoutRej"] < len(tpls)]
    add("tplBoutRejExcept", ", ".join(exc) if exc else "none", "models rejecting B-out in fewer than all templates (post hoc)", src_t)
    if imp_stage:
        for m in (list(imodels) or cfg["stages"][imp_stage]["models"]):
            M = model_macro(m)
            e = T.decisions(results_dir, stage, m, scen)
            i = {(b.removesuffix("-implicit"), c): v for (b, c), v in T.decisions(results_dir, imp_stage, m, scen).items()}
            per_i = T.per_template(i, btpl)
            n_imp = T.count(per_i, "D", "accept", tpls)
            add(f"tplImpDAcc{M}", n_imp,
                f"{model_label(m)}, implicit arm: templates where most variants accept D (post hoc)", src_t)
            words = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
            add(f"tplImpDAccWord{M}", words[n_imp] if n_imp < len(words) else str(n_imp),
                f"{model_label(m)}, implicit arm: the same count as a word (post hoc)", src_t)
            r = T.rises(e, i, btpl, "D")
            ev = {x: r[x][0] for x in tpls}
            total, top, _ = T.concentration(ev)
            add(f"tplImpRiseTop{M}", ev[top] if top else 0, f"{model_label(m)}: implicit-arm D rises in its most frequent template (post hoc)", src_t)
            add(f"tplImpRiseTotal{M}", total, f"{model_label(m)}: implicit-arm D rises, all templates (post hoc)", src_t)

    go = load_json(results_dir / "pilot" / "gonogo.json")
    n_go = sum(bool(v.get("go")) for v in go["models"].values()) if go else None
    n_pilot = len(go["models"]) if go else None
    add("nPilotGo", n_go if go else MISSING, "models that passed the pilot go/no-go (P1)", "results/pilot/gonogo.json")
    add("pilotVerdict", (f"GO for all {n_go} models" if n_go == n_pilot else f"GO for {n_go} of {n_pilot} models")
        if go else MISSING, "pilot go/no-go verdict, counted per model", "results/pilot/gonogo.json")
    ledger = results_dir / "spend-ledger.jsonl"
    spent = sum(json.loads(l).get("cost", 0.0) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()) \
        if ledger.exists() else None
    if ledger.exists():
        days = sorted({json.loads(l)["at"][:10] for l in ledger.read_text(encoding="utf-8").splitlines()
                       if l.strip() and json.loads(l).get("stage") in ("pilot", "main", "main-implicit")})
        if days:
            import datetime as _dt
            d0, d1 = (_dt.date.fromisoformat(d) for d in (days[0], days[-1]))
            fmt = lambda d: f"{d.day} {d.strftime('%B')} {d.year}"
            span = fmt(d0) if d0 == d1 else (f"{d0.day}--{fmt(d1)}" if (d0.month, d0.year) == (d1.month, d1.year) else f"{fmt(d0)} to {fmt(d1)}")
            add("runDates", span, "UTC dates on which the pilot, main and implicit-arm calls ran", "results/spend-ledger.jsonl")
        else:
            add("runDates", MISSING, "UTC dates on which the pilot, main and implicit-arm calls ran", "results/spend-ledger.jsonl")
    add("spendTotal", half_up(spent, 2) if spent is not None else MISSING, "API spend over all stages, USD", "results/spend-ledger.jsonl")
    return out


def write_clarification(stage: str, results_dir: Path, scenarios_path: Path, cfg: dict) -> list[Path]:
    """results/<stage>/clarification.csv for the stage and its implicit twin: per model and cell, valid sample-1
    replies, how many set clarification_required, how many accepted, and how many did both (clarification.py)."""
    from . import clarification as CL
    from . import templates as T
    scen = T.scenarios_by_id(scenarios_path)
    outside = cfg["stages"][stage].get("outside_panel", [])
    written = []
    for st in [stage, implicit_stage(stage, cfg)]:
        if not st or not (results_dir / st).exists():
            continue
        models = [m for m in cfg["stages"][st]["models"] if (results_dir / st / f"{m}.jsonl").exists()]
        if models:
            written.append(CL.write_csv(CL.rows(results_dir, st, models, outside, scen), results_dir / st / "clarification.csv"))
    return written


def write_numbers(rows: list[tuple[str, str, str, str]], outdir: Path) -> tuple[Path, Path, int]:
    outdir.mkdir(parents=True, exist_ok=True)
    tex = ["% Generated by exception-authority/scripts/08_make_numbers.py. Do not edit by hand.",
           "% Meanings and sources: numbers.md. A bold ?? is a result that does not exist yet.",
           r"\providecommand{\missing}{\textbf{??}}"]
    md = ["# Paper numbers", "",
          "Generated by `exception-authority/scripts/08_make_numbers.py`; do not edit by hand. "
          "Use the macro in the text, e.g. `\\priEstOpus{}`. A value of `\\missing{}` (bold ?? in the PDF) "
          "is a result that does not exist yet.", "",
          "| Macro | Value | Meaning | Source |", "|---|---|---|---|"]
    for macro, value, meaning, source in rows:
        assert re.fullmatch(r"[A-Za-z]+", macro), macro
        tex.append(f"\\newcommand{{\\{macro}}}{{{value}}}")
        md.append(f"| `\\{macro}` | {value.replace('|', '/')} | {meaning} | `{source}` |")
    missing = sum(1 for _, v, _, _ in rows if v == MISSING)
    md += ["", f"{len(rows)} macros; {missing} still missing."]
    (outdir / "numbers.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")
    (outdir / "numbers.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return outdir / "numbers.tex", outdir / "numbers.md", missing


# --- tables -----------------------------------------------------------------------------------------

def tex_escape(s: str) -> str:
    return s.replace("\\", r"\textbackslash{}").replace("&", r"\&").replace("%", r"\%").replace("$", r"\$") \
            .replace("#", r"\#").replace("_", r"\_")


def design_table(scenarios_path: Path) -> str:
    """The nine cells with the exact varying wording, taken from one generated base scenario, so the
    table cannot drift from the stimuli."""
    base = "refunds-permissive-v4"
    items = {json.loads(l)["cell"]: json.loads(l) for l in scenarios_path.read_text(encoding="utf-8").splitlines()
             if f'"base": "{base}"' in l}
    spec = S.DOMAINS[("refunds", "permissive")]
    tail = " Exceptions set by a holder of this power must be applied. They are published in the policy feed."
    rows = []
    for cell in S.CELLS:
        it = items[cell]
        record = S.delegation(cell, spec).replace(tail, "").strip() or "(none)"
        entry = it["tool_result"].split(":")[0]
        for part in ("Policy feed entry", f"issued {S.ISSUED}"):
            entry = entry.replace(part, "")
        entry = entry.strip(" ,()") or "(no issuer)"
        case = "outside" if cell == "B-out" else "in scope"
        gold = "exception" if it["derivable"] else "rule"
        rows.append(f"{cell} & {tex_escape(record)} & {tex_escape(entry)} & {case} & {gold} \\\\")
    return "\n".join([
        "% Generated by exception-authority/scripts/06_make_tables.py from resources/scenarios.jsonl "
        f"(base scenario {base}). Do not edit by hand.",
        r"\begin{table*}[t]", r"\centering", r"\small",
        r"\begin{tabular}{@{}l p{0.46\textwidth} p{0.24\textwidth} l l@{}}", r"\toprule",
        r"Cell & Operator's delegation record & Entry's issuer & Case & Gold follows \\", r"\midrule",
        *rows, r"\bottomrule", r"\end{tabular}",
        r"\caption{The nine cells for one base scenario (refunds, permissive). Every cell's prompt also "
        r"contains the shared sentences of Section~\ref{sec:design}: authentication, the role's employee status "
        r"and the closed-world rule. Acceptance means the decision the exception implies, which is a denial "
        r"in the restrictive direction.}",
        r"\label{tab:design}", r"\end{table*}"]) + "\n"


def row_label(m: str, outside: list[str]) -> str:
    """Model name for a table row; a dagger marks a model reported outside H1's Holm family and F."""
    return tex_escape(model_label(m)) + (r"$^\dagger$" if m in outside else "")


# Table 2 shading (presentation only; the printed numbers are unchanged).
# Upper block: distance from the correct answer, in points of the printed acceptance: the acceptance itself
# where the gold answer follows the rule, 100 minus it where it follows the exception. One hue mixed with
# white, ending at ColorBrewer Reds' darkest step, so lightness alone carries the value (colour-blind safe).
# White text from ERR_WHITE_TEXT on: with this endpoint white overtakes black in WCAG contrast at an error
# of 61, so the better of the two never falls below 4.6:1. Lower block: acceptance in neutral grey (at most
# 40% black, where black text keeps 7.4:1), because the implicit arm has no correct answer to measure from.
ERR_RED = "67000D"
ERR_WHITE_TEXT = 61
GREY_MAX = 0.40


def shaded_error(value: str, cell: str) -> str:
    if value == MISSING:
        return value
    v = int(value)
    err = 100 - v if cell in SC.AUTHORIZED_CELLS else v
    text = rf"\textcolor{{white}}{{{value}}}" if err >= ERR_WHITE_TEXT else value
    return rf"\cellcolor{{errred!{err}!white}}{text}"


def shaded_acceptance(value: str) -> str:
    if value == MISSING:
        return value
    return rf"\cellcolor{{black!{round(int(value) * GREY_MAX)}!white}}{value}"


def rates_table(eff: dict | None, cfg: dict, imp: dict | None = None, imp_stage: str | None = None) -> str:
    """Acceptance per cell: the main stage, then (lower block) the exploratory implicit-rule arm."""
    models = list((eff or {}).get("models", {})) or cfg["stages"]["main"]["models"]
    outside = cfg["stages"]["main"].get("outside_panel", [])
    head = " & ".join(S.CELLS)
    lines = []
    for m in models:
        rates = ((eff or {}).get("models", {}).get(m) or {}).get("rates", {})
        cells = " & ".join(shaded_error(pct(rates[c][0]) if c in rates else MISSING, c) for c in S.CELLS)
        lines.append(f"{row_label(m, outside)} & {cells} \\\\")
    if imp_stage:
        imodels = list((imp or {}).get("models", {})) or cfg["stages"][imp_stage]["models"]
        lines += [r"\midrule", r"\multicolumn{" + str(len(S.CELLS) + 1) + r"}{@{}l}{\emph{Implicit-rule arm (exploratory): closed-world rule deleted}} \\"]
        for m in imodels:
            rates = (((imp or {}).get("models", {}).get(m)) or {}).get("rates", {})
            cells = " & ".join(shaded_acceptance(pct(rates[c][0]) if c in rates else MISSING) for c in S.CELLS)
            lines.append(f"{row_label(m, outside)} & {cells} \\\\")
    derivable = ", ".join(c for c in S.CELLS if c in S.DERIVABLE)
    return "\n".join([
        "% Generated by exception-authority/scripts/06_make_tables.py from results/main/effects.json"
        + (f" and results/{imp_stage}/effects.json" if imp_stage else "") + ". Do not edit by hand.",
        r"\begin{table*}[t]", r"\centering", r"\small", r"\definecolor{errred}{HTML}{" + ERR_RED + "}",
        r"\begin{tabular}{@{}l" + "r" * len(S.CELLS) + r"@{}}", r"\toprule",
        f"Model & {head} \\\\", r"\midrule", *lines, r"\bottomrule", r"\end{tabular}",
        r"\caption{Acceptance of the exception per cell, in percent, sample~1, \nBaseMain{} base scenarios per cell. "
        f"Accepting is correct in {derivable}; " +
        r"in D, R and C-no the issuer lacks the power; in B-out the request falls outside the exception. The lower block is the exploratory implicit-rule arm, scored for acceptance only because "
        r"without the closed-world rule the labels that reject the exception are disputable. Shading in the upper block shows distance "
        r"from the correct answer (white = correct); in the implicit-rule block grey shows acceptance, not "
        r"correctness. $^\dagger$Reported outside H1's Holm family and prediction F.}",
        r"\label{tab:rates}", r"\end{table*}"]) + "\n"


CONTROL_COLUMN = "C-ok - C-ctl"  # the negation control H1 is read against (Table 3(b), last column)


def contrasts_rows(eff: dict | None, cfg: dict) -> tuple[str, list[str]]:
    models = list((eff or {}).get("models", {})) or cfg["stages"]["main"]["models"]
    outside = cfg["stages"]["main"].get("outside_panel", [])
    names = [*SC.PRIMARY, *SC.SECONDARY]
    lines = []
    for m in models:
        con = ((eff or {}).get("models", {}).get(m) or {}).get("contrasts", {})
        cells = []
        for n in names:
            c = con.get(n)
            if not c:
                cells.append(MISSING)
            elif m in outside:  # outside the Holm families: unadjusted p, marked
                cells.append(f"{pts(c['estimate'][0])} ({pval(c.get('mcnemar_p'))}$^\\ast$)")
            else:
                cells.append(f"{pts(c['estimate'][0])} ({pval(c.get('holm_p'))})")
        c = con.get(CONTROL_COLUMN)  # a control, never adjusted: the header carries the asterisk
        cells.append(f"{pts(c['estimate'][0])} ({pval(c.get('mcnemar_p'))})" if c else MISSING)
        lines.append(f"{row_label(m, outside)} & " + " & ".join(cells) + r" \\")
    labels = {"C-ctl - C-no": "H1 C-ctl$-$C-no", "R-ctl - R": "H2 R-ctl$-$R", "B-in - B-out": "H3 B-in$-$B-out",
              "D - A": "H4 D$-$A", "C-ok - C-no": "H5 C-ok$-$C-no"}
    head = " & ".join(labels.get(n, n) for n in names) + r" & C-ok$-$C-ctl$^\ast$"
    return head, lines


def summary_rows(eff: dict | None, cfg: dict) -> list[str]:
    models = list((eff or {}).get("models", {})) or cfg["stages"]["main"]["models"]
    outside = cfg["stages"]["main"].get("outside_panel", [])
    lines = []
    for m in models:
        res = ((eff or {}).get("models", {}).get(m) or {})

        def val(key, d=None):
            block = res.get("by_direction", {}).get(d, {}) if d else res
            v = block.get(key)
            return pct(v[0]) if v else MISSING
        cells = [val(SC.FALSE_KEY), val(SC.APPLIC_KEY), val(SC.RETAIN_KEY),
                 val(SC.FALSE_KEY, "permissive"), val(SC.FALSE_KEY, "restrictive"),
                 val(SC.RETAIN_KEY, "permissive"), val(SC.RETAIN_KEY, "restrictive")]
        for name, *_ in SC.PAIRED:
            v = res.get("paired_accuracy", {}).get(name)
            cells.append(pct(v[0]) if v else MISSING)
        lines.append(f"{row_label(m, outside)} & " + " & ".join(cells) + r" \\")
    return lines


def summary_table(eff: dict | None, cfg: dict) -> str:
    """One float, two panels: (a) the two-sided summary, by direction, and paired accuracy (descriptive);
    (b) the paired contrasts with Holm-adjusted p. Absolute rates come first, contrasts second."""
    pair_heads = " & ".join(n.replace(" / ", "/") for n, *_ in SC.PAIRED)
    head_b, lines_b = contrasts_rows(eff, cfg)
    ncol_a = 7 + len(SC.PAIRED)
    return "\n".join([
        "% Generated by exception-authority/scripts/06_make_tables.py from results/main/effects.json. Do not edit by hand.",
        r"\begin{table*}[t]", r"\centering", r"\small", r"\setlength{\tabcolsep}{4pt}",  # (a) fits \textwidth
        r"\begin{tabular}{@{}l" + "r" * ncol_a + r"@{}}", r"\toprule",
        r"\multicolumn{" + str(ncol_a + 1) + r"}{@{}l}{(a) Two-sided summary and paired accuracy, percent (descriptive)} \\",
        r" & \multicolumn{3}{c}{All} & \multicolumn{2}{c}{False acc.} & \multicolumn{2}{c}{Retention} & "
        + r"\multicolumn{" + str(len(SC.PAIRED)) + r"}{c}{Paired accuracy} \\",
        r"\cmidrule[0.5pt](lr){2-4}\cmidrule[0.5pt](lr){5-6}\cmidrule[0.5pt](lr){7-8}\cmidrule[0.5pt](lr){9-" + str(ncol_a + 1) + "}",
        r"Model & False acc. & B-out & Retention & Perm. & Restr. & Perm. & Restr. & " + pair_heads + r" \\",
        r"\midrule", *summary_rows(eff, cfg), r"\bottomrule", r"\end{tabular}",
        r"\par\medskip",
        r"\begin{tabular}{@{}l" + "r" * (len(SC.PRIMARY + SC.SECONDARY) + 1) + r"@{}}", r"\toprule",
        r"\multicolumn{" + str(len(SC.PRIMARY + SC.SECONDARY) + 2) + r"}{@{}l}{(b) Paired contrasts, percentage points (Holm-adjusted exact McNemar $p$)} \\",
        f"Model & {head_b} \\\\", r"\midrule", *lines_b, r"\bottomrule", r"\end{tabular}",
        r"\caption{Main stage, sample~1. (a) False acceptance is acceptance pooled over the cells where the issuer "
        r"lacks the power (D, R, C-no); B-out is acceptance of a valid exception outside its terms (an applicability "
        r"error); retention is acceptance pooled over B-in, R-ctl, C-ok and C-ctl. Perm.\ and Restr.\ split them by "
        r"direction. Paired accuracy: both cells of the pair right. Point estimates here; their registered Wilson 95\% "
        r"intervals are in \texttt{results/\allowbreak main/\allowbreak effects.json} (\texttt{paired\_accuracy}). (b) H1 is the pre-registered primary contrast "
        r"(Holm over the panel's models); H2 revocation, H3 applicability, H4 bare claim and H5 unmatched "
        r"re-delegation form the secondary family (Holm over models and contrasts); C-ok$-$C-ctl is the negation "
        r"control, unadjusted. Differences use counts, so they can differ by 1 from Table~\ref{tab:rates}. "
        r"$^\dagger$Outside H1's Holm "
        r"family and prediction F; $^\ast$unadjusted $p$.}",
        r"\label{tab:summary}", r"\end{table*}"]) + "\n"


def write_tables(stage: str, results_dir: Path, scenarios_path: Path, outdir: Path) -> list[Path]:
    cfg = config()
    eff = load_json(results_dir / stage / "effects.json")
    imp_stage = implicit_stage(stage, cfg)
    imp = load_json(results_dir / imp_stage / "effects.json") if imp_stage else None
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    tables = [("design.tex", design_table(scenarios_path)), ("rates.tex", rates_table(eff, cfg, imp, imp_stage)),
              ("summary.tex", summary_table(eff, cfg))]
    for old in ("contrasts.tex", "implicit.tex"):  # merged into rates.tex and summary.tex (17 Nov)
        (outdir / old).unlink(missing_ok=True)
    for name, text in tables:
        (outdir / name).write_text(text, encoding="utf-8")
        written.append(outdir / name)
    return written


# --- figure -----------------------------------------------------------------------------------------

def write_figure(stage: str, results_dir: Path, outdir: Path) -> Path | None:
    """Acceptance per cell and model with Wilson 95% intervals, read from results/<stage>/summary.csv
    (direction "all"; no statistic is computed here). Two rows of panels by gold answer: row 1 the cells
    whose gold follows the rule (correct acceptance 0%), row 2 those whose gold follows the exception
    (correct acceptance 100%). Models share the y axis in the order of the rates table; colours are
    Okabe-Ito with a distinct marker each, so the figure also reads in grayscale. Needs matplotlib."""
    import csv
    import shutil
    path_csv = results_dir / stage / "summary.csv"
    eff = load_json(results_dir / stage / "effects.json")
    if not path_csv.exists() or not eff:
        print(f"no {path_csv} or effects.json yet: figure not drawn")
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgba
    # Style kit: text at least 9 pt, lines at least 0.5 pt, Times or Helvetica, no Type 3 or CID/Identity-H fonts.
    # matplotlib's own PDF text is always one of those two, so LaTeX sets the labels in Type 1 Helvetica.
    usetex = shutil.which("latex") is not None
    if usetex:
        plt.rcParams.update({"text.usetex": True, "font.family": "sans-serif",
                             "text.latex.preamble": r"\usepackage[T1]{fontenc}\usepackage{helvet}"
                                                    r"\renewcommand{\familydefault}{\sfdefault}"})
    else:
        print("no LaTeX found: the figure's labels use matplotlib's own fonts (same data and layout)")
    tex = lambda text: text.replace("%", r"\%").replace("_", r"\_") if usetex else text

    rows = {(r["model"], r["cell"]): r for r in csv.DictReader(path_csv.open(encoding="utf-8"))
            if r["direction"] == "all"}
    models = list(eff["models"])                       # the rates table's order
    outside = config()["stages"]["main"].get("outside_panel", [])
    labels = [tex(model_label(m)) + ((r"$^\dagger$" if usetex else "\u2020") if m in outside else "") for m in models]
    # Okabe-Ito without yellow (too light for small marks on white), one marker each
    colours = ["#000000", "#E69F00", "#56B4E9", "#009E73", "#0072B2", "#D55E00", "#CC79A7"]
    markers = ["o", "s", "D", "^", "v", "P", "X"]
    # the 35% tint of each colour, blended with white so the marker is opaque
    tint = lambda c: tuple(0.35 * v + 0.65 for v in to_rgba(c)[:3]) + (1.0,)
    layout = [["D", "R", "C-no", "A", "B-out"], ["B-in", "R-ctl", "C-ctl", "C-ok", None]]  # C-ctl under C-no (H1)
    row_names = ["correct: reject", "correct: accept"]

    fig, axes = plt.subplots(2, 5, figsize=(7.0, 2.7), sharey=True)
    ys = list(range(len(models)))
    for r, cells in enumerate(layout):
        for c, cell in enumerate(cells):
            ax = axes[r][c]
            if cell is None:
                ax.axis("off")
                continue
            for k, m in enumerate(models):
                row = rows.get((m, cell))
                if row is None:
                    continue
                x = 100 * float(row["accept_rate"])
                lo, hi = 100 * max(float(row["accept_lo"]), 0.0), 100 * min(float(row["accept_hi"]), 1.0)
                # opaque marker in a light tint of the model's colour with a solid edge, drawn over the
                # interval: an interval narrower than the marker (most cells at 0 or 100) stays hidden
                ax.plot([x], [k], marker=markers[k], markersize=5.0, markerfacecolor=tint(colours[k]),
                        markeredgecolor=colours[k], markeredgewidth=0.7, linestyle="none", zorder=4)
                ax.errorbar([x], [k], xerr=[[x - lo], [hi - x]], fmt="none", ecolor=colours[k],
                            elinewidth=1.0, capsize=2.2, capthick=1.0, zorder=3)
            ax.set_xlim(-8, 108)
            ax.set_xticks([0, 50, 100])
            ax.set_xticklabels(["0", "", "100"])   # 50 stays as an unlabelled tick and gridline
            # one shared 0-100 scale: tick labels only on the bottom row and on B-out, which has no
            # panel beneath it
            ax.set_ylim(len(models) - 0.5, -0.5)
            ax.set_yticks(ys)
            ax.set_yticklabels(labels, fontsize=9)
            ax.tick_params(axis="y", labelleft=(c == 0))   # shared y: hide, never clear, inner labels
            ax.tick_params(axis="x", labelsize=9, length=2, pad=1.5,
                           labelbottom=(r == len(layout) - 1 or layout[r + 1][c] is None))
            ax.tick_params(axis="y", length=0, pad=2)
            ax.grid(axis="x", color="0.88", lw=0.5, zorder=0)
            ax.set_title(cell, fontsize=9, pad=2)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
        axes[r][0].set_ylabel(row_names[r], fontsize=9, labelpad=3)
    fig.supxlabel(tex("Acceptance of the exception (%)"), fontsize=9, y=0.01)
    fig.tight_layout(pad=0.3, h_pad=0.6, w_pad=1.6)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "cells.pdf"
    fig.savefig(path)
    plt.close(fig)
    old = outdir / "two_sided.pdf"   # the scatter this figure replaced (18 Nov)
    if old.exists():
        old.unlink()
    return path


def defaults() -> dict:
    return {"results_dir": RESULTS, "scenarios": SCENARIOS, "manuscript": MANUSCRIPT}
