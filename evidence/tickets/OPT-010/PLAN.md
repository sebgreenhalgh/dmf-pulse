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

## R2H acceptance-order authorization

The first R2G ledger was invalidated at command 20. Commands 1–18 passed with the established
TEST database environment, but the former command 19 had correctly torn that database down
before repository-wide coverage. That suite contains database-requiring integration tests and
also checks that the repository manifest reflects the current governed bytes; the former
manifest-generation command was scheduled after it.

The repository owner authorized a narrow order-only amendment that retains exactly 31 commands:
the existing manifest command moves from ordinal 24 to 19, repository coverage remains ordinal
20 while the TEST database is available, and the existing mandatory teardown moves from ordinal
19 to 21. No command literal other than its position, target, assertion, threshold, fixture,
dependency, production rule, or optimiser semantic changed. The invalidated R2G generated
coverage and transcripts were removed; this history remains authoritative. A fresh 31-command
ledger is required against the R2H governance commit.

## R2H continuation acceptance — complete

The R2H full acceptance run reached command 20 with commands 1–19 proven PASS against
implementation/governance revision `79102d41fc5d4e2c70d8251d643b705602573045` and tree
`f1d5987331517e3aaae794594923c80f16e7ec3a`, then an external one-hour runner limit terminated
the still-running repository-wide command. No semantic repository byte changed after that
checkpoint.

The unfinished command-20 semantic gate was completed once under the authorized PATH B
continuation: exact collection proved a disjoint union of 1,868 non-performance pytest nodes,
all successful shards completed, and the final aggregate repository coverage command passed at
91.84% combined line/statement coverage (87.37% branch coverage). The previous environment
teardown record lacked its transcript, so only that idempotent command was specifically rerun
and recorded; this was not a broad acceptance restart. Commands 22–31 then passed with final
retry records for generated-evidence-only manifest, secret-scan, and whitespace repairs.

Status: `READY_FOR_INDEPENDENT_SOL_REREVIEW`. The final evidence is explicitly a
`CONTINUATION_AFTER_INFRASTRUCTURE_TIMEOUT`; it does not claim an uninterrupted 31-command
wall-clock run. Implementation self-acceptance remains false, and independent Sol review plus
human acceptance remain required.

## R3 independent-rereview remediation

The fresh independent rereview identified contract, lineage, validation, artifact-safety,
factory-semantics, and coverage gaps. The remediation aligns the public optimiser models with
the frozen SOL plan, binds request and Stage-9 lineage hashes, validates the Stage-9 player
universe before search, performs independent exact plan recomputation, rejects artifact leaf
symlinks (including the race branch), preserves explicit appearance independently of points,
and strengthens exact public-contract and artifact-assurance regressions.

The first complete R3 acceptance attempt against
`1782171fc8be5691d96d30386786a36eaf0b3b6c` passed commands 1–10 and then truthfully failed
command 11 because critical branch coverage for `optimisation/artifacts.py` was 85.71%, below
the frozen 95% threshold. A tests-only follow-up covered the missing safety branches and was
committed as `590740bfc6f139b193550dc32047625a24d3e29f`.

The final R3B ledger then executed all 31 literal commands, in frozen order, as one fresh
monolithic sequence against revision `590740bfc6f139b193550dc32047625a24d3e29f` and tree
`563c415c61e2b3114fdc2cf6b0059a90944f1cb1`. All 31 passed. The exact repository-wide command
passed 1,872 tests at 91.55% combined coverage; Stage-10 targeted coverage passed at 91.70%,
with every critical-file branch threshold at or above 95%.

Status: `READY_FOR_INDEPENDENT_SOL_REREVIEW`. Implementation self-acceptance remains false;
independent review and human acceptance remain separate.
