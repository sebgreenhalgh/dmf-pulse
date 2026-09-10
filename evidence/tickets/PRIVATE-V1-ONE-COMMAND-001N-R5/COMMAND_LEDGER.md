# R5 command ledger

Commands run in `review_pack/one-command-n-r5`. Python uses the frozen Python 3.13 environment.
All inputs for tests and profiling are repository-owned synthetic data, not live identities.

| Command/check | Observed result |
|---|---|
| Parent `gh run view 34259589435 --json headSha,status,conclusion,jobs` | Exact required R4 SHA, all 12 jobs successful |
| `git worktree add -b readiness/PRIVATE-V1-ONE-COMMAND-001N-R5-horizon-candidate-scope review_pack/one-command-n-r5 56a0776e8e13bfae31297b6b40f631361e1fce95` | Isolated branch created at exact parent |
| Initial new horizon-screen pytest file | RED, missing `_horizon_private_incoming_ids` before implementation |
| Final horizon-screen unit file | 10 passed in 2.03 s, including distinct-bucket overflow |
| Initial exact reduced-universe oracle and screen matrix | 13 passed in 41.98 s; final run also uses generic full-universe oracle |
| Stage-11 `test_multi_gameweek*` unit files and property matrix, branch instrumented | 216 passed in 42.83 s |
| Broad private/R2/R4/frontier/contract/golden/FPL matrix below | 291 passed in 1670.61 s |
| Final automatic scope/report service test | 1 passed in 42.18 s; V2 emitted, stale V1 absent from three-GW report |
| Fresh final screen/oracle/rolling/three-GW one-command coverage suite | 46 passed in 771.94 s |
| Changed executable lines and originating branch arcs, fresh final run only | PASS, 85/85 = 100%; no missing changed executable lines/arcs |
| One-GW helper source comparison against exact parent | Ranking, pointwise dominance and bounded screen bodies unchanged |
| `uv run python -m ruff check .` | PASS |
| `uv run python -m ruff format --check .` | PASS, 769 files |
| `uv run python -m mypy src` | PASS, 284 source files |
| `uv sync --frozen` | PASS, 40 locked packages, dependency pins unchanged |
| `uv build --no-build-isolation` | PASS, version 0.2.0 wheel and sdist |
| Existing offline score-prior installed-wheel verifier | PASS, clean external environment, source rights/hash/conversion checks |
| Standalone pulse installed-wheel verifier | PASS, pulse help/horizon option and V2 policy import outside source tree |
| `uv run python -c 'from dmf_pulse.cli.app import app; app()' specs validate` | PASS, 94 decisions, 22 documents, 19 scopes |
| `uv run python scripts/benchmark_horizon_candidate_scope.py --output evidence/tickets/PRIVATE-V1-ONE-COMMAND-001N-R5/benchmark.json` | Complete synthetic retained searches, reduced fast/generic equality; full profiles in JSON |
| `git diff --check` | PASS |
| Active PRC-013 and R5 canonical manifest generators | Both generated, 1,342 deliverables |
| Repository validator and first-party secret scan | PASS, zero errors/findings |
| Repository manifest integration tests | 4 passed in 3.99 s |
| Canonical R5 review-pack command | `REVIEW_TICKET_UNSUPPORTED`; supplementary capped bundle used, not a canonical certificate |

Fresh final-code coverage JSON: `review_pack/r5/final-private-coverage.json`, SHA-256
`8c352818828b82c8dc80a519b03e2be09ce08188469fcab620b3325673e4764c`. The changed-code metric
uses executable added lines and arcs originating on added lines from `git diff --unified=0
HEAD -- src` against the immutable parent. Non-executable continuation lines in multi-line
expressions have no independent coverage denominator; end-to-end tests explicitly assert
the three-GW version/report values. Earlier instrumented snapshots are not combined into this
final changed-code measurement.

The 600-incoming-player benchmark retained 8 R4 / 9 R5, with 600 post-dominance in both cases.
R4: 31 root actions, 2,767 unique tactical node/squad evaluations, 25.981561 s.
R5: 34 root actions, 3,680 unique tactical node/squad evaluations, 34.832721 s.
The five-incoming-player benchmark retained 2 R4 / 4 R5; R5 accelerated/generic candidates
matched exactly and each evaluated 223 unique tactical node/squad keys. Timings are one
synthetic measurement while other acceptance work may be active, not live-runtime guarantees.

Development corrections were test-output directory creation, exact cross-universe comparison
of identity-dependent hashes, batched tactical counting using cache size rather than scalar
call count, and an end-to-end RED exposing the stale V1 three-GW header. None weakens exact
candidate/plan comparisons within the same request. No threshold or coverage exclusion changed.

Branch-instrumented broad command:

```text
uv run python -m coverage run --branch --data-file=review_pack/r5/.coverage -m pytest tests/unit/private_v1 tests/unit/optimisation/test_stage11_exact_acceleration.py tests/unit/optimisation/test_future_transfer_scope.py tests/unit/optimisation/test_three_gameweek_horizon.py tests/unit/optimisation/test_transfer_count_frontier.py tests/contract/optimisation tests/golden/optimisation/test_stage11_golden.py tests/golden/optimisation/test_three_gameweek_ft_carry.py tests/unit/ingestion/test_fpl_entry_duplicate_resolution.py tests/unit/ingestion/test_one_command_assembly.py -q --tb=short -p no:cacheprovider --basetemp=review_pack/r5/coverage-tests
```

Fresh final production-label coverage is collected separately from the initial broad run,
including horizon screen/oracle, automatic scope assembly, all rolling service/contracts, and
the literal three-GW one-command synthetic orchestration. Repository manifests are regenerated
before publication. Exact-SHA CI is a mandatory post-push gate, not inferred from local results.
