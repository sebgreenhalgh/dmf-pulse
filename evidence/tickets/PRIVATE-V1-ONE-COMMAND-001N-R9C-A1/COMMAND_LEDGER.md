# R9C-A1 command ledger

- `uv run python -m pytest tests/unit/private_v1/test_a1_allocation_injection.py -q`
  — PASS (8).
- `uv run python -m pytest tests/unit/private_v1/test_a1_shadow_adapter.py -q`
  — PASS (3).
- Combined A1, rolling and R9B synthetic regression — PASS (62).
- `uv run ruff check` / `uv run ruff format --check` / strict mypy — PASS.
- `uv run python scripts/validate_repository.py` and repository manifest tests — PASS.

No network or live execution command appears in this ledger.

## A1.03

- `uv run python -m pytest tests/unit/private_v1/test_a1_03_shadow_comparison.py -q`
  - PASS (2; real four-world canonical rolling comparison shared by the
  module-scoped fixture).
- `uv run python scripts/compare_r9c_a1_three_gw_shadow.py` - PASS; prints
  only synthetic aggregate comparison evidence and writes no result file.
- `uv run ruff check` / `uv run ruff format --check` / strict source mypy /
  `git diff --check` - PASS.
- `uv run python -m pytest tests/unit/private_v1/test_a1_allocation_injection.py`
  `tests/unit/private_v1/test_a1_shadow_adapter.py`
  `tests/unit/private_v1/test_a1_03_shadow_comparison.py -q` - PASS (13 in
  161.56 seconds).

## A1.02-CI-R1

- Reproduced the two failing static guard tests: FAIL as expected on A1.02.
- `pytest tests/unit/ingestion/test_horizon_probe.py`
  `tests/unit/ingestion/test_horizon_rights_approval.py` — PASS (102).
- A1/R9B/rolling focused regression — PASS (66).
