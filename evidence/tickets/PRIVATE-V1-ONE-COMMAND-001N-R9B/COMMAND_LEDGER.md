# R9B command ledger

All engineering inputs are synthetic or previously committed historical artifacts.
No live FPL/Odds call, credential inspection or live recommendation is authorized.
Existing unrelated shared-worktree edits remain untouched.

## Initial checkpoints

- `git status --short`: parent checkout, two previously generated untracked files;
  continue those files, do not restart.
- Local `git show b4353dbd...:evidence/tickets/GW1-PLY-003/GW1_CURRENT_PLAYER_POSTERIOR_{CENTRAL,LOW,HIGH}.json`:
  all three stored canonical artifact digests independently recomputed and equal.
- Initial focused tests: 36 passed. Expanded source-relation/diagnostic tests: 57
  passed. The first fallback assertion was corrected to compare numerical rates
  and identity: a changed event-live body legitimately changes every row's source
  digest, even for unchanged players. No such provenance change is numerical drift.
- Windows sandbox initially denied pytest's existing temporary directory. The
  same offline tests passed using approved execution with temporary-file access.
- Strict mypy for the three added production modules: passed at this checkpoint.

## Final local commands

Working directory for all commands is the isolated `review_pack/one-command-n-r9b`
worktree. Parent worktree `../one-command-n-r9a` is clean at the immutable parent.
Commands below use only repository-owned synthetic or historical inputs.

```text
uv sync --all-groups --frozen
uv run ruff format --check .
uv run ruff check .
uv run python -m mypy src/dmf_pulse
uv build
uv run python scripts/verify_r9b_wheel.py
uv run python scripts/generate_r9b_historical_rate_priors.py
uv run pytest tests/unit/fpl_points/test_current_player_shadow.py tests/unit/fpl_points/test_current_player_shadow_diagnostics.py tests/unit/fpl_points/test_current_player_posterior_contract.py tests/unit/fpl_points/test_current_player_shadow_operations.py tests/unit/fpl_points/test_current_player_shadow_stage9.py --cov=dmf_pulse.fpl_points.current_player_posterior --cov=dmf_pulse.fpl_points.current_player_shadow --cov=dmf_pulse.fpl_points.current_player_shadow_diagnostics --cov-branch --cov-report=term-missing --cov-report=json:review_pack/r9b-coverage.json --cov-fail-under=90 -q --junitxml=review_pack/r9b-focused.xml
uv run pytest tests/unit/ingestion tests/unit/availability tests/unit/fpl_points tests/unit/private_v1 tests/unit/optimisation/test_stage10_r7_factoring.py tests/unit/optimisation/test_stage11_r7_layers.py tests/unit/optimisation/test_terminal_r7_equivalence.py tests/unit/optimisation/test_stage11_exact_acceleration.py tests/unit/optimisation/test_r7_canonical_primitives.py tests/unit/optimisation/test_three_gameweek_horizon.py -m "not postgres and not migration and not performance" -q --disable-warnings --junitxml=review_pack/r9b-regression.xml
uv run pytest tests/performance/optimisation/test_preflight.py tests/performance/fpl_points/test_smoke_budget.py -q
uv run python scripts/collect_r9b_synthetic_evidence.py --output evidence/tickets/PRIVATE-V1-ONE-COMMAND-001N-R9B/SYNTHETIC_DIAGNOSTICS.json
uv run python scripts/replay_r7_frozen_service.py --code-root ../one-command-n-r9a --fixture-dir review_pack/r9b-differential/frozen --output review_pack/r9b-differential/parent.json --synthetic-fixed-build-identity
uv run python scripts/replay_r7_frozen_service.py --code-root . --fixture-dir review_pack/r9b-differential/frozen --output review_pack/r9b-differential/candidate.json --synthetic-fixed-build-identity
uv run python scripts/generate_repository_manifest.py --ticket PRC-013
uv run python scripts/generate_repository_manifest.py --ticket PRIVATE-V1-ONE-COMMAND-001N-R9B
uv run python scripts/validate_repository.py
uv run python scripts/scan_secrets.py
uv run pytest tests/integration/repository/test_manifests.py tests/unit/assurance/test_manifests.py -q
git diff --check
```

Observed: 85 focused pass, 1792 broad pass (one warning), 2 performance smoke pass.
Final changed production coverage: 97.8261% combined; 458/464 statements and
127/134 branches. Ruff clean; strict mypy clean across 291 source files; frozen
sync 40 packages; sdist/wheel built; R9B external installed-wheel smoke PASS.
Canonical repository generation recorded 1401 files in each current manifest.
Source-isolated replay equality is recorded in ACTIVE_PATH_DIFFERENTIAL.json.

## Failed/superseded checks disclosed

- `uv run mypy src/dmf_pulse` launcher was rejected by Windows Application Control
  (4551); the same installed strict checker passed via `uv run python -m mypy`.
- First external wheel attempt timed out during isolated frozen sync; retry and
  final rebuilt-wheel verification passed. No timeout was represented as success.
- Canonical `scripts/verify_wheel.py::verify_wheel`, invoked with an R9B-scoped
  report path, requires `DMF_TEST_DATABASE_URL`; it stopped before that database
  validation because no local test database was supplied. No unrelated report was
  written. The R9B clean-wheel check passed separately; full database acceptance is
  required in exact-SHA CI, not claimed locally.
- Initial `uv run pytest` collection could not import script modules from repository
  root; the test helper now explicitly loads the script paths. Canonical rerun passed.
- A superseded generic tactical experiment was stopped after checking its exact
  process command. The final harness uses the existing exact R7 kernel and unchanged
  sealed cumulative budgets. A 64-scenario candidate exceeded that budget and was
  correctly blocked; the recorded two-squad experiment uses 16 scenarios.
- A test compared Decimal formatting (`1.000` versus `1`) instead of value; it was
  fixed to assert exact Decimal equality, not a tolerance or altered result.

Independent review, publication and exact-SHA CI remain pending at this checkpoint.

## Publication hygiene

- Local implementation checkpoint: `53fac8339dd06891787713ea08e45d29d5c6c2f8`.
- Manifest tests: 8 passed in 2.04s. Repository validator: zero errors. Secret scan:
  zero findings. Diff whitespace check passed.
- Git index/newline inspection caught a Windows CRLF in the generated compact
  resource. The generator now explicitly emits LF and bounds local Git reads to
  30 seconds. Regenerated numerical/resource semantic hash is unchanged; current
  manifests now describe the exact Git-published bytes. No model change.
- `uv run python scripts/build_review_pack.py --ticket PRIVATE-V1-ONE-COMMAND-001N-R9B --output review_pack/R9B --baseline b4d4c774ac4150a6fbdeb579c143a0458fa9156b`
  returned REVIEW_TICKET_UNSUPPORTED: the existing canonical builder only supports
  its installed foundation ticket list. It was not weakened or extended out of
  scope. A bounded Git source-delta archive is used as a supplementary review aid,
  not a canonical acceptance certificate; the reviewer inspects the full Git diff.

## Independent-review remediation validation

- Hygiene checkpoint: `44d305c7ddedc04081bbb9a1cadb542b79a459ad`.
- Reviewer identified one material P2 missing acceptance-test matrix, not a formula
  defect. Added all-donor/channel three-world historical arithmetic parity, matched
  three-strength/fixed-rate exposure response, exact compiled assist ratio, and
  a resealed Stage-7 future-minute perturbation proving no posterior reweighting.
- Reviewer P3 unit ambiguity resolved: aggregate discipline exclusions are now
  explicitly `zero_exposure_discipline_excluded_channel_rows`, not unique player-GWs.
  A fully published yellow/red player-GW can contribute two channel-rows, including
  observed-zero counts. Excluded event sums and rate numerics are unchanged.
- Repeated the exact focused coverage command above: **93 passed in 30.16s**,
  97.8261% combined coverage. Ruff format/check and strict mypy passed. Refreshed
  synthetic summaries, active replay, sdist/wheel, and external R9B wheel check:
  all passed; shadow/resource and active numerical hashes remain unchanged.
- Latest native build identity is recorded separately in ACTIVE_PATH_DIFFERENTIAL;
  the diagnostic-label source change is not numerical recommendation drift.
- Supplementary review archive checkpoint: 29 files, 1770895 uncompressed bytes
  under a 5 MiB cap; canonical builder unsupported status remains disclosed.
