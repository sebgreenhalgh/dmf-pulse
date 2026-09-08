# R4 command evidence

All commands were run in the isolated R4 worktree. The unrelated dirty root worktree was
preserved. `uv run python` uses the frozen Python 3.13 environment. No private IDs or provider
bodies were used in these checks.

| Command / check | Observed result |
|---|---|
| `git rev-parse HEAD` before implementation | `47215656bac92d0ef72077b79e179a8c001915bc` |
| `gh run view 34251969815 --json headSha,status,conclusion` | Exact parent, completed/success; checked before work and again before publication |
| Initial scope regression | RED: missing `TransferActionScope` before implementation |
| `uv run python -m pytest tests/unit/optimisation/test_future_transfer_scope.py -q --tb=short` | Initial expanded matrix: 13 passed in 47.59 s; subsequent club-slot/cohort-price test passed |
| Branch-instrumented new scope and assembly tests | 15 passed in 137.67 s before final defensive additions |
| Final counterfactual absent/incomplete/mismatch tests | 3 passed, 13 deselected in 1.62 s |
| Final FT-only decision/report coverage append | 1 passed in 23.66 s |
| Final complete new scope/assembly test files | PASS, 19 passed in 58.42 s |
| Broad branch-instrumented acceptance command below | PASS, 509 passed in 2042.62 s |
| `coverage combine --data-file=review_pack/r4/.coverage-final --keep review_pack/r4/.coverage review_pack/r4/.coverage-new` | PASS, both measured runs combined |
| Affected six production modules, `coverage report --fail-under=90` | PASS, 93% combined; 3,108 statements, 994 branches |
| Changed executable lines and originating branch arcs versus immutable parent | PASS, 88/92 = 95.652174%; missing only defensive error paths |
| `uv run python -m ruff check .` | PASS |
| `uv run python -m ruff format --check .` | PASS, 765 files |
| `uv run python -m mypy src` | PASS, 284 source files |
| `uv sync --frozen` | PASS, 40 packages; lock unchanged |
| `uv build --no-build-isolation` | PASS, wheel and sdist version 0.2.0 |
| `uv run python scripts/verify_current_score_prior_wheel.py` | PASS, inherited offline source-rights/conversion/hash tests outside repository |
| Existing offline wheel harness with standalone R4 smoke | PASS, installed scope model and `pulse --help` including `--horizon-gameweeks`, clean environment outside repository |
| `uv run python -c 'from dmf_pulse.cli.app import app; app()' specs validate` | PASS, 94 decisions, 22 documents, 19 scopes |
| `uv run python scripts/generate_repository_manifest.py --ticket PRC-013` | Active canonical manifest regenerated; final regeneration follows all source/test edits |
| `uv run python scripts/validate_repository.py` | PASS, zero errors |
| `uv run python scripts/scan_secrets.py` | PASS, zero findings |
| `uv run python -m pytest tests/integration/repository/test_manifests.py -q --tb=short -p no:cacheprovider --basetemp=review_pack/r4/manifests` | PASS, 4 tests |
| `git diff --check` | PASS |

The combined coverage JSON is operational output at `review_pack/r4/coverage.json`, SHA-256
`9c40803f32930c7ae747793f9a28181ff6660210e3b68634e0ebcf4aed20452a`. Changed-code coverage counts
only executable added lines and branch arcs originating on added lines from
`git diff --cached --unified=0 HEAD -- src`. Missing arcs: rolling.py 769->772 and 833->834;
rolling_models.py 527->528, plus line 528. No source line or branch exclusion was added.

The final manifest retest passed all four tests in 2.28 s, with repository validator and
secret scan again returning zero findings. Protected ingestion, Stage 7/8/9, one-command
assembly, configuration, approved authority, CI and dependency paths were compared with
the parent and are byte-identical. The supplementary review bundle passed the existing
flat-layout/20-file cap check and archive content-hash checks.

The broad branch-instrumented acceptance command is:

```text
uv run python -m coverage run --branch --data-file=review_pack/r4/.coverage -m pytest tests/unit/optimisation tests/property/optimisation tests/contract/optimisation tests/golden/optimisation tests/unit/private_v1 tests/unit/ingestion/test_fpl_entry_duplicate_resolution.py tests/unit/ingestion/test_one_command_assembly.py -q --tb=short -p no:cacheprovider --basetemp=review_pack/r4/pytest
```

Final new/defensive tests were separately measured with `coverage run --branch` and appended
to `review_pack/r4/.coverage-new`, then combined with the broad run. No thresholds or
exclusions were changed. All pytest temporary directories are operational output beneath
`review_pack/r4`, not removed from repository scope by a new exclusion.

Development corrections: the assembly fixture has one retained incoming player, so its
search cap must remain one (not an asserted two). A test exception import and synthetic
decision resealing were corrected. Windows denied several sandboxed executable launches;
the same commands ran with approved execution permissions. The inherited score-prior smoke
intentionally blocks market imports, so the pulse smoke was run separately, not appended
inside that unrelated import blocker.

The canonical review-pack command reports `REVIEW_TICKET_UNSUPPORTED` for R4. No new review
infrastructure or governance bypass was added; the supplementary local review ZIP is labelled
as such and uses the existing flat-entry/20-file cap checker. It is not a canonical acceptance
certificate. No independent external reviewer was available in this session.
