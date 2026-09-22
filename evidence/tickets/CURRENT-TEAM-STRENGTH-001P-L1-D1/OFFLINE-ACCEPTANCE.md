# D1 offline acceptance

All commands run in the isolated D1 exact-parent worktree. Test material is
synthetic, accepted retained public evidence or reconstructed public evidence.
FPL requests = 0; Odds requests = 0; live OpenFootball requests = 0.
No private credentials or historical private snapshot were inspected.

## Completed checks

| Command/population | Result |
| --- | --- |
| `uv run --offline pytest -q tests/unit/ingestion/openfootball tests/unit/football_events tests/unit/fpl_points tests/unit/optimisation tests/property/football_events tests/property/fpl_points tests/property/optimisation tests/unit/private_v1/test_horizon_markets.py tests/unit/evaluation/test_team_strength_replay.py` | 1,185 passed, 695.67s |
| `uv run --offline pytest -q tests/unit/private_v1/test_team_strength_d1_diagnostics.py tests/unit/private_v1/test_team_strength_d1_controls.py tests/unit/private_v1/test_team_strength_d1_markets.py` | 113 passed, 138.42s on final reviewed behavior; every major fixture-heavy boundary, real market matrix and control witness |
| Final fast diagnostic coverage command in `coverage-summary.json` | 69 passed, 20 fixture-heavy cases deselected (covered by complete direct run); 208/208 statements, 26/26 branches, no exclusions |
| `uv run --offline pytest -q tests/integration/repository/test_manifests.py tests/unit/assurance/test_manifests.py tests/unit/assurance/test_secret_scan.py` | 31 passed, 2.54s |
| `uv run --offline pytest -q tests/contract/football_events tests/contract/fpl_points tests/contract/optimisation tests/golden/football_events tests/golden/fpl_points tests/golden/optimisation tests/integration/football_events tests/integration/fpl_points tests/integration/optimisation` | 128 passed, 225.10s |
| `uv run --offline pytest -q tests/unit/private_v1/test_team_strength_d1_diagnostics.py -k 'signature_failure or completed_worlds'` | 3 passed, 80 deselected; final additional nested control/signature/timing wrapping |
| `uv run --offline ruff format --check .` | PASS, 894 files |
| `uv run --offline ruff check .` | PASS |
| `uv run --offline mypy src/dmf_pulse` | PASS, 312 source files |
| `uv sync --all-groups --frozen --offline` | PASS, 40 packages; no dependency change |
| `uv build --no-sources --offline` | PASS, wheel and sdist |
| `uv run --offline python scripts/verify_team_strength_l1_wheel.py` | PASS, outside-source runtime-only installed import, closed diagnostic, consumed and wrong-purpose pre-provider blocks, mutable-source rejection, operator help; provider calls zero |
| `uv run --offline python scripts/verify_gcs008_wheel.py` | PASS, actual outside-source Stage-8 command; unchanged golden result `31d41317c0cf06002edd8e8fb47c4702706661f2227304182e3c4b8995e06b7e`; 380 wheel members verified |
| `uv run --offline python scripts/validate_repository.py` | PASS, zero errors |
| `uv run --offline python scripts/scan_secrets.py` | PASS, zero findings |
| `uv run --offline dmf --version` | `dmf 0.2.0` |
| `git diff --check` | PASS |

Canonical manifest commands: `uv run --offline python scripts/generate_repository_manifest.py --ticket PRC-013`
and the same command with `--ticket CURRENT-TEAM-STRENGTH-001P-L1-D1`.
The source-only capped archive is built with
`uv run --offline python scripts/build_team_strength_d1_review_pack.py`.
No runtime directory, private artifact or response body is eligible for that pack.

## In-progress acceptance (not yet claimed passed)

The instrumented 001P input/comparison/five-case differential, L1 generated-data,
A2 preparation and ordinary one-command population is running. Final review
and final Git sealing remain separate gates.

## Verification issues and limits

- Independent review confirmed a material P2 localization issue: initializing a
  pending projector call as INPUT_INVALID could falsely diagnose an unexpected
  RuntimeError/ArithmeticError. D1 now leaves its outcome unknown until the
  existing input-exception handler runs. Unexpected failures retain safe location
  with generic world failure. Six tests cover caught/uncaught errors with and
  without an earlier successful fallback, preventing stale outcome carryover.
- Initial adversarial diagnostic test revealed that serializing a malformed
  Pydantic enum can warn with its raw value. Production now validates exact type
  and raw fields first, then converts validation failure to fixed safe text.
  Direct-helper and L1 terminal regressions pass; no serializer warning escapes.
- Initial synthetic totals-only test used the wrong shape: totals live in
  `totals_markets`, separately from H2H `markets`. It now removes H2H only and
  proves the governed future builder returns H2H_UNAVAILABLE/empty constraints.
- The real generated fixture uses the accepted Stage-8 prior fallback. An initial
  test incorrectly expected plain PROJECTED; the corrected test explicitly
  requires PROJECTED_WITH_PRIOR_FALLBACK and the corresponding aggregate count.
  Production Stage-8 mathematics and golden expectations were not changed.
- The broad legacy `scripts/verify_wheel.py` cannot run locally because its
  inherited disposable `DMF_TEST_DATABASE_URL` is absent. It returned a finite
  failure and is not claimed passed. D1 introduces no database requirement; the
  D1 outside-source wheel check passes. No database credential inspection or
  environment mutation was performed to bypass this inherited prerequisite.

The large population command is:

```
uv run --offline coverage run --branch --data-file=review_pack/d1.coverage -m pytest -q tests/unit/private_v1/test_team_strength_d1_diagnostics.py tests/unit/private_v1/test_team_strength_shadow_inputs.py tests/unit/private_v1/test_team_strength_shadow_comparison.py tests/unit/private_v1/test_team_strength_shadow_cases.py tests/unit/private_v1/test_team_strength_l1.py tests/unit/private_v1/test_team_strength_l1_e2e.py tests/unit/private_v1/test_team_strength_l1_cli.py tests/unit/private_v1/test_a2_preparation.py tests/unit/private_v1/test_one_command.py
```

No assertion of historical root cause, live execution success or production
promotion follows from any offline result.
