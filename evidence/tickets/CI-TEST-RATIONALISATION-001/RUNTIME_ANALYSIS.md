# Runtime analysis

The Phase-1 deterministic planner's 20 highest-weight modules account for 74.2%
of its scheduling weight. Sequential isolated measurement without coverage took
2,922.95 seconds (48m43s). The profile identifies real optimizer/model/orchestration
work rather than node-count overhead.

The main findings are:

- `test_team_strength_shadow_cases.py` already shares its immutable model preparation;
  the five costly calls assert distinct canonical cases.
- `test_team_strength_shadow_comparison.py` and the D1 diagnostic suite already share
  expensive module preparation. Their downstream tamper and fail-closed cases are cheap.
- A2, one-command, R2A, R2C, assurance-surface, score-prefetch, and prepared-runner
  modules mix one or more minute-scale nodes with many cheap contract checks.
- The horizon/terminal suites compare generic and accelerated optimisers across distinct
  states. Similar structure is not redundant protection.
- Two inherited static weights (`repository_persistence_boundaries` and
  `configuration_contracts`) are now demonstrably stale: both modules run in under one
  second without coverage. Replacing the whole static map remains Phase-3 work because
  Phase-1 CI is healthy and the current weights affect balance only, not selection.

No measured test is removed on timing evidence alone. Deep modules remain in mandatory
full CI. The new fast command excludes the versioned deep set while retaining pure
unit/property/contract/security work; the nightly command repeats the deep set and
performance population without weakening the blocking gate.
