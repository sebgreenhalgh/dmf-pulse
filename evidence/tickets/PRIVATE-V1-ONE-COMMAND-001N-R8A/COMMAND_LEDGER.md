# R8A command ledger (synthetic engineering only)

- Read the supplied execution request, R8 research Markdown and source register.
  Broader R8B research instructions are not active implementation authority.
- Reverified parent SHA and gh run view 34619880451: all 12 exact-SHA jobs success.
- Created isolated worktree/branch at c60d5b34a7d8922cd274d1ef28648b9e6235d718.
- RED: uv run python -m pytest tests/unit/ingestion/test_horizon_probe.py -q --tb=short
  failed at missing horizon_probe module, before implementation.
- Initial fixture setup corrections: unique FPL fixture codes and consistent
  is_next/is_current flags; corrected synthetic OddsHttpResponse argument order.
- Corrected profile hashing to serialize immutable capabilities explicitly.
- Initial nine observation tests passed; expanded first set: 55 passed.
- Affected parser/client/identity/direct-FPL/one-command ingestion regressions:
  294 passed in 16.20 seconds (including the then-current focused tests).
- Synthetic end-to-end spies corrected to use existing CurrentScorePriorService.build;
  large payload parameter given a bounded test ID (no live material involved).
- Expanded focused suite: 81 passed in 4.79 seconds under branch coverage.
  Classifier 96%, operator script 98%, combined 97%; no coverage policy change.
- Rights gate additionally checks reviewed terms version date, not just approval date.

## Corrected-candidate gates

- uv run ruff format --check .; uv run ruff check .; uv run mypy src/dmf_pulse:
  PASS (788 formatted files, 286 typed source files at initial checkpoint).
- uv sync --all-groups --frozen: PASS, 40 packages.
- uv build --no-build-isolation: PASS, 0.2.0 wheel and sdist; repeated after review fixes.
- uv run python review_pack/r8a/verify_installed_probe.py: PASS twice, including
  rebuilt corrected source. Reuses clean offline external wheel environment;
  synthetic stdin, no live socket, native installed configuration resources.
- uv run python scripts/verify_odd005_wheel.py: local prerequisite failure,
  DMF_TEST_DATABASE_URL missing. Docker daemon unavailable; no DB provisioning.
- uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing
  -m 'not postgres and not performance' -q --tb=short -p no:cacheprovider:
  initial broad run INTERRUPTED after independent review source remediation;
  no full-suite pass claimed. Whole-repository combined floor remains exact-SHA CI.
- Independent reviewer found two material P2 defects on c08020a (invalid totals
  summary and mixed-scale order dependence); both independently reproduced.
- Added two RED regressions: both failed as predicted. Implemented canonical line
  rendering and typed valid/invalid/unsupported/missing totals summary counts.
- uv run pytest tests/unit/ingestion/test_horizon_probe.py -q --tb=short initially
  exposed script-package import dependence; changed test loading to explicit
  file import, not sys.path manipulation or production changes. Then 83 PASS.
- Final affected regression command (322 PASS, 15.93 seconds):
  uv run pytest tests/unit/ingestion/test_horizon_probe.py
  tests/unit/ingestion/test_one_command_odds_transient.py
  tests/unit/ingestion/test_one_command_assembly.py
  tests/unit/ingestion/test_live_odds_001_provider_drift.py
  tests/unit/ingestion/test_live_odds_001_current_boundaries.py
  tests/unit/ingestion/test_odds_transport_parser_boundaries.py
  tests/unit/ingestion/test_odds_model_config_boundaries.py
  tests/unit/ingestion/test_fpl_odds_fixture_identity.py
  tests/unit/ingestion/test_fpl_odds_team_identity.py
  tests/unit/ingestion/test_fpl_direct.py
  tests/unit/ingestion/test_fpl_direct_transport.py -q --tb=short
- Final focused coverage, COVERAGE_FILE=review_pack/r8a/focused-final.coverage:
  uv run python -m coverage run --branch --source=src/dmf_pulse/ingestion/odds,scripts
  -m pytest tests/unit/ingestion/test_horizon_probe.py -q --tb=short
  (83 PASS, 4.89 seconds).
  uv run python -m coverage report --include='*/horizon_probe.py,*/probe_horizon_market_coverage.py'
  --show-missing --fail-under=90: PASS, combined 96%.
  uv run python -m coverage json --include='*/horizon_probe.py,*/probe_horizon_market_coverage.py'
  -o review_pack/r8a/focused-final-coverage.json: PASS.
- Initial coverage selection using the script package alias missed the file-loaded
  script; corrected to directory/file matching above. Only corrected report is final.
- uv run python scripts/generate_repository_manifest.py --ticket PRC-013;
  uv run python scripts/generate_repository_manifest.py --ticket PRIVATE-V1-ONE-COMMAND-001N-R8A:
  canonical generator used; repeat after final metadata updates.
- uv run dmf specs validate: 94 decisions, 22 documents, 19 scopes, PASS.
- uv run python scripts/validate_repository.py: zero errors.
- uv run python scripts/scan_secrets.py: final zero findings. No scanner/allowlist
  change; synthetic fixture uses the inherited short marker variable convention.
- Protected R7 source/config/dependency/CI git diff --exit-code: PASS.

Independent re-review and exact-SHA CI remain pending at this snapshot. No push,
live request, credentials inspection, model execution by the probe, or observation export.
