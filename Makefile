.PHONY: bootstrap format format-check lint type test coverage-gates rules-validate rules-golden postgres-up postgres-down migrations migration-matrix postgres-test data-model-smoke fpl-validate fpl-replay odds-replay odds-query build wheel validate scan quality

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
	uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/ODD-005/coverage.json
	uv run python scripts/check_odd005_coverage_gates.py evidence/tickets/ODD-005/coverage.json

coverage-gates:
	uv run python scripts/check_odd005_coverage_gates.py evidence/tickets/ODD-005/coverage.json

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

migration-matrix:
	uv run python scripts/test_migration_matrix.py --baseline-revision 20260724_0002 --target head

postgres-test:
	uv run pytest -q -m "postgres and integration" tests/integration

data-model-smoke:
	uv run dmf data-model doctor --json
	uv run dmf data-model schema-manifest --json
	uv run dmf data-model demo --fixture fixtures/data_model/DAT-003/demo.json --json
	uv run dmf data-model as-of --fixture fixtures/data_model/DAT-003/as_of_queries.json --json

fpl-validate:
	uv run dmf ingest fpl validate --resource bootstrap --input fixtures/fpl/FPL-004/happy_path/bootstrap.json --contract-version fpl-reference-v1 --output json

fpl-replay:
	uv run dmf ingest fpl replay --fixture-set fixtures/fpl/FPL-004 --scenario happy_path --information-cutoff 2026-08-21T17:30:00Z --rights-profile synthetic_test_v1 --output json

odds-replay:
	uv run dmf ingest odds replay --fixture-set fixtures/odds/ODD-005 --scenario happy_path --information-cutoff 2026-08-21T17:30:00Z --rights-profile synthetic_the_odds_api_v1 --output json

odds-query:
	uv run dmf market observations --fixture-external-provider official_fpl --fixture-external-id 101 --season-code 2026/27 --as-of 2026-08-20T12:05:00Z --output json

build:
	uv build

wheel:
	uv run python scripts/verify_odd005_wheel.py

validate:
	uv run python scripts/validate_repository.py

scan:
	uv run python scripts/scan_secrets.py

quality: format-check lint type test rules-validate rules-golden build wheel validate scan
