# Windows and Linux setup

Install Python 3.13 with uv, run `uv sync --all-groups --frozen`, and use the copy-paste PowerShell/POSIX database setup in the root README. The canonical PostgreSQL test endpoint is localhost port 55432, the literal fake password is `changeme`, and `DMF_TEST_DATABASE_URL` should omit credentials while `PGPASSWORD` supplies the fake password to libpq.

Docker Compose is required only for DAT-003 database integration and acceptance. The image is digest-pinned PostgreSQL 18.4; the named test volume must be removed with `docker compose -f compose.test.yaml down -v --remove-orphans` in `finally`/`trap`. Never point tests at a production host or mount production data.

Use uv/Python commands directly; Make targets only delegate. The package retains its hash-pinned `Europe/London` timezone fallback. Provider/network access is never required at runtime or in tests.

Windows CI intentionally remains a scheduled/manual pure portability and installed-wheel smoke. Ubuntu/local Docker is the authoritative PostgreSQL gate.
