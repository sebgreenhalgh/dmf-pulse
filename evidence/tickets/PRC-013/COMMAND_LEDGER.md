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

## Final main integration

17. Cleared stale `GH_TOKEN`/`GITHUB_TOKEN` process overrides, then ran
    `gh auth status -h github.com` and `gh api user --jq .login`.
    - PASS; host-keyring identity `sebgreenhalgh` authenticated.
18. `git fetch --all --prune`, exact remote SHA checks and local backup-ref creation.
    - PASS; remote Stage-13 HEAD `b0e3b0724b92ec2d483191f0329c0c38ae8a9e08`, remote
      `main` `9eb57143f6ee92f67c78607cc386678d962e62d4`, and
      `backup/stage13-pre-main-integration` preserved at the reviewed HEAD.
19. `git merge --no-ff --no-commit origin/main`.
    - One conflict: `PLANS.md`; resolved semantically by retaining both complete histories. All
      other current-main rules, engine, evidence and allowlist changes merged cleanly.
20. Integration smoke over the new price/rules contract and directly changed configuration and
    observation tests.
    - PASS; 28 tests in 1.49 seconds.
21. Complete Stage-13 unit/property/contract/golden/integration/replay/performance suite with
    branch coverage over `dmf_pulse.prices` and `dmf_pulse.cli.prices` and
    `--cov-fail-under=90`.
    - PASS; 116 tests in 14.92 seconds, 90.56% branch-aware coverage.
22. Exact preserved 17-node inherited command recorded in `TARGETED_REGRESSION_SCOPE.txt`.
    - PASS; 17 tests in 1.12 seconds.
23. Current-main dependency command over the six exact rule/schema/lifecycle/Stage-11 selectors
    recorded in `TARGETED_REGRESSION_SCOPE.txt`.
    - PASS; 104 tests in 5.50 seconds.
24. Post-integration complete repository command:
    `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
    --basetemp=review_pack/prc013-main-integration-full-repository`.
    - RESOURCE_LIMIT; one run reached the 1204-second command ceiling without a final pytest
      summary or emitted failure trace. It was not rerun unchanged and is not PASS.
25. `uv sync --all-groups --frozen`, Ruff format/lint and strict mypy.
    - PASS; 40 packages checked, 539 files formatted, lint clean and 209 source files typed.
26. `uv run python -m build` plus ZIP/member/hash checks.
    - PASS; wheel and sdist hashes are recorded in `BUILD_WHEEL_RESULT.md`.
27. New external Python 3.13 environment, integrated wheel install and installed Typer entrypoint
    for version, current-rules show, price validation, path simulation and ACT/WAIT.
    - PASS; 23 packages installed outside the repository with `PYTHONPATH` removed. Exact results
      are recorded in `CLI_ACCEPTANCE.md`.
28. `uv run python scripts/generate_repository_manifest.py --ticket PRC-013`.
    - PASS; 1021 deliverable files recorded from the integrated tree.
29. `uv run python scripts/validate_repository.py` and
    `uv run python scripts/scan_secrets.py`.
    - PASS; zero repository errors and zero unallowlisted secret findings.
30. `git diff --check` and unmerged-path inspection.
    - PASS; no whitespace errors and no unresolved merge entries.
31. Explicit merge commit and normal push to
    `stage/A13/PRC-013-price-prediction`.
    - PASS; integration commit `6dc58db48415d831b37a10b423a9a555aa9fe833` has parents
      `b0e3b0724b92ec2d483191f0329c0c38ae8a9e08` and
      `9eb57143f6ee92f67c78607cc386678d962e62d4`; no force push was used, and
      local/remote HEAD equality was verified after fetch.
32. Draft PR #12 body update and live GitHub state check after clearing stale token overrides.
    - PASS; PR #12 targets `main`, remains open, draft and unmerged, and reports `MERGEABLE` with
      merge-state status `UNSTABLE`. This is not a code-conflict state and is not treated as human
      acceptance or a completed required-check gate.
