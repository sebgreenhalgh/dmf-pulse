"""PostgreSQL proof for the provider-native live odds current-input path."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.tables import (
    data_provider,
    odds_observation,
    operator_market_observation,
    provider_quota_observation,
    raw_blob,
    raw_storage_object,
    rights_decision,
    source_processing_event,
    source_snapshot,
)
from dmf_pulse.ingestion.fpl.service import DATABASE_REF
from dmf_pulse.ingestion.odds.client import (
    OddsHttpRequest,
    OddsHttpResponse,
    StaticCredentialProvider,
)
from dmf_pulse.ingestion.odds.live import LiveOddsSnapshotService

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]

RECEIVED = datetime(2026, 8, 20, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
DUMMY_RUNTIME_VALUE = "dummy-live-odds-key-1234567890"


class _Transport:
    def __init__(self, response: OddsHttpResponse) -> None:
        self.response = response
        self.requests: list[OddsHttpRequest] = []

    def send(self, request: OddsHttpRequest) -> OddsHttpResponse:
        self.requests.append(request)
        return self.response


def _count(session: Session, table: object) -> int:
    query = select(func.count()).select_from(table)  # type: ignore[arg-type]
    return int(session.scalar(query) or 0)


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

    outcome = service.snapshot(
        provider="the_odds_api",
        competition_key="PL",
        sport_key="soccer_epl",
        region="uk",
        market="h2h",
        as_of=CUTOFF,
        database_url_ref=DATABASE_REF,
    )

    assert outcome.exit_code == 0
    assert outcome.result.status == "COMPLETE"
    assert outcome.result.current_input is not None
    assert outcome.result.current_input.identity_scope == "PROVIDER_NATIVE_UNMAPPED"
    assert outcome.result.current_input.provenance.raw_payload_retained is False
    assert outcome.result.current_input.provenance.canonical_fpl_fixture_mapping_performed is False
    assert len(transport.requests) == 1
    assert transport.requests[0].credential == DUMMY_RUNTIME_VALUE
    assert DUMMY_RUNTIME_VALUE not in outcome.result.model_dump_json()

    snapshot_id = outcome.result.source_snapshot_id
    assert snapshot_id is not None
    with postgres_session_factory() as session:
        snapshot = (
            session.execute(
                select(source_snapshot).where(source_snapshot.c.source_snapshot_id == snapshot_id)
            )
            .mappings()
            .one()
        )
        assert snapshot["raw_storage_policy"] == "FORBIDDEN"
        assert snapshot["raw_blob_id"] is None
        assert snapshot["raw_storage_object_id"] is None
        assert snapshot["body_sha256"] is not None
        assert snapshot["body_size"] == len(body)
        assert snapshot["validation_status"] == "RECEIVED"
        assert snapshot["dataset_mode"] == "RAW_OBSERVED"
        assert snapshot["parsed_at"] is None
        assert snapshot["usable_at"] is None
        assert "apiKey" not in snapshot["sanitized_target"]
        assert DUMMY_RUNTIME_VALUE not in snapshot["sanitized_target"]

        provider_key = session.scalar(
            select(data_provider.c.provider_key).where(
                data_provider.c.provider_id == snapshot["provider_id"]
            )
        )
        assert provider_key == "the_odds_api"

        stages = list(
            session.scalars(
                select(source_processing_event.c.stage)
                .where(source_processing_event.c.source_snapshot_id == snapshot_id)
                .order_by(source_processing_event.c.sequence_number)
            )
        )
        assert stages == [
            "RECEIVED",
            "RAW_DISCARDED",
            "PARSED",
            "VALIDATED",
            "MAPPED",
            "PROMOTED",
            "QUALITY_PASSED",
            "USABLE",
        ]

        decisions = set(
            session.scalars(
                select(rights_decision.c.capability).where(
                    rights_decision.c.source_snapshot_id == snapshot_id
                )
            )
        )
        assert {
            "automated_access",
            "transient_processing",
            "raw_storage",
            "derived_storage",
            "private_internal_use",
            "public_display",
            "redistribution",
            "backup",
            "model_training",
        }.issubset(decisions)

        quota = (
            session.execute(
                select(provider_quota_observation).where(
                    provider_quota_observation.c.source_snapshot_id == snapshot_id
                )
            )
            .mappings()
            .one()
        )
        assert quota["remaining"] == 499
        assert quota["used"] == 1
        assert quota["last_cost"] == 1

        lifecycle = session.execute(
            text(
                "SELECT current_state, usable_at "
                "FROM provenance.source_snapshot_lifecycle "
                "WHERE source_snapshot_id = :snapshot_id"
            ),
            {"snapshot_id": snapshot_id},
        ).one()
        assert lifecycle.current_state == "USABLE"
        assert lifecycle.usable_at == RECEIVED + timedelta(seconds=1)

        assert _count(session, raw_blob) == 0
        assert _count(session, raw_storage_object) == 0
        assert _count(session, operator_market_observation) == 0
        assert _count(session, odds_observation) == 0
