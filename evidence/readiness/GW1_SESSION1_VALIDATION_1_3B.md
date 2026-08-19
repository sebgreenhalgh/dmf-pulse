# GW1 Checkpoint 1.3B Remediation Validation

- Workflow run — `32246327083`
- Reproduced failing workflow — `32194395276`
- Exact startup remote SHA — `196224c729e1df25a30f3a0d5ac55bac74f7fcc2`
- Remediation commit — `e0e1459f203bd4f7e00c7173e18446b5e454cff7`
- Branch — `readiness/GW1-2026-27-live-input-initial-squad`
- Overall — `FAIL`
- Real credentialled provider call — `OPERATOR_CHECKPOINT`

## Root causes and remediation

- CLI: retained the accepted `schema_version` / `status` / `error` envelope and corrected the stale test.
- PostgreSQL: restored `MAPPED` and `PROMOTED` in the accepted lifecycle before `QUALITY_PASSED`, while recording provider-native identity, zero canonical rows, no fuzzy matching and no raw retention.
- Ruff: fixed import ordering and imported `Callable` from `collections.abc`; no suppressions were added.

## Results

- `focused_pytest` — `PASS` (exit `0`)
- `inherited_odds_pytest` — `PASS` (exit `0`)
- `affected_cli_pytest` — `PASS` (exit `0`)
- `postgres_integration` — `FAIL` (exit `1`)
- `ruff_format` — `PASS` (exit `0`)
- `ruff_lint` — `PASS` (exit `0`)
- `strict_mypy` — `PASS` (exit `0`)
- `wheel_build` — `PASS` (exit `0`)
- `secret_scan` — `PASS` (exit `0`)
- `diff_check` — `PASS` (exit `0`)

## focused_pytest output

```text
................................................................         [100%]
64 passed in 3.09s
```

## inherited_odds_pytest output

```text
........................................................................ [ 69%]
...............................                                          [100%]
103 passed in 2.28s
```

## affected_cli_pytest output

```text
.............................                                            [100%]
29 passed in 2.25s
```

## postgres_integration output

```text
            else:
                effective_parameters = cast(
                    "_CoreSingleExecuteParams", effective_parameters
                )
                if self.dialect._has_events:
                    for fn in self.dialect.dispatch.do_execute:
                        if fn(
                            cursor,
                            str_statement,
                            effective_parameters,
                            context,
                        ):
                            evt_handled = True
                            break
                if not evt_handled:
>                   self.dialect.do_execute(
                        cursor, str_statement, effective_parameters, context
                    )

.venv/lib/python3.13/site-packages/sqlalchemy/engine/base.py:1969: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.venv/lib/python3.13/site-packages/sqlalchemy/engine/default.py:952: in do_execute
    cursor.execute(statement, parameters)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <psycopg.Cursor [closed] [BAD] at 0x7ff7870ca5d0>
query = 'UPDATE provenance.source_snapshot SET parsed_at=%(parsed_at)s::TIMESTAMP WITH TIME ZONE, usable_at=%(usable_at)s::TIM...us=%(validation_status)s::VARCHAR WHERE provenance.source_snapshot.source_snapshot_id = %(source_snapshot_id_1)s::UUID'
params = {'parsed_at': datetime.datetime(2026, 8, 20, 12, 0, 1, tzinfo=datetime.timezone.utc), 'usable_at': datetime.datetime(2...a_fingerprint': '6f56ce48f1dba69bd322cbc57ab3c5055a27310b1b86332de314751ed018c56b', 'validation_status': 'USABLE', ...}
prepare = None, binary = None

    def execute(
        self,
        query: Query,
        params: Params | None = None,
        *,
        prepare: bool | None = None,
        binary: bool | None = None,
    ) -> Self:
        """
        Execute a query or command to the database.
        """
        try:
            with self._conn.lock:
                self._conn.wait(
                    self._execute_gen(query, params, prepare=prepare, binary=binary)
                )
        except e._NO_TRACEBACK as ex:
>           raise ex.with_traceback(None)
E           psycopg.errors.ObjectNotInPrerequisiteState: IMMUTABLE_RECORD
E           CONTEXT:  PL/pgSQL function provenance.reject_immutable_change() line 3 at RAISE

.venv/lib/python3.13/site-packages/psycopg/cursor.py:117: ObjectNotInPrerequisiteState

The above exception was the direct cause of the following exception:

repository_root = PosixPath('/home/runner/work/dmf-pulse/dmf-pulse')
postgres_session_factory = sessionmaker(class_='Session', bind=Engine(postgresql+psycopg://dmf_test@127.0.0.1:5432/dmf_pulse_test), autoflush=False, expire_on_commit=False)

    def test_live_provider_native_input_persists_governed_evidence_without_mapping(
        repository_root: Path,
        postgres_session_factory: sessionmaker[Session],
    ) -> None:
        body = (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes()
        transport = _Transport(
            OddsHttpResponse(
                status_code=200,
                content_type="application/json",
                headers={
                    "x-requests-remaining": "499",
                    "x-requests-used": "1",
                    "x-requests-last": "1",
                    "x-request-id": "provider-request-913",
                },
                body=body,
            )
        )
        service = LiveOddsSnapshotService(
            credential_provider=StaticCredentialProvider(DUMMY_RUNTIME_VALUE),
            transport_factory=lambda: transport,
            clock=lambda: RECEIVED,
            processing_clock=lambda: RECEIVED + timedelta(seconds=1),
            sleeper=lambda _seconds: None,
            monotonic=lambda: 0.0,
        )
    
>       outcome = service.snapshot(
            provider="the_odds_api",
            competition_key="PL",
            sport_key="soccer_epl",
            region="uk",
            market="h2h",
            as_of=CUTOFF,
            database_url_ref=DATABASE_REF,
        )

tests/integration/ingestion/odds/test_live_provider_current_input.py:80: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/dmf_pulse/ingestion/odds/live.py:797: in snapshot
    evidence_store.record_usable(
src/dmf_pulse/ingestion/odds/live.py:427: in record_usable
    session.execute(
.venv/lib/python3.13/site-packages/sqlalchemy/orm/session.py:2373: in execute
    return self._execute_internal(
.venv/lib/python3.13/site-packages/sqlalchemy/orm/session.py:2280: in _execute_internal
    result = conn.execute(
.venv/lib/python3.13/site-packages/sqlalchemy/engine/base.py:1421: in execute
    return meth(
.venv/lib/python3.13/site-packages/sqlalchemy/sql/elements.py:526: in _execute_on_connection
    return connection._execute_clauseelement(
.venv/lib/python3.13/site-packages/sqlalchemy/engine/base.py:1643: in _execute_clauseelement
    ret = self._execute_context(
.venv/lib/python3.13/site-packages/sqlalchemy/engine/base.py:1848: in _execute_context
    return self._exec_single_context(
.venv/lib/python3.13/site-packages/sqlalchemy/engine/base.py:1988: in _exec_single_context
    self._handle_dbapi_exception(
.venv/lib/python3.13/site-packages/sqlalchemy/engine/base.py:2365: in _handle_dbapi_exception
    raise sqlalchemy_exception.with_traceback(exc_info[2]) from e
.venv/lib/python3.13/site-packages/sqlalchemy/engine/base.py:1969: in _exec_single_context
    self.dialect.do_execute(
.venv/lib/python3.13/site-packages/sqlalchemy/engine/default.py:952: in do_execute
    cursor.execute(statement, parameters)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <psycopg.Cursor [closed] [BAD] at 0x7ff7870ca5d0>
query = 'UPDATE provenance.source_snapshot SET parsed_at=%(parsed_at)s::TIMESTAMP WITH TIME ZONE, usable_at=%(usable_at)s::TIM...us=%(validation_status)s::VARCHAR WHERE provenance.source_snapshot.source_snapshot_id = %(source_snapshot_id_1)s::UUID'
params = {'parsed_at': datetime.datetime(2026, 8, 20, 12, 0, 1, tzinfo=datetime.timezone.utc), 'usable_at': datetime.datetime(2...a_fingerprint': '6f56ce48f1dba69bd322cbc57ab3c5055a27310b1b86332de314751ed018c56b', 'validation_status': 'USABLE', ...}
prepare = None, binary = None

    def execute(
        self,
        query: Query,
        params: Params | None = None,
        *,
        prepare: bool | None = None,
        binary: bool | None = None,
    ) -> Self:
        """
        Execute a query or command to the database.
        """
        try:
            with self._conn.lock:
                self._conn.wait(
                    self._execute_gen(query, params, prepare=prepare, binary=binary)
                )
        except e._NO_TRACEBACK as ex:
>           raise ex.with_traceback(None)
E           sqlalchemy.exc.OperationalError: (psycopg.errors.ObjectNotInPrerequisiteState) IMMUTABLE_RECORD
E           CONTEXT:  PL/pgSQL function provenance.reject_immutable_change() line 3 at RAISE
E           [SQL: UPDATE provenance.source_snapshot SET parsed_at=%(parsed_at)s::TIMESTAMP WITH TIME ZONE, usable_at=%(usable_at)s::TIMESTAMP WITH TIME ZONE, schema_fingerprint=%(schema_fingerprint)s::VARCHAR, validation_status=%(validation_status)s::VARCHAR WHERE provenance.source_snapshot.source_snapshot_id = %(source_snapshot_id_1)s::UUID]
E           [SQL parameters hidden due to hide_parameters=True]
E           (Background on this error at: https://sqlalche.me/e/20/e3q8)

.venv/lib/python3.13/site-packages/psycopg/cursor.py:117: OperationalError
=========================== short test summary info ============================
FAILED tests/integration/ingestion/odds/test_live_provider_current_input.py::test_live_provider_native_input_persists_governed_evidence_without_mapping - sqlalchemy.exc.OperationalError: (psycopg.errors.ObjectNotInPrerequisiteState) IMMUTABLE_RECORD
CONTEXT:  PL/pgSQL function provenance.reject_immutable_change() line 3 at RAISE
[SQL: UPDATE provenance.source_snapshot SET parsed_at=%(parsed_at)s::TIMESTAMP WITH TIME ZONE, usable_at=%(usable_at)s::TIMESTAMP WITH TIME ZONE, schema_fingerprint=%(schema_fingerprint)s::VARCHAR, validation_status=%(validation_status)s::VARCHAR WHERE provenance.source_snapshot.source_snapshot_id = %(source_snapshot_id_1)s::UUID]
[SQL parameters hidden due to hide_parameters=True]
(Background on this error at: https://sqlalche.me/e/20/e3q8)
1 failed in 0.65s
```

## ruff_format output

```text
7 files already formatted
```

## ruff_lint output

```text
All checks passed!
```

## strict_mypy output

```text
Success: no issues found in 3 source files
```

## wheel_build output

```text
Building source distribution...
Building wheel from source distribution...
Successfully built dist/dmf_pulse-0.2.0.tar.gz
Successfully built dist/dmf_pulse-0.2.0-py3-none-any.whl
```

## secret_scan output

```text
{
  "finding_count": 0,
  "findings": [],
  "status": "PASS"
}
```

## diff_check output

```text
```

## Rights and storage

- Runtime credential provider wiring remains unchanged; no API-key CLI option exists.
- HTTPS, approved-host, redirect, timeout, retry, response-size/content-type and explicit provider-status controls remain covered by the focused suite.
- Raw provider payload retention remains forbidden; no raw blob/object or canonical market/odds rows are created by the provider-native path.
- Public display, redistribution, backup and model training remain denied by the current Rights Profile.
- Canonical FPL fixture mapping and fuzzy team matching remain unperformed.

## Scope

- Checkpoint 1.3C — `NOT_STARTED`.
- Checkpoint 1.4 — `INCOMPLETE` / not started.
- Exact next action — **CHECKPOINT 1.3C — CHECKPOINT ACCEPTANCE / OPERATOR CONTRACT**.
