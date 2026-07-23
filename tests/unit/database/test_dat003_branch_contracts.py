"""Branch-level false-success tests for DAT-003 database boundaries."""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from psycopg.types.range import Range
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from dmf_pulse.cli import data_model_cmd
from dmf_pulse.cli.app import app
from dmf_pulse.data_model import repositories as repository_module
from dmf_pulse.data_model import services as service_module
from dmf_pulse.data_model.errors import DataModelError
from dmf_pulse.data_model.models import DataQualityValue, DataValueState
from dmf_pulse.data_model.repositories import commit_session
from dmf_pulse.database import doctor as doctor_module
from dmf_pulse.database import migrate as migrate_module
from dmf_pulse.database import schema as schema_module
from dmf_pulse.database.errors import DatabaseError
from dmf_pulse.database.migrations import env as migration_env
from dmf_pulse.database.models import SchemaManifest


class _Scalar:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one(self) -> object:
        return self.value

    def scalar_one_or_none(self) -> object:
        return self.value


@pytest.mark.unit
def test_data_quality_states_reject_every_contradictory_shape() -> None:
    assert DataQualityValue(state=DataValueState.PRESENT, value="known").value == "known"
    for value in (
        {"state": DataValueState.PRESENT, "value": "known", "reason": "contradiction"},
        {"state": DataValueState.ZERO, "value": 0, "reason": "contradiction"},
        {"state": DataValueState.NULL, "value": None, "reason": "contradiction"},
        {"state": DataValueState.UNKNOWN, "value": "unexpected", "reason": "unknown"},
    ):
        with pytest.raises(ValidationError):
            DataQualityValue.model_validate(value)


@pytest.mark.unit
def test_repository_scalar_and_range_guards_reject_invalid_database_results() -> None:
    with pytest.raises(DataModelError) as invalid_range:
        repository_module._range_value(Range(empty=True))
    assert invalid_range.value.code == "TEMPORAL_RANGE_INVALID"
    with pytest.raises(DataModelError) as invalid_identifier:
        repository_module._uuid("not-a-uuid")
    assert invalid_identifier.value.code == "DATABASE_RESULT_INVALID"

    session = Mock(spec=Session)
    session.commit.side_effect = OperationalError("statement", {}, Exception("offline"))
    with pytest.raises(DataModelError) as commit_error:
        commit_session(session)
    assert commit_error.value.code == "DATABASE_UNAVAILABLE"
    session.rollback.assert_called_once_with()


@pytest.mark.unit
def test_rules_registry_timestamp_parser_rejects_malformed_values() -> None:
    assert repository_module._parse_utc("2026-07-23T12:00:00Z").isoformat() == (
        "2026-07-23T12:00:00+00:00"
    )
    for value in (None, "2026-07-23T12:00:00+00:00", "not-a-timestampZ"):
        with pytest.raises(DataModelError) as invalid:
            repository_module._parse_utc(value)
        assert invalid.value.code == "RULESET_REGISTRY_INTEGRITY"


@pytest.mark.unit
def test_fixture_parsers_fail_closed_for_wrong_types_and_time_formats(tmp_path: Path) -> None:
    too_large = tmp_path / "too-large.json"
    too_large.write_bytes(b" " * (1024 * 1024 + 1))
    invalid_root = tmp_path / "root.json"
    invalid_root.write_text("[]", encoding="utf-8")
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    for path in (too_large, invalid_root, invalid_json, tmp_path / "missing.json"):
        with pytest.raises(DataModelError) as fixture_error:
            service_module._load_object(path)
        assert fixture_error.value.code == "FIXTURE_INVALID"

    operations = (
        lambda: service_module._object([], "object"),
        lambda: service_module._object({1: "value"}, "object"),
        lambda: service_module._objects({}, "objects"),
        lambda: service_module._objects([[]], "objects"),
        lambda: service_module._string(1, "string"),
        lambda: service_module._string("", "string"),
        lambda: service_module._integer("1", "integer"),
        lambda: service_module._integer(True, "integer"),
        lambda: service_module._datetime("2026-07-23T00:00:00+00:00", "timestamp"),
        lambda: service_module._datetime("not-a-dateZ", "timestamp"),
        lambda: service_module._date("not-a-date", "date"),
    )
    for operation in operations:
        with pytest.raises(DataModelError) as parser_error:
            operation()
        assert parser_error.value.code == "FIXTURE_INVALID"
    assert service_module._uuid_version_is_seven({}) is False
    assert (
        service_module._uuid_version_is_seven(
            {"ordinary": UUID("00000000-0000-4000-8000-000000000001")}
        )
        is False
    )
    with pytest.raises(DataModelError) as assertion_error:
        service_module._assertions({"first": True, "second": False})
    assert assertion_error.value.code == "FIXTURE_ASSERTION_FAILED"

    unknown_query = tmp_path / "unknown-query.json"
    unknown_query.write_text(
        json.dumps(
            {
                "fixture_id": "unknown-kind",
                "queries": [
                    {
                        "expect": {},
                        "kind": "unsupported",
                        "known_at": "2026-07-23T00:00:00Z",
                        "query_id": "unknown",
                        "valid_at": "2026-07-23T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    state = service_module._SeedState(
        aliases={
            "gameweek-1": UUID("00000000-0000-7000-8000-000000000001"),
            "gameweek-2": UUID("00000000-0000-7000-8000-000000000002"),
        },
        fixture={},
    )
    with pytest.raises(DataModelError) as unknown_kind:
        service_module._as_of_result(Mock(spec=Session), state, unknown_query)
    assert unknown_kind.value.code == "FIXTURE_INVALID"


class _Transaction:
    def __init__(self, active: bool) -> None:
        self.is_active = active
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True


class _Session:
    def __init__(self, active: bool) -> None:
        self.transaction = _Transaction(active)
        self.closed = False

    def begin(self) -> _Transaction:
        return self.transaction

    def close(self) -> None:
        self.closed = True


@pytest.mark.unit
@pytest.mark.parametrize("active", [False, True])
def test_rollback_boundary_preserves_original_failure(active: bool) -> None:
    session = _Session(active)

    def fail(_session: object) -> None:
        raise RuntimeError("constructed operation failure")

    with pytest.raises(RuntimeError, match="constructed"):
        service_module._run_rollback(lambda: session, fail)  # type: ignore[arg-type]
    assert session.transaction.rolled_back is active
    assert session.closed is True


@pytest.mark.unit
def test_schema_revision_absence_and_required_revision_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_table = Mock()
    missing_table.execute.return_value = _Scalar(False)
    assert schema_module.current_alembic_revision(missing_table) is None

    empty_revision = Mock()
    empty_revision.execute.side_effect = [_Scalar(True), _Scalar(None)]
    assert schema_module.current_alembic_revision(empty_revision) is None

    connection = Mock()
    connection.execute.return_value = _Scalar("18.4")
    monkeypatch.setattr(schema_module, "current_alembic_revision", lambda _connection: None)
    with pytest.raises(DatabaseError) as behind:
        schema_module.inspect_schema(connection)
    assert behind.value.code == "DATABASE_SCHEMA_BEHIND"


@pytest.mark.unit
def test_database_doctor_rejects_wrong_major_and_missing_capabilities() -> None:
    manifest = SchemaManifest(
        postgres_version="18.4",
        alembic_revision="revision",
        extensions=(),
        schemas={
            name: {"functions": [], "tables": {}, "triggers": [], "views": {}}
            for name in ("core", "football", "fpl", "provenance")
        },
        schema_sha256="0" * 64,
    )
    capabilities = doctor_module._capabilities(manifest, uuidv7=False)
    assert capabilities == {
        "controlled_supersession": False,
        "gist_exclusion": False,
        "immutable_point_observations": False,
        "tstzrange": False,
        "uuidv7": False,
    }

    connection = Mock()
    connection.execute.side_effect = [_Scalar("17.9"), _Scalar(170009)]
    engine = Mock()
    engine.connect.return_value = nullcontext(connection)
    with pytest.raises(DatabaseError) as unsupported:
        doctor_module.build_database_doctor(
            engine, "postgresql+psycopg://user:" + "changeme@127.0.0.1/database"
        )
    assert unsupported.value.code == "DATABASE_VERSION_UNSUPPORTED"


@pytest.mark.unit
def test_migration_helpers_expose_fail_closed_head_and_execute_every_statement(
    monkeypatch: pytest.MonkeyPatch,
    repository_root: Path,
) -> None:
    script = SimpleNamespace(get_current_head=lambda: None)
    monkeypatch.setattr(migrate_module.ScriptDirectory, "from_config", lambda _config: script)
    with pytest.raises(RuntimeError, match="no head"):
        migrate_module.head_revision()

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        migrate_module.command,
        "upgrade",
        lambda _config, revision: calls.append(("upgrade", revision)),
    )
    monkeypatch.setattr(
        migrate_module.command,
        "downgrade",
        lambda _config, revision: calls.append(("downgrade", revision)),
    )
    migrate_module.upgrade_database("postgresql://host/database", "next")
    migrate_module.downgrade_database("postgresql://host/database", "prior")
    assert calls == [("upgrade", "next"), ("downgrade", "prior")]

    revision_path = (
        repository_root
        / "src/dmf_pulse/database/migrations/versions/20260723_0001_dat003_foundation.py"
    )
    revision: dict[str, object] = {"__name__": "dat003_revision_dispatch_test"}
    exec(compile(revision_path.read_bytes(), str(revision_path), "exec"), revision)
    executed: list[str] = []
    monkeypatch.setattr(revision["op"], "execute", executed.append)
    revision["upgrade"]()
    assert executed == list(revision["UPGRADE_STATEMENTS"])
    executed.clear()
    revision["downgrade"]()
    assert executed == list(revision["DOWNGRADE_STATEMENTS"])


@pytest.mark.unit
def test_alembic_environment_helpers_cover_offline_and_online_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_table = SimpleNamespace(schema=None)
    assert (
        migration_env._include_object(version_table, "alembic_version", "table", True, None)
        is False
    )
    assert migration_env._include_object(version_table, "team", "table", True, None) is True

    monkeypatch.setattr(migration_env, "config", None)
    monkeypatch.delenv("DMF_TEST_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="required"):
        migration_env._database_url()
    monkeypatch.setenv("DMF_TEST_DATABASE_URL", "postgresql://host/database")
    assert migration_env._database_url() == "postgresql://host/database"

    configure = Mock()
    run_migrations = Mock()
    monkeypatch.setattr(migration_env.context, "configure", configure)
    monkeypatch.setattr(migration_env.context, "begin_transaction", nullcontext)
    monkeypatch.setattr(migration_env.context, "run_migrations", run_migrations)
    migration_env.run_migrations_offline()
    assert configure.call_args.kwargs["literal_binds"] is True
    run_migrations.assert_called_once_with()

    with pytest.raises(RuntimeError, match="unavailable"):
        migration_env.run_migrations_online()

    fake_config = SimpleNamespace(
        config_ini_section="alembic",
        get_section=lambda _name, _default: {"sqlalchemy.url": "ignored"},
        get_main_option=lambda _name: "postgresql://configured/database",
    )
    monkeypatch.setattr(migration_env, "config", fake_config)
    assert migration_env._database_url() == "postgresql://configured/database"
    connection = object()
    connectable = SimpleNamespace(connect=lambda: nullcontext(connection))
    monkeypatch.setattr(migration_env, "engine_from_config", lambda *_args, **_kwargs: connectable)
    configure.reset_mock()
    run_migrations.reset_mock()
    migration_env.run_migrations_online()
    assert configure.call_args.kwargs["connection"] is connection
    run_migrations.assert_called_once_with()


class _DisposableEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


@pytest.mark.unit
@pytest.mark.parametrize(
    "code",
    [
        "DATABASE_VERSION_UNSUPPORTED",
        "DATABASE_SCHEMA_BEHIND",
        "DATABASE_UNAVAILABLE",
    ],
)
def test_database_doctor_cli_preserves_typed_nonzero_errors(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    engine = _DisposableEngine()
    monkeypatch.setattr(data_model_cmd, "_runtime", lambda: (engine, "redacted"))

    def fail(_engine: object, _url: str) -> None:
        raise DatabaseError(code, "safe deterministic failure")

    monkeypatch.setattr(data_model_cmd, "build_database_doctor", fail)
    result = CliRunner().invoke(app, ["data-model", "doctor", "--json"])
    assert result.exit_code == 50
    assert json.loads(result.stderr) == {
        "error": {"code": code, "message": "safe deterministic failure"}
    }
    assert engine.disposed is True


@pytest.mark.unit
def test_as_of_cli_preserves_not_found_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = _DisposableEngine()
    monkeypatch.setattr(data_model_cmd, "_runtime", lambda: (engine, "redacted"))
    monkeypatch.setattr(data_model_cmd, "session_factory", lambda _engine: object())

    def fail(_factory: object, _fixture: Path) -> None:
        raise DataModelError("AS_OF_NOT_FOUND", "as-of fact was not found")

    monkeypatch.setattr(data_model_cmd, "run_as_of", fail)
    result = CliRunner().invoke(
        app,
        ["data-model", "as-of", "--fixture", str(tmp_path / "fixture.json"), "--json"],
    )
    assert result.exit_code == 50
    assert json.loads(result.stderr)["error"]["code"] == "AS_OF_NOT_FOUND"
    assert engine.disposed is True
