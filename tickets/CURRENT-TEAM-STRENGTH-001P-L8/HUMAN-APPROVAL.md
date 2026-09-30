# L8 human approval and Phase A boundary

Sebastian approved exactly one operator-initiated live transient three-Gameweek
comparison under `DMF-CTS-001P-L8-LIVE-RIGHTS-2026-09-30` and
`CURRENT-TEAM-STRENGTH-001P-L8#ONE-SHOT-2026-09-30`. It compares the ordinary
`LEAGUE_BASELINE` with `TEAM_STRENGTH_SHADOW` through canonical Stage 8–11 using
the accepted D1–D7 diagnostics and exact Stage-11 policy-v2 search.

This ticket implements **Phase A only**. No official FPL or The Odds API access,
credential inspection, or private observation is authorized for the agent in
Phase A. L1–L7 remain permanently consumed. L8 is consumed by the first
attempted FPL or Odds transport request in a later human-operated Phase B,
including a failed request; no automatic retry is authorized.

The Odds approval changes only the purpose metadata for the existing
`the_odds_api_private_analytics_v1` profile. Account, geography, terms,
capabilities, unresolved rights, and zero retention remain unchanged. The
standing `fpl_official_private_operator_initiated_read_v1` and
`openfootball_football_json_team_strength_v1` profiles are not broadened.
All live private inputs and comparison objects must remain transient and
memory-only; only the allowlisted terminal summary or diagnostic may leave the
process. The approval permits no candidate narrowing, approximate Stage-11
answer, parameter mixture, training, calibration, production adoption, or
activation. Team strength remains `SHADOW_NOT_MODEL_INPUT`.
