# Static override migration audit

The Phase-2 parent contained 53 `FILE_WEIGHT_OVERRIDES` entries. Phase 3 leaves
zero Python weight overrides and zero retained exceptional weight constants.

## Replaced by runtime evidence (20)

- `tests/assurance/optimisation/test_r2c_artifact_validation.py`
- `tests/assurance/optimisation/test_surface.py`
- `tests/contract/optimisation/test_r2a_contract_gates.py`
- `tests/golden/optimisation/test_golden.py`
- `tests/integration/optimisation/test_integration.py`
- `tests/unit/markets/test_repository_persistence_boundaries.py`
- `tests/unit/optimisation/test_service.py`
- `tests/unit/optimisation/test_terminal_r7_equivalence.py`
- `tests/unit/prices/test_configuration_contracts.py`
- `tests/unit/private_v1/test_a1_03_shadow_comparison.py`
- `tests/unit/private_v1/test_a2_preparation.py`
- `tests/unit/private_v1/test_bounded_horizon_oracle.py`
- `tests/unit/private_v1/test_horizon_candidate_oracle.py`
- `tests/unit/private_v1/test_one_command.py`
- `tests/unit/private_v1/test_score_prior_prefetch.py`
- `tests/unit/private_v1/test_team_strength_d1_diagnostics.py`
- `tests/unit/private_v1/test_team_strength_d3_seam.py`
- `tests/unit/private_v1/test_team_strength_l1_e2e.py`
- `tests/unit/private_v1/test_team_strength_shadow_cases.py`
- `tests/unit/private_v1/test_team_strength_shadow_comparison.py`

## Obsolete; replaced by the documented fallback (33)

- `tests/golden/optimisation/test_three_gameweek_ft_carry.py`
- `tests/integration/availability/test_min007g_service.py`
- `tests/integration/availability/test_audit0073_cli_mapping.py`
- `tests/integration/migrations/test_migrations.py`
- `tests/integration/markets/test_current_market_identity_readonly.py`
- `tests/property/optimisation/test_oracle_equivalence.py`
- `tests/unit/availability/test_audit0073_cli_semantics.py`
- `tests/unit/availability/test_current_model.py`
- `tests/unit/optimisation/test_r2b_semantics.py`
- `tests/unit/optimisation/test_future_transfer_scope.py`
- `tests/unit/optimisation/test_stage10_r7_factoring.py`
- `tests/unit/optimisation/test_stage11_exact_acceleration.py`
- `tests/unit/optimisation/test_three_gameweek_horizon.py`
- `tests/unit/private_v1/test_team_strength_shadow_inputs.py`
- `tests/unit/private_v1/test_team_strength_l1.py`
- `tests/unit/ingestion/openfootball/test_team_strength_current.py`
- `tests/unit/ingestion/test_current_unified_state_boundaries.py`
- `tests/unit/ingestion/test_fpl_client.py`
- `tests/unit/ingestion/test_fpl_current_manager_boundaries.py`
- `tests/unit/ingestion/test_fpl_current_game_settings.py`
- `tests/unit/ingestion/test_fpl_current_input.py`
- `tests/unit/ingestion/test_odds_model_config_boundaries.py`
- `tests/unit/ingestion/test_one_command_assembly.py`
- `tests/unit/markets/test_current_market_contract_invariants.py`
- `tests/unit/markets/test_current_market_weight_canonicalisation.py`
- `tests/unit/markets/test_current_markets_boundaries.py`
- `tests/unit/private_v1/test_a1_allocation_injection.py`
- `tests/unit/private_v1/test_a2_live_shadow_observation.py`
- `tests/unit/private_v1/test_future_scope_assembly.py`
- `tests/unit/private_v1/test_horizon_markets.py`
- `tests/unit/private_v1/test_rolling_contracts.py`
- `tests/unit/private_v1/test_rolling_service.py`
- `tests/unit/private_v1/test_service.py`

No entry was retained as a Python exception. The two node-partition exceptions
are manifest policy with explicit evidence, not manually tuned file weights.
