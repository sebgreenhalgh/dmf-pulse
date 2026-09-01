# PRIVATE-V1-E2E-001A implementation result

The implementation is a direct descendant of immutable stacked parent
`7f4254905bccf79cdc282d04f4928cba850276be` on branch
`readiness/PRIVATE-V1-E2E-001A`. Parent exact-SHA CI run `33453614474` was verified green before
work began. The historical dirty CURRENT-AVAILABILITY-001A worktree was not used or modified.

## Delivered vertical slice

`PrivateV1RecommendationService` joins the accepted transient current FPL/manager bundle,
current market constraints, explicit canonical player identities, manual transient Stage 7,
the existing `ScoreDistributionService`, the existing `FplPointsService`, canonical Gameweek
joint scenarios, the existing exact Stage-11 transfer/no-transfer service and Stage-10 tactical
adapter, and the existing captain/vice evaluator. It emits one strict hash-bound decision plus a
concise human report. No alternative score simulator, scorer, solver, lineup selector, captain
selector, acquisition path, or production surface was added.

The one operator front door is:

- `dmf private-v1 run --input <execution.json> [--freeze-dir <new-directory>] [--output report|json]`
- `dmf private-v1 replay --bundle <directory> [--output report|json]`

Machine output is canonical `private-v1-decision-v1` JSON. Human output includes target/cutoff,
current state, transfer or explicit no-transfer, legal 15/XI/bench, captain/vice, hit-adjusted
paired comparison, uncertainty, data-quality warnings, hashes, and replay guidance.

Real FPL/manager retention fails before execution when `--freeze-dir` is requested. The artifact
layer independently enforces the same rule, writes only repository-owned synthetic bundles
atomically, verifies an exact four-file set and every byte/hash, and re-executes without network,
clock, provider, database, or source-tree access.

## Status

`PRIVATE_V1_E2E_001A_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`

`NOT_PRODUCTION_ACTIVE`

The synthetic product proof passed. The required genuine current private recommendation did not
run and is not claimed; see `real_run_attempt.md` for the exact fail-closed blockers.
