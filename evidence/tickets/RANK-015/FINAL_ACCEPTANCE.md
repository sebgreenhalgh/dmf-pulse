# RANK-015 final bounded acceptance

## Identity and status

- Finalisation starting remote SHA: `0a16ebaf6376c2347845ae9bb7804433fe6823e4`.
- Immutable main SHA: `c53a1dfae952f481c1e885200ebf6120e4b63c24`.
- Checkpoint 15.05 capability SHA: `62f1828edcfbd0569dbf76fc93e241f2db95094d`.
- Checkpoint 15.06 capability SHA: `c77b8950a4a150407b51d9bfed69b2314c74380e`.
- Engineering status: `IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`.
- Production activation remains fail-closed to `PURE_POINTS`.

## Stage-15 acceptance

- Complete Stage-15 suite: `243 passed in 15.85s`.
- Raw branch coverage: `91.334895%` (`780/854`).
- Combined line/branch coverage: `95.192007%`.
- Projection invariance: PASS.
- Same-football-scenario identity: PASS.
- Exact mini-league oracle: PASS.
- Independent exact synthetic-field oracle: PASS.
- Nonanticipativity and future-label exclusion: PASS.
- Required `PURE_POINTS` fallback gates: PASS.
- Service/CLI semantic equivalence: PASS.
- Artifact detached and semantic tamper rejection: PASS.

## Targeted inherited regressions

The final bounded inherited matrix ran `37` test cases from the exact nodes below.

| Authority surface | Exact node | Rationale |
|---|---|---|
| Rules | `tests/unit/rules/test_one_gameweek.py::test_reference_rules_view_is_resolved_from_compiled_values` | Confirms Stage 15 still consumes compiled rules rather than hidden literals. |
| Rules | `tests/unit/rules/test_one_gameweek.py::test_current_target_remains_blocked_for_test_and_production` | Preserves target-season activation blocking. |
| Stage 9 | `tests/unit/fpl_points/test_rules_and_scoring.py::test_appearance_clean_sheet_goal_and_assist_components_are_exact` | Protects deterministic raw FPL scoring. |
| Stage 9 | `tests/property/fpl_points/test_properties.py::test_fixture_pmf_threshold_quantile_and_mapping_properties` | Protects PMF and quantile semantics consumed by rank evaluation. |
| Stage 9 | `tests/property/fpl_points/test_properties.py::test_double_gameweek_total_equals_fixture_scenario_sum` | Protects shared Gameweek scenario aggregation. |
| Stage 10 | `tests/property/optimisation/test_oracle_equivalence.py::test_independent_oracle_matches_every_scenario_score` | Protects exact tactical scenario scoring. |
| Stage 10 | `tests/property/optimisation/test_oracle_equivalence.py::test_independent_exhaustive_oracle_matches_exact_global_optimum` | Protects the accepted points-optimal baseline. |
| Stage 11 | `tests/unit/optimisation/test_multi_gameweek_tree.py::test_future_actions_recourse_only_after_revelation` | Protects nonanticipative recourse. |
| Stage 11 | `tests/unit/optimisation/test_multi_gameweek_tree.py::test_clairvoyant_root_policy_is_not_representable` | Rejects perfect-information policies. |
| Stage 11 | `tests/unit/optimisation/test_multi_gameweek_state.py::test_selling_price_retains_floor_half_profit_and_full_loss` | Protects accepted manager-state value semantics. |
| Stage 11 | `tests/unit/optimisation/test_multi_gameweek_state.py::test_free_transfer_banking_consumption_hits_and_boundaries` | Protects transfer-count and hit state used by rank tie logic. |
| Stage 12 | `tests/unit/evaluation/test_leakage.py::test_required_adversarial_leakage_cases_block` | Exercises all parameterised leakage blockers. |
| Stage 12 | `tests/unit/evaluation/test_information_and_vintages.py::test_strict_live_includes_only_live_operational` | Protects cutoff-safe inputs. |
| Stage 12 | `tests/unit/evaluation/test_information_and_vintages.py::test_strict_live_blocks_every_nonoperational_mode_instead_of_silent_exclusion` | Prevents silent dataset-mode degradation. |
| Stage 13 | `tests/unit/prices/test_paths_selling.py::test_complete_recurrent_path_distribution_is_deterministic_and_integer` | Protects immutable price paths. |
| Stage 13 | `tests/unit/prices/test_paths_selling.py::test_stage11_selling_value_is_exact_across_profit_and_loss_paths` | Protects manager-state price lineage. |
| Stage 13 | `tests/unit/prices/test_decisions_evaluation_artifacts.py::test_act_wait_uses_complete_utility_not_probability_threshold` | Prevents price probability from replacing decision utility. |
| Stage 13 | `tests/unit/prices/test_decisions_evaluation_artifacts.py::test_evaluation_rejects_future_labels_and_nonchronological_rows` | Protects temporal integrity. |
| Stage 14 | `tests/unit/chips/test_captaincy.py::test_captain_absent_vice_appears` | Protects conditional vice-captain multiplier semantics. |
| Stage 14 | `tests/unit/chips/test_bench_boost.py::test_autosub_overlap_is_subtracted_from_bench_sum` | Protects Bench Boost/autosub interaction. |
| Stage 14 | `tests/unit/chips/test_free_hit.py::test_permanent_squad_bank_and_purchase_prices_restore_exactly` | Protects Free Hit temporary-state restoration. |
| Stage 14 | `tests/unit/chips/test_free_hit.py::test_common_scenario_mismatch_and_duplicate_candidates_fail_closed` | Protects common-scenario identity. |
| Stage 14 | `tests/unit/chips/test_temporal_leakage.py::test_executable_service_rejects_every_future_information_class` | Exercises all parameterised chip temporal-leakage gates. |

## Engineering and packaging gates

- `uv sync --all-groups --frozen`: PASS in successful GitHub validation and source-export runs for the starting remote SHA. The local container has no external DNS, so local finalisation reused the exact exported site-packages from that frozen environment. No dependency or lock file changed.
- `ruff format --check .`: PASS (`635 files already formatted`).
- `ruff check .`: PASS.
- `mypy --strict src/dmf_pulse`: PASS (`245 source files`).
- `git diff --check`: PASS.
- Repository validation after active-manifest refresh: PASS.
- First-party secret scan after recovery cleanup: PASS with zero findings.
- Hatchling build: PASS for sdist and wheel.
- External wheel installation with no source-tree `PYTHONPATH`: PASS.
- Installed commands exercised successfully: `dmf --version`, `dmf rank --help`, `dmf rank validate`, `dmf rank eo --input ...`, `dmf rank evaluate --input ...`, and `dmf rank compare --input ...`.

## Cleanup

Removed:

- `.github/workflows/stage15-publish.yml`
- `.github/workflows/stage15-source-export.yml`
- `.github/workflows/stage15-terminal-finalizer.yml`
- `.github/workflows/stage15-validation.yml`
- `recovery/stage1505/`
- `recovery/stage1506/`
- empty `recovery/` directory

Legitimate repository CI was retained.

## Limitations

- `FULL_REPOSITORY_PYTEST = NOT_RUN_BY_DESIGN — DEFERRED_TO_SOL`.
- Target-season rank activation remains conditional on verified rules, lawful data, valid cohort/opponent models and confidence gates.
- No PR, merge, tag or human acceptance is created by this finalisation.
