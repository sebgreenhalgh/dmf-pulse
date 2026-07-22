.PHONY: bootstrap format format-check lint type test build wheel validate scan quality

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
	uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing

build:
	uv build

wheel:
	uv run python scripts/verify_wheel.py

validate:
	uv run python scripts/validate_repository.py

scan:
	uv run python scripts/scan_secrets.py

quality: format-check lint type test build wheel validate scan
