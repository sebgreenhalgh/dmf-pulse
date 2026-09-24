# Redundancy review and removal mapping

## Method

All 5,304 Phase-1 nodes were collected before modification. Test-function bodies
were compared by exact normalized AST, and the high-cost modules were reviewed
against their fixtures, production paths, and assertion oracles. Similar names,
age, coverage percentage, and runtime were not treated as removal evidence.

The exact-body scan found five clusters. Three clusters were retained because the
same small assertion wrapper intentionally gives semantically distinct parameter
groups their own test names (manager declaration shapes, horizon JSON size/depth,
and historical parent-file domains). Two clusters contained genuinely redundant
states and were rationalised.

## Removed node 1: superseded production capability gate

- Removed: `tests/unit/optimisation/test_service.py::test_production_current_target_fails_closed`
- Successor: `tests/contract/optimisation/test_r2a_contract_gates.py::test_forged_capability_cannot_change_current_production_gate`
- Production path: `optimise_one_gameweek` -> production one-gameweek rules capability gate.
- Evidence: the removed and retained functions had byte-equivalent normalized AST
  bodies: the same synthetic ruleset, request, projection, status assertion, and
  `MANAGER_TACTICS_CAPABILITY_UNAVAILABLE` oracle.
- Strength: the retained test is in the public contract suite and sits beside the
  later R2A capability-forgery and cutoff-lineage gates.
- Counterfactual: temporarily changing the production error to
  `MANAGER_TACTICS_CAPABILITY_MUTATED` made the retained successor fail with the
  exact expected/original code mismatch. Restoring the source made it pass. The
  production file is byte-identical to the Phase-1 parent in the final diff.

## Removed node 2: duplicate invalid-authority parameter

- Removed: the `wrong/wrong` parameter instance from the historical
  `test_unknown_l4_pair_fails_closed` function.
- Successor: `test_no_unknown_l1_l2_l3_or_l4_pair_can_authorize[wrong-wrong]`.
- Production path: `TeamStrengthL1ObservationService.run` authority validation,
  before credential inspection or provider access.
- Evidence: both old parameter instances called the same `blocked("wrong", "wrong")`
  helper and asserted the same `AUTHORITY_INVALID` oracle. The merged parameter list
  retains each distinct wrong L1, L2, L3, and all-wrong state exactly once.
- Focused result: the complete consolidated L2 module and retained optimiser
  successor passed in the 29-test focused run.

## Accounting

- Baseline nodes: 5,304.
- Removed redundant nodes: 2.
- Added cadence-planner regression nodes: 2.
- Final nodes: 5,304.
- Distinct baseline behavioral states lost: 0.
- Tests moved exclusively to nightly: 0.
- Production files changed in final diff: 0.

The result does not chase a lower headline count. It replaces two redundant nodes
with two tests for the new selection architecture while preserving the exact total
and every distinct baseline state.
