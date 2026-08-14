# GW1 MVP status

## Implemented Stage 9 path

The branch contains the bounded raw-player-points path from accepted Stage 7
participation and final Stage 8 score uncertainty through coherent TEMP-EVT-002 event
allocation, accepted rules scoring, joint BPS/bonus, fixture/Gameweek distributions,
the full joint scenario matrix, Monte Carlo diagnostics, immutable artifacts, and an
offline installed-wheel CLI.

TEST/REPLAY is usable with the explicitly labelled reference artifact. It produces
exact integer scenario components and totals, retains negative support and dependence,
and verifies hashes and upstream identities on replay.

## Production status

**BLOCKED for 2026/27 production/GW1 recommendations.** The target ruleset is still
`CAPTURED_UNVERIFIED`, not production eligible, not human approved, and not ACTIVE.
The current installed-wheel production probe correctly fails closed.

TEMP-EVT-002 and TEMP-PTS-001 are transparent baseline models, not production
calibration. Multiple-fixture Gameweeks share deterministic draw identity but do not
model sequential injury, dismissal, suspension, fatigue, or readiness transitions.

## Outside this milestone

Squad and transfer optimisation, captain/vice transforms, chips, autosubs, transfer
hits, price changes, effective ownership/rank strategy, advanced prop reconciliation,
and a production event/BPS residual model remain later-stage work.
