# PRIVATE-V1-ONE-COMMAND-001K command ledger

All commands ran from the isolated `review_pack/one-command-k` worktree on the required branch and
parent. The unrelated dirty repository-root worktree was not modified. No credential, entry ID,
manager squad, player identity, provider body or private hash is recorded.

| Gate | Result |
|---|---|
| Parent/worktree | PASS; exact parent `e2961220ed110854eb9c912448f809ff3bad5e20` |
| Parent exact-SHA CI | PASS; GitHub Actions run `33659620693` |
| RED FT/position generation | PASS; old two-argument policy and Cartesian cap failed as expected |
| Focused FT/search/cache/pruning | PASS; all focused regressions green |
| Full affected optimiser/private/ingestion matrix | PASS; `370 passed` |
| Performance smoke | PASS; `3 passed, 1 deselected` |
| Monolithic local repository coverage | STOPPED during CPU-heavy assurance replay; no failure observed; exact 4,201-test branch-coverage gate delegated to the repository's mandatory 8-shard CI |
| Ruff format/lint | PASS after canonical formatting |
| Strict mypy | PASS; zero issues in 281 source files |
| Frozen sync | PASS; 40 development packages unchanged |
| Build | PASS; sdist and `dmf_pulse-0.2.0-py3-none-any.whl` built |
| Clean installed wheel | PASS; isolated offline v0.2.0 private-search import outside source tree |
| Repository/secret validation | PASS after active-manifest refresh; secret scan PASS with zero findings |
| Literal live GW3 | BLOCKED; Odds key, FPL bearer and runtime entry-ID presences are all false |
| Exact final-SHA CI | Pending final commit and push |

The first `uv build` invocation encountered the previously recorded transient Windows
application-control denial of the `uv.exe` launcher. Repeating through the approved absolute uv
executable completed without a dependency or source change. The generic wheel verifier completed
its clean build/install/version/doctor/rules checks and stopped only at the absent local test
database URL; the narrower isolated offline wheel probe then verified the changed installed
modules without a database or network dependency. The older OPT-010 wheel helper created an
unlocked Typer environment and failed on that helper's dependency mismatch; it was not used as a
success claim.
