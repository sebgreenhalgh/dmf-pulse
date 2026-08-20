# RANK-015 checkpoint 15.06 assurance

## Scope

Checkpoint 15.06 supplies the shared Stage-15 application service, accepted-plan
re-evaluation, fail-closed activation policy, immutable decision artifacts and
the real `dmf rank` CLI vertical slice.

It consumes accepted Stage-12, Stage-13 and Stage-14 candidate identities. It
does not call or duplicate upstream projection, price, squad, transfer,
lineup, captaincy or chip optimisers.

## Shared service

Implemented in `src/dmf_pulse/rank_strategy/service.py` with strict public
contracts in `service_models.py`.

The service binds and preserves:

- Stage-9 scenario identity;
- Stage-10 tactical-evaluator identity;
- Stage-11 manager-state identity;
- accepted Stage-12 plan/result identities;
- Stage-13 price-model identity;
- Stage-14 chip-model identity;
- Stage-15 EO, cohort and opponent-model identities;
- raw projection and scenario-set hashes;
- ruleset, rights profile, information cutoff, code and configuration versions;
- points-floor configuration hash.

For every evaluation it retains the points-optimal plan, rank-optimal plan,
selected plan, expected-points difference, target-probability difference, rank
PMF diagnostics, confidence and fail-closed reasons.

## Projection and scenario invariance

Accepted scenario points are snapshotted before and after rank evaluation.
Rank utility never mutates raw football/FPL projections. Every candidate must
share the sealed raw-projection hash, Stage-9 scenario-set hash, scenario IDs
and scenario weights. Any mismatch disables executable rank utility and selects
`PURE_POINTS`.

## Fail-closed activation

Executable rank utility requires all of the following gates:

- verified rules;
- valid user-selected objective/target;
- permitted rights state;
- valid cohort identity;
- valid opponent-model identity;
- sufficient confidence;
- common raw-projection lineage;
- common scenario lineage;
- satisfied expected-points floor;
- early-season material-points policy.

A failed required gate selects the preserved points-optimal plan. Safe diagnostic
rank output remains available when the rank evaluation itself is valid.
Early-season material expected-points sacrifice is blocked.

## CLI

`src/dmf_pulse/cli/rank.py` is wired into the existing Typer application and
calls the shared service for:

```text
dmf rank validate
dmf rank eo
dmf rank mini-league
dmf rank opponents
dmf rank cohort
dmf rank evaluate
dmf rank compare
```

The CLI has no second numerical implementation. Library/CLI equivalence tests
compare sealed semantic result identities.

## Artifact and tamper protection

The Stage-15 decision artifact uses the repository's canonical JSON,
`hash_without` semantic hash convention and immutable artifact-store path.
It binds the sealed request and result, including all cutoff, lineage, objective,
target, plan, gate, confidence, rights and version fields. Loading recomputes
request, nested model, result and artifact hashes; any mismatch fails closed.

## Focused verification before publication

```text
243 passed in 11.86s
raw branch coverage: 91.334895% (780/854)
combined line/branch coverage: 95.192007%
Ruff format: PASS
Ruff lint: PASS
strict mypy: PASS
python diff whitespace gate: PASS
```

The matrix covers all Stage-15 unit, property, integration and rank CLI tests.
Repository-wide pytest was not run by design.

## Status

`CHECKPOINT_15_06_READY_FOR_REMOTE_PUBLICATION`

Independent review, final inherited regression selection, build/wheel testing,
repository validation, secret scan and temporary-workflow cleanup remain final
hardening work and are not claimed here.
