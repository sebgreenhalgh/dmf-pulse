# PRC-013 independent-review command ledger

Commands ran from the repository root on Windows PowerShell with Python 3.13.9. Pytest used a
workspace-contained base temp because the sandbox cannot enumerate the default pytest temp.

1. Corrected lineage gate: `git fetch --all --prune`, remote/head/parent/tree/diff checks.
   - PASS; remote baseline `a2fdeea7b6514cb8f37b2f687d892998a1422973`, direct parent
     `ce7fe8f4354d95a477afcf6eed45f63cf0ab772e`; price package present; recovery material absent.
2. Focused red review regressions before remediation.
   - Expected red state observed: 11 independent-review failures exposed the initial defects.
3. Final Stage-13 coverage command over unit/property/contract/golden/integration/replay/performance
   price scopes with `--cov-branch --cov-fail-under=90`.
   - PASS; 112 tests, 90.57% branch-aware coverage.
4. Targeted inherited command listing the 17 nodes in `TARGETED_REGRESSION_SCOPE.txt`.
   - PASS; 17 tests in 1.29 seconds.
5. Complete repository command:
   `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
   --basetemp=review_pack/prc013-sol-full-repository`.
   - RESOURCE_LIMIT; the single complete run reached the 20-minute execution ceiling without a
     final summary or emitted failure trace. It was not rerun unchanged.
6. `uv sync --all-groups --frozen`.
   - PASS; 40 packages checked; no lock mutation.
7. `uv run ruff format --check .` and `uv run ruff check .`.
   - PASS; 533 files formatted, lint clean.
8. `uv run mypy src/dmf_pulse`.
   - PASS; no issues in 208 source files.
9. `uv run python -m build`.
   - PASS; canonical Hatchling sdist and wheel built.
10. Clean external venv: `uv venv --python 3.13 <external-dir>` then
    `uv pip install --python <external-python> dist/dmf_pulse-0.2.0-py3-none-any.whl`.
    - PASS; installed 23 packages including `dmf-pulse==0.2.0`; import resolved to external
      `site-packages` with repository `PYTHONPATH` removed.
11. Installed application version/help/validation/simulation through the wheel's Typer entry point.
    - PASS WITH ENVIRONMENT LIMITATION; `dmf 0.2.0`, ten price commands present, fail-closed
      validation, 2187 paths. Windows Application Control blocked the generated temp `dmf.exe`, so
      the same entry point ran through the external environment's Python process.
12. `uv run python scripts/generate_repository_manifest.py --ticket PRC-013`.
    - PASS; 997 deliverable files recorded.
13. `uv run python scripts/validate_repository.py`.
    - PASS; zero errors.
14. `uv run python scripts/scan_secrets.py`.
    - PASS; zero unallowlisted findings.
15. `git diff --check`, worktree inventory, recovery/archive absence, package-resource equivalence
    and complete base-to-head scope review.
    - PASS; only intended Stage-13 remediation/evidence files were committed, packaged and root
      price configurations are byte-identical, and no recovery/archive material is present.
16. Commit/push/remote-equality check and GitHub draft-PR creation.
    - PASS; remediation commit `1ebbbde0e80829c8c3c23a676c814a2f80487371` was pushed normally,
      local and remote HEAD matched, and draft PR #12 was opened against `main`. The PR remains
      unmerged and human acceptance remains false.
