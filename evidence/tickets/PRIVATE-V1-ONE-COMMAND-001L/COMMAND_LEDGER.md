# PRIVATE-V1-ONE-COMMAND-001L command ledger

All commands ran from isolated worktree `review_pack/one-command-l` on the required branch. The
unrelated dirty root worktree was not modified. No credential, entry ID, provider body or private
state is recorded.

| Gate | Result |
|---|---|
| Parent/worktree | PASS; exact parent `9ce56b93502b894a5c2763d6f19e013714336b00` |
| Parent exact-SHA CI | PASS; GitHub Actions run `33671160751` |
| RED batch API/kernel | PASS; imports failed before implementation |
| Golden/multi-squad batch | PASS; complete exact tuples/hashes and shuffled order |
| Frozen private old/new | PASS; entire optimiser result identical |
| Affected optimiser/private matrix | PASS; 103 tests after final kernel |
| Focused branch coverage | PASS; 103 tests, aggregate 92.74%, tactics 96%, private service 91% |
| Full 263x256 benchmark | PASS; exact, 1,510.7243s to 14.8505s, 101.7292x |
| Unique-global-mask stress | PASS; 256 masks, 263 accelerated squads in 14.9435s |
| Ruff format/lint | PASS; 748 files formatted, zero lint findings |
| Strict mypy | PASS; zero issues in 281 source files |
| Frozen sync | PASS; 40 development packages unchanged |
| Build | PASS; sdist and `dmf_pulse-0.2.0-py3-none-any.whl` built |
| Clean installed wheel | PASS for locked install/version/doctor/rules and installed 001L modules |
| Literal live GW3 | BLOCKED; Odds key, FPL bearer and runtime entry-ID presences are false |
| Repository/secret validation | PASS; refreshed active manifests and zero secret findings |
| Exact final-SHA CI | Pending final commit and push |

The repository's generic clean-wheel verifier passed its clean locked build/install, version,
doctor and installed-rules checks, then stopped at the absent local `DMF_TEST_DATABASE_URL`. A
separate offline isolated wheel probe confirmed version 0.2.0 and that all three changed modules
and their batch APIs came from site-packages. The probe's unlocked Typer console-script wrapper
was blocked by host application control and is not used as a CLI success claim.

The monolithic 4,000+ test coverage gate is intentionally left to the mandatory repository
eight-shard exact-SHA CI, matching the accepted 001K workflow. The affected local matrix and
focused branch-coverage gate completed without failure.
