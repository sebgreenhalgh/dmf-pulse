# DMF Pulse

DMF Pulse is a private FPL decision-engine project. DAT-003 adds the minimum governed PostgreSQL 18.4 canonical temporal foundation to the existing strict rules package: server-generated UUIDv7 identity, bitemporal facts and as-of reads, immutable source observations, a rules activation registry, reversible migrations, deterministic data-model CLI, and first-party evidence.

The milestone contains no live provider access, SQLite substitute, odds/market schema, model, optimiser, scheduler, server/API, UI, manager-account state, or autonomous FPL action. Pure rules scoring remains database-free; only explicit `dmf data-model` commands and PostgreSQL-marked tests connect to the disposable TEST database.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Git
- Docker Desktop/Engine with Compose for PostgreSQL acceptance
- PostgreSQL image `postgres:18.4-bookworm` (digest pinned in `compose.test.yaml`)

The project is proprietary and All Rights Reserved. Approved architecture lives under `specs/approved/`, with hashes enforced by governed manifests.

## Disposable PostgreSQL setup

PowerShell:

```powershell
uv sync --all-groups --frozen
$env:DMF_ENVIRONMENT = 'TEST'
$env:PGPASSWORD = 'changeme'
$env:DMF_TEST_DATABASE_URL = 'postgresql+psycopg://dmf_test@127.0.0.1:55432/dmf_pulse_test'
docker compose -f compose.test.yaml up -d --wait
try {
    uv run alembic upgrade head
    uv run dmf data-model doctor --json
    uv run dmf data-model schema-manifest --json
    uv run dmf data-model demo --fixture fixtures/data_model/DAT-003/demo.json --json
    uv run dmf data-model as-of --fixture fixtures/data_model/DAT-003/as_of_queries.json --json
    uv run pytest -m "postgres or migration" tests/integration/data_model tests/integration/migrations
} finally {
    docker compose -f compose.test.yaml down -v --remove-orphans
}
```

POSIX shell:

```sh
uv sync --all-groups --frozen
export DMF_ENVIRONMENT=TEST
export PGPASSWORD=changeme
export DMF_TEST_DATABASE_URL=postgresql+psycopg://dmf_test@127.0.0.1:55432/dmf_pulse_test
docker compose -f compose.test.yaml up -d --wait
trap 'docker compose -f compose.test.yaml down -v --remove-orphans' EXIT
uv run alembic upgrade head
uv run dmf data-model doctor --json
uv run dmf data-model schema-manifest --json
uv run dmf data-model demo --fixture fixtures/data_model/DAT-003/demo.json --json
uv run dmf data-model as-of --fixture fixtures/data_model/DAT-003/as_of_queries.json --json
uv run pytest -m "postgres or migration" tests/integration/data_model tests/integration/migrations
```

`changeme` is a literal disposable test credential. Committed application configuration stores only a secret reference. Do not substitute a production database or place a credential-bearing URL in source/evidence.

## Quality and acceptance

Canonical quality commands are executable without Make:

```text
uv run ruff format --check .
uv run ruff check .
uv run mypy src/dmf_pulse
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/DAT-003/coverage.json
uv run python scripts/check_coverage_gates.py
uv build
uv run python scripts/verify_wheel.py
uv run python scripts/validate_repository.py
uv run python scripts/scan_secrets.py
```

The literal 23-command gate, guaranteed teardown, final evidence, and exact 20-file archive are orchestrated by:

```text
uv run python scripts/run_acceptance.py --ticket DAT-003
```

Ubuntu CI is the authoritative PostgreSQL gate. The scheduled/manual Windows workflow covers portable package and pure CLI behavior without duplicating Docker database minutes.

## CLI

Foundation/config/rules commands remain public. DAT-003 adds:

```text
dmf data-model doctor [--json]
dmf data-model schema-manifest [--json]
dmf data-model demo --fixture <path> [--json]
dmf data-model as-of --fixture <path> [--json]
dmf review-pack build --ticket DAT-003 --baseline <commit> --output <path>
```

See `docs/data_model/README.md`, `docs/operations/windows_and_linux_setup.md`, and `tickets/DAT-003/ACCEPTANCE.md` before changing schema, dependencies, temporal semantics, or public contracts.
