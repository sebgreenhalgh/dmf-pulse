# FND-001 acceptance

Status: **COMPLETE**. Mandatory commands passed: **14/14**. Tests: **104 passed**; branch coverage: **90.57%**.

| # | Exact command | Exit | Duration (s) | Status |
|---:|---|---:|---:|---|
| 1 | `uv sync --all-groups --frozen` | 0 | 0.043 | PASS |
| 2 | `uv run ruff format --check .` | 0 | 0.083 | PASS |
| 3 | `uv run ruff check .` | 0 | 0.087 | PASS |
| 4 | `uv run mypy src/dmf_pulse` | 0 | 0.413 | PASS |
| 5 | `uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing` | 0 | 21.629 | PASS |
| 6 | `uv run dmf --version` | 0 | 0.534 | PASS |
| 7 | `uv run dmf doctor --json` | 0 | 3.563 | PASS |
| 8 | `uv run dmf config validate --environment test --config-root config` | 0 | 0.455 | PASS |
| 9 | `uv run dmf config show --environment test --config-root config --json` | 0 | 0.448 | PASS |
| 10 | `uv build` | 0 | 2.597 | PASS |
| 11 | `uv run python scripts/verify_wheel.py` | 0 | 9.486 | PASS |
| 12 | `uv run python scripts/validate_repository.py` | 0 | 0.2 | PASS |
| 13 | `uv run python scripts/scan_secrets.py` | 0 | 1.654 | PASS |
| 14 | `uv run dmf review-pack build --ticket FND-001 --output review_pack/FND-001` | 0 | 3.114 | PASS |

The clean-wheel verifier independently built both distributions, installed the wheel in a temporary environment outside the repository, ran the installed version and doctor commands, proved module provenance, validated the bundled Windows timezone fallback, and removed the environment. No mandatory result was inferred from another command.
