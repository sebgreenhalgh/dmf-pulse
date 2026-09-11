# R7 performance stop — NOT ACCEPTED / NOT PRODUCTION READY

The user's section 22 stopping condition applies. The tested exact kernel prototype
achieved 3.51x wall / 3.60x CPU acceleration, below the required 5x minimum. This is
a resumable engineering checkpoint, not completed R7. No live retry, production
activation, PR, merge, tag or next model-quality work was performed.

## Frozen measurements

Immutable R6 parent: `5878a39448456df0d07d58823e6dfa7c8e574715`.
Parent CI `34503653544`: all 12 jobs passed. That is parent evidence, NOT R7 CI.

R6's 17,000 action-combination limit resets per state, as confirmed in
`enumerate_legal_actions`. It does not limit cumulative tactical squads/actions.
`Stage10TacticalAdapter.evaluate_many` uses batching but calls the kernel for
each unique squad. Batching does not eliminate that physical work.

The frozen synthetic search has 12 incoming players at every node, 46 root
actions, 46 second-node states, 892 terminal economic states, 64,288 terminal
actions and 8,104 terminal squads (8,997 unique node/squad keys overall).
R6 fast-path CPU 42.28125s / wall 44.1837817s, with 1,836 memo hits and 614
terminal tactical batches. This search-shape run uses an explicitly labelled
synthetic tactical surrogate, NOT physical Stage-10 timings. Terminal action
enumeration wall 34.0043s includes transition wall 32.6536s; do not add overlapping
inclusive phase timings. No full R6/R7 production-shaped tactical search equality
has been established at this stop.

The direct physical kernel benchmark covers all 847 frozen overlapping squads
reachable by at most two same-position-count replacements from a 15-player squad
with 12 incoming players. It uses 256 seeded joint scenarios, including joint
absences and negative scores. R6 and R7 run sequentially, without cProfile:

| Metric | R6 | R7 prototype |
| --- | ---: | ---: |
| Wall seconds | 339.6959693 | 96.8327667 |
| Process CPU seconds | 326.328125 | 90.75 |
| Squads / wall second | 2.4934061 | 8.7470391 |
| Appearance-state XI visits | 75,224,050 | 30,136,425 |
| Logical scenario operations | 78,710,016,000 | 78,710,016,000 |
| Canonical final scenario operations | 216,832 | 216,832 |

All 847 complete tactical results match, including tactics, point distributions,
quantiles, objectives, tie counts and plan hashes. Shared semantic SHA256:
`26258b0493a9dfb584d061477e80a567caf0a6d9d61912f074fa1c498843d30d`.
Both CPU and wall ratios are below 5x. These local measurements show no multi-hour
suspension-like gap; they do not explain the suspension/stall in the user's live run.

## Exact prototype architecture

1. Aggregate weighted bench points by sufficient substitution state: absent starter
   counts by position plus the unordered bench appearance mask. Resolve each of the
   six bench orders after aggregation. Integer numerator arithmetic is unchanged;
   no independence assumptions, point rounding or scenario deletion are introduced.
2. Reuse that exact outfield function across goalkeeper choices and overlapping
   squads. Goalkeeper state cannot affect outfield substitution selection. A 4,096
   entry LRU bounds this physical cache; eviction recomputes exactly and never
   rejects work or removes actions. This is NOT a STANDARD cumulative-work guard.
3. Rank exact captain/vice pair bonuses once for the current 15-player squad and
   scan until all maximising feasible pairs have been retained for each XI. Primitive
   preparation does not expand to the full 540-player catalog. Final deterministic
   tie selection is unchanged.
4. Avoid building signatures for tactics whose already-exact objective is lower than
   the current exact incumbent. All tactical configurations remain counted.
5. Retain canonical `evaluate_tactical_configuration` for every winning fixed-squad
   result. No approximation or heuristic branch-and-bound is used.

The original bench arithmetic remains temporarily as a differential reference;
remove or relocate it only after a successful follow-up design review.

## Residual work and unfulfilled acceptance

The 128-scenario profile showed R6 bench/autosub work at ~78% of kernel time.
After exact factoring/captain reuse, bench work remains dominant and canonical
scenario verification becomes material. More exact reuse is necessary; larger
batches alone cannot remove per-squad kernel work. Small instrumented profiles
are diagnostic only, not the basis for the reported full-family speedup.

Terminal coalescing beyond R6's existing closed-history/active-economics memo,
same-selling-price cohort equivalence, layered node-wide batching, and cumulative
STANDARD work guards were NOT implemented. No unproven terminal key was installed.
The existing R6 replay equality compares active purchase-cohort economics, so
changing it to selling-price equivalence requires a separate proof and hostile
tests, especially nonzero-terminal and paid-transfer fallback.

Missing acceptance includes whole-run CPU phase instrumentation/governance, >5x
performance, full real-kernel production-shaped frozen differential, new terminal
equivalence tests, full generic-oracle matrix, changed-code coverage, clean-wheel
acceptance, final exact-SHA CI and independent review. Do not infer completion from
passing targeted tests or manifests. No new STANDARD threshold was invented.

R6 candidate module, rolling/service/comparator assembly and Stage-11 solver remain
byte-identical to the parent. Only tactical prototype, profiling, tests and ticket
metadata change. The R6 live result and R4-to-R6 cutoff difference remain untouched.
