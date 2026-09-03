# PRIVATE-V1-ONE-COMMAND-001M command ledger

All commands ran from isolated worktree `review_pack/one-command-m` on the required branch. The
unrelated dirty root worktree was not modified. No credential, private entry ID, provider body or
private manager state is recorded.

| Gate | Result |
|---|---|
| Parent/worktree | PASS; exact parent `7001d507142cbef8c1d54bff88b3fa67810e65a2` |
| Parent exact-SHA CI | PASS; GitHub Actions run `33688833338` |
| RED frontier contracts | PASS; frontier imports failed before implementation |
| Focused frontier tests | PASS; 19 tests after hostile/legacy additions |
| Final focused/golden replay | PASS; 19 focused and 33 Stage-11 golden tests |
| Optimisation property/contract tests | PASS; 64 tests |
| Stage-11 golden tests | PASS; 33 tests after intentional successful-result hash refresh |
| Affected measured matrix | PASS; 383 tests in 913.23 seconds |
| Changed-code branch coverage | PASS; 90.40% aggregate with branch instrumentation |
| Stage-10 re-evaluation oracle | PASS; zero additional evaluator calls for frontier selection |
| Frozen recommendation equality | PASS; action, moves, squad, tactics, hold tactics and paired summary byte-identical |
| Sequential synthetic benchmark | PASS; median 8.296368s parent, 8.325914s current, +0.029546s / about 0.36% |
| Ruff format/lint | PASS; 751 files formatted, zero lint findings |
| Strict mypy | PASS; zero issues in 282 source files |
| Frozen sync | PASS; 40 packages checked and unchanged |
| Build | PASS; sdist and `dmf_pulse-0.2.0-py3-none-any.whl` built |
| Clean installed wheel | PASS; locked offline install outside source tree, version, doctor, rules, imports and additive contracts |
| Generic wheel verifier | BLOCKED after clean build/install/version/doctor/rules; local `DMF_TEST_DATABASE_URL` is absent |
| Repository/evidence/secret validation | PASS; repository, exact ticket manifest and secret scan |
| Generic capped review-pack builder | NOT APPLICABLE; repository reports this newer ticket contract is not installed |
| Exact final-SHA CI | Pending final commit and push |

The generic verifier's database step was not bypassed and no credential was invented. The
equivalent ticket-relevant wheel probe first synchronized the repository's frozen runtime
environment into a new temporary virtual environment, installed the built wheel with no
dependencies, and verified `dmf 0.2.0`, healthy doctor output, synthetic rules validation,
site-packages import provenance, both additive frontier fields and the installed renderer.

The coverage dataset combines the materially affected unit, property, contract, golden and
integration suites. It contains 402 passing test executions, including 19 focused hostile and
legacy cases appended to the 383-test measured matrix, and reports 90.40% line coverage with
branch measurement enabled. The repository's complete sharded gate remains mandatory on the
pushed exact final SHA.

The ticket-specific repository manifest and the refreshed active `PRC-013` repository manifest
both cover the exact 1,311 deliverable files and validate without drift. The first-party capped
review-pack builder does not install a contract for this post-PRC private ticket family, so its
explicit `REVIEW_TICKET_UNSUPPORTED` response is recorded rather than misrepresented as a pack.

The first final-replay invocation selected a nonexistent nested `review_pack` parent for pytest's
base temporary path, so pytest reported setup errors before any test body ran. The unchanged
commands were rerun against an existing workspace-owned temporary parent and passed 19/19 and
33/33; the exact generated temporary directories were then removed.
