# RANK-015 Stage 15 progress

- Ticket: `RANK-015`
- Immutable parent: `c53a1dfae952f481c1e885200ebf6120e4b63c24`
- Branch: `stage/A15/RANK-015-rank-aware-strategy`
- Engineering status: `IN_PROGRESS`
- Production activation: `FAIL_CLOSED_TO_PURE_POINTS`
- Human acceptance: `false`
- Pull request: none
- Merge: none
- Accepted tag: none

## Non-negotiable invariants

- Rank strategy changes decision utility only. Raw football, minutes, price and FPL-points
  projections must remain hash-identical between points and rank modes.
- Sebastian and every represented opponent are scored from the same shared football scenario.
- Effective ownership is the weighted mean counted manager multiplier, never raw ownership.
- Rival future actions are cutoff-safe probabilistic scenarios, not perfect Pulse clones.
- Rank-aware activation fails closed when rules, target, rights, cohort, opponent or confidence
  gates are invalid.
- Only synthetic, repository-approved or authorised named-rival data are permitted; no mass
  manager scraping or final-rank hindsight cohorts.

## Baseline

- Immutable parent verified against `origin/main` before branch creation.
- Branch was created directly from the immutable parent and pushed before implementation.
- Accepted Stage-14 targeted matrix: `399 passed in 10.21s`.
- No Stage-15 `rank_strategy` package or `dmf rank` CLI existed at the parent.
- A temporary branch-only source-export workflow was required because the execution container
  could not resolve GitHub. It will be deleted from the final tree before handoff.

## Checkpoints

| Checkpoint | Status | Capability SHA | Verification |
|---|---|---|---|
| 15.01 manager multipliers / EO | IN_PROGRESS | — | — |
| 15.02 exact named mini-league | NOT_STARTED | — | — |
| 15.03 baseline opponent model | NOT_STARTED | — | — |
| 15.04 target / rank utility | NOT_STARTED | — | — |
| 15.05 synthetic overall cohort | NOT_STARTED | — | — |
| 15.06 service / CLI / evidence | NOT_STARTED | — | — |

## Required final status

`IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`

`FULL_REPOSITORY_PYTEST = NOT_RUN_BY_DESIGN — DEFERRED_TO_INDEPENDENT_SOL_REVIEW`
