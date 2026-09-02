# PRIVATE-V1-ONE-COMMAND-001H engineering acceptance

Every accepted current-model Stage-7 team scenario preserves its sampled START/BENCH/OUT roles
and underlying model/source identities while replacing independent marginal minute draws with an
exact deterministic minimum-L1 team path. Each ordinary path has 11 kickoff starters, 11 players
and one goalkeeper throughout `[0, 90)`, paired starter exits and bench entries, no OUT entry, at
most the five standard substitutions governed by Premier League Handbook 2026/27 Rule L.29, and
exactly 990 pre-dismissal player-minutes. Equal distortion prefers fewer substitutions and then
stable identity/order.

Each scenario records and hash-binds the original and reconciled minute-vector commitments plus
`original_team_minutes`, `reconciled_team_minutes`, `adjusted_player_count`,
`total_absolute_minute_adjustment`, `maximum_absolute_player_adjustment` and
`substitution_count`. `CurrentModelTeamScenarios` independently rejects structural incoherence,
and current model inputs disclose `CURRENT_STAGE7_TEAM_MINUTES_RECONCILED_V1` without claiming
that the Bayesian model generated the joint path directly.

Stage 9 continues to prefer the current on-pitch official-FPL hierarchy, then positive governed
historical `penalty_taker_share`. Its general exhaustion default remains `BLOCK`. Only private
current no-retention execution explicitly opts into
`PRIVATE_CURRENT_PENALTY_ROLE_GOAL_SHARE_PROXY_V1`; only when a team hierarchy is present and both
higher-priority sources are exhausted may it weight actual on-pitch candidates by existing
positive `goal_share`. Both scored and extra penalty routes share the resolver. Actual use emits
`CURRENT_PENALTY_HIERARCHY_EXHAUSTED_GOAL_SHARE_PROXY_V1` through fixture, gameweek, private
decision and report; zero eligible proxy mass retains `NO_ELIGIBLE_PENALTY_TAKER`.

Acceptance requires the live-shape, over/under-total, goalkeeper, substitution-cap, exhaustive
optimality, determinism, tamper, priority and warning regressions; affected availability,
FPL-points, private-v1 and CLI suites; branch coverage; Ruff; strict mypy; frozen sync; PostgreSQL;
build and clean installed-wheel verification; repository and secret validation; and exact-final-SHA
CI. A live retry occurs only if both existing credentials and the operator's runtime entry ID are
available; otherwise evidence records only their absence and the exact blocker.
