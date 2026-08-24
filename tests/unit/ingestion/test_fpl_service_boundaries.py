"""Service boundary and fail-closed branch tests independent of PostgreSQL."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.exc import SQLAlchemyError

from dmf_pulse.database.errors import DatabaseError
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fixtures import ApprovedFixture
from dmf_pulse.ingestion.fpl import service as service_module
from dmf_pulse.ingestion.fpl.adapter import FplReferenceAdapter
from dmf_pulse.ingestion.fpl.parser import (
    MAX_PAYLOAD_BYTES,
    FixturePayload,
    FplResource,
    ParsedFplResource,
    parse_fpl_payload,
)
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    FplImportRequest,
    FplIngestionService,
    FplReplayRequest,
    IngestionInterrupted,
)
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability, RightsProfile
from dmf_pulse.ingestion.rights import load_rights_profiles

pytestmark = pytest.mark.unit


def _fixture(root: Path, scenario: str, resource: str) -> Path:
    return root / "fixtures/fpl/FPL-004" / scenario / f"{resource}.json"


def _parsed_pair(root: Path) -> tuple[ParsedFplResource, ParsedFplResource]:
    return (
        parse_fpl_payload(
            FplResource.BOOTSTRAP, _fixture(root, "happy_path", "bootstrap").read_bytes()
        ),
        parse_fpl_payload(
            FplResource.FIXTURES, _fixture(root, "happy_path", "fixtures").read_bytes()
        ),
    )


@pytest.mark.parametrize("reference", ["literal", "postgresql://host/db", "env:user@host"])
def test_database_reference_rejects_every_nonopaque_form(reference: str) -> None:
    with pytest.raises(IngestionError) as caught:
        service_module.resolve_database_reference(reference)
    assert caught.value.code == "DATABASE_REFERENCE_INVALID"


def test_database_reference_translates_database_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*, environment: str) -> str:
        assert isinstance(environment, str)
        raise DatabaseError("DATABASE_ENVIRONMENT_INVALID", "safe failure")

    monkeypatch.setattr(service_module, "resolve_test_database_url", fail)
    with pytest.raises(IngestionError, match="safe failure") as caught:
        service_module.resolve_database_reference(DATABASE_REF)
    assert caught.value.code == "DATABASE_REFERENCE_INVALID"


class _Scalar:
    def __init__(self, value: str) -> None:
        self.value = value

    def scalar_one(self) -> str:
        return self.value


class _Connection:
    def __init__(self, revision: str) -> None:
        self.revision = revision

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _statement: object) -> _Scalar:
        return _Scalar(self.revision)


class _Engine:
    def __init__(self, revision: str) -> None:
        self.revision = revision
        self.disposed = False

    def connect(self) -> _Connection:
        return _Connection(self.revision)

    def dispose(self) -> None:
        self.disposed = True


def test_engine_rejects_stale_revision_and_disposes(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _Engine("20260723_0001")
    monkeypatch.setattr(service_module, "resolve_database_reference", lambda _reference: "safe-url")
    monkeypatch.setattr(service_module, "create_database_engine", lambda *_args: engine)
    with pytest.raises(IngestionError) as caught:
        service_module._engine(DATABASE_REF)
    assert caught.value.code == "DATABASE_SCHEMA_BEHIND"
    assert engine.disposed is True


@pytest.mark.parametrize(
    "failure",
    [DatabaseError("DATABASE_UNAVAILABLE", "hidden"), SQLAlchemyError("hidden")],
)
def test_engine_translates_driver_failures(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    monkeypatch.setattr(service_module, "resolve_database_reference", lambda _reference: "safe-url")

    def fail(*_args: object) -> None:
        raise failure

    monkeypatch.setattr(service_module, "create_database_engine", fail)
    with pytest.raises(IngestionError) as caught:
        service_module._engine(DATABASE_REF)
    assert caught.value.code == "DATABASE_UNAVAILABLE"
    assert "hidden" not in caught.value.message


@pytest.mark.parametrize("sqlstate", ["40001", "40P01", "55P03"])
def test_database_retryable_sqlstates_are_typed_without_driver_text(sqlstate: str) -> None:
    original = type("DriverFailure", (), {"sqlstate": sqlstate})()
    failure = type("WrappedFailure", (), {"orig": original})()
    translated = service_module._database_error(failure)
    assert translated.code == "DATABASE_RETRYABLE"
    assert translated.exit_code == 5
    assert translated.retryable is True
    assert translated.details == {"sqlstate": sqlstate}


def test_database_constraint_sqlstate_and_data_model_failure_are_typed() -> None:
    original = type("DriverFailure", (), {"sqlstate": "23503"})()
    failure = type("WrappedFailure", (), {"orig": original})()
    translated = service_module._database_error(failure)
    assert translated.code == "DATABASE_CONSTRAINT"
    assert translated.retryable is False
    data_model = service_module._database_error(
        DatabaseError("TEMPORAL_OVERLAP", "hidden database detail")
    )
    assert data_model.code == "DATABASE_CONSTRAINT"
    assert "hidden" not in data_model.message


def test_bounded_reader_rejects_missing_symlink_and_oversize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(IngestionError) as unavailable:
        service_module._read_bounded(missing)
    assert unavailable.value.code == "USAGE_INVALID"

    regular = tmp_path / "regular.json"
    regular.write_text("{}", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == regular or original(path))
    with pytest.raises(IngestionError, match="unavailable"):
        service_module._read_bounded(regular)
    monkeypatch.setattr(Path, "is_symlink", original)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * (MAX_PAYLOAD_BYTES + 1))
    with pytest.raises(IngestionError) as too_large:
        service_module._read_bounded(oversized)
    assert too_large.value.code == "PAYLOAD_TOO_LARGE"


def test_missing_profile_and_invalid_adapter_fetch_fail_before_side_effects() -> None:
    with pytest.raises(IngestionError) as missing:
        FplIngestionService().snapshot(
            resource="all",
            competition_key="PL",
            season_code="2026/27",
            rights_profile_id="missing",
        )
    assert missing.value.code == "CONFIGURATION_INVALID"

    with pytest.raises(IngestionError) as adapter:
        FplReferenceAdapter().fetch(FplResource.BOOTSTRAP)
    assert adapter.value.code == "CONFIGURATION_INVALID"


def test_cross_resource_validation_rejects_wrong_types_and_unknown_relations(
    repository_root: Path,
) -> None:
    bootstrap, fixtures = _parsed_pair(repository_root)
    with pytest.raises(IngestionError) as wrong_type:
        service_module._cross_validate(fixtures, bootstrap)
    assert wrong_type.value.code == "INTERNAL_INVARIANT"

    assert isinstance(fixtures.payload, FixturePayload)
    fixture = fixtures.payload.fixtures[0]
    bad_team_payload = fixtures.payload.model_copy(
        update={"fixtures": [fixture.model_copy(update={"team_h": 999})]}
    )
    with pytest.raises(IngestionError) as team:
        service_module._cross_validate(
            bootstrap, fixtures.model_copy(update={"payload": bad_team_payload})
        )
    assert team.value.code == "MAPPING_CONFLICT"

    bad_event_payload = fixtures.payload.model_copy(
        update={"fixtures": [fixture.model_copy(update={"event": 999})]}
    )
    with pytest.raises(IngestionError) as event:
        service_module._cross_validate(
            bootstrap, fixtures.model_copy(update={"payload": bad_event_payload})
        )
    assert event.value.code == "MAPPING_CONFLICT"


def test_fixture_relative_path_must_remain_governed(tmp_path: Path) -> None:
    approved = ApprovedFixture(path=tmp_path / "x", relative_path="outside/x", sha256="0" * 64)
    with pytest.raises(IngestionError) as caught:
        service_module._relative_fixture_path(approved)
    assert caught.value.code == "FIXTURE_NOT_APPROVED"


def test_durable_fixture_readback_uses_the_approved_absolute_path(tmp_path: Path) -> None:
    body = b'{"fixture":"installed-wheel"}'
    fixture = tmp_path / "external-fixtures" / "bootstrap.json"
    fixture.parent.mkdir()
    fixture.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    approved = ApprovedFixture(
        path=fixture.resolve(),
        relative_path="fixtures/fpl/FPL-004/happy_path/bootstrap.json",
        sha256=digest,
    )

    assert service_module._verified_fixture_storage(approved, body) == (
        f"repository://fixtures/fpl/FPL-004/happy_path/bootstrap.json#sha256={digest}"
    )

    with pytest.raises(IngestionError) as changed:
        service_module._verified_fixture_storage(approved, b"changed")
    assert changed.value.code == "FIXTURE_NOT_APPROVED"


def _automated_profile(repository_root: Path) -> RightsProfile:
    profile = load_rights_profiles(repository_root / "config/rights/fpl_profiles.json")[
        "synthetic_test_v1"
    ]
    capabilities = dict(profile.capabilities)
    capabilities[RightsCapability.AUTOMATED_ACCESS] = CapabilityValue.ALLOW
    return profile.model_copy(update={"capabilities": capabilities})


@pytest.mark.parametrize(
    ("resource", "expected"),
    [("all", [FplResource.BOOTSTRAP, FplResource.FIXTURES]), ("fixtures", [FplResource.FIXTURES])],
)
def test_even_hypothetically_allowed_snapshot_cannot_persist_live_data(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    expected: list[FplResource],
) -> None:
    calls: list[FplResource] = []

    class FakeAdapter:
        def __init__(self, _profile: RightsProfile, _factory: object) -> None:
            del _profile, _factory

        def fetch(self, item: FplResource) -> bytes:
            calls.append(item)
            return b"{}"

    monkeypatch.setattr(
        service_module, "_profile", lambda _profile_id: _automated_profile(repository_root)
    )
    monkeypatch.setattr(service_module, "FplReferenceAdapter", FakeAdapter)
    with pytest.raises(IngestionError, match="not approved") as caught:
        FplIngestionService().snapshot(
            resource=resource,
            competition_key="PL",
            season_code="2026/27",
            rights_profile_id="synthetic_test_v1",
        )
    assert caught.value.code == "RIGHTS_BLOCKED"
    assert calls == expected


def test_official_manual_import_accepts_ordinary_paths_via_clean_service_owned_copies(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service_module.tempfile, "gettempdir", lambda: str(tmp_path / "service-temp")
    )

    def reached_database_boundary(_reference: str) -> object:
        raise IngestionError("DATABASE_UNAVAILABLE", "synthetic boundary reached")

    monkeypatch.setattr(service_module, "_engine", reached_database_boundary)
    happy = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap = tmp_path / "bootstrap.json"
    fixtures = tmp_path / "fixtures.json"
    bootstrap.write_bytes((happy / "bootstrap.json").read_bytes())
    fixtures.write_bytes((happy / "fixtures.json").read_bytes())
    with pytest.raises(IngestionError) as caught:
        FplIngestionService(repository_root=repository_root).import_pair(
            FplImportRequest(
                bootstrap_path=bootstrap,
                fixtures_path=fixtures,
                competition_key="PL",
                season_code="2026/27",
                captured_at=datetime(2026, 8, 21, 17, tzinfo=UTC),
                information_cutoff=datetime(2026, 8, 21, 17, 30, tzinfo=UTC),
                rights_profile_id="fpl_official_private_manual_v1",
            )
        )
    assert caught.value.code == "DATABASE_UNAVAILABLE"
    assert bootstrap.exists()
    assert fixtures.exists()
    assert not any(service_module._volatile_root().iterdir())


def test_validation_reports_one_deterministic_additive_warning(repository_root: Path) -> None:
    result = FplIngestionService().validate(
        FplResource.BOOTSTRAP,
        _fixture(repository_root, "unknown_additive", "bootstrap"),
    )
    assert result.status == "VALID_WITH_WARNINGS"
    assert result.quality.warning_count == 1
    assert result.quality.issues[0].code == "ADDITIVE_UNKNOWN"


def test_synthetic_profile_rejects_nonfixed_competition_before_fixture_access(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    happy = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap = tmp_path / "bootstrap.json"
    fixtures = tmp_path / "fixtures.json"
    bootstrap.write_bytes((happy / "bootstrap.json").read_bytes())
    fixtures.write_bytes((happy / "fixtures.json").read_bytes())
    monkeypatch.setattr(
        service_module,
        "approve_synthetic_fixture",
        lambda *_args, **_kwargs: pytest.fail("invalid context must fail before fixture access"),
    )
    with pytest.raises(IngestionError, match="fixed SYNTHETIC_PL") as caught:
        FplIngestionService(repository_root=repository_root).import_pair(
            FplImportRequest(
                bootstrap_path=bootstrap,
                fixtures_path=fixtures,
                competition_key="PL",
                season_code="2026/27",
                captured_at=datetime(2026, 8, 21, 17, tzinfo=UTC),
                information_cutoff=datetime(2026, 8, 21, 17, 30, tzinfo=UTC),
                rights_profile_id="synthetic_test_v1",
            )
        )
    assert caught.value.code == "USAGE_INVALID"
    assert bootstrap.exists()
    assert fixtures.exists()


class _Rows:
    def __init__(self, rows: list[dict[str, object]], scalar: object = None) -> None:
        self.rows = rows
        self.scalar = scalar

    def mappings(self) -> _Rows:
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows

    def scalar_one_or_none(self) -> object:
        return self.scalar


class _ResumeSession:
    def __init__(self, rows: list[dict[str, object]], scalar: object = None) -> None:
        self.result = _Rows(rows, scalar)

    def __enter__(self) -> _ResumeSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _statement: object, _parameters: object = None) -> _Rows:
        return self.result


class _ResumeFactory:
    def __init__(self, rows: list[dict[str, object]], scalar: object = None) -> None:
        self.rows = rows
        self.scalar = scalar

    def __call__(self) -> _ResumeSession:
        return _ResumeSession(self.rows, self.scalar)

    def begin(self) -> _ResumeSession:
        return self()


class _Disposable:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _resume_boundary(
    monkeypatch: pytest.MonkeyPatch,
    *,
    context: dict[str, object],
    rows: list[dict[str, object]],
) -> _Disposable:
    engine = _Disposable()

    def verified_pair(
        _self: FplIngestionService,
        _session: object,
        _snapshot_id: UUID,
    ) -> tuple[str, dict[str, object], dict[str, dict[str, object]]]:
        pair_key = context.get("pair_key")
        if not isinstance(pair_key, str):
            raise IngestionError("LIFECYCLE_INVARIANT", "snapshot pair context is unavailable")
        by_resource = {str(row["resource"]): row for row in rows}
        if len(rows) != 2 or set(by_resource) != {"bootstrap", "fixtures"}:
            raise IngestionError("LIFECYCLE_INVARIANT", "snapshot pair is incomplete")
        return pair_key, dict(context), by_resource

    monkeypatch.setattr(service_module, "_engine", lambda _reference: engine)
    monkeypatch.setattr(service_module, "session_factory", lambda _engine: _ResumeFactory(rows))
    monkeypatch.setattr(FplIngestionService, "_verified_resume_pair", verified_pair)
    return engine


def _resume_rows() -> list[dict[str, object]]:
    return [
        {
            "source_snapshot_id": UUID(int=1),
            "resource": "bootstrap",
            "body_sha256": "0" * 64,
        },
        {
            "source_snapshot_id": UUID(int=2),
            "resource": "fixtures",
            "body_sha256": "0" * 64,
        },
    ]


@pytest.mark.parametrize(
    ("context", "rows", "message"),
    [
        ({}, [], "pair context"),
        ({"pair_key": "pair"}, [], "pair is incomplete"),
        (
            {
                "pair_key": "pair",
                "bootstrap_path": "fixtures/fpl/FPL-004/happy_path/bootstrap.json",
                "fixtures_path": "fixtures/fpl/FPL-004/happy_path/fixtures.json",
            },
            _resume_rows(),
            "rights context",
        ),
    ],
)
def test_resume_rejects_incomplete_persisted_context_before_promotion(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    context: dict[str, object],
    rows: list[dict[str, object]],
    message: str,
) -> None:
    engine = _resume_boundary(monkeypatch, context=context, rows=rows)
    with pytest.raises(IngestionError, match=message):
        FplIngestionService(repository_root=repository_root).resume(
            UUID(int=1), database_url_ref=DATABASE_REF
        )
    assert engine.disposed is True


def test_resume_rejects_fixture_bytes_that_changed_after_receive(
    repository_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context: dict[str, object] = {
        "bootstrap_path": "fixtures/fpl/FPL-004/happy_path/bootstrap.json",
        "captured_at": "2026-08-21T17:00:00Z",
        "fixtures_path": "fixtures/fpl/FPL-004/happy_path/fixtures.json",
        "operation_time_policy": "FROZEN_REPLAY_CAPTURED_AT_V1",
        "profile_id": "synthetic_test_v1",
        "profile_version": "1.0.0",
        "rights_config_sha256": service_module.rights_config_sha256(),
        "provider_config_sha256": service_module.provider_config_sha256(),
        "effective_config_sha256": service_module.effective_config_sha256(),
        "contract_version": service_module.CONTRACT_VERSION,
    }
    context["pair_key"] = service_module.canonical_sha256(context)
    profile_record_id = UUID(int=3)
    rows = [
        {
            **row,
            "rights_profile_key": "synthetic_test_v1",
            "rights_profile_version": "1.0.0",
            "rights_profile_record_id": profile_record_id,
            "adapter_version": service_module.CONTRACT_VERSION,
            "contract_version": service_module.CONTRACT_VERSION,
        }
        for row in _resume_rows()
    ]
    monkeypatch.setattr(
        service_module, "register_rights_profile", lambda _session, _profile: profile_record_id
    )
    monkeypatch.setattr(
        FplIngestionService, "_pair_state", lambda _self, _session, _snapshots: ("STORED", "STORED")
    )
    engine = _resume_boundary(monkeypatch, context=context, rows=rows)
    with pytest.raises(IngestionError, match="input hash changed"):
        FplIngestionService(repository_root=repository_root).resume(
            UUID(int=1), database_url_ref=DATABASE_REF
        )
    assert engine.disposed is True


@pytest.mark.parametrize("found", [False, True])
def test_bundle_lookup_handles_absent_and_present_snapshot_without_hidden_resolution(
    monkeypatch: pytest.MonkeyPatch, found: bool
) -> None:
    engine = _Disposable()
    snapshot = UUID(int=1) if found else None
    monkeypatch.setattr(service_module, "_engine", lambda _reference: engine)
    monkeypatch.setattr(
        service_module,
        "session_factory",
        lambda _engine: _ResumeFactory([], snapshot),
    )
    sentinel = object()

    class Persistence:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            del _args, _kwargs

        def bundle_summary(self, _bundle_id: UUID) -> object:
            return sentinel

    monkeypatch.setattr(service_module, "FplPersistence", Persistence)
    if not found:
        with pytest.raises(IngestionError, match="not found"):
            FplIngestionService().show_bundle(UUID(int=2), database_url_ref=DATABASE_REF)
    else:
        assert (
            FplIngestionService().show_bundle(UUID(int=2), database_url_ref=DATABASE_REF)
            is sentinel
        )
    assert engine.disposed is True


@pytest.mark.parametrize(
    ("scenario", "expected_scenario", "captured", "halt"),
    [
        ("happy", "happy_path", datetime(2026, 8, 21, 17, tzinfo=UTC), None),
        ("changed", "changed_snapshot", datetime(2026, 8, 21, 17, 10, tzinfo=UTC), None),
        ("post_cutoff", "post_cutoff", datetime(2026, 8, 21, 17, 31, tzinfo=UTC), None),
        ("resume-mapped", "happy_path", datetime(2026, 8, 21, 17, tzinfo=UTC), "MAPPED"),
        ("resume-parsed", "happy_path", datetime(2026, 8, 21, 17, tzinfo=UTC), "PARSED"),
        (
            "resume-promoted",
            "happy_path",
            datetime(2026, 8, 21, 17, tzinfo=UTC),
            "PROMOTED",
        ),
        (
            "resume-raw_discarded",
            "happy_path",
            datetime(2026, 8, 21, 17, tzinfo=UTC),
            "STORED_OR_RAW_DISCARDED",
        ),
        ("resume-stored", "happy_path", datetime(2026, 8, 21, 17, tzinfo=UTC), "STORED"),
        (
            "resume-stored_or_raw_discarded",
            "happy_path",
            datetime(2026, 8, 21, 17, tzinfo=UTC),
            "STORED_OR_RAW_DISCARDED",
        ),
        (
            "resume-validated",
            "happy_path",
            datetime(2026, 8, 21, 17, tzinfo=UTC),
            "VALIDATED",
        ),
    ],
)
def test_replay_aliases_are_explicit_and_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_scenario: str,
    captured: datetime,
    halt: str | None,
) -> None:
    observed: dict[str, Any] = {}
    sentinel = object()

    def capture(
        _self: FplIngestionService,
        request: FplImportRequest,
        *,
        operation_time_policy: str,
    ) -> Any:
        observed["request"] = request
        observed["operation_time_policy"] = operation_time_policy
        return sentinel

    monkeypatch.setattr(FplIngestionService, "_import_pair", capture)
    service = FplIngestionService(repository_root=tmp_path)
    result = service.replay(FplReplayRequest(fixture_set=tmp_path / "fixtures", scenario=scenario))
    request = observed["request"]
    assert result is sentinel
    assert request.bootstrap_path == tmp_path / "fixtures" / expected_scenario / "bootstrap.json"
    assert request.captured_at == captured
    assert request.halt_after_stage == halt
    assert observed["operation_time_policy"] == "FROZEN_REPLAY_CAPTURED_AT_V1"


@pytest.mark.parametrize("scenario", ("resume-post_cutoff", "resume-typo"))
def test_replay_rejects_arbitrary_resume_aliases_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    def unexpected_import(*_args: object, **_kwargs: object) -> Any:
        pytest.fail("an unapproved resume alias must fail before fixture import")

    monkeypatch.setattr(FplIngestionService, "import_pair", unexpected_import)
    monkeypatch.setattr(
        FplIngestionService,
        "_import_pair",
        unexpected_import,
        raising=False,
    )
    with pytest.raises(IngestionError, match="resume scenario is not approved") as caught:
        FplIngestionService(repository_root=tmp_path).replay(
            FplReplayRequest(fixture_set=tmp_path / "fixtures", scenario=scenario)
        )
    assert caught.value.code == "USAGE_INVALID"


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param("happy_path/../post_cutoff", id="path-traversal"),
        pytest.param("HAPPY_PATH", id="case-variant"),
        pytest.param("happy_path/.", id="noncanonical-path"),
        pytest.param(None, id="absolute-path"),
    ],
)
def test_replay_rejects_noncanonical_scenario_identity_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str | None,
) -> None:
    fixture_set = tmp_path / "fixtures"
    scenario = scenario or str((tmp_path / "outside" / "post_cutoff").resolve())

    def unexpected_import(*_args: object, **_kwargs: object) -> Any:
        pytest.fail("an unapproved scenario must fail before fixture import")

    # Patch both boundaries so the regression stays red against the pre-policy
    # implementation as well as guarding the policy-aware private boundary.
    monkeypatch.setattr(FplIngestionService, "import_pair", unexpected_import)
    monkeypatch.setattr(
        FplIngestionService,
        "_import_pair",
        unexpected_import,
        raising=False,
    )
    with pytest.raises(IngestionError, match="scenario is not approved") as caught:
        FplIngestionService(repository_root=tmp_path).replay(
            FplReplayRequest(fixture_set=fixture_set, scenario=scenario)
        )
    assert caught.value.code == "USAGE_INVALID"


def test_replay_rejects_approved_name_resolving_to_another_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_set = tmp_path / "fixtures"
    target = fixture_set / "post_cutoff"
    target.mkdir(parents=True)
    scenario_path = fixture_set / "happy_path"
    original_resolve = Path.resolve
    redirected_target = original_resolve(target)

    def redirected_resolve(path: Path, strict: bool = False) -> Path:
        if path == scenario_path:
            return redirected_target
        return original_resolve(path, strict=strict)

    # Model the portable observable effect of a directory symlink/junction. This
    # executes on Windows hosts that do not grant the symlink creation privilege.
    monkeypatch.setattr(Path, "resolve", redirected_resolve)

    def unexpected_import(*_args: object, **_kwargs: object) -> Any:
        pytest.fail("a redirected scenario must fail before fixture import")

    monkeypatch.setattr(
        FplIngestionService,
        "_import_pair",
        unexpected_import,
        raising=False,
    )
    with pytest.raises(IngestionError, match="scenario path is not approved") as caught:
        FplIngestionService(repository_root=tmp_path).replay(
            FplReplayRequest(fixture_set=fixture_set, scenario="happy_path")
        )
    assert caught.value.code == "FIXTURE_NOT_APPROVED"


def test_replay_translates_scenario_resolution_oserror_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_set = tmp_path / "fixtures"
    service = FplIngestionService(repository_root=tmp_path)
    original_resolve = Path.resolve

    def unavailable_resolve(path: Path, strict: bool = False) -> Path:
        if path == fixture_set:
            raise OSError("sensitive host path failure")
        return original_resolve(path, strict=strict)

    def unexpected_import(*_args: object, **_kwargs: object) -> Any:
        pytest.fail("an unavailable scenario path must fail before fixture import")

    monkeypatch.setattr(Path, "resolve", unavailable_resolve)
    monkeypatch.setattr(FplIngestionService, "import_pair", unexpected_import)
    monkeypatch.setattr(
        FplIngestionService,
        "_import_pair",
        unexpected_import,
        raising=False,
    )
    with pytest.raises(IngestionError, match="scenario path is unavailable") as caught:
        service.replay(FplReplayRequest(fixture_set=fixture_set, scenario="happy_path"))
    assert caught.value.code == "FIXTURE_NOT_APPROVED"
    assert "sensitive host path failure" not in caught.value.message


def test_operation_time_policy_separates_frozen_replay_from_processing_time() -> None:
    captured = datetime(2026, 8, 21, 17, tzinfo=UTC)
    future = datetime(2027, 8, 22, 18, tzinfo=UTC)
    service = FplIngestionService(clock=lambda: future)

    assert (
        service._operation_time(
            captured,
            policy="FROZEN_REPLAY_CAPTURED_AT_V1",
        )
        == captured
    )
    assert service._operation_time(captured, policy="PROCESSING_TIME_V1") == future
    with pytest.raises(IngestionError, match="policy is unavailable") as unknown:
        service._operation_time(captured, policy="UNKNOWN")
    assert unknown.value.code == "LIFECYCLE_INVARIANT"


def test_operation_time_policy_preserves_utc_and_naive_datetime_rejection(
    tmp_path: Path,
) -> None:
    aware = datetime(2026, 8, 21, 17, tzinfo=UTC)
    naive = datetime(2026, 8, 21, 17)
    service = FplIngestionService(clock=lambda: naive)

    for policy in ("FROZEN_REPLAY_CAPTURED_AT_V1", "PROCESSING_TIME_V1"):
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            service._operation_time(naive, policy=policy)
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        service._operation_time(aware, policy="PROCESSING_TIME_V1")
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        FplIngestionService(repository_root=tmp_path, clock=lambda: aware).import_pair(
            FplImportRequest(
                bootstrap_path=tmp_path / "fixtures/bootstrap.json",
                fixtures_path=tmp_path / "fixtures/fixtures.json",
                competition_key="SYNTHETIC_PL",
                season_code="2026/27",
                captured_at=naive,
                information_cutoff=aware,
                rights_profile_id="synthetic_test_v1",
            )
        )
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        service.replay(
            FplReplayRequest(
                fixture_set=tmp_path / "fixtures",
                scenario="happy_path",
                information_cutoff=naive,
            )
        )
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        service._context_time({"captured_at": "2026-08-21T17:00:00"}, "captured_at")


def test_resume_operation_time_policy_is_strict_and_fail_closed() -> None:
    synthetic = service_module._profile("synthetic_test_v1")
    official = service_module._profile("fpl_official_private_manual_v1")

    with pytest.raises(IngestionError, match="policy is unavailable") as missing:
        FplIngestionService._resume_operation_time_policy({}, synthetic)
    assert missing.value.code == "LIFECYCLE_INVARIANT"
    assert (
        FplIngestionService._resume_operation_time_policy(
            {"operation_time_policy": "FROZEN_REPLAY_CAPTURED_AT_V1"},
            synthetic,
        )
        == "FROZEN_REPLAY_CAPTURED_AT_V1"
    )
    with pytest.raises(IngestionError, match="policy is unavailable") as unknown:
        FplIngestionService._resume_operation_time_policy(
            {"operation_time_policy": "UNKNOWN"},
            synthetic,
        )
    assert unknown.value.code == "LIFECYCLE_INVARIANT"
    with pytest.raises(IngestionError, match="approved synthetic profile") as unauthorized:
        FplIngestionService._resume_operation_time_policy(
            {"operation_time_policy": "FROZEN_REPLAY_CAPTURED_AT_V1"},
            official,
        )
    assert unauthorized.value.code == "RIGHTS_BLOCKED"


def test_replay_rejects_frozen_time_for_non_synthetic_profile_before_clock(
    tmp_path: Path,
) -> None:
    clock_calls = 0

    def unexpected_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return datetime(2026, 8, 21, 17, tzinfo=UTC)

    service = FplIngestionService(repository_root=tmp_path, clock=unexpected_clock)
    with pytest.raises(IngestionError, match="approved synthetic profile") as blocked:
        service.replay(
            FplReplayRequest(
                fixture_set=tmp_path / "fixtures",
                scenario="happy_path",
                rights_profile_id="fpl_official_private_manual_v1",
            )
        )
    assert blocked.value.code == "RIGHTS_BLOCKED"
    assert clock_calls == 0


def test_resume_context_and_interruption_guards_are_typed(tmp_path: Path) -> None:
    service = FplIngestionService(repository_root=tmp_path)
    for value in (None, "outside.json"):
        with pytest.raises(IngestionError, match="resume fixture path"):
            service._safe_resume_path(value)
    with pytest.raises(IngestionError, match="escapes repository"):
        service._safe_resume_path("fixtures/../../escape.json")
    with pytest.raises(IngestionError, match="context is incomplete"):
        service._context_string({}, "missing")
    with pytest.raises(IngestionError, match="time is invalid"):
        service._context_time({"at": "not-time"}, "at")

    snapshots = (service_module.UUID(int=1), service_module.UUID(int=2))
    with pytest.raises(IngestionInterrupted) as interrupted:
        service._maybe_interrupt("stored-or-raw-discarded", "STORED", snapshots)
    assert interrupted.value.snapshot_ids == snapshots
    service._maybe_interrupt(None, "STORED", snapshots)


def test_post_cutoff_issue_evidence_rejects_missing_blocker() -> None:
    with pytest.raises(IngestionError, match="evidence is incomplete") as caught:
        FplIngestionService._record_bundle_eligibility_issues(
            None,  # type: ignore[arg-type]
            (UUID(int=1), UUID(int=2)),
            service_module._clean_quality(),
        )
    assert caught.value.code == "INTERNAL_INVARIANT"


def test_post_cutoff_issue_evidence_is_idempotent_when_rows_exist() -> None:
    class ExistingIssueSession:
        def __init__(self) -> None:
            self.scalar_calls = 0

        def scalar(self, _statement: object) -> int:
            self.scalar_calls += 1
            return 1

        def execute(self, _statement: object) -> None:
            pytest.fail("an existing post-cutoff issue must not be inserted again")

    session = ExistingIssueSession()
    quality = service_module._quality_with_blocker(
        service_module._clean_quality(),
        "POST_CUTOFF",
        observed_at=datetime(2026, 8, 21, 17, 31, tzinfo=UTC),
    )
    FplIngestionService._record_bundle_eligibility_issues(
        session,  # type: ignore[arg-type]
        (UUID(int=1), UUID(int=2)),
        quality,
    )
    assert session.scalar_calls == 2
