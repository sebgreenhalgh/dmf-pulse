# PRIVATE-V1-ONE-COMMAND-001N-R1 command ledger

All commands run from isolated worktree `review_pack/one-command-n-r1` on the required branch.
The unrelated dirty root worktree is not modified. No credential, private entry ID, provider body,
or private manager state is recorded.

| Gate | Result |
|---|---|
| Parent/worktree | PASS; exact immutable parent `ba8d9917c75ba94e5739c605f38407d4438ff41c` |
| Parent exact-SHA CI | PASS; GitHub Actions run `33725396189` |
| Authority/root cause | PASS; A3/A8/A10/A11/B2 and authenticated source lifecycle reviewed; source acquisition was ordered after long Stage 7 |
| Test-first RED | PASS; Stage-7 boundary observed zero OpenFootball requests before remediation |
| Focused live-shaped regression | PASS; 1 test in 96.86 seconds |
| OpenFootball/source contracts | PASS; 132 tests in 7.38 seconds |
| Existing one-command compatibility | PASS; 8 tests in 188.33 seconds |
| Rolling/three-GW/CLI compatibility | PASS; 45 tests in 71.55 seconds |
| Full private-v1 plus CLI under branch instrumentation | PASS; 130 final-tree tests across the main and appended boundary passes |
| Changed-module coverage | PASS; 92.73% aggregate statement/branch score for `one_command.py`; 251 statements and 38 branches; unchanged 90% gate |
| Full Stage-11 matrix | PASS; 308 unit/golden/property/contract/rolling tests in 131.28 seconds |
| Strict mypy | PASS; zero issues in 284 source files |
| Frozen sync | PASS; 40 packages checked and unchanged |
| Repository-wide Ruff and diff check | PASS; 759 files formatted and zero lint findings |
| Build | PASS; canonical sdist and `dmf_pulse-0.2.0-py3-none-any.whl` built |
| Clean installed wheel | PASS; exact locked runtime sync outside the source tree, installed version/imports, and `pulse --horizon-gameweeks` verified |
| Secret scan | PASS; zero findings after the synthetic credential construction used the established indirect marker pattern |
| First exact-SHA candidate CI | Run `33740594971` failed only at Linux Ruff formatting; no test or coverage job started |

The first isolated `python -m build` attempt could not bootstrap pinned Hatchling because sandbox
network access was denied. The approved identical retry succeeded. A first cleanup attempt for the
resolved disposable environment was denied by the sandbox; the approved retry removed that exact
verified Windows-temp path. Neither event changed repository content or acceptance criteria.

The first pushed candidate exposed one cross-platform Ruff wrapping difference in the new test.
Pinned Ruff 0.15.22 reproduced the GitHub result in a disposable Python 3.13 Linux container; the
one-line formatter output now passes both Windows and Linux checks. The container was removed.

Remaining manifest/repository/secret gates and the exact pushed-SHA CI result are completed or
reported out of band only after they run. Embedding a commit's own final SHA or later CI run ID in
that commit would be self-referential.
