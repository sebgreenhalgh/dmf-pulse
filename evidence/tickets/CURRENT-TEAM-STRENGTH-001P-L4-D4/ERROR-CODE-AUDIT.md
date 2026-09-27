# D4 rolling error-code audit

The comparison-only trace exposes no exception text. A rolling failure always
has a finite phase, failure class and closed rolling code.

Safe literal post-Stage-8 codes:

- `STAGE9_GAMEWEEK_INVALID`, `STAGE9_MC_QUALITY_BLOCKED`,
  `ROLLING_HORIZON_INCOMPLETE`;
- `ONE_GAMEWEEK_COMPARATOR_BLOCKED`, `ROLLING_OPTIMISER_BLOCKED`,
  `ONE_GAMEWEEK_COUNTERFACTUAL_UNAVAILABLE`;
- `ROLLING_FRONTIER_UNAVAILABLE`, `ROLLING_POLICY_INCOMPLETE`;
- `ROLLING_FT_TRANSITION_MISMATCH`,
  `ROLLING_COMPARATOR_SCENARIO_MISMATCH`, `ROLLING_COMPARATOR_INVALID`,
  `ROLLING_COMPARATOR_HORIZON_MISMATCH`,
  `ROLLING_COMPARATOR_OBJECTIVE_MISMATCH`;
- `COUNTERFACTUAL_ACTION_MISMATCH`.

Closed known optimiser-result codes:

- `MULTI_GAMEWEEK_PRODUCTION_BACKEND_UNAVAILABLE`;
- `MULTI_GAMEWEEK_INPUT_INVALID`, `MULTI_GAMEWEEK_INFEASIBLE`,
  `MULTI_GAMEWEEK_RESOURCE_LIMIT`;
- `OPTIMISER_EMITTED_INVALID_POLICY`,
  `NO_TRANSFER_BASELINE_UNAVAILABLE`, `MOVE_ATTRIBUTION_INVALID`.

Any other optimizer result code is
`OPTIMISER_FAILURE_UNCLASSIFIED`. Another unknown typed rolling code is
`PRIVATE_V1_FAILURE_UNCLASSIFIED`. A non-typed exception is
`ROLLING_UNEXPECTED_FAILURE`. The accompanying closed `rolling_phase` supplies
the exact finite failure boundary in every case.

Reachable helper codes deliberately classified as internal-only generic
(`PRIVATE_V1_FAILURE_UNCLASSIFIED`) include:

- request/input assembly: `CURRENT_FPL_INPUT_INVALID`,
  `HORIZON_PLAYER_UNIVERSE_MISMATCH`, `MISSING_PLAYER_PROJECTION`,
  `STAGE9_PLAYER_NOT_CURRENT`, `HORIZON_COMPARATOR_ACTION_REQUIRED`,
  `HORIZON_SCREEN_INPUT_INVALID`;
- governed screening/scope: `PRIVATE_HORIZON_V3_FINAL_MODEL_TIE_CAPACITY`,
  `PRIVATE_TRANSFER_SCREEN_UNBOUNDED`,
  `PRIVATE_TRANSFER_COUNT_SCOPE_INCOMPLETE`;
- post-solve decision validation: `OPTIMISER_OUTPUT_INVALID`,
  `CAPTAIN_LAYER_MISMATCH`;
- pre-Stage-9 rolling verification: `PRIVATE_ROLLING_EXECUTION_INPUT_INVALID`,
  `ROLLING_TERMINAL_POLICY_INVALID`, `FUTURE_FIXTURE_INPUT_BLOCKED`, and
  `SHADOW_ABLATION_CONFLICT`.

These identities are not emitted because they are internal implementation
detail rather than part of the approved terminal disclosure contract. Their
finite phase and generic classification remain non-null.
