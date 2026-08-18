# Static analysis and frozen sync

- `uv sync --all-groups --frozen`: PASS, 40 packages checked; lock unchanged.
- Ruff format check over Stage-13 production, modified CLI, tests, pack script and repository
  validator: PASS, 40 files already formatted.
- Ruff lint over the same scope: PASS.
- Strict mypy over `src/dmf_pulse/prices`, `cli/prices.py` and modified `cli/app.py`: PASS,
  23 source files with no issues.
- `git diff --check`: PASS.
