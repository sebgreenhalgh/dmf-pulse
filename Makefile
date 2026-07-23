.PHONY: bootstrap format format-check lint type test coverage-gates rules-validate rules-golden postgres-up postgres-down migrations postgres-test data-model-smoke build wheel validate scan quality

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
	uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/DAT-003/coverage.json
	uv run python scripts/check_coverage_gates.py

coverage-gates:
	uv run python scripts/check_coverage_gates.py

rules-validate:
	uv run dmf rules validate fixtures/rules/RUL-002/synthetic_complete --json

rules-golden:
	uv run pytest tests/golden/rules tests/unit/rules/test_bonus_and_lifecycle.py

postgres-up:
	docker compose -f compose.test.yaml up -d --wait

postgres-down:
	docker compose -f compose.test.yaml down -v --remove-orphans

migrations:
	uv run alembic upgrade head

postgres-test:
	uv run pytest -m "postgres or migration" tests/integration/data_model tests/integration/migrations

data-model-smoke:
	uv run dmf data-model doctor --json
	uv run dmf data-model schema-manifest --json
	uv run dmf data-model demo --fixture fixtures/data_model/DAT-003/demo.json --json
	uv run dmf data-model as-of --fixture fixtures/data_model/DAT-003/as_of_queries.json --json

build:
	uv build

wheel:
	uv run python scripts/verify_wheel.py

validate:
	uv run python scripts/validate_repository.py

scan:
	uv run python scripts/scan_secrets.py

quality: format-check lint type test rules-validate rules-golden build wheel validate scan
