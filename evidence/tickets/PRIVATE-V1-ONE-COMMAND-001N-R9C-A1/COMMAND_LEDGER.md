# R9C-A1 command ledger

- `uv run python -m pytest tests/unit/private_v1/test_a1_allocation_injection.py -q`
  — PASS (8).
- `uv run python -m pytest tests/unit/private_v1/test_a1_shadow_adapter.py -q`
  — PASS (3).
- Combined A1, rolling and R9B synthetic regression — PASS (62).
- `uv run ruff check` / `uv run ruff format --check` / strict mypy — PASS.
- `uv run python scripts/validate_repository.py` and repository manifest tests — PASS.

No network or live execution command appears in this ledger.

## A1.02-CI-R1

- Reproduced the two failing static guard tests: FAIL as expected on A1.02.
- `pytest tests/unit/ingestion/test_horizon_probe.py`
  `tests/unit/ingestion/test_horizon_rights_approval.py` — PASS (102).
- A1/R9B/rolling focused regression — PASS (66).
