# PTS-009 Static Acceptance R2 finding closure

Owner Scope Amendment 1 permits exactly
`evidence/tickets/GCS-008/current_manifest.json` as the mutable active
repository snapshot. No other scope is widened.

| Finding | Closure | Evidence |
| --- | --- | --- |
| F1 | Stage-2 production activation provenance: ACTIVE production scoring requires a verified immutable activation bundle. | `test_accepted_rules_adapter.py`; installed-wheel check |
| F2 | Stage-7 semantic binding and no Stage-9 official-minute rewrite: exact projections, roles, intervals, and selected official minutes are retained. | `test_upstream_contracts.py` |
| F3 | Duplicate Gameweek fixtures fail closed. | `test_fail_closed_edges.py` |
| F4 | Artifact assurance recomputes every derived output: points, matrices, summaries, and Monte Carlo diagnostics. | `test_assurance_mutations.py` |
| F5 | BPS competition-rank universe excludes zero-minute participants while preserving eligible player competition ranks. | `test_rules_and_scoring.py`; rules regressions |
| F6 | Scope assurance resolves the real Git diff from the pinned parent and compares it with the declaration. | `check_stage9_scope.py`; temporary-repository tests |
| N01 | Primitive artifact/request lineage is hashed and assurance deterministically regenerates the scenario sequence. | `test_assurance_mutations.py`; CLI artifact replay |
| N02 | Gameweek `player_minutes`/`player_appeared`, fixture-result lineage, and Gameweek result hash derive from fixture event scenarios. | `test_fixture_pipeline.py` |
| N03 | Artifact-root path confinement rejects traversal, separators, drive-qualified paths, and symlink escape. | `test_evaluation_and_artifacts.py` |

## Windows executable limitation

The Windows host denied creation of the test symlink under its current privilege
policy. The symlink-escape executable case therefore requires a Linux/CI check
before human acceptance. The non-symlink path-confinement cases pass; this does
not claim the unavailable executable symlink case passed on Windows.
