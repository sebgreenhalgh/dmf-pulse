# L2 Phase A offline acceptance

Exact parent `4d712ecf84e9c1f01a0f29354bd93c5296befb35`; isolated branch
`readiness/CURRENT-TEAM-STRENGTH-001P-L2-one-shot-live-observation`.
The unrelated dirty original worktree is preserved. No PR, merge or tag.

Phase A: FPL requests=0, Odds requests=0, public OpenFootball requests=0,
credential inspection=0. Test inputs are generated/synthetic or governed retained
public/reconstructed evidence. No live private invocation or live comparison.
The Phase B command is supplied to the human only, not run by the agent.

## Completed checks

| Command/population | Result |
| --- | --- |
| `uv run --offline pytest -q tests/unit/private_v1/test_team_strength_d1_controls.py tests/unit/private_v1/test_team_strength_d1_diagnostics.py tests/unit/private_v1/test_team_strength_d1_markets.py tests/unit/private_v1/test_team_strength_l1_cli.py tests/unit/private_v1/test_team_strength_l2.py` | 139 passed, 146.07s |
| `uv run --offline pytest -q tests/unit/private_v1/test_team_strength_l1.py tests/unit/private_v1/test_team_strength_l1_cli.py tests/unit/private_v1/test_team_strength_l2.py` | 73 passed, 122.24s; final corrected labels |
| `uv run --offline pytest -q tests/unit/private_v1/test_team_strength_l1_e2e.py` | 1 passed, 205.99s; real generated-data Stage 8-11 two-world path with inherited no-private-write boundary |
| `uv run --offline pytest -q tests/unit/private_v1/test_team_strength_shadow_inputs.py tests/unit/private_v1/test_team_strength_comparison_contracts.py tests/unit/private_v1/test_team_strength_shadow_comparison.py tests/unit/private_v1/test_team_strength_shadow_cases.py` | 69 passed, 760.91s; inherited 001P input/contract/real-comparison and locked canonical cases |
| `uv run --offline pytest -q tests/unit/ingestion/openfootball tests/unit/football_events tests/unit/fpl_points tests/unit/optimisation tests/property/football_events tests/property/fpl_points tests/property/optimisation tests/unit/private_v1/test_horizon_markets.py tests/unit/evaluation/test_team_strength_replay.py` | 1,185 passed, 659.60s; P0/001A/readiness/replay and relevant Stage 8-11 unit/property regressions |
| `uv run --offline pytest -q tests/contract/football_events tests/contract/fpl_points tests/contract/optimisation tests/golden/football_events tests/golden/fpl_points tests/golden/optimisation tests/integration/football_events tests/integration/fpl_points tests/integration/optimisation` | 128 passed, 229.99s |
| `uv run --offline pytest -q tests/integration/repository/test_manifests.py tests/unit/assurance/test_manifests.py tests/unit/assurance/test_secret_scan.py` | 31 passed, 2.47s |
| `uv run --offline pytest -q tests/unit/ingestion/test_horizon_rights_approval.py tests/unit/ingestion/test_horizon_probe.py tests/unit/private_v1/test_team_strength_l2.py` | 126 passed, 3.89s; final inherited purpose-metadata correction, unchanged capability-denial checks and extra old-reference rejection |
| `uv run --offline pytest -q tests/unit/ingestion tests/contract/odds` | 1,344 passed, 283.72s; broad inherited ingestion/Odds regression after the metadata-test correction |
| `uv sync --all-groups --frozen --offline` | PASS, 40 packages; no dependency change |
| `uv run --offline ruff format --check .` | PASS, 896 files |
| `uv run --offline ruff check .` | PASS |
| `uv run --offline mypy src/dmf_pulse` | PASS, 312 source files |
| `uv build --no-sources --offline` | PASS, wheel and sdist |
| `uv run --offline python scripts/verify_team_strength_l1_wheel.py` | PASS, runtime-only external installation, exact L2 rights, consumed L1 rejection, finite diagnostics, public-unavailable block, wrong-purpose block, immutable source and operator help; provider calls=0 |
| `uv run --offline python scripts/verify_gcs008_wheel.py` | PASS on final rerun; 380 members and unchanged Stage-8 golden `31d41317c0cf06002edd8e8fb47c4702706661f2227304182e3c4b8995e06b7e` |
| `uv run --offline python scripts/validate_repository.py` | PASS, zero errors |
| `uv run --offline python scripts/scan_secrets.py` | PASS, zero findings |
| `uv run --offline dmf --version` | `dmf 0.2.0` |
| `git diff --check` | PASS |
| `uv run --offline python scripts/build_team_strength_l2_review_pack.py` | PASS, 20 entries including manifest; explicit source/document allowlist only |

Canonical manifests are regenerated with
`uv run --offline python scripts/generate_repository_manifest.py --ticket PRC-013`
and the same command with `--ticket CURRENT-TEAM-STRENGTH-001P-L2`.
The capped review archive command is
`uv run --offline python scripts/build_team_strength_l2_review_pack.py`.
Its explicit 19-source/document allowlist plus manifest excludes runtime artifacts,
public readiness bytes, private inputs and the operator entry identifier.

## Direct changed-authority coverage

```
uv run --offline coverage run --branch --data-file=review_pack/l2-authority.coverage -m pytest -q tests/unit/private_v1/test_team_strength_l2.py tests/unit/private_v1/test_team_strength_l1.py -k 'authority or purposes or drift or clock or historical_l1 or mismatched_pair or exact_new_pair'
uv run --offline coverage report --data-file=review_pack/l2-authority.coverage --include='*/team_strength_live_authority.py' --show-missing --fail-under=100
```

36 passed, 34 deselected, 38.38s. Authority: 32/32 statements, 10/10 branches,
100%, no exclusions. The deselected fixture/transport paths passed in the complete
73-test run. All inherited combined repository coverage gates remain mandatory
in the final exact-SHA CI; no coverage floor or exclusion changes.

## Verification corrections and limits

- Initial focused run: 72 passed, one test still expected the old L1 argument-error
  label. Only its expected identity was corrected; the full 73-test rerun passed.
- Ruff requested a conventional operand order in one consumed-set assertion.
  Only the test expression changed; final lint passes.
- An initial `coverage --source` pointing directly to the nested authority module
  caused premature package-import/Decimal validator collection errors. Using the
  repository's existing package-wide source configuration passed. No model or
  Decimal behavior changed to accommodate the tool invocation.
- The first inherited Stage-8 wheel invocation returned the finite local message
  "installed Stage-8 CLI could not complete". A diagnostic wrapper reran the exact
  same verifier/function and wheel, without source edits; it passed the full
  installed command, artifact validation and golden. The initial transient launch
  failure was not reproduced; the literal script command also passed on the
  subsequent rebuilt wheel. No unsupported root cause is asserted.
- No local PostgreSQL credential/configuration was inspected. L2 introduces no
  database requirement. Inherited PostgreSQL, full eight-shard branch coverage,
  performance, build and post-coverage acceptance are required in exact-SHA CI.

## Final publication boundary

Fresh independent clearance and safe public readiness are recorded separately.
No final CI success is fabricated inside its own pre-run commit: the final handoff
must identify and verify the exact committed SHA, remote equality, clean worktree
and successful mandatory CI run. A final public reassessment must precede that
handoff; actual Phase B also rechecks before credentials. Historical L1 stays
consumed, L2 is unconsumed by the agent, and production remains inactive.

## Post-seal inherited test correction

Initial published checkpoint `be25495475eb3ca1ac9c3a4a4dc459d4760c97d8`, CI
`35784439584`, is not a green acceptance claim. Coverage shard 5 reported seven
failures and 746 passes: `test_horizon_rights_approval.py` still pinned L1's
approval, purpose text, capture timestamp and a pre-L2 test clock. Its six
capability-denial cases consequently stopped at the earlier purpose gate instead
of reaching their intended unchanged RIGHTS_BLOCKED assertions. This inherited
population was missed in the initial focused local selection.

The correction updates only those test metadata literals to the approved L2
values, places the synthetic clock after approval, and adds explicit rejection of
the historical L1 reference. Capability matrices, denial assertions, stale terms,
schema checks, network/credential guards and all production/rights files remain
unchanged. No model golden, numerical tolerance, solver, runtime policy, rights
or CI workflow is modified. The 126-test inherited rights/probe/L2 population now
passes. The 20-entry archive substitutes this corrected test for the redundant
PLANS copy; its source-only boundary and caps are unchanged.

A new immutable descendant and fresh exact-SHA CI are required. No prior green
result is reused for this descendant, and Phase B remains human-only.
