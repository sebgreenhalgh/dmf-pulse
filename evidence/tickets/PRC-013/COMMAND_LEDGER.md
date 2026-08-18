# PRC-013 command ledger

All commands ran from the repository root on Windows PowerShell with Python 3.13.9. Pytest used a
workspace-contained base temp because the sandbox cannot enumerate the user's default pytest temp.

1. `uv sync --all-groups --frozen`
   - PASS; 40 packages checked; no lock mutation.
2. `uv run ruff format --check <Stage-13 production, CLI, tests, pack script>`
   - PASS; 40 files already formatted after the pack script was formatted once.
3. `uv run ruff check <same scope>`
   - PASS.
4. `uv run mypy src/dmf_pulse/prices src/dmf_pulse/cli/prices.py src/dmf_pulse/cli/app.py`
   - PASS; no issues in 23 source files.
5. `uv run pytest -q -p no:cacheprovider --basetemp=review_pack/prc013-final-coverage-20260818 tests/unit/prices tests/property/prices tests/contract/prices tests/golden/prices tests/integration/prices tests/replay/prices tests/performance/prices --cov=dmf_pulse.prices --cov=dmf_pulse.cli.prices --cov-branch --cov-report=term --cov-report=json:evidence/tickets/PRC-013/coverage.json --cov-fail-under=90`
   - PASS; 88 passed; 91.44% branch-aware coverage.
6. Targeted inherited pytest command listing the 17 nodes recorded in
   `TARGETED_REGRESSION_SCOPE.txt`.
   - PASS; 17 passed in 0.88s.
7. `uv run python -m build`
   - PASS; canonical sdist and wheel built once.
8. Clean external venv: `uv venv --python 3.13 <external-dir>` then
   `uv pip install --python <external-python> dist/dmf_pulse-0.2.0-py3-none-any.whl`.
   - PASS; installed 23 packages including `dmf-pulse==0.2.0` from the local wheel.
9. External installed commands `dmf --version`, `dmf prices validate`, and
   `dmf prices simulate-path --input <absolute synthetic fixture>`.
   - PASS; version 0.2.0, fail-closed validation, 2187 paths.
10. Read-only first-party repository validation against the refreshed PRC-013 manifest.
    - PASS; zero errors.
11. `.venv/Scripts/python.exe scripts/scan_secrets.py`.
    - PASS; zero unallowlisted findings.

Full repository pytest was not run by design and is deferred to independent Sol review.
