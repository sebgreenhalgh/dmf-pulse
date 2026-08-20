# GW1 Session 3 - initial squad, XI, bench and captaincy

## Result

- Engineering engine - `COMPLETE`.
- Real current 15-player decision - `NOT_EXECUTED / OPERATOR_INPUT_REQUIRED`.
- Chips and FPL account action - `NOT_USED / NOT_IMPLEMENTED`.

## Historical blocker retest

The historical `MANAGER_TACTICS_CAPABILITY_UNAVAILABLE` condition remained valid
for target VERIFIED rules in the existing production path. It was not globally
weakened. `PRODUCTION` still requires ACTIVE `FULL_SEASON` authority.

The target source now compiles an exact, source-backed, production-eligible,
blocker-free `GW1_INITIAL_SQUAD` capability at hash
`b2e1268800d793c48a92299b49a60b69aab6ebbfb330708658d3386ea623549a`.
Only `PRESEASON_DECISION_SUPPORT` may use that exact artifact. A missing,
different, blocked or detached capability still returns the historical error.

## Optimisation slice

The accepted Stage-10 legality, autosub, captain/vice and reporting semantics are
retained. The new preseason solver factorizes base XI/bench scenario evaluation
from captain/vice expectations, then independently reconstructs every retained
winner through the original tactical evaluator. This is algebraically exact for
the declared search scope; TEST, REPLAY and PRODUCTION continue to use the
legacy solver route.

The permanent 1,000-scenario acceptance proves a legal 15-player declared pool,
£75.0 spend, £25.0 bank, legal XI/formation/bench, distinct captain and vice,
363,000 implied exact tactics, all 1,000 scenario scores, and exact objective
reconciliation inside the 20-million-operation policy. The unfactorized
cross-product would require 363 million scenario/tactic operations.

For a real projection, a deterministic beam selects three distinct legal
15-player pools from accepted Stage-9 distributions:

- `EXPECTED_POINTS` - mean, P(start), then P(appearance);
- `CONSERVATIVE` - p10, P(appearance), then lower uncertainty;
- `HIGHER_UPSIDE` - p90, P(10+), then mean.

Every pool enforces compiled budget, position quotas and club maximum before it
is passed to Stage 10. Stage 10 then exactly selects XI, bench goalkeeper, bench
order, captain and vice within that declared pool and returns manager-point
distribution, spend and bank. The output states
`NO_GLOBAL_OPTIMUM_CLAIM_OUTSIDE_THREE_BOUNDED_PORTFOLIOS`; portfolio selection
is heuristic, while tactics within each declared pool are exact.

## Validation

- Focused preseason tests include exact-capability rejection/acceptance,
  unchanged production blocker, 1,000-scenario exact tactics, and three distinct
  legal beam portfolios.
- One-Gameweek inherited/new Stage-10 group - `43 passed` in `681.17s`, including
  service, legality, semantics, Hypothesis/oracle equivalence, performance and
  assurance suites.
- The import-first rules gate found and remediated an eager-package circular
  import; a clean process now imports rules then current optimisation safely.
- Final exact-SHA Linux validation - `PENDING_FINAL_PUBLICATION`.
