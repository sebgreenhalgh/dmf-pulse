# R7 resumed acceptance review — local validation in progress

The original stop below is historical checkpoint evidence. The resume preserves
`65f344dc0661179dbd3963ae2fc8a8ad3aad2ff6`; no R7 commit has been pushed.
The >5x tactical performance floor is now met, but broad branch coverage and
independent review/publication gates remain pending. This is not final acceptance.

## Resumed architecture and exactness

- Terminal-only decision quotient: sealed request/node/rules, active IDs/club/
  position/current price/exact integer sale proceeds, bank and FT. Different
  original purchase prices may share work only when sale proceeds agree. At the
  deterministic static-price, chip-free, FT-only final node with zero terminal
  value, no remaining decision observes another purchase-price function. Nonfinal,
  paid, nonzero terminal-value and unsupported requests retain existing behavior.
  Every reused candidate is replayed through full transfer validation against the
  caller's complete ownership history; state objects from other histories are
  never substituted. Hostile separation, fallback and replay tests pass.
- Forward discovery enumerates legal transitions once per canonical state and
  retains validated transitions under the cumulative legal-work envelope. Backward
  layers collect unique squads and populate the exact node cache before computing
  unchanged Pareto frontiers. All full-history rebases remain validated.
- Bench arithmetic separates official substitution legality from player points.
  Six bench orders use exact packed integer lanes with an explicit absolute signed
  bound and offset; no lane can carry/borrow into its neighbor. Negative and
  512-bit hostile numerators match the retained original arithmetic. Existing
  outfield/GK factoring, captain reuse and all legal configurations are preserved.
- Canonical final evaluation still constructs every scenario score, event,
  captain/vice resolution, distribution and plan. Node-local interpretation and a
  bounded LRU of official resolver outputs are reused within the adapter's sealed
  input context; canonical verification is never skipped.
- Whole-run STANDARD legal work uses the existing 250,000 policy envelope after
  measuring 67,062 legal actions. Rejected combinations remain diagnostic and retain
  inherited per-state/state caps. Known violations fail before tactical work;
  no dynamic candidate/action pruning or false exact guarantee is introduced.

## Resumed evidence

Repeated 847x256 samples are bound in `repeated_benchmark.json`. R7 median wall/CPU
is 60.8643s / 58.15625s, 13.9162 squads/sec. R6 median is 456.7890s / 439.171875s,
with substantial baseline variation. Median ratios are 7.505x wall / 7.552x CPU;
the conservative fastest-R6/slowest-R7 ratios are 5.464x / 5.457x. The 10x target
is not claimed. Full tactical semantic hash and logical/canonical work are unchanged.

Actual Stage-10/11 frozen replay matches every request/candidate/result field,
including hashes, alternatives and attribution (395 node/squads; 48 to 3 batches).
The full 12-candidate structural request/candidates/squad inventory also match
exactly (8,997 node/squads; one batch/node); its tactical surrogate and suspended
wall time are explicitly not physical performance evidence.

Full private-stack semantic replay freezes a labelled synthetic market build
identity because native market provenance intentionally hashes all package bytes.
All calculations and exact-source verification still run. Every decision field
and hash matches with this common provenance input. Separately, the R7 native-build
full service passes from a clean offline installed wheel outside the source tree,
without that override. This does not claim native R6 artifacts verify under R7.

Targeted suite: 93 passed. Full formatting/lint, strict typing, frozen sync, build,
installed wheel, specification validation, secrets, repository validation, canonical
manifests (4 tests), and CI collection (4,418 eligible tests) pass at this checkpoint.
Final fresh changed-code coverage and all exact-SHA CI remain pending. Independent
review has been requested, not claimed. No live run/PR/merge/tag/activation.

## Historical checkpoint stop (65f344dc)

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
