# R6 command ledger

Working directory: `review_pack/one-command-n-r6`, isolated from unrelated root-worktree edits.
All tests/profiles use repository-owned synthetic inputs. No live credentials or identifiers.

| Command/check | Observed result |
|---|---|
| Parent `git show` and `gh run view 34483828704 --json headSha,status,conclusion,jobs` | Exact required R5 SHA, all 12 jobs passed |
| `git worktree add -b readiness/PRIVATE-V1-ONE-COMMAND-001N-R6-bounded-horizon-candidate-search review_pack/one-command-n-r6 9c02ed86bf181c0a7e75c5983f08d23fe8824dc9` | Isolated exact-parent branch |
| Initial new capacity pytest file | RED: V3 module absent before implementation |
| First new node-scope oracle | RED: inherited R2 fast-path rejected differing node scope |
| Subsequent full-universe oracle | RED: missing third incoming in final recourse (124 vs 126; 120 vs 122); depth escape fixed implementation |
| Final screen/oracle/actual comparator/positional budget matrix | 18 passed in 71.92s |
| Resource guard plus final capacity/renaming/failure tests | 13 passed in 1.27s |
| Real automatic service plus R2/R4 regression checkpoint | 61 passed in 92.92s |
| Stage-11 `test_multi_gameweek*` unit and property matrix | 216 passed in 16.71s |
| One-GW helpers and V2 AST source-span comparison to exact parent | PASS, byte-identical after newline normalization |
| `uv run python scripts/profile_horizon_candidate_pressure.py --output review_pack/r6/v2-pressure.json` | Exact V2 union 115 and 36 reproductions, safe counts/overlap/tie/action diagnostics |
| `uv run python scripts/benchmark_bounded_horizon_scope.py --shape <shape> --output review_pack/r6/final-<shape>.json` for large_tie, low_overlap, high_overlap, oracle, near_limit | All final solves complete; reduced fast/generic equality; see benchmark JSON |
| Benchmark `--collect-from review_pack/r6 --output evidence/tickets/PRIVATE-V1-ONE-COMMAND-001N-R6/benchmark.json` | Final/prototype evidence sealed with production source hashes |
| `uv run python -m ruff check .` | PASS |
| `uv run python -m ruff format --check .` | PASS, 774 files |
| `uv run python -m mypy src` | PASS, 285 source files |
| `uv sync --frozen` | PASS, 40 locked packages; pins unchanged |
| `uv build --no-build-isolation` | PASS, version 0.2.0 wheel and sdist |
| `uv run python scripts/verify_current_score_prior_wheel.py` | PASS, clean external offline environment, unchanged conversion/rights/hash tests |
| Same clean-wheel harness with installed `dmf pulse --help` and V3 budget/complete-tie smoke | PASS, imports outside source tree |
| Full actual synthetic three-GW recommendation stack from the installed wheel, automatic V3 scope and pinned comparator | PASS, clean external offline environment; synthetic execution passed in memory via stdin |
| `uv run python -c 'from dmf_pulse.cli.app import app; app()' specs validate` | PASS, 94 decisions, 22 documents, 19 scopes |
| `git diff --check` | PASS |
| Canonical PRC-013 and R6 manifest generators | PASS, 1,349 deliverables each |
| Repository validator (read-only function entry) | PASS, zero errors |
| `uv run python scripts/scan_secrets.py` | PASS, zero findings |
| Repository manifest integration file | 4 passed in 2.13s |
| R6 manifest explicit model/load/validation | PASS, zero errors |
| Canonical review build with exact parent and R6 ticket | `REVIEW_TICKET_UNSUPPORTED`; use supplementary capped bundle, not a canonical certificate |

## Completed extended gates

- Broad private/R2/R4/frontier/R3 matrix: **306 passed in 1674.73s**. This checkpoint overlapped
  candidate-policy refinement; it is not used to calculate final changed-code coverage.
- Fresh final-code matrix below: **99 passed in 804.31s**. Comparator-error fault injection
  added **2 passed in 40.40s**, verifying that no horizon request follows a failed one-GW solve.
- Diagnostic projected action counts independently matched canonical FT2 enumeration:
  **1 passed in 1.29s**. Resource-guard-before-tactical regression also passed.
- Final changed executable lines and originating arcs: **127/127 = 100%**. Including the
  smallest originating AST statement for multiline condition/version edits: **140/140 = 100%**.
  In particular the solver's changed multiline eligibility predicate has both originating
  branches covered, rather than reporting zero independent executable continuation lines.
- Coverage JSON `review_pack/r6/final-coverage.json`: SHA256
  `5acfaaa5d0dc2236c81218cf8cabc7bfd323e2d981a97cfc011ff864113c3ec5`.
  Only the final production snapshot's fresh run and fault-injection append are used. The
  report is exported via Coverage's reporting API. A focused suite is not the repository-wide
  90% gate (the initial CLI report correctly flagged its partial whole-repository denominator).
  Repository thresholds/configuration remain unchanged; complete exact-SHA CI is mandatory.

Publication CI is checked after committing/pushing the immutable implementation SHA and
reported at handoff; it cannot be certified by this pre-publication ledger.

Development corrections: explicit PowerShell test paths replaced an unexpanded pytest wildcard;
the external CLI smoke uses the canonical installed `dmf pulse` entry point, not a nonexistent
`pulse.exe`. These checks failed clearly before correction. No production command contract,
dependency, validation threshold or test assertion was weakened to hide a failure.
The optional full-wheel synthetic check initially rejected an oversized command-line payload
before launch; in-memory stdin avoided Windows argument limits without persisting input bodies.

Broad branch-instrumented command:

```text
uv run python -m coverage run --branch --data-file=review_pack/r6/.coverage-broad -m pytest tests/unit/private_v1 tests/unit/optimisation/test_stage11_exact_acceleration.py tests/unit/optimisation/test_future_transfer_scope.py tests/unit/optimisation/test_three_gameweek_horizon.py tests/unit/optimisation/test_transfer_count_frontier.py tests/contract/optimisation tests/golden/optimisation/test_stage11_golden.py tests/golden/optimisation/test_three_gameweek_ft_carry.py tests/unit/ingestion/test_fpl_entry_duplicate_resolution.py tests/unit/ingestion/test_one_command_assembly.py -q --tb=short -p no:cacheprovider --basetemp=review_pack/r6/broad-tests
```

Fresh final-code coverage command:

```text
uv run python -m coverage run --branch --data-file=review_pack/r6/.coverage-final -m pytest tests/unit/private_v1/test_bounded_horizon_candidates.py tests/unit/private_v1/test_bounded_horizon_oracle.py tests/unit/private_v1/test_future_scope_assembly.py tests/unit/private_v1/test_rolling_service.py tests/unit/private_v1/test_rolling_contracts.py tests/unit/private_v1/test_rolling_contract_hardening.py tests/unit/private_v1/test_one_command.py tests/unit/optimisation/test_stage11_exact_acceleration.py -q --tb=short -p no:cacheprovider --basetemp=review_pack/r6/final-coverage-tests
```
