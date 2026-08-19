# CHIP-014 checkpoint 14.03 assurance

## Scope

Checkpoint 14.03 implements Bench Boost as an incremental common-scenario
policy comparison. It does not equate projected bench points with chip value.
The no-chip comparator is the best accepted tactical policy from the supplied
candidate set, not a frozen current XI.

## Implemented capability

- Four-player bench, including the bench goalkeeper.
- Scenario-level appearance handling from the Stage-9 joint scenario state.
- Ordinary autosub overlap removed from Bench Boost incremental points.
- Independent optimisation of the normal tactical comparator and BB tactic.
- Natural and engineered preparation routes.
- Explicit preparation hits, bench-budget shift, future starting-XI cost,
  post-BB unwinding and price-route cost.
- Gross current gain kept separate from net pre-continuation value.
- Optional WC-prepared route with measured positive or negative WC-BB synergy.
- Generic inventory activation and deterministic rules/definition/scenario/
  inventory hashes.
- Continuation value explicitly marked not included at this checkpoint; the
  finite-inventory scheduler owns it in checkpoint 14.06.

## Focused validation

Command:

```text
PYTHONPATH=src python -m coverage run --branch -m pytest -q \
  tests/unit/chips/test_captaincy.py \
  tests/unit/chips/test_bench_boost.py
```

Result: `67 passed` (`41` inherited captaincy/TC plus `26` Bench Boost).

Coverage command:

```text
python -m coverage report \
  --include='*/dmf_pulse/chips/captaincy.py,*/dmf_pulse/chips/bench_boost.py,*/dmf_pulse/chips/policy_models.py' -m
```

Result: `586 statements`, `24 missed`, `204 branches`, `25 partial`, `94%`.

Syntax/publication gates:

- Python compileall for affected production/tests: `PASS`.
- Trailing-whitespace and final-newline check: `PASS`.

## Required assurance

- Four-player bench: PASS.
- Bench goalkeeper: PASS.
- Autosub overlap subtraction: PASS.
- Zero bench appearances: PASS.
- Natural BB route: PASS.
- Engineered BB with worse net value: PASS.
- Best normal tactic instead of frozen-XI comparator: PASS.
- Negative bench score retained: PASS.
- WC-BB positive synergy synthetic: PASS.
- WC-BB negative synergy synthetic: PASS.
- Missing/blocked BB effect and wrong/expired token: blocked.
- Duplicate candidates, invalid scenarios and scenario-universe gaps: blocked.
- Artifact arithmetic/hash tampering: blocked.

## Inherited reuse

The production default delegates normal manager scoring and autosub selection to
`dmf_pulse.optimisation.autosub_evaluator.evaluate_scenario`. Bench Boost adds
only bench players who appeared but were not already included in the accepted
normal score's `counted_player_ids`.

## Not run at this checkpoint

- Repository-wide pytest: not run by design.
- Ruff and mypy: deferred to final Stage-14 acceptance and not relabelled as passed.
- Build/wheel/installed CLI: final Stage-14 acceptance.

## Status

`CHECKPOINT_14_03_PASS_PENDING_REMOTE_PUBLICATION`
