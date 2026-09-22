# 001P.03 — two-world comparison

The explicit private API consumes one `_PrivateV1PreparedRollingContext` and authenticated
shadow preparation. It creates a literal default baseline service and a fresh shadow service.
Both execute real Stage 8/9/10/11. Current-model Stage-7 projections must already be materialised;
manual-minute inputs are rejected by this comparison route. No acquisition, fitting, activation,
filesystem write or player-allocation resolver is part of the comparison.

Authenticated memory-only records bind all fixture priors/markets/Stage-8 outputs, 24 mandatory
hard controls, every common player/Gameweek projection, decision/FT/bank/tactical signatures,
utility/gain distributions and fixed materiality classification. Missing or divergent controls
fail closed. Candidate-screen equality is reported, not imposed; changed root action plus changed
screen is `CANDIDATE_SCREEN_CONFOUNDED`. The output allowlist omits raw state and player projection
rows. Timings are a nonsemantic envelope; unmeasured preparation time is null, never false zero.

## Completed checks

- Initial complete real model-prepared comparison: 1 passed, 231.83 seconds.
- Expanded real comparison/control population: 20 passed, 567.26 seconds under branch coverage.
- Hardened comparison/control population: 32 passed, 587.21 seconds under branch coverage.
- Latest isolated fixed-policy/control contract population: 13 passed, 2.02 seconds.
- Ruff/format and strict mypy: pass, 307 production source files.
- Fresh independent bounded review: no P0/P1/material P2; see `COMPARISON_PRE_REVIEW.md`.

The real test observes, without replacing numerical outputs:

- exactly one Stage-7 fit and 18 team predictions during preparation;
- no Stage-7 fit/predict/manual reconstruction during either solve;
- actual Stage-8 requests identical after removing only `prior`;
- identical scoreline RNG seed/namespace/index and exact integer quantile draws;
- actual nonzero canonical Stage-11 legal-action counts in both worlds.

Tests also cover unavailable worlds without a solve, context mismatch, source integrity,
control divergence, malformed options, resealed false aggregates, projection/fixture coverage,
partial-market classification, mutation during a solve and safe-summary authentication.

Five required behaviors have already been observed with fixed synthetic sources and actual
solves. Their acceptance definitions are included for resumability; the full locked-case rerun
and final fresh direct coverage are in progress and belong to .04/.05 acceptance. No complete
ticket or final coverage claim is made here. Source variants change generated observations only,
never the accepted statistical model or historical hyperparameter selection.

CI's existing static module-weight hints now account for the new expensive tests. Test selection,
module grouping, timeouts, permissions, database contracts and coverage thresholds are unchanged.

No live provider action, private live persistence, ordinary `dmf pulse` change, PR, merge, tag,
or production activation occurred.
