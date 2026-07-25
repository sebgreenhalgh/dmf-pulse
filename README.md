# DMF Pulse

DMF Pulse is a private FPL decision-engine project. FPL-004 builds on the governed PostgreSQL 18.4 temporal foundation with rights-gated ingestion of official-FPL-shaped bootstrap and fixture data. The accepted full pipeline uses synthetic fixtures to create immutable retrieval envelopes, append-only lifecycle history, season-scoped canonical mappings, typed observations, quality reports, and cutoff-safe source bundles.

The default official FPL profile permits bounded transient manual validation only and blocks live snapshot transport as well as persistent raw/derived storage. No live provider request, real provider payload, authenticated manager access, recurring polling, SQLite substitute, odds/market ingestion, model, optimiser, scheduler, server/API, UI, or autonomous FPL action belongs in this milestone. Pure rules scoring and payload validation remain database-free; explicit persistence commands and PostgreSQL-marked tests use only the disposable TEST database.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Git
- Docker Desktop/Engine with Compose for PostgreSQL acceptance
- PostgreSQL image `postgres:18.4-bookworm` (digest pinned in `compose.test.yaml`)

The project is proprietary and All Rights Reserved. Approved architecture lives under `specs/approved/`, with hashes enforced by governed manifests.

## Rights-safe FPL workflow

The deterministic end-to-end example uses only approved synthetic fixtures:

```text
dmf ingest fpl replay --fixture-set fixtures/fpl/FPL-004 --scenario happy_path --information-cutoff 2026-08-21T17:30:00Z --rights-profile synthetic_test_v1 --output json
```

Database-free contract validation is available independently:

```text
dmf ingest fpl validate --resource bootstrap --input fixtures/fpl/FPL-004/happy_path/bootstrap.json --contract-version fpl-reference-v1 --output json
```

The official-profile snapshot command is a controlled negative operation: it must return `RIGHTS_BLOCKED` with exit code 4 before any transport call. Do not use it as a live smoke test. See `docs/ingestion/README.md` for the command surface, lifecycle, resume, retention, and cutoff boundaries.

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
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-fail-under=90
uv build
uv run python scripts/verify_fpl004_wheel.py
uv run python scripts/validate_repository.py
uv run python scripts/scan_secrets.py
```

The literal 25-command gate, including the expected rights-blocked exit, PostgreSQL teardown, final evidence, and exact 20-file archive is frozen in `tickets/FPL-004/ACCEPTANCE.md`. Its ticket-specific verifier is:

```text
uv run python scripts/verify_fpl004_acceptance.py
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

FPL-004 adds:

```text
dmf ingest fpl validate --resource <bootstrap|fixtures> --input <path> --contract-version fpl-reference-v1 --output json
dmf ingest fpl import --bootstrap <path> --fixtures <path> --competition-key <key> --season-code <code> --captured-at <utc> --information-cutoff <utc> --rights-profile <profile> --database-url-ref <reference> --output json
dmf ingest fpl replay --fixture-set <directory> --scenario <scenario> --database-url-ref <reference> --output json
dmf ingest fpl resume --snapshot-id <uuid> --database-url-ref <reference> --output json
dmf ingest fpl bundle show --bundle-id <uuid> --database-url-ref <reference> --output json
dmf ingest fpl snapshot --resource <bootstrap|fixtures|all> --competition-key <key> --season-code <code> --rights-profile <profile> --database-url-ref <reference> --output json
dmf review-pack build --ticket FPL-004 --baseline 9b3160a2574d2868b5f26e3a2d429924567510b0 --output review_pack/FPL-004
```

See `docs/ingestion/README.md`, `docs/data_model/README.md`, `docs/operations/windows_and_linux_setup.md`, and `tickets/FPL-004/ACCEPTANCE.md` before changing rights, schemas, dependencies, temporal/lifecycle semantics, or public contracts.
