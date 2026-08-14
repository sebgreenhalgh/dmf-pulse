# Stage 9 specification reconciliation

## Requirements implemented

- Pure scenario-level FPL scoring transform with one immutable rules identity.
- Exact integer components/BPS/totals, including negative point support.
- Complete fixture participant universe and joint competition-rank BPS/bonus ties.
- No expected-BPS ranking and no independent expected-component summation.
- Exact Stage 8 team-score conservation and participation-bound player events.
- Weighted PMFs, quantiles, thresholds, covariance/correlation, and complete joint
  player-by-scenario matrices.
- Explicit Monte Carlo numerical error separate from football uncertainty.
- Deterministic root seed and named stream lineage with partition invariance.
- Cutoff, Stage 7 context/player, Stage 8 result, ruleset, and artifact identities.
- Raw player points only; no manager-state transforms.

## Accepted decisions applied

- ADR-PTS-001: scenario transform rather than direct xP regression.
- ADR-PTS-002: bonus from joint scenario BPS ranking.
- ADR-PTS-003: explicit Monte Carlo error.
- ADR-PTS-004: preserve full joint dependence.
- ADR-GOV-003/004: activation gates and no hidden rule constants.
- TEMP-EVT-002/TEMP-PTS-001: public, replaceable degraded baselines.

## Reconciled candidate assumptions

1. The provisional Stage 8 cell/alias model was replaced by the final accepted
   `JointScoreDistribution` matrix and exact 12-place probability semantics.
2. Final Stage 7 team/player identities and `Stage7MinutesContext` are embedded and
   checked; Stage 9 defines only the missing sampled participation-path input.
3. The reference test oracle now uses the accepted compiled rules adapter rather than
   duplicated arithmetic.
4. NumPy was removed in favor of a bounded standard-library deterministic RNG layer.
5. Reference configs are packaged as importable resources and byte-checked against
   their canonical configuration files.
6. Canonical JSON fulfills the bounded immutable matrix contract without a new
   Parquet dependency or relational migration.

## Decisions remaining outside integration

- verification, approval, and activation of the target 2026/27 ruleset;
- calibrated production scorer/assist/save/defensive/BPS models;
- sequential multiple-fixture readiness transitions;
- any future high-volume artifact-format decision.
