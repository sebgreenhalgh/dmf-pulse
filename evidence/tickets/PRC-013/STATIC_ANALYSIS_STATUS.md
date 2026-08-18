# Static analysis and frozen sync

- `uv sync --all-groups --frozen`: PASS, 40 packages checked; lock unchanged.
- `uv run ruff format --check .`: PASS, 533 files already formatted.
- `uv run ruff check .`: PASS.
- `uv run mypy src/dmf_pulse`: PASS, 208 source files with no issues.
- Final `git diff --check`: PASS.
