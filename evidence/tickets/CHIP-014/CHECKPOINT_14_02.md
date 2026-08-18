# CHIP-014 checkpoint 14.02 assurance

## Scope

Checkpoint 14.02 implements joint captain/vice selection and Triple Captain
valuation on one common coherent Stage-9 Gameweek scenario set. It delegates
lineup legality, autosubs, captain fallback and manager scoring to the accepted
Stage-10 tactical evaluator rather than creating a second scoring engine.

## Implemented capability

- Exact ordered captain/vice pair enumeration over starting-XI candidates.
- Vice valued only through conditional fallback scenarios, with explicit
  fallback probability and incremental fallback points.
- Captain and vice joint absence retained from common correlated scenarios.
- Triple Captain multiplier compiled from the accepted rules-bound chip bundle.
- Ordinary and Triple Captain pairs optimised independently on the same scenarios.
- Triple Captain current gain measured as the difference between optimised
  manager-score policies, not as a Double-Gameweek heuristic.
- Inventory activation projected through the generic 14.01 state transition;
  a zero-extra outcome still consumes the configured chip token.
- Scenario identity hash includes player points, appearance state, fixture IDs,
  Gameweek/assembly context when supplied, and probability weights.
- Ruleset ID/version/hash, chip definition hash and before/after inventory hashes
  retained in the immutable evaluation artifact.

## Focused validation

Command:

```text
PYTHONPATH=src python -m coverage run --branch -m pytest -q \
  tests/unit/chips/test_captaincy.py
```

Result: `41 passed`.

Production coverage command:

```text
python -m coverage report \
  --include='*/dmf_pulse/chips/captaincy.py,*/dmf_pulse/chips/policy_models.py' -m
```

Result: `303 statements`, `2 missed`, `104 branches`, `2 partial`, `99%`.

Syntax gate:

```text
PYTHONPATH=src python -m compileall -q \
  src/dmf_pulse/chips/captaincy.py \
  src/dmf_pulse/chips/policy_models.py \
  tests/unit/chips/test_captaincy.py
```

Result: `PASS`.

## Required assurance

- Captain appears: PASS.
- Captain absent / vice appears: PASS.
- Captain and vice both absent: PASS.
- DGW player appears in one fixture; aggregate Gameweek score used: PASS.
- Correlated postponement/nonappearance: PASS.
- Alternative captain/vice pair search under TC: PASS.
- Single-fixture TC opportunity can beat a weak double: PASS.
- TC chip consumed when extra score is zero: PASS.
- Rules, chip definition, scenario set and inventory lineage: PASS.
- Semantic hash tampering: blocked.
- Invalid scenario weights, duplicate identities, candidate universes, evaluator
  resolutions and non-finite scores: blocked.

## Inherited reuse

The default adapter imports
`dmf_pulse.optimisation.autosub_evaluator.evaluate_scenario`. The checkpoint does
not duplicate autosubstitution, captain fallback or manager-score mechanics.
The focused test harness injects a deterministic evaluator with the same public
call shape; inherited repository integration is included in final targeted
regression scope.

## Not run at this checkpoint

- Repository-wide pytest: not run by design.
- Ruff and mypy: deferred to final Stage-14 acceptance and not relabelled as passed.
- Build/wheel/installed CLI: final Stage-14 acceptance.

## Status

`CHECKPOINT_14_02_PASS_PENDING_REMOTE_PUBLICATION`
