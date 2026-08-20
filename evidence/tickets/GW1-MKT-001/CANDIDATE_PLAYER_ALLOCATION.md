# Candidate current-player allocation — not accepted, not implemented

Status: **BLOCKED; NO NUMERICAL ARTIFACT ISSUED**

The existing Stage-9 interface already accepts per-player `goal_share`,
`assist_share`, `penalty_taker_share`, and `own_goal_share`, and binds them to
the current Stage-7 roster/minutes paths. It is therefore the correct single
DMF-native allocation seam; no external player simulator or optimiser is
needed.

However, the repository has no pinned, rights-reviewed historical player-event
sample capable of estimating the requested role/position/share priors. The
available Stage-7 training lineage is explicitly synthetic/replay minutes
evidence and cannot be repurposed as scoring or assist calibration. The
current prior-artifact contract also correctly requires an independently
accepted artifact rather than operator-invented live shares.

A future **CANDIDATE** may use the following bounded input hierarchy, after
data/right review:

1. Official current FPL identity, price, position, and team mapping.
2. Accepted Stage-7 start/bench/out probabilities and minute PMFs.
3. Pinned historical player event/minute sample, leakage-safe as of cutoff.
4. Position/role pooled goal and assist rate priors, shrunk for new signings,
   promoted clubs, transfers, and sparse minutes.
5. Explicit penalty role evidence and a conservative fallback distribution.
6. Per-team simplex validation before writing the existing Stage-9 profile.

It must publish exact data/licence hashes, role inference policy, season/time
splits, calibration by position and minutes band, promoted/new-player policy,
uncertainty/smoothing parameters, and an independent review record. Until
then, the accepted current-event artifact remains the genuine player-layer
blocker; this note neither supplies values nor changes the current contract.
