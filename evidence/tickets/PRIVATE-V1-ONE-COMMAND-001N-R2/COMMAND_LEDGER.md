# Command ledger

All work is in the isolated `review_pack/one-command-n-r2` worktree on the requested branch.
The unrelated dirty root worktree is preserved. Python commands use the frozen Python 3.13
environment; `python` below denotes that environment's interpreter.

| Gate / command | Observed result |
|---|---|
| `git rev-parse HEAD` before implementation | Exact immutable parent `43229ea760bc2b3587a4ed05e22bef3c9e505497` |
| `gh run list --branch readiness/PRIVATE-V1-ONE-COMMAND-001N-R1-score-prior-prefetch --limit 1 --json databaseId,headSha,status,conclusion` | Parent CI `33741523810`, completed/success at the exact parent SHA |
| Initial new-test RED | Import of not-yet-implemented `Stage11SearchProfile` failed |
| Expanded precondition RED | Expected exception type in new test corrected to `InputInvalidError`; all guarded requests were already rejected |
| Broad inherited run, `coverage run --branch -m pytest` over multi-Gameweek/Stage-10-batch/new tests plus `tests/unit/private_v1` | 384 passed; one generic monkeypatch-seam failure in 1010.60 s; corrected by preserving the old generic call signature |
| Corrected seam plus initial 36 new tests | 37 passed in 23.85 s |
| Final core branch-instrumented matrix | 313 passed in 287.54 s; exact argv and log hash in `final_core_tests.json` |
| Appended Stage-11 golden/integration, three-GW FT, 001M frontier, private boundaries and replay/profile tests | 132 passed in 179.51 s |
| Final node-kernel/cache/multiobjective branch pass | 3 passed in 3.11 s |
| Final complete new acceleration test file, workspace-local temp | 42 passed in 26.46 s |
| Changed executable lines and originating branch arcs versus immutable parent | PASS, 461/465, 99.139785%; no new exclusions |
| Six affected modules, aggregate statement/branch gate `coverage report --fail-under=90` | PASS, 2,236 statements and 682 branches, 90.78% combined coverage |
| STANDARD-scale benchmark | PASS, 329.285223 s to 12.577433 s, 26.180639x, full candidate equality |
| Real exact Stage-10 benchmark | PASS, 28.026534 s to 8.110473 s, 3.455598x, full candidate equality |
| Final small structural benchmark smoke | PASS, complete exact candidate equality after dispatch-history hardening |
| `python -m ruff check .` | PASS, no findings |
| `python -m ruff format --check .` | PASS, 761 files |
| Pinned Linux Ruff 0.15.22 in disposable Python 3.13.15 container, read-only source mount, `format --no-cache --check .` | PASS, 761 files; no retained container |
| `python -m mypy src/dmf_pulse` | PASS, 284 source files |
| `uv sync --all-groups --frozen` | PASS, 40 packages checked; lock/dependencies unchanged |
| `python -m build --no-isolation` | PASS, `dmf_pulse-0.2.0.tar.gz` and `dmf_pulse-0.2.0-py3-none-any.whl` |
| Installed wheel using the existing offline clean-environment harness | PASS, version/imports and `dmf pulse --help` horizon option outside source tree |
| `python scripts/verify_current_score_prior_wheel.py` | PASS, inherited offline rights, pinned-source, no-network, conversion and hash-tamper checks |
| `dmf specs validate` | PASS, 94 decisions, 22 documents, 19 scopes |
| `python scripts/generate_repository_manifest.py --ticket PRC-013` and `--ticket PRIVATE-V1-ONE-COMMAND-001N-R2` | Regenerated current manifests; the inherited repository validator consumes the PRC-013 manifest |
| `python scripts/validate_repository.py` | PASS, zero errors |
| `python scripts/scan_secrets.py` | PASS, zero findings |
| `git diff --check` | PASS |

The first child-process coverage capture was blocked by permissions on the shared Windows
pytest temp directory. The rerun used a fresh, explicitly scoped workspace-local temp path and
disabled pytest's optional cache provider; neither test selection nor assertion behavior changed.
The separate earlier broad direct run was unaffected. The first Linux formatting attempt could
not create a cache in the read-only mount; the rerun disabled Ruff's cache. The initial sandboxed
uv launch was denied and the approved identical frozen-sync retry passed. These were environment
or harness issues, not bypassed acceptance gates.

The appended command was `python -m coverage run --append --branch
--data-file=review_pack/r2/.coverage-final -m pytest` with
`tests/unit/optimisation/test_stage11_exact_acceleration.py`,
`tests/unit/optimisation/test_three_gameweek_horizon.py`,
`tests/unit/optimisation/test_transfer_count_frontier.py`,
`tests/golden/optimisation/test_stage11_golden.py`,
`tests/golden/optimisation/test_three_gameweek_ft_carry.py`,
`tests/contract/optimisation/test_stage11_integration.py`,
`tests/unit/private_v1/test_transfer_frontier.py`,
`tests/unit/private_v1/test_artifact_boundaries.py`, and
`tests/unit/private_v1/test_input_coherence.py`, plus `-q --tb=short -p no:cacheprovider
--basetemp=review_pack/r2/pytest-append-001`. The final three-test append selects
`node_kernel or future_node_batch or multiobjective` from the new acceleration test file,
with a separate `pytest-append-002` temp path. All appends use the same final production source.
The changed-code branch proof and capped archive are sealed separately after these commands.
No coverage threshold, exclusion, workflow permission, dependency pin or CI shard is weakened.

Final commit identity and exact-SHA CI are reported out of band only after push and completion;
embedding a commit's own SHA or its later CI result in that same commit is self-referential.
The optional live three-GW run remains prohibited before green CI and requires all private inputs
already present in the operator environment. No private credentials or entry ID are requested.
