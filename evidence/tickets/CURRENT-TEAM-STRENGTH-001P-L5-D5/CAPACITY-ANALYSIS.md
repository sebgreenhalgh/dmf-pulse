# D5 Stage-11 capacity analysis

All measurements are offline, repository-owned synthetic or previously retained
public-core evidence. No historical L5 private input was retained or reconstructed.
No provider was contacted. Peak memory is explicitly unavailable because the locked
runtime has no approved memory profiler and D5 adds no dependency.

## Five 001P decision cases

`five-case-capacity.json` records both worlds for all five cases (10 solves). Every
solve passed and the provider-call counter is zero.

| Measure | Minimum | Maximum | Mean |
|---|---:|---:|---:|
| candidate pool | 120 | 120 | 120 |
| retained incoming | 1 | 4 | 1.6 |
| cumulative legal actions | 14 | 22 | 15.0 |
| reachable states solved | 9 | 12 | 9.4 |
| policy candidates | 8 | 13 | 8.8 |
| peak Pareto size | 1 | 1 | 1.0 |
| tactical squads | 6 | 9 | 6.6 |
| wall seconds | 0.100361 | 0.189044 | 0.122625 |
| CPU seconds | 0.093750 | 0.187500 | 0.118750 |

## Retained R7 and R9 evidence

The retained R7 search-shape benchmark uses 12 incoming candidates per node. Its
single-frontier shape contains 46 root actions, 46 second-node states, 892 terminal
economic states, 64,288 terminal legal actions, 8,104 terminal squads and 8,997
unique node squads, with 1,836 memo hits. The surrogate search took 44.183782 wall
seconds and 42.281250 CPU seconds. The corresponding retained whole-public solve
ledger reports 130,317 cumulative legal actions and 1,788 state expansions.

R7's separate exact tactical-kernel benchmark covers 847 squads by 256 scenarios.
That evidence is useful for tactical scale, but it is not a whole-search timing and
must not be added to the surrogate search time. Memory was not retained.

The retained R9C-A1 root- and continuation-sensitive worlds each report a 120-player
candidate catalogue, 14 cumulative legal actions, 9 state expansions, 8 policy
candidates, 6 unique tactical squads and a peak Pareto size of 1. Their retained
artifacts contain no comparable wall/CPU or memory measurements; D5 does not invent
them.

## Generated near-envelope workload

The D5 workload has a 31-player candidate pool and 16 retained incoming candidates.
It is the same sealed synthetic three-Gameweek action space in each row below; only
the governed cumulative exact-work cap differs.

| Cap | Status | Kind | Legal actions | States | Policies | Peak Pareto | Tactical squads | Wall s | CPU s |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 250,000 | RESOURCE_LIMIT / NO_INCUMBENT | CUMULATIVE_LEGAL_ACTION_LIMIT | 250,036 at stop | 1,623 | 163,743 | 1 | 20,963 | 124.370 | 121.766 |
| 524,288 | SUCCESS | none | 320,610 | 3,126 | 163,743 | 1 | 20,963 | 167.493 | 163.375 |
| 1,048,576 | SUCCESS | none | 320,610 | 3,126 | 163,743 | 1 | 20,963 | 170.243 | 165.766 |

The exact timing values are non-semantic diagnostics and vary with machine load.
The action/state/policy counts and decision summary are deterministic. The 524,288
and 1,048,576 results have identical cap-independent decision semantic SHA:
`f5b3d892d999e399be67c6137726adb54d136ccc73a40699b19f5d1efe5e2f47`.
That summary includes the recommendation, no-transfer baseline, root counterfactual
and complete two-point transfer-count frontier.

## Cap derivation and operational interpretation

The legacy 250,000 cap is empirically insufficient by at least 70,610 exact legal
actions for the generated representative workload. The smallest power-of-two
governance boundary above the measured 320,610 requirement is 524,288. It provides
203,678 actions, or 63.5%, of explicit exact-work headroom. This replaces the earlier
unmeasured breadth-multiplier rationale.

The new value changes only when the solver fails closed; it does not narrow or prune
the declared action space. The generated run shows that a large exact solve can take
roughly 2.8 minutes with the repository surrogate on this machine, so the cap is an
operator resource envelope rather than a latency target. Memory remains unmeasured,
and this limitation is retained rather than estimated.
