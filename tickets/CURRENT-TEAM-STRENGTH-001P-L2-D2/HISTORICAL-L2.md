# Historical L2 record

The consumed L2 attempt emitted only this safe result:

```text
status = CURRENT_TEAM_STRENGTH_001P_L2_LIVE_EXECUTION_NOT_COMPLETED
stage = RUN_TWO_WORLD_COMPARISON
reason = TWO_WORLD_COMPARISON_FAILED
FPL requests = 12
Odds acquisitions = 1
Odds requests = 1
private_attempt_consumed = true
persistence = false
production_activation = false
```

No D1 comparison diagnostic fields were emitted. This proves that the terminal
result used an untyped/fallback boundary. Because no private comparison context was
retained, D2 does not and cannot identify the exact historical root cause.

`PRIOR_L1_ONE_SHOT_CONSUMED = TRUE`

`PRIOR_L2_ONE_SHOT_CONSUMED = TRUE`
