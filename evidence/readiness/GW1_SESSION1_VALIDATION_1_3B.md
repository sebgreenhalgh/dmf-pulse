# GW1 Checkpoint 1.3B Focused Validation

- Workflow run — `32194395276`
- Staging commit — `e2b6446faf8f502cbdc969650e2357b44da4c0d4`
- Branch — `readiness/GW1-2026-27-live-input-initial-squad`
- Overall — `FAIL`
- Real credentialled provider call — `OPERATOR_CHECKPOINT`

## Exit codes

- `archive_integrity` — `PASS` (exit `0`)
- `archive_extract` — `PASS` (exit `0`)
- `install_uv` — `PASS` (exit `0`)
- `frozen_sync` — `PASS` (exit `0`)
- `ruff_format_apply` — `PASS` (exit `0`)
- `focused_pytest` — `FAIL` (exit `1`)
- `inherited_odds_pytest` — `PASS` (exit `0`)
- `postgres_integration` — `FAIL` (exit `1`)
- `ruff_format` — `PASS` (exit `0`)
- `ruff_lint` — `FAIL` (exit `1`)
- `strict_mypy` — `PASS` (exit `0`)
- `wheel_build` — `PASS` (exit `0`)
- `secret_scan` — `PASS` (exit `0`)
- `diff_check` — `PASS` (exit `0`)

## focused_pytest output

```text
...............................................................F         [100%]
=================================== FAILURES ===================================
__________________ test_snapshot_usage_failure_is_secret_free __________________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fd202e97e00>

    def test_snapshot_usage_failure_is_secret_free(monkeypatch: pytest.MonkeyPatch) -> None:
        def invalid(*_args: object, **_kwargs: object) -> object:
            from dmf_pulse.ingestion.errors import IngestionError
    
            raise IngestionError("USAGE_INVALID", "odds snapshot options are not allowlisted")
    
        monkeypatch.setattr(odds_cmd.OddsIngestionService, "snapshot", invalid)
        args = _args()
        args[args.index("soccer_epl")] = "not-epl"
        result = runner.invoke(app, args, env=_runtime_env())
    
        assert result.exit_code == 3
        assert DUMMY_RUNTIME_VALUE not in result.stdout
>       assert json.loads(result.stdout) == {
            "error": {
                "code": "USAGE_INVALID",
                "message": "odds snapshot options are not allowlisted",
                "retryable": False,
            }
        }
E       AssertionError: assert {'error': {'c...us': 'FAILED'} == {'error': {'c...able': False}}
E         
E         Omitting 1 identical items, use -vv to show
E         Left contains 2 more items:
E         {'schema_version': '1.0.0', 'status': 'FAILED'}
E         
E         Full diff:
E           {
E               'error': {
E                   'code': 'USAGE_INVALID',
E                   'message': 'odds snapshot options are not allowlisted',
E                   'retryable': False,
E               },
E         +     'schema_version': '1.0.0',
E         +     'status': 'FAILED',
E           }

tests/unit/cli/test_live_odds_snapshot.py:155: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/cli/test_live_odds_snapshot.py::test_snapshot_usage_failure_is_secret_free - AssertionError: assert {'error': {'c...us': 'FAILED'} == {'error': {'c...able': False}}
  
  Omitting 1 identical items, use -vv to show
  Left contains 2 more items:
  {'schema_version': '1.0.0', 'status': 'FAILED'}
  
  Full diff:
    {
        'error': {
            'code': 'USAGE_INVALID',
            'message': 'odds snapshot options are not allowlisted',
            'retryable': False,
        },
  +     'schema_version': '1.0.0',
  +     'status': 'FAILED',
    }
1 failed, 63 passed in 2.51s
```

## inherited_odds_pytest output

```text
........................................................................ [ 69%]
...............................                                          [100%]
103 passed in 1.61s
```

## postgres_integration output

```text

tests/integration/ingestion/odds/test_live_provider_current_input.py:80: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/dmf_pulse/ingestion/odds/live.py:766: in snapshot
    evidence_store.record_usable(
src/dmf_pulse/ingestion/odds/live.py:349: in record_usable
    append_processing_event_idempotent(
src/dmf_pulse/ingestion/repository.py:457: in append_processing_event_idempotent
    return SourceObservationRepository(session).append_processing_event(
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <dmf_pulse.data_model.repositories.SourceObservationRepository object at 0x7fd8d4590d60>
snapshot_id = UUID('01a01710-6908-756f-a129-a0c38322f55e')
stage = 'QUALITY_PASSED'
event_at = datetime.datetime(2026, 8, 20, 12, 0, 1, tzinfo=datetime.timezone.utc)
stage_version = 'the-odds-api-v4-reference-v1', operation_id = None
input_sha256 = 'b6782d6e6f657e7b9e7ef68e8327e89c6b1881bb076a0d2602811b2fa5e0ca69'
output_sha256 = 'a1f71471da1b16e322fb97c84233175f23df03ed9f516d535c55e6027e746303'
safe_details = {'provider_native': True, 'raw_payload_retained': False, 'canonical_fpl_fixture_mapping_performed': False}
error_code = None, actor = 'the-odds-api-current-input-v1'

    def append_processing_event(
        self,
        *,
        snapshot_id: UUID,
        stage: str,
        event_at: datetime,
        stage_version: str,
        operation_id: UUID | None = None,
        input_sha256: str | None = None,
        output_sha256: str | None = None,
        safe_details: Mapping[str, object] | None = None,
        error_code: str | None = None,
        actor: str = "dmf-pulse",
    ) -> UUID:
        locked_snapshot = self.session.execute(
            select(source_snapshot.c.source_snapshot_id)
            .where(source_snapshot.c.source_snapshot_id == snapshot_id)
            .with_for_update()
        ).scalar_one_or_none()
        if locked_snapshot is None:
            raise DataModelError("PROVENANCE_INTEGRITY", "source snapshot was not found")
        previous = (
            self.session.execute(
                select(
                    source_processing_event.c.processing_event_id,
                    source_processing_event.c.sequence_number,
                )
                .where(source_processing_event.c.source_snapshot_id == snapshot_id)
                .order_by(source_processing_event.c.sequence_number.desc())
                .limit(1)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        sequence = 1 if previous is None else int(previous["sequence_number"]) + 1
        previous_id = None if previous is None else _uuid(previous["processing_event_id"])
        operation = operation_id or snapshot_id
        occurred_at = require_utc(event_at)
        event_body = {
            "actor": actor,
            "error_code": error_code,
            "event_at": _utc_text(occurred_at),
            "input_sha256": input_sha256,
            "operation_id": str(operation),
            "output_sha256": output_sha256,
            "previous_event_id": str(previous_id) if previous_id is not None else None,
            "safe_details": dict(safe_details or {}),
            "sequence_number": sequence,
            "snapshot_id": str(snapshot_id),
            "stage": stage,
            "stage_version": stage_version,
        }
        event_sha256 = hashlib.sha256(
            json.dumps(
                event_body,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        try:
            return _uuid(
                self.session.execute(
                    insert(source_processing_event)
                    .values(
                        source_snapshot_id=snapshot_id,
                        operation_id=operation,
                        previous_event_id=previous_id,
                        sequence_number=sequence,
                        stage=stage,
                        outcome=(
                            "FAILED_RETRYABLE"
                            if stage == "FAILED_RETRYABLE"
                            else "FAILED_PERMANENT"
                            if stage == "FAILED_PERMANENT"
                            else "SUCCEEDED"
                        ),
                        event_at=occurred_at,
                        stage_version=stage_version,
                        input_sha256=input_sha256,
                        output_sha256=output_sha256,
                        event_sha256=event_sha256,
                        safe_details=dict(safe_details or {}),
                        error_code=error_code,
                        actor=actor,
                    )
                    .returning(source_processing_event.c.processing_event_id)
                ).scalar_one()
            )
        except DBAPIError as exc:
>           raise translate_database_error(exc) from exc
E           dmf_pulse.data_model.errors.DataModelError: database constraint rejected data

src/dmf_pulse/data_model/repositories.py:1281: DataModelError
=========================== short test summary info ============================
FAILED tests/integration/ingestion/odds/test_live_provider_current_input.py::test_live_provider_native_input_persists_governed_evidence_without_mapping - dmf_pulse.data_model.errors.DataModelError: database constraint rejected data
1 failed in 0.60s
```

## ruff_format output

```text
7 files already formatted
```

## ruff_lint output

```text
I001 [*] Import block is un-sorted or un-formatted
  --> src/dmf_pulse/cli/odds_cmd.py:3:1
   |
 1 |   """Typer surface for governed The Odds API validation and current retrieval."""
 2 |
 3 | / from __future__ import annotations
 4 | |
 5 | | import json
 6 | | from collections.abc import Callable
 7 | | from datetime import datetime
 8 | | from pathlib import Path
 9 | | from typing import Annotated, NoReturn
10 | |
11 | | import typer
12 | | from pydantic import BaseModel
13 | |
14 | | from dmf_pulse.ingestion.errors import IngestionError
15 | | from dmf_pulse.ingestion.fpl.parser import parse_rfc3339_timestamp
16 | | from dmf_pulse.ingestion.fpl.service import DATABASE_REF
17 | | from dmf_pulse.ingestion.odds.credentials import (
18 | |     RuntimeOddsCredentialProvider,
19 | |     credential_is_configured,
20 | | )
21 | | from dmf_pulse.ingestion.odds.live import LiveOddsOperationOutcome, LiveOddsSnapshotService
22 | | from dmf_pulse.ingestion.odds.parser import CONTRACT_VERSION
23 | | from dmf_pulse.ingestion.odds.service import (
24 | |     OddsImportRequest,
25 | |     OddsIngestionService as ReferenceOddsIngestionService,
26 | |     OddsOperationOutcome,
27 | |     OddsReplayRequest,
28 | | )
   | |_^
29 |
30 |   odds_app = typer.Typer(help="Validate and ingest governed The Odds API-shaped observations.")
   |
help: Organize imports

UP035 [*] Import from `collections.abc` instead: `Callable`
  --> tests/unit/ingestion/test_live_odds_current_input.py:9:1
   |
 7 | from datetime import UTC, datetime, timedelta
 8 | from pathlib import Path
 9 | from typing import Any, Callable
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
10 | from uuid import UUID
   |
help: Import from `collections.abc`

Found 2 errors.
[*] 2 fixable with the `--fix` option.
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
