# PRIVATE-V1-ONE-COMMAND-001J engineering acceptance

The private current Stage-7 adapter represents the complete provider-mapped club roster in every
one of its exact 256 samples. Every sample contains one occurrence of every mapped player, exactly
11 START, exactly 9 BENCH, all remaining players OUT, one starting goalkeeper, one bench
goalkeeper, hard-ineligible players OUT, and exactly 990 reconciled pre-dismissal team-minutes.
No player is pruned and no observed-size cap is introduced.

The full roster is semantic-hash input even when additional players are always zero-minute OUT. A
42-, 43-, and 44-player current sample hashes differently, and changing only one OUT identity
changes the hash. The operator-authored manual transient contract remains separate and continues
to reject 41 players at its governed maximum of 40.

The interactive command retains the outer Stage-7 timer and emits fixed, disclosure-safe progress
for each fixture's home prediction, away prediction, and scenario reconciliation. The fixture
completion duration spans all three operations. A predictor-returned BLOCKED result preserves its
safe stable error code; predictor exceptions remain `CURRENT_MINUTES_MODEL_BLOCKED`; adapter or
reconciliation failures use `CURRENT_STAGE7_SCENARIO_ROSTER_INVALID`.

Acceptance requires 39/40/41/43 and larger current-roster tests; the exact 43-player/all-256 live
shape; missing, extra, duplicate, hard-ineligible and goalkeeper failures; manual-boundary and
hash regressions; ordered progress and disclosure tests; affected suites; branch coverage; Ruff;
strict mypy; frozen sync; build and clean-wheel verification; repository and secret validation;
exact-final-SHA CI; and the literal live retry when existing runtime inputs are present.
