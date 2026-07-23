# DAT-003 Acceptance Contract

The milestone is accepted only when all checkpoints and commands below pass from the required baseline on PostgreSQL 18.4.

## Functional gates

1. All seven RUL-002 P1 findings in `04_RUL-002_INDEPENDENT_REVIEW.md` are closed with direct regression tests.
2. Existing corrected RUL-002 v1.1 golden fixture/Gameweek/tie oracles remain unchanged and pass.
3. PostgreSQL is exactly major 18 and reports `uuidv7()`.
4. Alembic clean upgrade, downgrade to base and re-upgrade pass.
5. Required schemas/tables/constraints/views/functions exactly match `08_DATABASE_SCHEMA_CONTRACT.md`.
6. UUIDs created by persistence are version 7; business time is explicit and independent.
7. Adjacent closed-open valid intervals are allowed; current overlapping intervals fail at the database under concurrent writers.
8. As-of queries honor both `valid_at` and `known_at` at exact boundaries.
9. Corrections preserve prior values and close only approved system/supersession metadata.
10. Raw blobs/source snapshots cannot be updated or deleted.
11. Identical raw content may be deduplicated while repeated retrieval/source snapshots remain distinct.
12. CLI JSON output is deterministic, versioned, secret-redacted and demonstrated from an installed wheel outside the repository.
13. No SQLite dependency, file or test marker exists.

## Test/quality gates

- zero test skips in required suites;
- overall branch coverage >= 90%;
- rules package branch coverage >= 98%;
- new `data_model`/`database` production packages branch coverage >= 92%;
- critical temporal/constraint/immutability paths >= 95% branch coverage or explicit mutation/oracle evidence;
- mypy strict production package passes;
- Ruff format/lint pass;
- secret scan passes;
- frozen clean-wheel verification passes.

## Exact acceptance sequence

The repository acceptance runner must record exact command, exit code and duration. A safe equivalent command may be used only when Windows shell syntax requires it and the evidence records the equivalence.

1. `uv sync --all-groups --frozen`
2. `uv run ruff format --check .`
3. `uv run ruff check .`
4. `uv run mypy src/dmf_pulse`
5. `docker version`
6. `docker compose version`
7. `docker compose -f compose.test.yaml up -d --wait`
8. `uv run alembic upgrade head`
9. `uv run pytest -m "postgres or migration" tests/integration/data_model tests/integration/migrations`
10. `uv run alembic downgrade base`
11. `uv run alembic upgrade head`
12. `uv run alembic upgrade head --sql > evidence/tickets/DAT-003/offline_upgrade.sql`
13. `uv run dmf data-model doctor --json`
14. `uv run dmf data-model schema-manifest --json`
15. `uv run dmf data-model demo --fixture fixtures/data_model/DAT-003/demo.json --json`
16. `uv run dmf data-model as-of --fixture fixtures/data_model/DAT-003/as_of_queries.json --json`
17. `uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/DAT-003/coverage.json`
18. `uv build`
19. `uv run python scripts/verify_wheel.py`
20. `uv run python scripts/validate_repository.py`
21. `uv run python scripts/scan_secrets.py`
22. `uv run dmf review-pack build --ticket DAT-003 --baseline f9b51e965aad1bc94796c17c897f0d99b4c16e1b --output review_pack/DAT-003`
23. `docker compose -f compose.test.yaml down -v --remove-orphans`

The teardown command must run in a `finally`/trap even if an earlier acceptance command fails.

## Expected negative gates

These are passes only when they fail with the declared typed error:

- target incomplete rules activation remains blocked;
- unquoted YAML integer mapping key is rejected;
- current temporal overlap is rejected by PostgreSQL;
- typed entity table using the wrong canonical entity type is rejected;
- source snapshot update/delete is rejected;
- contradictory red-card/dismissal scenario is rejected;
- same ruleset ID/version with different activation evidence is rejected.
