# Historical L4 bounded safe result

The retained terminal-safe L4 result is exactly:

```text
status = CURRENT_TEAM_STRENGTH_001P_L4_LIVE_EXECUTION_NOT_COMPLETED
stage = RUN_LEAGUE_BASELINE_WORLD
reason = BASELINE_WORLD_FAILED
failed_world = LEAGUE_BASELINE
baseline_world_started = true
baseline_world_completed = false
shadow_world_started = false
shadow_world_completed = false
baseline_stage8_projected = 30
baseline_stage8_prior_fallback = 3
stage8_outcome = PROJECTED
internal_code = null
FPL requests = 12
Odds acquisitions = 1
Odds requests = 1
private_attempt_consumed = true
```

This proves only:

- all 30 baseline Stage-8 fixtures projected;
- 3 projections used the governed prior fallback;
- the baseline world failed downstream of those fixture projections;
- the team-strength shadow world never started;
- the exact historical post-Stage-8 failure phase remains unknown;
- 12 FPL requests, one Odds acquisition and one Odds request occurred in the
  historical authorized attempt, so L4 is consumed.

It does not establish team strength as the observed blocker and must not be used
to infer a retroactive downstream root cause.
