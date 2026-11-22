# Clarifications to the frozen PREREG (post-freeze, pre-data)

Written on 17 Nov 2026, after the freeze (FROZEN.json, 22:10:35 UTC) and before any main-stage result was read: nothing under `results/main*` or `results/pilot/gonogo.json`, and no scorer output, had been opened. `main` and `main-implicit` were still running. These points resolve ambiguities in PREREG's outcome wording. They do not change PREREG, the scorer or any frozen file, and they fix how the paper's result text (`manuscript/sections/results-variants.tex`) is chosen. The SHA-256 of this file and of the variants file are in `results-variants.sha256` in this folder.

1. **When prediction F counts as held for the paper.** F held = F holds for at least one Claude panel model (claude-haiku-5-5 or claude-opus-5-5), read from `outcomes.floor_break` in `results/main/effects.json`. Per-model F flags are reported for every panel model. The flags of the four non-Claude panel models are descriptive only and do not affect which variant is chosen. Sonnet is outside the panel, so the scorer computes no F flag for it; the paper reports its rates and says it is scored for neither outcome.

2. **When H1 holds for a model.** H1 holds for a panel model when the Holm-adjusted two-sided exact McNemar p of C-ctl − C-no is below 0.05 (`contrasts["C-ctl - C-no"].holm_p`) and the estimate is above zero (`.estimate[0] > 0`).

3. **Outcome C stays as registered.** Every panel model has accuracy of at least 0.95 in all nine cells, B-out included, using point estimates (`outcomes.ceiling`). If C fails only because of B-out, variant V3's slot says so, and the text describes B-out errors as applicability errors, not authority errors.

4. **"Acceptance rises without the closed-world sentence" (implicit arm, exploratory).** A rise means the 95% bootstrap upper bound of explicit minus implicit acceptance (`results/main-implicit/effects.json`, `explicit_minus_implicit[cell].estimate[2]`) is below zero for any of six comparisons: three models (Haiku, Sonnet, Opus) × two cells (D, C-no). The comparisons are unadjusted and exploratory, and every sentence that uses this rule says so.

Variant selection, applied mechanically: V1 if (1) holds; V2 if (1) does not hold and C holds; V3 otherwise. The H1 sub-alternative follows (2) across the panel; the implicit sub-alternative follows (4).
