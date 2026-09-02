# PRIVATE-V1-ONE-COMMAND-001J command ledger

All commands ran from the isolated `review_pack/one-command-j` worktree on the required branch and
exact parent. The unrelated dirty repository-root worktree was not modified. No provider body,
credential, runtime entry identifier, manager squad, player identity or private hash is recorded.

| Gate | Result |
|---|---|
| Parent/worktree | PASS; exact parent `88e1bd8779abe125fed4c0387b14e4247aaad15f` |
| Parent exact-SHA CI | PASS; GitHub Actions run `33651419913` |
| RED current roster | PASS; missing current-specific scenario contract failed collection |
| RED progress/errors | PASS; progress argument rejected and all three new tests failed |
| Focused roster/progress | PASS; `25 passed`, then `8 passed` after total-timer refinement |
| Full affected availability/private/ingestion/integration matrix | PASS; `278 passed` |
| Focused changed-module branch coverage | PASS observation; current model 90%, progress 93%; all new Stage-7 progress/error branches covered |
| Ruff format/lint | PASS; 746 files formatted; all lint checks passed |
| Strict mypy | PASS; zero issues in 281 source files |
| Frozen sync | PASS; 40 development packages unchanged |
| Build | PASS; sdist and `dmf_pulse-0.2.0-py3-none-any.whl` built |
| Clean installed wheel | PASS; v0.2.0, 43 players, 990 minutes, manual max 40 and OUT-identity hash binding verified outside source tree |
| Temporary wheel environment | PASS; exact validated temp target removed after verification |
| Live prerequisites | BLOCKED; Odds key, FPL bearer and runtime entry-ID presences are all false |
| Repository/secret validation | PASS; two 1300-file deterministic manifests, zero repository errors and zero secret findings |
| Exact final-SHA CI | Pending final commit and push |

The first build invocation encountered the same transient Windows application-control denial of
the `uv.exe` launcher recorded in 001I. Repeating through the approved absolute uv executable
completed without a dependency or code change. The generic wheel verifier also required an absent
test-database URL, so a smaller isolated offline wheel check exercised the exact changed contracts
without introducing a database or network dependency.
