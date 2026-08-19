# CHIP-014 checkpoint 14.01 assurance

## Scope

Checkpoint 14.01 implements the optimisation-facing generic chip definition,
closed effect grammar, compiler, finite inventory tokens and deterministic
inventory transitions. Deterministic target-season chip mechanics remain owned
by the accepted rules layer; this compiler consumes the rules-layer public view
and stores ruleset identity/version/hash without copying season constants.

## Implemented capability

- Generic definitions, effects, inventory grants and compiled bundles.
- Closed capabilities for scoring, captain, bench, transfer, temporary/permanent
  squad, restoration, budget, club, position, free-transfer and conflict effects.
- Fail-closed unknown-effect and invalid-semantics blockers.
- Multiple copies, acquisition, availability, pending selection, cancellation,
  activation, use, expiry and future acquisition.
- Activation windows, exclusions, minimum gaps, concurrency limits/groups and
  multi-Gameweek occupancy.
- Semantic SHA-256 identities for definitions, compiled bundles and inventory.
- Adapter from the accepted rules-layer public chip view.
- Explicit synthetic future-chip compilation for engineering tests only.

## Focused validation

Command:

```text
PYTHONPATH=src python -m coverage run --branch -m pytest -q \
  tests/unit/chips tests/property/chips
```

Result: `58 passed`.

Production coverage command:

```text
python -m coverage report --include='*/dmf_pulse/chips/*' -m
```

Result: `439 statements`, `3 missed`, `156 branches`, `9 partial`, `98%`.

Additional syntax gate:

```text
PYTHONPATH=src python -m compileall -q \
  src/dmf_pulse/chips tests/unit/chips tests/property/chips
```

Result: `PASS`.

## Required synthetic assurance

- Multi-week chip: PASS.
- Transfer-cost modifying chip: PASS.
- Budget modifying chip: PASS.
- Unknown effect blocks activation: PASS.
- Conflicting-duration/group occupancy: PASS.
- Multiple copies and future acquisition: PASS.
- Consumed and expired token reuse blocking: PASS.
- Deterministic semantic hashes: PASS.

## Not run at this checkpoint

- Repository-wide pytest: not run by design.
- Ruff and mypy: deferred to final Stage-14 acceptance; the current execution
  environment has no cached Ruff/mypy installation and no outbound package
  transport. This does not relabel those gates as passed.
- Inherited Stage 9-13 regressions: deferred to the checkpoint that first
  integrates those interfaces and final targeted regression scope.

## Status

`CHECKPOINT_14_01_PASS_PENDING_REMOTE_PUBLICATION`
