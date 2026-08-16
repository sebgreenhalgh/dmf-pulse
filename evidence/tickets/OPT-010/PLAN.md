# OPT-010 R2 remediation execution plan

Starting head: `3f1550e3838e6f44c31990dcf83b2bc6ed7dc6fd`  
Required base: `a33f46cd7ec190fbd4959e2840527116f22547ac`

## R2A — contract and gates

Complete. Mapped the ticket/accepted Stage-9 and rules contracts; added regressions for
capability forgery, exact Stage-9 alignment, cutoff ordering, and public-model validation.
The focused optimiser regression suite passed (31 tests) after the final R2A/R2B changes.

## R2B — exact semantics

Complete. Added regressions for the multiple-absence autosub audit pair, independent
legality, global canonical exact ties, aggregate caps, duplicate provided squads, typed
validation, and Decimal-context invariance.

## R2C — artifacts and CLI

Complete for the targeted R2E checkpoint. Added stale-hash, detached-sidecar, collision,
root-confinement and substantive `validate-plan` regressions, including stable malformed-input
and blocked public CLI exit contracts.

The additive R2E governance exception now permits a schema-1.1 test-synthetic fixture under
`fixtures/optimisation/one_gameweek/**`. The fixture is `REFERENCE_ONLY`, non-production,
contains no target-season claims, and binds the static Stage-9 input to its canonical ruleset
hash. Source-tree and isolated installed-wheel one-gameweek and `validate-plan` proofs pass;
the current target-season artifact remains blocked from scoring. See `BLOCKER.md` for the
original conflict and its narrow resolution.

## R2D — independent proof and evidence

Pending the final comprehensive pass. The independent oracle/adversarial suite and critical
branch coverage were strengthened; the strict coverage checker passed with 100%, 100%,
96.55%, 95%, and 96.30% for artifacts, autosubs, legality, tactics, and rules respectively in
the prior checkpoint. R2E deliberately did not rerun or regenerate the full 31-command ledger,
full repository coverage, final evidence set, or review pack.

Status: `R2E_TARGETED_PASS`; run one final comprehensive acceptance/evidence pass, then obtain
a fresh independent Sol review. Human acceptance remains separate.

## R2 final-acceptance attempt — invalidated

The first R2 final ledger was stopped at command 11. Commands 1–10 completed against
implementation commit `aed0b03faa1c614efc42b21cb3b1dcba11c437d7`, with Windows
Application-Control console-shim guards recorded and the repository-supported `python -m`
equivalents used for substantive mypy/pytest execution. The Stage-10 coverage assurance then
reported 87.93% aggregate branch coverage (required 90%) and 94.64% for
`rules/one_gameweek.py` (required 95%).

Focused R2F coverage regressions were added and pass, but this changes the candidate
implementation tree. This ledger is therefore invalidated: do not use it as final acceptance,
do not generate final evidence or a review pack from it, and do not push. Create a new
implementation freeze and run one fresh full ledger after reviewing the focused coverage fix.

## R2F focused coverage freeze

The focused R2F regression file passed (8 tests). The frozen command-10 Stage-10 coverage
selection then passed with 31 tests, 90.23% aggregate branch coverage, and critical branch
coverage of 100% artifacts, 100% autosub evaluator, 96.55% legality, 95% tactics, and 96.43%
rules/one_gameweek. The coverage checker passed with the unchanged 90% aggregate and 95%
critical thresholds. This is a pre-freeze gate only, not final acceptance; one fresh full ledger
remains required after the R2F implementation commit.

## R2G portable acceptance invocation authorization

Windows Application Control blocked the generated `mypy` console launcher with os error 4551,
although the same locked module executed through `uv run python -m mypy`. The repository owner
authorized only the canonical `uv run python -m mypy` and `uv run python -m pytest` invocation
forms in the ticket; no test selection, option, threshold, environment requirement, or semantic
behavior changed. No full acceptance was run after the R2F literal-entry-point blocker. A fresh
31-command ledger is required against the new R2G governance commit.
