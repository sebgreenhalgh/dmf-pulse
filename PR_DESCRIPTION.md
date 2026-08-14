# PTS-009 review handoff (no PR opened)

## Summary

Implements the bounded Stage 9 player-points vertical slice on the final accepted
Stage 8 parent. Accepted Stage 7 participation identities and the final Stage 8 joint
score matrix feed coherent event allocation, accepted-rules scoring, joint BPS/bonus,
fixture/Gameweek distributions, complete scenario matrices, Monte Carlo diagnostics,
canonical artifacts, and an offline CLI.

## Material integration changes

- Replaced provisional GCS-008 aliases with the final `JointScoreDistribution` and
  exact matrix/cutoff/context semantics.
- Bound actual Stage 7 team and player projection identities.
- Removed NumPy; no dependency or lock change.
- Replaced duplicate reference scoring with the accepted compiled-rules adapter.
- Hardened resource, scope, coverage, artifact, and wheel assurance.
- Preserved all accepted CLI registrations and added only `fpl-points`.

## Production status

Production 2026/27 output remains blocked until the target ruleset is complete,
verified, approved, production eligible, and ACTIVE. TEMP-EVT-002 and TEMP-PTS-001
remain explicit degraded baselines.

## Exclusions

No optimiser, manager-state transform, captaincy, chips, autosubs, transfer hits,
rank/EO, price model, migration, advanced prop reconciliation, full event tree, or
production BPS residual model.

This file is handoff material only. No PR was opened by the integration task.
