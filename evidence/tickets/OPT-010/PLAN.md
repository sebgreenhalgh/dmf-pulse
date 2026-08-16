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
