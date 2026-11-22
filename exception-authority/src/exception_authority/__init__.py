"""Says is not controls: do LLM agents check whether an authentic issuer had the power to make a rule?

Modules:
  scenarios  generate the nine-cell minimal-pair scenarios (the gold rule is in its docstring)
  guard      spending guard: estimates, hard cap, per-request worst-case reservation, stops, ledger
  runner     run one stage against scripted, Anthropic or OpenAI-compatible models; freeze the protocol
  health     protocol health of a stage's results, with no outcome rates
  scoring    per-cell rates, the pilot go/no-go, paired contrasts with Holm, pre-registered outcomes
  outputs    LaTeX numbers, tables and figures for the manuscript, generated from the results
"""

__version__ = "0.1.0"
