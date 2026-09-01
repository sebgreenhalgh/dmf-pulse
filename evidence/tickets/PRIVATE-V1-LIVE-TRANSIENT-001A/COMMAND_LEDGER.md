# PRIVATE-V1-LIVE-TRANSIENT-001A command ledger

All product commands ran from the isolated `review_pack/live-transient` worktree on
`readiness/PRIVATE-V1-LIVE-TRANSIENT-001A`, based on exact parent
`8f1047e24745afbcaf27c8aed7e8fdebc6203cd9`. No real official-FPL network, authentication,
credential, database-write, replay-write or report-write action occurred.

| Gate | Result |
|---|---|
| Parent/ref/worktree/CI preflight | PASS; parent CI `33473963268`, attempt 2, exact parent SHA successful; unrelated dirty root worktree untouched |
| Focused authority/prior/CLI tests | PASS; 14 tests before the live E2E checkpoint |
| Current-like transient E2E before final hardening | PASS; 1 test in 244.53s, then branch-instrumented PASS as part of 15 tests in 937.73s |
| New authority/live focused branch coverage | PASS; authority 100%, live service 96%, combined 98% after fail-before-read tests |
| Complete private/current-allocation regression after hardening | PASS; 48 tests in 537.16s, including live transient and unchanged synthetic freeze/replay |
| Manager/unified-state/prior/rules regression | PASS; 278 tests in 120.05s |
| Rules anti-hardcoding contract | Initial broad run found one target-season literal in a runtime conditional; fixed with a hash-bound attestation season field; complete contract 12/12 PASS |
| Frozen dependency sync | PASS; exact lock, 40 packages |
| Ruff format and lint | PASS; 722 files formatted, zero lint findings |
| Strict mypy | PASS through `python -m mypy`; zero issues in 270 source files. Direct launcher was blocked by Windows application control |
| Diff whitespace | PASS |
| Build | PASS; `dmf_pulse-0.2.0.tar.gz` and `dmf_pulse-0.2.0-py3-none-any.whl` |
| Locked clean-wheel live CLI smoke | PASS outside source tree; version 0.2.0, exact frozen runtime graph, live command present, no output/freeze options, temporary environment removed |
| Broad sealed-state local suite | Pytest completed `3754 passed, 1 skipped, 253 deselected, 114 warnings in 1777.09s`; the one skip states disposable PostgreSQL is not configured. The PTY wrapper returned nonzero at its approximately 30-minute ceiling after the complete pytest summary, so exact exit-code acceptance is deferred to sharded CI |
| Real operator-input inventory | BLOCKED before execution; every approved candidate input root was absent; no payload or credential read |
| Repository manifests | PASS; active PRC-013 and ticket manifests each cover 1,254 files |
| Repository validation | PASS; zero errors through the read-only validator entry point |
| Secret scan | PASS; zero findings |
| Exact final-SHA CI | Must be observed after the final push; not inferred in repository evidence |

Earlier broad attempts were stopped and classified rather than relabelled successful when they
reached unexcluded database tests or the intentionally stale pre-sealing manifest. The final
sealed-state run completed every locally selected test. GitHub Actions supplies pinned PostgreSQL
18.4 and is the controlling exit-code proof for the sharded complete collection.
