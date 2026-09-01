# Command and gate ledger

All commands ran from isolated worktree `review_pack/e2e` on
`readiness/PRIVATE-V1-E2E-001A`, based on
`7f4254905bccf79cdc282d04f4928cba850276be`.

| Gate | Result |
|---|---|
| Parent/ref/worktree/CI preflight | PASS; parent CI `33453614474` exact SHA green; dirty availability worktree untouched |
| Fast private contracts/boundaries/coherence/CLI after hardening | `34 passed in 6.14s` |
| Full exact synthetic service freeze/replay after runtime hash additions | `1 passed in 358.09s` |
| Branch-instrumented private suite before added hostile tests | `25 passed in 544.00s`; coverage gate correctly failed at 85% |
| Added-hostile-tests coverage append over unchanged production code | `34 passed in 9.33s`; total 966 statements, 218 branches, 90% PASS |
| Broad current manager/unified state/markets/Stage-7/Stage-8/Stage-9/captain/all optimisation regressions | `656 passed in 5693.15s` |
| Whole-repository Ruff format/lint | PASS; 717 files formatted, zero lint errors |
| Whole-repository strict mypy | PASS; zero issues in 268 source files |
| `git diff --check` | PASS |
| Frozen dependency sync | PASS; 40 packages checked |
| Version/config smoke | PASS through package entry function: `dmf 0.2.0`; TEST configuration valid |
| Build | sdist and wheel PASS |
| General clean installed-wheel verifier | PASS; network fetch disabled; exact runtime graph; DB/schema/demo/as-of healthy |
| Dedicated installed-wheel private replay | PASS outside source tree with exact lock and DNS/socket guard |
| Repository validation | PASS, zero errors after active PRC-013 manifest refresh |
| Secret scan | PASS, zero findings after generated-test cleanup |
| Synthetic replay manifest | `a4b1c8e2a55fb361bc87481e156641151035bddc6d7730e101334f46c95c187d` |
| Real current operator attempt | `IMPLEMENTED_REAL_RUN_BLOCKED`; no recommendation or manifest emitted |

The first general wheel-verifier attempt was an honest precondition failure because
`DMF_TEST_DATABASE_URL` was absent. The pinned disposable PostgreSQL service was then started,
migrated to `20260807_0006`, the verifier passed, and the container/network/volume were removed.
The dedicated external wheel environment was also removed after its successful replay.

Windows Application Control blocked the worktree `.venv` launcher executable for the local
version/config smoke. The identical package entry function passed under the environment Python,
and the independently installed wheel's `dmf.exe` completed the full replay, so this is recorded
as launcher policy rather than an application failure.

Push and exact-final-SHA CI results remain pending and must not be inferred before those commands
complete.
