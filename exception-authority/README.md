# exception-authority

A minimal-pair test of whether LLM agents separate an authentic issuer's statement from that issuer's authority: in ABLP's terms, "A says φ" from "A controls φ". An agent reads an authenticated policy-feed entry that grants an exception. The entry stays fixed while the operator's delegation record varies across nine cells: no power, a direct grant, out of scope, revoked, re-delegation allowed or forbidden, and two length and negation controls. Each cell's gold label follows from the record alone.

The code generates the scenarios, runs them against Claude models (Anthropic SDK) and OpenAI-compatible models (OpenRouter), and keeps spending under a hard cap. It checks protocol health without showing outcome rates, scores the pre-registered analysis, and writes every number, table and figure the paper cites.

The study rules are in [../PREREG.md](../PREREG.md) and the cells in [../DESIGN.md](../DESIGN.md).

## Results

All stages have run (check, pilot, main and main-implicit, 17–18 Nov 2026), with no protocol problems and no deviations from `../PREREG.md`. Scored results are in `results/main/effects.json` and `results/main-implicit/effects.json`. The scorer output, the post-data edits to the result text (`deviations.md`) and the hashes are in `results/logs/`. The free gate (`scripts/run_smoke.sh`) passes: self-tests, the unit tests, the scripted smoke stage and its health check.

Outcome-selection rules and clarifications were fixed before the main-stage data were read: see results/logs/prereg-clarifications.md and results/logs/results-variants.sha256.

### Files the paper cites

| File | Contents |
|---|---|
| `results/main/effects.json` | The registered analysis (`scripts/05_score.py effects main`). Under `models.<model>.paired_accuracy`, each pair (`C-no / C-ctl`, `C-no / C-ok`, `R / R-ctl`, `B-out / B-in`) is `[rate, Wilson 95% lower, Wilson 95% upper, pairs]`; Table 3(a) prints only the rates |
| `results/main/clarification.csv` | The clarification flag per model and cell (PREREG section 4, items 2 and 6; exploratory): sample-1 valid replies (`valid`), how many set `clarification_required` (`flagged`), accepted the exception (`accepted`), or both (`accepted_and_flagged`). `panel` marks Claude Sonnet 5.5 as outside the confirmatory panel |
| `results/main-implicit/clarification.csv` | The same counts for the exploratory implicit-rule arm (PREREG section 4b) |
| `results/template-facts.md` | Post hoc, descriptive: results per scenario template, including H1 discordant pairs in each direction per template |

## Rebuild the paper's numbers, tables and Figure 1 (free, no API calls)

The anonymous archive unzips to `exception-authority/`, `PREREG.md` and `DESIGN.md`. Prerequisites: Python 3.11 or later; matplotlib only for Figure 1 (the figure in the paper was made with matplotlib 3.11.2 on Python 3.13, with LaTeX setting its labels; without LaTeX the script draws the same data with matplotlib's own fonts). No API key is read. From the unzipped folder:

```bash
cd exception-authority
python3 -m venv .venv
.venv/bin/python -m pip install "matplotlib==3.11.2"
.venv/bin/python scripts/08_make_numbers.py    # ../manuscript/numbers.tex, numbers.md; results/main/clarification.csv, results/main-implicit/clarification.csv
.venv/bin/python scripts/06_make_tables.py     # ../manuscript/tables/design.tex, rates.tex, summary.tex (Tables 1-3)
.venv/bin/python scripts/07_make_figures.py    # ../manuscript/figures/cells.pdf (Figure 1)
.venv/bin/python scripts/10_template_facts.py  # results/template-facts.md (post hoc)
```

The scripts read only `resources/` and `results/` in this folder and write into `../manuscript/`, next to `exception-authority/` (created if missing). The LaTeX sources of the paper are not in the archive.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt     # anthropic, openai; matplotlib for figures
.venv/bin/python -m pip install -e .                    # optional: scripts and tests also run without it
scripts/run_smoke.sh                                    # free: self-tests, unit tests, smoke stage, health
```

**Keys:** `.env` in this folder, as `ANTHROPIC_API_KEY=...` and `OPENROUTER_API_KEY=...`. A variable already set in the shell wins. Keys are passed to the SDKs explicitly, so a stored login on another account is never billed. `.env` is in `.gitignore`, and the export script refuses to include it.

## Steps

Run from this folder with `.venv/bin/python`. Steps 02 and 03 (and the stage-specific uses of 04 and 05) are the protocol; 06–09 only read results.

| Step | Command | What it does |
|---|---|---|
| 01 | `scripts/01_generate_scenarios.py [--selftest]` | Writes `resources/scenarios.jsonl`: 1,350 items, 9 cells × 150 base scenarios (check 54, pilot 216, main 1,080 per model). The self-test checks every minimal pair, the shared sentences and balance, and recomputes every gold label from the prompt text with `derive.py` |
| 02 | `scripts/02_run_stage.py STAGE [--model M] [--dry-run [--show N]] [--max-cost USD] [--yes]` | Runs a stage. `smoke` is scripted and free; `check`, `pilot` and `main` are paid. Always `--dry-run` first |
| 03 | `scripts/03_freeze_protocol.py` | Fingerprints the protocol into `FROZEN.json`. Pilot and main refuse to run if a frozen file changed |
| 04 | `scripts/04_health_check.py STAGE [--model M]` | Missing, refused, truncated or unparsed replies, wrong served model or host, mixed settings, tokens and cost. Never shows outcome rates |
| 05 | `scripts/05_score.py summary\|gonogo\|effects STAGE` | Per-cell rates; the pilot go/no-go (never reads cell D; `gonogo.json`); the main analysis with Holm and outcomes F and C (`effects.json`) |
| 06 | `scripts/06_make_tables.py` | `../manuscript/tables/`: `design.tex` (the nine cells, quoted from the scenarios), `rates.tex`, `summary.tex` |
| 07 | `scripts/07_make_figures.py` | `../manuscript/figures/cells.pdf`: acceptance per cell and model with Wilson 95% intervals, two rows of panels by gold answer |
| 08 | `scripts/08_make_numbers.py` | `../manuscript/numbers.tex` and `numbers.md`: a macro for every number in the paper, with meaning and source. A result that does not exist yet prints as a bold ??. Also writes `results/main/clarification.csv` and `results/main-implicit/clarification.csv` |
| 09 | `scripts/09_export_anonymous.sh` | `../submission/exception-authority-anonymous.zip`, without `.env`, `.venv` or caches. Drops provider request and generation ids from the exported results (`scripts/scrub_export.py`; nothing else in a row changes). Refuses if it finds a name, a local path, a key or a remaining id |
| 10 | `scripts/10_template_facts.py [--out FILE]` | Post hoc, descriptive (added 18 Nov 2026, after the main data were read): results per scenario template (6 templates, one per domain and direction, × 20 noun variants), the number of templates showing each key pattern, and effects that come from a single template; `results/template-facts.md` by default |
| gate | `scripts/run_smoke.sh` | The free gate |
| gate | `scripts/run_check_anthropic.sh CAP_HS CAP_OPUS CAP_IMPLICIT` | Check stage on Haiku, Sonnet and Opus, explicit and implicit, with health checks and a main-stage re-estimate. Asks for a typed yes before each paid command |
| gate | `scripts/run_check.sh CAP_CHEAP CAP_OPUS` | Check stage: the five cheaper models under one cap, then Opus under its own, each with health checks. It asks for a typed yes and never passes `--yes` |

### Running order

```bash
PY=.venv/bin/python
scripts/run_smoke.sh                                   # free
$PY scripts/02_run_stage.py check --dry-run --show 1   # estimate, one full request, key check
scripts/run_check_anthropic.sh 2.75 5.00 7.50          # Anthropic models first, no OpenRouter key needed
scripts/run_check.sh 1.50 5.00                         # then the OpenRouter models; done items are skipped
# read ~10 replies in results/check/*.jsonl; pin the Gemini and Qwen hosts in resources/config.json
# review ../PREREG.md, then:
$PY scripts/03_freeze_protocol.py
$PY scripts/02_run_stage.py pilot --dry-run            # estimates now use the check's real token counts
$PY scripts/02_run_stage.py pilot --model llama-3.3-70b --max-cost <approved>      # cheapest first
...
$PY scripts/04_health_check.py pilot && $PY scripts/05_score.py gonogo pilot
$PY scripts/02_run_stage.py main --model <each GO model> --max-cost <approved>
$PY scripts/04_health_check.py main && $PY scripts/05_score.py effects main
cd ../manuscript && make outputs && make && make check
```

Dry-run estimates on 17 Nov, using the deliberately high default of 2,000 output tokens per reply, for six models at 9 cells each:

| Stage | Items per model | Five cheaper models together | Opus 5.5 | All six | Worst case |
|---|---|---|---|---|---|
| check | 54 | $0.70 | $2.36 | $3.06 | $6.16 |
| pilot | 216 | $2.83 | $9.43 | $12.25 | $24.64 |
| main | 1,080 | $14.13 | $47.15 | $61.28 | $123.21 |

The worst case assumes every reply hits `max_tokens`. After the check, estimates come from logged token counts. Most of the cost is Opus's thinking tokens, so the Opus main run is the step to look at hardest.

Actual API spend over every paid command was $40.60: the sum of `cost` in `results/spend-ledger.jsonl`, covering the check, pilot, main and implicit-arm stages for every model plus three test calls under $0.001 (`cache-test`, `pin-test`).

## Spending guard ([src/exception_authority/guard.py](src/exception_authority/guard.py))

- **Before sending:** a paid run refuses to start without `--max-cost` and a typed `yes`. Use `--yes` only after the run and its cap are approved.
- **Cap:** before each request, its worst case (twice the input estimate plus a full `max_tokens` of output) is reserved against the cap. A request that could cross the cap is not sent, so spend stays under the cap even with 4 parallel workers.
- **Stops:**
  - an account or request error (key, credit, unknown model, a 400 from a malformed request) stops the model's run at once;
  - so do ten failures in a row;
  - once 20 replies have finished, the run stops if replies cost more than 1.5 times the estimate on average.
- **Ledger:** every paid command is appended to `results/spend-ledger.jsonl`, including runs that stop early or are interrupted. Ctrl-C starts nothing new and keeps the replies already in flight.
- **No mixing:**
  - a results file never mixes settings: changing effort, `max_tokens`, the tool or the output schema starts a new file;
  - scenario text that changed after rows were written also stops the run;
  - the pilot and main stages refuse to run if any frozen file changed since the freeze.
- **Resume and retries:** reruns skip finished items. A failed item is retried on rerun, up to 3 attempts in all.
- **Prompt caching:** the Claude `main` and `main-implicit` stages cache each item's prompt; samples 2 and later read the cache (hit rate 100%). Caching does not change the input the model sees, so it does not change outputs; it lowers cost and latency.

## What each row records

- **The request:** item id, sample number, stage, cell and base scenario; the feed protocol, the number of calls and any protocol deviation; the model requested and the model that served it; effort and `max_tokens`; usage per call.
- **Integrity:** a settings hash and a scenario-text hash.
- **The reply:** request id, stop reason and refusal category, input and output tokens, cost, raw text, parsed decision and clarification flag, and whether it parsed.
- **Provenance:** hashes of the runner, guard and scenarios; SDK and Python versions; whether the protocol was frozen.

## Layout

```
README.md, LICENSE (MIT), pyproject.toml, requirements.txt
resources/config.json      model registry, prices, settings, stages (frozen)
resources/scenarios.jsonl  generated by step 01 (frozen)
src/exception_authority/
  paths.py                 where everything is read and written
  scenarios.py             the generator and its self-test; the gold rule is in its docstring (frozen)
  runner.py                requests, callers, resume, freeze, provenance (frozen)
  guard.py                 the spending guard (frozen)
  scoring.py               rates, go/no-go, contrasts, Holm, outcomes F and C (frozen)
  templates.py             post-hoc counts per scenario template (not part of the registered analysis)
  clarification.py         clarification flag per model and cell (exploratory; PREREG section 4, items 2 and 6)
  health.py                protocol health, no outcome rates
  outputs.py               numbers.tex, tables, figure
scripts/                   numbered steps 01-09 and the gate scripts
tests/                     unittest suite (scripted models only): python -m unittest discover -s tests -t .
results/<stage>/           <model>.jsonl, <model>.errors.jsonl, summary.csv, gonogo.json, effects.json
results/spend-ledger.jsonl every paid command
FROZEN.json                written by step 03
```

## Not used, and why

- **Message Batches (half price):** the per-request reservation and the drift and failure stops do not apply to a batch, and a batch can take up to 24 hours. That is too long two days before the Nov 20 deadline. Reconsider only if the main estimate after the check is large.
- **Refusal fallbacks:** a fallback answers with another model, which would mix models in one results file.
