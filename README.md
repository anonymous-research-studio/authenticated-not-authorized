# Authenticated Is Not Authorized: Do LLM Agents Check Who May Set a Policy Exception?

Anonymized research artifact for a paper under double-blind review. It contains the pre-registration, the scenario generator, the frozen evaluation protocol, all model responses, the scoring code, and the scripts that produce every number, table and figure in the paper.

## Overview

An agent that reads a rule in a tool result faces two questions: did the named author really issue it, and did that author have the power to make it? This study tests the second. Every policy-feed entry is authentic by construction, and the operator states so. Across nine cells, the entry and the request stay nearly fixed while the operator's delegation record varies: no power, a direct grant, a revoked grant, and a delegation with or without the right to re-delegate, together with length- and negation-matched controls and an applicability control. The main stage has 120 base scenarios (6 templates × 20 noun variants) in each cell, run on a six-model panel from five vendors plus one additional model reported outside the panel, and an exploratory arm without the closed-world rule.

## Repository structure

```
PREREG.md                 pre-registration (frozen 17 Nov 2026; dated changelog at the end)
DESIGN.md                 cell definitions and stimuli
exception-authority/
  README.md               full documentation: setup, every script, spending guard, data format
  resources/              generated scenarios (scenarios.jsonl) and model configuration (config.json)
  src/exception_authority/ generator, label check, runner, spending guard, scorer, output generators
  scripts/                numbered pipeline steps 01-10
  tests/                  unit tests
  results/                model responses, scored analyses and logs (see below)
  FROZEN.json             SHA-256 fingerprints of the frozen protocol files
LICENSE                   MIT
```

## Requirements

- Python 3.11 or later (the results were produced with Python 3.13 on macOS).
- `matplotlib` 3.11.2, only to redraw Figure 1. LaTeX sets the figure's labels in the paper; without LaTeX the script draws the same data with matplotlib's own fonts.
- No API key is needed to reproduce the paper's numbers, tables or figure from the saved responses.

## Reproducing the paper's numbers, tables and Figure 1

All steps read only `exception-authority/resources/` and `exception-authority/results/` and make no API calls.

```bash
cd exception-authority
python3 -m venv .venv
.venv/bin/python -m pip install "matplotlib==3.11.2"
.venv/bin/python scripts/08_make_numbers.py    # number macros, plus the clarification-flag tables
.venv/bin/python scripts/06_make_tables.py     # Tables 1-3
.venv/bin/python scripts/07_make_figures.py    # Figure 1
.venv/bin/python scripts/10_template_facts.py  # per-template results (post hoc)
```

Outputs are written to `manuscript/` at the repository root (`numbers.tex`, `tables/`, `figures/cells.pdf`). To rerun the registered analysis itself from the responses, use `scripts/05_score.py effects main` and `scripts/05_score.py effects main-implicit`. The unit tests run with `.venv/bin/python -m unittest discover -s tests -t .`.

## Results and records

| Path (under `exception-authority/`) | Contents |
|---|---|
| `results/main/`, `results/main-implicit/` | One JSONL file of responses per model, and the scored analysis (`effects.json`) |
| `results/main/effects.json` | The registered analysis; paired accuracy with Wilson 95% intervals under `models.<model>.paired_accuracy` |
| `results/main/clarification.csv`, `results/main-implicit/clarification.csv` | The clarification flag per model and cell (registered as exploratory) |
| `results/template-facts.md` | Post hoc, descriptive results per scenario template |
| `results/pilot/`, `results/check/` | Pilot (go/no-go) and protocol-check stages |
| `results/logs/deviations.md` | Every change made to the paper's result text after the data were read, with diffs |
| `results/logs/prereg-clarifications.md`, `results/logs/results-variants.sha256` | Clarifications fixed before the main-stage data were read, and the hash log of the pre-written result text |
| `results/spend-ledger.jsonl` | Every paid command, with its cap and cost |

Provider request and generation identifiers were removed from the response files for anonymity; no other field was changed.

## Re-running the experiments

Running new model calls requires API keys and incurs cost; the runner refuses to start a paid stage without an explicit cost cap and confirmation. The protocol is frozen: the pilot and main stages refuse to run if any fingerprinted file differs from `FROZEN.json`. See `exception-authority/README.md` for the full procedure.

## License

Code and data are released under the MIT License (see `LICENSE`).
