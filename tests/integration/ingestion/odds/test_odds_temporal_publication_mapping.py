"""NRM-006 post-commit publication and strict temporal-mapping canaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import insert, select
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.data_model.tables import (
    data_provider,
    entity_alias,
    fixture,
    fixture_observation,
    odds_observation,
    odds_publication_attestation,
    odds_publication_batch,
    operator_market_observation,
    source_processing_event,
    source_snapshot,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.persistence import FplPersistence
from dmf_pulse.ingestion.fpl.service import (
    DATABASE_REF,
    FplImportRequest,
    FplIngestionService,
)
from dmf_pulse.ingestion.odds.mapping import load_mapping_plan
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.ingestion.odds.persistence import OddsPersistence
from dmf_pulse.ingestion.odds.service import OddsImportRequest, OddsIngestionService
from dmf_pulse.markets.service import MarketService

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

CANARY_ROOT = Path("fixtures/odds/NRM-006")
ODDS_ROOT = Path("fixtures/odds/ODD-005")
FPL_ROOT = Path("fixtures/fpl/FPL-004/happy_path")
MAPPING_APPROVED_AT = datetime(2026, 8, 1, tzinfo=UTC)


class _OneShotClock:
    def __init__(self, values: list[datetime]) -> None:
        self._values = iter(values)
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        try:
            return next(self._values)
        except StopIteration:
            raise AssertionError("scripted UTC clock was sampled too many times") from None


def _load_json(root: Path, relative_path: Path) -> dict[str, Any]:
    value = json.loads((root / relative_path).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _instant(value: object) -> datetime:
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    return parsed.astimezone(UTC)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _seed_fpl(
    root: Path,
    *,
    captured_at: datetime,
    information_cutoff: datetime,
) -> dict[str, UUID]:
    outcome = FplIngestionService(
        repository_root=root,
        clock=lambda: captured_at,
    ).import_pair(
        FplImportRequest(
            bootstrap_path=root / FPL_ROOT / "bootstrap.json",
            fixtures_path=root / FPL_ROOT / "fixtures.json",
            competition_key="SYNTHETIC_PL",
            season_code="2026/27",
            captured_at=captured_at,
            information_cutoff=information_cutoff,
            rights_profile_id="synthetic_test_v1",
            database_url_ref=DATABASE_REF,
        )
    )
    assert outcome.exit_code == 0
    assert outcome.result.status == "USABLE"
    snapshots = {
        resource.resource: resource.source_snapshot_id for resource in outcome.result.resources
    }
    assert set(snapshots) == {"bootstrap", "fixtures"}
    return snapshots


def _market_projection(as_of: datetime) -> dict[str, Any]:
    return (
        MarketService()
        .observations(
            fixture_external_provider="synthetic_fpl",
            fixture_external_id="101",
            season_code="2026/27",
            as_of=as_of,
            database_url_ref=DATABASE_REF,
        )
        .model_dump(mode="json")
    )


def test_receipt_before_cutoff_is_excluded_when_post_commit_attestation_is_late(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    fixture_canary = _load_json(
        repository_root,
        CANARY_ROOT / "processing_crosses_cutoff.json",
    )
    expected = _load_json(
        repository_root,
        CANARY_ROOT / "expected_outputs/processing_crosses_cutoff.json",
    )
    received_at = _instant(fixture_canary["received_at"])
    information_cutoff = _instant(fixture_canary["information_cutoff"])
    usable_sequence = fixture_canary["post_commit_usable_clock_sequence"]
    assert isinstance(usable_sequence, list) and len(usable_sequence) == 1
    post_commit_usable_at = _instant(usable_sequence[0])
    _seed_fpl(
        repository_root,
        captured_at=MAPPING_APPROVED_AT,
        information_cutoff=information_cutoff,
    )
    processing_clock = _OneShotClock([received_at])
    publication_clock = _OneShotClock([post_commit_usable_at])
    service = OddsIngestionService(
        repository_root=repository_root,
        processing_clock=processing_clock,
        clock=publication_clock,
    )

    outcome = service.import_payload(
        OddsImportRequest(
            input_path=repository_root / ODDS_ROOT / "happy_path.json",
            mapping_plan_path=repository_root / ODDS_ROOT / "mapping_plan.json",
            captured_at=received_at,
            information_cutoff=information_cutoff,
            rights_profile_id="synthetic_the_odds_api_v1",
            database_url_ref=DATABASE_REF,
        )
    )

    assert outcome.exit_code == 2
    assert outcome.result.status == fixture_canary["expected_status"]
    assert outcome.result.status == expected["status"]
    assert outcome.result.observations_created == 6
    assert "POST_CUTOFF" in outcome.result.quality.warnings
    assert processing_clock.calls == publication_clock.calls == 1
    assert _market_projection(information_cutoff)["observation_count"] == 0
    assert _market_projection(post_commit_usable_at)["observation_count"] == 6
    assert fixture_canary["expected_eligible_before_cutoff"] is False

    snapshot_id = outcome.result.source_snapshot_id
    assert snapshot_id is not None
    with postgres_session_factory() as session:
        publication = (
            session.execute(
                select(
                    source_snapshot.c.received_at,
                    odds_publication_batch.c.publication_batch_id,
                    odds_publication_batch.c.mapping_cutoff,
                    odds_publication_batch.c.mapping_plan_approved_at,
                    odds_publication_batch.c.activation_xid,
                    odds_publication_attestation.c.usable_at,
                    odds_publication_attestation.c.attestation_xid,
                )
                .join(
                    odds_publication_batch,
                    odds_publication_batch.c.source_snapshot_id
                    == source_snapshot.c.source_snapshot_id,
                )
                .join(
                    odds_publication_attestation,
                    odds_publication_attestation.c.publication_batch_id
                    == odds_publication_batch.c.publication_batch_id,
                )
                .where(source_snapshot.c.source_snapshot_id == snapshot_id)
            )
            .mappings()
            .one()
        )
        activation_at = session.scalar(
            select(source_processing_event.c.event_at).where(
                source_processing_event.c.source_snapshot_id == snapshot_id,
                source_processing_event.c.stage == "USABLE",
            )
        )
        book_rows = session.execute(
            select(
                operator_market_observation.c.publication_batch_id,
                operator_market_observation.c.usable_at,
            ).where(operator_market_observation.c.source_snapshot_id == snapshot_id)
        ).all()
        quote_rows = session.execute(
            select(
                odds_observation.c.publication_batch_id,
                odds_observation.c.usable_at,
            ).where(odds_observation.c.source_snapshot_id == snapshot_id)
        ).all()

    assert publication["received_at"] == received_at
    assert activation_at == received_at
    assert publication["mapping_cutoff"] == information_cutoff
    assert publication["mapping_plan_approved_at"] == MAPPING_APPROVED_AT
    assert publication["usable_at"] == post_commit_usable_at
    assert publication["activation_xid"] != publication["attestation_xid"]
    assert len(book_rows) == 2 and len(quote_rows) == 6
    assert all(row.publication_batch_id == publication["publication_batch_id"] for row in book_rows)
    assert all(
        row.publication_batch_id == publication["publication_batch_id"] for row in quote_rows
    )
    assert all(row.usable_at is None for row in (*book_rows, *quote_rows))
    observed_oracle = {
        "status": outcome.result.status,
        "received_at": _rfc3339(received_at),
        "activation_transaction_outcome": "COMMITTED",
        "usable_at": _rfc3339(publication["usable_at"]),
        "usable_at_source": "POST_COMMIT_ATTESTATION",
        "attestation_outcome": "COMMITTED",
        "information_cutoff": _rfc3339(information_cutoff),
        "eligible_before_cutoff": False,
    }
    assert observed_oracle == expected


def test_future_mapping_alias_and_kickoff_cannot_change_earlier_strict_replay(
    repository_root: Path,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    canary = _load_json(
        repository_root,
        CANARY_ROOT / "future_mapping_canaries.json",
    )
    expected = _load_json(
        repository_root,
        CANARY_ROOT / "expected_outputs/future_mapping_canaries.json",
    )
    mapping_cutoff = _instant(canary["mapping_cutoff"])
    initial_kickoff = _instant(canary["initial_fixture_kickoff"])
    future_mapping_at = _instant(canary["future_mapping_approved_at"])
    future_alias_at = _instant(canary["future_alias_system_from"])
    future_fixture_usable_at = _instant(canary["future_fixture_correction_usable_at"])
    future_kickoff = _instant(canary["future_fixture_kickoff"])
    _seed_fpl(
        repository_root,
        captured_at=MAPPING_APPROVED_AT,
        information_cutoff=mapping_cutoff,
    )
    processing_clock = _OneShotClock([mapping_cutoff - timedelta(seconds=20)])
    publication_clock = _OneShotClock([mapping_cutoff - timedelta(seconds=10)])
    odds_outcome = OddsIngestionService(
        repository_root=repository_root,
        processing_clock=processing_clock,
        clock=publication_clock,
    ).import_payload(
        OddsImportRequest(
            input_path=repository_root / ODDS_ROOT / "happy_path.json",
            mapping_plan_path=repository_root / ODDS_ROOT / "mapping_plan.json",
            captured_at=mapping_cutoff - timedelta(seconds=30),
            information_cutoff=mapping_cutoff,
            rights_profile_id="synthetic_the_odds_api_v1",
            database_url_ref=DATABASE_REF,
        )
    )
    assert odds_outcome.exit_code == 0
    assert processing_clock.calls == publication_clock.calls == 1
    before = _market_projection(mapping_cutoff)
    assert before["observation_count"] == 6

    alias_capture = future_alias_at - timedelta(microseconds=11)
    alias_snapshots = _seed_fpl(
        repository_root,
        captured_at=alias_capture,
        information_cutoff=future_alias_at + timedelta(seconds=1),
    )
    correction_capture = future_fixture_usable_at - timedelta(microseconds=12)
    correction_snapshots = _seed_fpl(
        repository_root,
        captured_at=correction_capture,
        information_cutoff=future_fixture_usable_at + timedelta(seconds=1),
    )
    parsed = parse_odds_payload((repository_root / ODDS_ROOT / "happy_path.json").read_bytes())
    mapping_plan = load_mapping_plan(repository_root / ODDS_ROOT / "mapping_plan.json")
    odds_snapshot_id = odds_outcome.result.source_snapshot_id
    assert odds_snapshot_id is not None
    future_alias = "Alpha Athletic (future canary)"

    with postgres_session_factory.begin() as session:
        fixture_row = session.execute(select(fixture)).mappings().one()
        home_team_id = fixture_row["home_team_id"]
        provider_id = session.scalar(
            select(data_provider.c.provider_id).where(
                data_provider.c.provider_key == "synthetic_fpl"
            )
        )
        assert isinstance(home_team_id, UUID) and isinstance(provider_id, UUID)
        alias_persistence = FplPersistence(
            session,
            captured_at=alias_capture,
            system_at=future_alias_at,
            competition_key="SYNTHETIC_PL",
            season_code="2026/27",
            bootstrap_snapshot_id=alias_snapshots["bootstrap"],
            fixtures_snapshot_id=alias_snapshots["fixtures"],
        )
        alias_persistence._ensure_alias(
            entity_id=home_team_id,
            raw_text=future_alias,
            alias_type="OFFICIAL",
            provider_id=provider_id,
            snapshot_id=alias_snapshots["bootstrap"],
        )
        future_alias_row = (
            session.execute(select(entity_alias).where(entity_alias.c.raw_text == future_alias))
            .mappings()
            .one()
        )
        assert future_alias_row["system_during"].lower == future_alias_at

        source_correction = (
            session.execute(
                select(fixture_observation)
                .where(fixture_observation.c.fixture_id == fixture_row["fixture_id"])
                .order_by(fixture_observation.c.usable_at)
                .limit(1)
            )
            .mappings()
            .one()
        )
        correction_source_usable_at = session.scalar(
            select(source_processing_event.c.event_at).where(
                source_processing_event.c.source_snapshot_id == correction_snapshots["fixtures"],
                source_processing_event.c.stage == "USABLE",
            )
        )
        assert correction_source_usable_at == future_fixture_usable_at
        correction_values = dict(source_correction)
        correction_values.pop("fixture_observation_id")
        correction_values["kickoff_at"] = future_kickoff
        correction_values["observed_at"] = correction_capture
        correction_values["received_at"] = correction_capture
        correction_values["usable_at"] = future_fixture_usable_at
        correction_values["source_snapshot_id"] = correction_snapshots["fixtures"]
        correction_values["semantic_sha256"] = canonical_sha256(
            {
                "prior_semantic_sha256": source_correction["semantic_sha256"],
                "synthetic_future_kickoff": _rfc3339(future_kickoff),
            }
        )
        session.execute(insert(fixture_observation).values(**correction_values))

    profile_record_id: UUID
    with postgres_session_factory.begin() as session:
        profile_record_id = session.scalar(
            select(source_snapshot.c.rights_profile_record_id).where(
                source_snapshot.c.source_snapshot_id == odds_snapshot_id
            )
        )
        assert isinstance(profile_record_id, UUID)
        future_plan = mapping_plan.model_copy(update={"approved_at": future_mapping_at})
        with pytest.raises(IngestionError) as mapping_failure:
            OddsPersistence(
                session,
                snapshot_id=odds_snapshot_id,
                rights_profile_record_id=profile_record_id,
                captured_at=mapping_cutoff - timedelta(seconds=30),
                mapping_cutoff=mapping_cutoff,
                mapping_plan=future_plan,
            )
        assert mapping_failure.value.code == "MAPPING_CONFLICT"

        strict_persistence = OddsPersistence(
            session,
            snapshot_id=odds_snapshot_id,
            rights_profile_record_id=profile_record_id,
            captured_at=mapping_cutoff - timedelta(seconds=30),
            mapping_cutoff=mapping_cutoff,
            mapping_plan=mapping_plan,
        )
        future_alias_event = parsed.events[0].model_copy(update={"home_team": future_alias})
        with pytest.raises(IngestionError) as alias_failure:
            strict_persistence.resolve_fixture(future_alias_event)
        assert alias_failure.value.code == "MAPPING_CONFLICT"
        strict_fixture = strict_persistence.resolve_fixture(parsed.events[0])

    after = _market_projection(mapping_cutoff)
    assert json.dumps(after, sort_keys=True, separators=(",", ":")) == json.dumps(
        before,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert strict_fixture.kickoff_at == initial_kickoff
    assert canary["expected_strict_mapping_resolved"] is False
    observed_oracle = {
        "mapping_cutoff": _rfc3339(mapping_cutoff),
        "strict_mapping_resolved": False,
        "strict_fixture_kickoff": _rfc3339(strict_fixture.kickoff_at),
        "future_state_used": False,
    }
    assert observed_oracle == expected
