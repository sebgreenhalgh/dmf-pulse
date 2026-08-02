"""Pre-persistence invariants and offline ODD service refusal boundaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from dmf_pulse.ingestion import repository as repository_module
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.ingestion.models import RightsDecision
from dmf_pulse.ingestion.odds import service as service_module
from dmf_pulse.ingestion.odds.client import StaticCredentialProvider
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.service import (
    OddsImportRequest,
    OddsIngestionService,
    OddsReplayRequest,
)

pytestmark = pytest.mark.unit
NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)


class _DbResult:
    def __init__(self, value: object = None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value

    def scalar_one(self) -> object:
        return self.value

    def mappings(self) -> _DbResult:
        return self

    def one_or_none(self) -> object:
        return self.value

    def one(self) -> object:
        return self.value

    def first(self) -> object:
        return self.value


class _DbSession:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def execute(self, *_args: object, **_kwargs: object) -> _DbResult:
        return _DbResult(self.values.pop(0) if self.values else None)


def test_repository_rejects_invalid_identifiers_attempts_and_unchecked_rights() -> None:
    with pytest.raises(IngestionError, match="invalid identifier"):
        repository_module._uuid("not-a-uuid")
    with pytest.raises(IngestionError, match="attempt must be positive"):
        repository_module.record_ingestion_run(
            None,  # type: ignore[arg-type]
            provider_id=UUID(int=1),
            pair_key="pair",
            started_at=NOW,
            attempt_number=0,
        )
    decision = RightsDecision(
        profile_id="synthetic",
        profile_version="1.0.0",
        capability="derived_storage",
        decision="ALLOW",
        reason="synthetic authority",
        checked_at=None,
    )
    with pytest.raises(IngestionError, match="lacks a check time"):
        repository_module.record_rights_decision(
            None,  # type: ignore[arg-type]
            rights_profile_record_id=UUID(int=1),
            source_snapshot_id=None,
            decision=decision,
            context={},
        )


def _checked_decision() -> RightsDecision:
    return RightsDecision(
        profile_id="synthetic",
        profile_version="1.0.0",
        capability="derived_storage",
        decision="ALLOW",
        reason="synthetic authority",
        checked_at=NOW,
    )


def test_rights_decision_idempotency_and_conflicts_are_explicit() -> None:
    created_id = UUID(int=10)
    assert (
        repository_module.record_rights_decision(
            _DbSession([created_id]),  # type: ignore[arg-type]
            rights_profile_record_id=UUID(int=1),
            source_snapshot_id=None,
            decision=_checked_decision(),
            context={"synthetic": True},
        )
        == created_id
    )

    with pytest.raises(IngestionError, match="conflict is unavailable"):
        repository_module.record_rights_decision(
            _DbSession([None, None]),  # type: ignore[arg-type]
            rights_profile_record_id=UUID(int=1),
            source_snapshot_id=UUID(int=2),
            decision=_checked_decision(),
            context={"synthetic": True},
        )

    context = {"synthetic": True}
    existing = {
        "decision": "ALLOW",
        "reason_code": "synthetic authority",
        "context_sha256": repository_module.canonical_sha256(context),
        "rights_decision_id": UUID(int=11),
    }
    assert repository_module.record_rights_decision(
        _DbSession([None, existing]),  # type: ignore[arg-type]
        rights_profile_record_id=UUID(int=1),
        source_snapshot_id=None,
        decision=_checked_decision(),
        context=context,
    ) == UUID(int=11)
    with pytest.raises(IngestionError, match="stored rights decision conflicts"):
        repository_module.record_rights_decision(
            _DbSession([None, {**existing, "decision": "DENY"}]),  # type: ignore[arg-type]
            rights_profile_record_id=UUID(int=1),
            source_snapshot_id=None,
            decision=_checked_decision(),
            context=context,
        )


def test_ingestion_run_raw_content_and_processing_event_idempotency() -> None:
    provider_id = UUID(int=1)
    created_id = UUID(int=20)
    assert (
        repository_module.record_ingestion_run(
            _DbSession([created_id]),  # type: ignore[arg-type]
            provider_id=provider_id,
            pair_key="pair",
            started_at=NOW,
        )
        == created_id
    )

    expected_run = {
        "provider_id": provider_id,
        "resource": "bootstrap+fixtures",
        "logical_run_key": "fpl004:pair",
        "status": "RUNNING",
        "started_at": NOW,
        "adapter_version": "fpl-reference-v1",
        "code_commit": None,
        "counts": {"attempt_number": 1},
        "ingestion_run_id": UUID(int=21),
    }
    assert repository_module.record_ingestion_run(
        _DbSession([None, expected_run]),  # type: ignore[arg-type]
        provider_id=provider_id,
        pair_key="pair",
        started_at=NOW,
    ) == UUID(int=21)
    with pytest.raises(IngestionError, match="ingestion run identity conflicts"):
        repository_module.record_ingestion_run(
            _DbSession([None, {**expected_run, "resource": "conflict"}]),  # type: ignore[arg-type]
            provider_id=provider_id,
            pair_key="pair",
            started_at=NOW,
        )

    with pytest.raises(IngestionError, match="raw content identity conflicts"):
        repository_module.get_or_create_raw_content(
            _DbSession([None, {"raw_blob_id": UUID(int=30), "byte_size": 99}]),  # type: ignore[arg-type]
            b"synthetic",
        )

    existing_event = {
        "input_sha256": "a" * 64,
        "output_sha256": "b" * 64,
        "safe_details": {"synthetic": True},
        "error_code": None,
        "processing_event_id": UUID(int=40),
    }
    assert repository_module.append_processing_event_idempotent(
        _DbSession([UUID(int=2), existing_event]),  # type: ignore[arg-type]
        snapshot_id=UUID(int=2),
        stage="PARSED",
        event_at=NOW,
        input_sha256="a" * 64,
        output_sha256="b" * 64,
        safe_details={"synthetic": True},
    ) == UUID(int=40)
    with pytest.raises(IngestionError, match="processing stage was already recorded"):
        repository_module.append_processing_event_idempotent(
            _DbSession([UUID(int=2), {**existing_event, "output_sha256": "c" * 64}]),  # type: ignore[arg-type]
            snapshot_id=UUID(int=2),
            stage="PARSED",
            event_at=NOW,
            input_sha256="a" * 64,
            output_sha256="b" * 64,
            safe_details={"synthetic": True},
        )


def _snapshot_kwargs() -> dict[str, Any]:
    return {
        "provider_id": UUID(int=1),
        "ingestion_run_id": UUID(int=2),
        "attempt_number": 1,
        "resource": "odds",
        "captured_at": NOW,
        "body": None,
        "raw_blob_id": None,
        "raw_storage_object_id": None,
        "rights_profile_record_id": UUID(int=3),
        "profile": load_rights_profiles()["synthetic_the_odds_api_v1"],
        "sanitized_target": "fixture://synthetic/odds",
        "context": {"synthetic": True},
    }


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"request_started_at": NOW + timedelta(seconds=1)}, "request time"),
        ({"body": b"x", "body_sha256_override": "0" * 64}, "body hash"),
        ({"body": b"x", "body_size_override": 2}, "body size"),
        ({"body_sha256_override": "a" * 64}, "metadata is incomplete"),
        (
            {"body_sha256_override": "z" * 64, "body_size_override": 1},
            "metadata is invalid",
        ),
        (
            {"body_sha256_override": "a" * 64, "body_size_override": -1},
            "metadata is invalid",
        ),
        ({"http_status": 99}, "HTTP status"),
        ({"request_fingerprint_override": "bad"}, "fingerprint"),
    ),
)
def test_received_snapshot_rejects_contradictory_metadata_before_database(
    updates: dict[str, object],
    message: str,
) -> None:
    values = _snapshot_kwargs()
    values.update(updates)
    with pytest.raises(IngestionError, match=message):
        repository_module.record_received_snapshot(None, **values)  # type: ignore[arg-type]


def test_odds_service_bounded_read_and_contract_refusals(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OddsIngestionService(repository_root=repository_root)
    with pytest.raises(IngestionError) as missing:
        service.validate(tmp_path / "missing.json")
    assert missing.value.code == "FIXTURE_NOT_APPROVED"

    payload = tmp_path / "large.json"
    payload.write_bytes(b"[]")
    monkeypatch.setattr(service_module, "MAX_INPUT_BYTES", 1)
    with pytest.raises(IngestionError) as too_large:
        service.validate(payload)
    assert too_large.value.code == "PAYLOAD_TOO_LARGE"

    with pytest.raises(IngestionError) as unsupported:
        service.validate(payload, provider="unsupported")
    assert unsupported.value.code == "USAGE_INVALID"


def test_odds_replay_rejects_rights_and_invalid_scenario_before_database(
    repository_root: Path,
) -> None:
    fixture_set = repository_root / "fixtures/odds/ODD-005"
    service = OddsIngestionService(repository_root=repository_root)
    with pytest.raises(IngestionError) as rights:
        service.replay(
            OddsReplayRequest(
                fixture_set=fixture_set,
                scenario="happy_path",
                rights_profile_id="the_odds_api_private_analytics_v1",
            )
        )
    assert rights.value.code == "RIGHTS_BLOCKED"
    with pytest.raises(IngestionError) as scenario:
        service.replay(OddsReplayRequest(fixture_set=fixture_set, scenario="missing"))
    assert scenario.value.code == "FIXTURE_NOT_APPROVED"


def test_odds_manual_import_rejects_private_profile_before_fixture_access(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    request = OddsImportRequest(
        input_path=tmp_path / "unused.json",
        mapping_plan_path=tmp_path / "unused-mapping.json",
        captured_at=NOW,
        information_cutoff=NOW + timedelta(days=1),
        rights_profile_id="the_odds_api_private_analytics_v1",
    )
    with pytest.raises(IngestionError) as raised:
        OddsIngestionService(repository_root=repository_root).import_payload(request)
    assert raised.value.code == "RIGHTS_BLOCKED"
    assert raised.value.message == "manual odds import is not synthetic"


def test_seed_and_empty_attempt_invariants_fail_before_persistence(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingSeed:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def replay(self, _request: object) -> object:
            return SimpleNamespace(exit_code=2)

    monkeypatch.setattr(service_module, "FplIngestionService", FailingSeed)
    service = OddsIngestionService(repository_root=repository_root)
    with pytest.raises(IngestionError, match="seed is not usable"):
        service._seed_fpl_fixture(DATABASE_REF, NOW)
    with pytest.raises(IngestionError, match="transport evidence"):
        service._record_live_attempts(
            None,  # type: ignore[arg-type]
            profile=load_rights_profiles()["the_odds_api_private_analytics_v1"],
            attempts=(),
        )


def test_snapshot_invalid_options_and_quota_lookup_failure_remain_offline(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OddsIngestionService(repository_root=repository_root, clock=lambda: NOW)
    with pytest.raises(IngestionError) as invalid:
        service.snapshot(
            provider="unsupported",
            competition_key="PL",
            sport_key="soccer_epl",
            region="uk",
            market="h2h",
            as_of=NOW,
        )
    assert invalid.value.code == "USAGE_INVALID"

    monkeypatch.setattr(
        OddsIngestionService,
        "_latest_provider_quota",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic database")),
    )
    refused = service.snapshot(
        provider="the_odds_api",
        competition_key="PL",
        sport_key="soccer_epl",
        region="uk",
        market="h2h",
        as_of=NOW,
    )
    assert refused.exit_code == 4
    assert refused.result.error is not None
    assert refused.result.error.code.value == "CREDENTIAL_UNAVAILABLE"
    assert refused.result.error.transport_called is False

    credential_service = OddsIngestionService(
        repository_root=repository_root,
        credential_provider=StaticCredentialProvider(
            (repository_root / "fixtures/odds/ODD-005/security_fake_credential.txt")
            .read_text(encoding="utf-8")
            .strip()
        ),
        clock=lambda: NOW,
    )
    with pytest.raises(IngestionError) as database:
        credential_service.snapshot(
            provider="the_odds_api",
            competition_key="PL",
            sport_key="soccer_epl",
            region="uk",
            market="h2h",
            as_of=NOW,
        )
    assert database.value.code == "DATABASE_UNAVAILABLE"
    assert database.value.__context__ is None

    class ExplodingCredentialProvider:
        calls = 0

        def get_credential(self) -> str:
            self.calls += 1
            raise RuntimeError("ODD005_CREDENTIAL_EXCEPTION_CANARY")

    exploding = ExplodingCredentialProvider()
    exception_service = OddsIngestionService(
        repository_root=repository_root,
        credential_provider=exploding,
        clock=lambda: NOW,
    )
    with pytest.raises(IngestionError) as safe_database:
        exception_service.snapshot(
            provider="the_odds_api",
            competition_key="PL",
            sport_key="soccer_epl",
            region="uk",
            market="h2h",
            as_of=NOW,
        )
    assert safe_database.value.code == "DATABASE_UNAVAILABLE"
    assert safe_database.value.__context__ is None
    assert "CANARY" not in repr(safe_database.value)
    assert exploding.calls == 0
