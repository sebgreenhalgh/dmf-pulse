# PRC-013 final main integration

## Lineage

- Original Stage-13 implementation parent: `ce7fe8f4354d95a477afcf6eed45f63cf0ab772e`.
- Independently reviewed pre-integration HEAD:
  `b0e3b0724b92ec2d483191f0329c0c38ae8a9e08`.
- Current `main` integrated: `9eb57143f6ee92f67c78607cc386678d962e62d4`.
- Preserved local backup ref: `backup/stage13-pre-main-integration` at the reviewed HEAD.
- Method: explicit non-fast-forward merge of `origin/main` into the Stage-13 branch; reviewed
  implementation and remediation commits were not rewritten.

The original implementation lineage remains authoritative historical fact. This section records
the subsequent final integrated lineage and does not replace it.

## Conflicts and semantic resolution

Git reported one textual conflict, in `PLANS.md`. Both the Stage-13 implementation/review record and
the current-main `RUL-2026-27` review/readiness record were retained. The secret-scan allowlist and
all rules/evidence/engine files merged without textual conflict.

The semantic integration added a fail-closed binding between the Stage-13 model configuration and
the compiled DMFP-02 price rules. `price_step_units: 1` is now explicitly
`RULESET_VALIDATION_REFERENCE` metadata under `DMFP-02_RULESET`, not an independent model-owned
mechanic. The binding verifies the compiled artifact hash, integer tenths price unit, purchase-price
bases, floor-half-profit/current-loss selling branches, retained-profit rounding and undisclosed
change-threshold algorithm. Stage 11 remains the sole executable selling-value implementation.

The captured first-party 2026/27 predictor is handled as a displayed/predicted progress signal and
benchmark observation. Progress can exceed 100 and is explicitly not a calibrated probability or
disclosure of the hidden threshold algorithm. Rights-profile lineage and the automated-capture
block remain in force.

## Integration validation

- Complete Stage-13 price suite: **PASS**, 116 tests in 14.92 seconds.
- Branch-aware coverage of `dmf_pulse.prices` and `dmf_pulse.cli.prices`: **PASS**, 90.56%
  (required >=90%).
- Preserved inherited dependency selectors: **PASS**, 17 tests in 1.12 seconds.
- Current-main rules/schema/lifecycle/Stage-11 assurance batch: **PASS**, 104 tests in 5.50
  seconds. Exact file selectors are recorded in `TARGETED_REGRESSION_SCOPE.txt`.
- Single post-integration complete repository attempt: **RESOURCE_LIMIT** at 1204 seconds; no
  final pytest summary or emitted failure trace. It was not rerun unchanged and is not PASS.
- Frozen sync: **PASS**, 40 packages checked.
- Ruff format/lint: **PASS**, 539 files formatted; lint clean.
- Strict mypy: **PASS**, 209 source files.
- Canonical Hatchling build: **PASS**.
- Wheel: 697057 bytes, 250 members, SHA-256
  `944c4c3d6792ec0beb5a0ef6d04318990575681967278a253fd62db8b06ebfa3`.
- Sdist: 3723843 bytes, SHA-256
  `e1865ed8078efbaf7cf0f09c60389d36c4dd37ddc946e3adc62aab6bd414506d`.
- Clean external wheel: **PASS**, 23 packages installed outside the repository; import resolved to
  external `site-packages` with `PYTHONPATH` removed.
- Installed CLI: current rules loaded as `fpl-2026-27`/`VERIFIED`; `prices validate` returned
  `ENGINEERING_READY` and `production_actionable=false`; `simulate-path` returned 2187 paths;
  `act-or-wait` returned `WAIT_FOR_INFORMATION`, `actionable=true` for the synthetic reconstructed
  acceptance payload.
- Repository manifest: **PASS**, 1021 deliverable files.
- Repository validation and deterministic secret scan: **PASS**, zero errors/findings.
- `git diff --check` and unresolved-entry inspection: **PASS**.

## Activation and acceptance

Verified deterministic 2026/27 rules do not calibrate or activate the predictive price model.
Stage 13 remains `SHADOW_ONLY`, `TARGET_SEASON_UNCALIBRATED` and `RIGHTS_BLOCKED`. Independent
review is complete; human acceptance, merge and accepted tagging remain pending.
