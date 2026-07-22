.PHONY: bootstrap format format-check lint type test coverage-gates rules-validate rules-golden build wheel validate scan quality

bootstrap:
	uv sync --all-groups --frozen

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

type:
	uv run mypy src/dmf_pulse

test:
	uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/RUL-002/coverage.json
	uv run python scripts/check_coverage_gates.py

coverage-gates:
	uv run python scripts/check_coverage_gates.py

rules-validate:
	uv run dmf rules validate fixtures/rules/RUL-002/synthetic_complete --json

rules-golden:
	uv run pytest tests/golden/rules tests/unit/rules/test_bonus_and_lifecycle.py

build:
	uv build

wheel:
	uv run python scripts/verify_wheel.py

validate:
	uv run python scripts/validate_repository.py

scan:
	uv run python scripts/scan_secrets.py

quality: format-check lint type test rules-validate rules-golden build wheel validate scan
