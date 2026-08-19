"""Provider-native response, temporal, and rights oracles for live odds."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.current import build_current_odds_input
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload

pytestmark = pytest.mark.unit

RECEIVED = datetime(2026, 8, 20, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
SOURCE_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000913")
SANITIZED_TARGET = (
    "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?"
    "regions=uk&markets=h2h&oddsFormat=decimal&dateFormat=iso&commenceTimeFrom="
    "2026-08-21T17%3A30%3A00Z"
)


def _fixture(repository_root: Path) -> bytes:
    return (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes()


def _value(repository_root: Path) -> list[dict[str, Any]]:
    value = json.loads(_fixture(repository_root))
    assert isinstance(value, list)
    return value


def _body(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":")).encode()


def _build_from_value(
    repository_root: Path,
    value: object,
    *,
    received_at: datetime = RECEIVED,
    usable_at: datetime = RECEIVED + timedelta(seconds=1),
    last_cost: int = 1,
    quota_source: QuotaSource = QuotaSource.RESPONSE_HEADERS,
    sanitized_target: str = SANITIZED_TARGET,
):
    parsed = parse_odds_payload(_body(value))
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    return build_current_odds_input(
        parsed,
        profile=profile,
        source_snapshot_id=SOURCE_SNAPSHOT_ID,
        request_started_at=received_at - timedelta(seconds=1),
        received_at=received_at,
        information_cutoff=CUTOFF,
        usable_at=usable_at,
        quota=QuotaState(
            remaining=499,
            used=max(last_cost, 1),
            last_cost=last_cost,
            observed_at=received_at,
            source=quota_source,
        ),
        request_fingerprint="1" * 64,
        sanitized_target=sanitized_target,
        attempt_count=1,
        transport_call_count=1,
        provider_request_id_sha256="2" * 64,
    )


def test_valid_epl_h2h_response_builds_provider_native_unmapped_contract(
    repository_root: Path,
) -> None:
    current = _build_from_value(repository_root, _value(repository_root))

    assert current.contract == "ODDS_PROVIDER_CURRENT_INPUT"
    assert current.identity_scope == "PROVIDER_NATIVE_UNMAPPED"
    assert current.provider == "the_odds_api"
    assert current.sport_key == "soccer_epl"
    assert current.region == "uk"
    assert current.market == "h2h"
    assert current.events[0].provider_event_id == "todapi-event-001"
    assert current.events[0].provider_home_team == "Alpha Athletic"
    assert current.events[0].provider_away_team == "Beta Borough"
    assert [item.outcome for item in current.events[0].bookmakers[0].markets[0].outcomes] == [
        "HOME",
        "DRAW",
        "AWAY",
    ]
    assert current.temporal.received_at == RECEIVED
    assert current.temporal.captured_at == RECEIVED
    assert current.temporal.information_cutoff == CUTOFF
    assert current.temporal.provider_response_generated_at is None
    assert current.temporal.provider_response_generated_at_state == "NOT_PUBLISHED"
    assert current.provenance.canonical_fpl_fixture_mapping_performed is False
    assert current.provenance.raw_payload_retained is False
    assert current.provenance.sanitized_target == SANITIZED_TARGET
    assert "apiKey" not in current.model_dump_json()


def test_current_rights_preserve_declared_unknowns_and_effective_denials(
    repository_root: Path,
) -> None:
    rights = _build_from_value(repository_root, _value(repository_root)).rights

    assert rights.automated_access_declared == "ALLOW"
    assert rights.automated_access == "ALLOW"
    assert rights.derived_storage_declared == "ALLOW"
    assert rights.derived_storage == "ALLOW"
    assert rights.raw_storage_declared == "UNKNOWN"
    assert rights.raw_storage == "DENY"
    assert rights.public_display_declared == "DENY"
    assert rights.public_display == "DENY"
    assert rights.redistribution_declared == "DENY"
    assert rights.redistribution == "DENY"
    assert rights.backup_declared == "UNKNOWN"
    assert rights.backup == "DENY"
    assert rights.model_training_declared == "UNKNOWN"
    assert rights.model_training == "DENY"
    assert rights.raw_retention_seconds == 0
    assert rights.raw_payload_retained is False


@pytest.mark.parametrize(
    ("mutation", "blocker"),
    (
        (lambda value: value.clear(), "EMPTY_PROVIDER_RESPONSE"),
        (lambda value: value[0].__setitem__("bookmakers", []), "BOOKMAKER_MISSING"),
        (
            lambda value: value[0]["bookmakers"][0]["markets"][0].__setitem__("key", "totals"),
            "UNSUPPORTED_MARKET",
        ),
        (
            lambda value: value[0]["bookmakers"][0]["markets"][0]["outcomes"].pop(1),
            "THREE_WAY_H2H_INCOMPLETE",
        ),
        (
            lambda value: value[0]["bookmakers"][0]["markets"][0]["outcomes"][0].__setitem__(
                "point", 0.5
            ),
            "LINE_BEARING_H2H_OUTCOME",
        ),
        (
            lambda value: value[0].__setitem__("commence_time", "2026-08-21T12:00:00Z"),
            "EVENT_NOT_PREMATCH_AT_CUTOFF",
        ),
        (
            lambda value: value[0]["bookmakers"][0].__setitem__(
                "last_update", "2026-08-20T12:01:00Z"
            ),
            "PROVIDER_TIMESTAMP_AFTER_RECEIPT",
        ),
        (
            lambda value: value[0]["bookmakers"][0]["markets"][0].__setitem__(
                "last_update", "2026-08-20T12:00:30Z"
            ),
            "PROVIDER_TIMESTAMP_AFTER_RECEIPT",
        ),
        (
            lambda value: value[0].__setitem__("api" + "Key", "unexpected-sensitive-value"),
            "SECRET_LIKE_PROVIDER_FIELD",
        ),
    ),
)
def test_decision_critical_provider_payload_failures_block(
    repository_root: Path,
    mutation: Callable[[list[dict[str, Any]]], object],
    blocker: str,
) -> None:
    value = _value(repository_root)
    mutation(value)
    with pytest.raises(IngestionError) as raised:
        _build_from_value(repository_root, value)
    assert raised.value.code == "QUALITY_BLOCKED"
    assert blocker in raised.value.details["blockers"]


def test_builder_rejects_duplicate_provider_event_identity(repository_root: Path) -> None:
    parsed = parse_odds_payload(_fixture(repository_root))
    duplicated = replace(parsed, events=(parsed.events[0], parsed.events[0]))
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]

    with pytest.raises(IngestionError) as raised:
        build_current_odds_input(
            duplicated,
            profile=profile,
            source_snapshot_id=SOURCE_SNAPSHOT_ID,
            request_started_at=RECEIVED - timedelta(seconds=1),
            received_at=RECEIVED,
            information_cutoff=CUTOFF,
            usable_at=RECEIVED + timedelta(seconds=1),
            quota=QuotaState(
                remaining=499,
                used=1,
                last_cost=1,
                observed_at=RECEIVED,
                source=QuotaSource.RESPONSE_HEADERS,
            ),
            request_fingerprint="1" * 64,
            sanitized_target=SANITIZED_TARGET,
            attempt_count=1,
            transport_call_count=1,
            provider_request_id_sha256="2" * 64,
        )

    assert raised.value.code == "QUALITY_BLOCKED"
    assert "DUPLICATE_PROVIDER_EVENT_ID" in raised.value.details["blockers"]


def test_equal_duplicate_outcome_is_not_accepted_as_current(repository_root: Path) -> None:
    value = _value(repository_root)
    outcomes = value[0]["bookmakers"][0]["markets"][0]["outcomes"]
    outcomes.append(dict(outcomes[1]))
    with pytest.raises(IngestionError) as raised:
        _build_from_value(repository_root, value)
    assert raised.value.code == "QUALITY_BLOCKED"
    assert "DUPLICATE_OUTCOME" in raised.value.details["blockers"]


def test_post_cutoff_receipt_or_validation_is_rejected(repository_root: Path) -> None:
    value = _value(repository_root)
    with pytest.raises(IngestionError) as received:
        _build_from_value(repository_root, value, received_at=CUTOFF + timedelta(seconds=1))
    assert received.value.code == "POST_CUTOFF"

    with pytest.raises(IngestionError) as usable:
        _build_from_value(repository_root, value, usable_at=CUTOFF + timedelta(seconds=1))
    assert usable.value.code == "POST_CUTOFF"


def test_non_provider_quota_source_is_quality_blocked(repository_root: Path) -> None:
    with pytest.raises(IngestionError) as raised:
        _build_from_value(
            repository_root,
            _value(repository_root),
            quota_source=QuotaSource.SYNTHETIC_FIXTURE,
        )
    assert raised.value.code == "QUALITY_BLOCKED"
    assert raised.value.details["blockers"] == ["QUOTA_SOURCE_INVALID"]


def test_provider_request_cost_mismatch_is_quality_blocked(repository_root: Path) -> None:
    with pytest.raises(IngestionError) as raised:
        _build_from_value(repository_root, _value(repository_root), last_cost=2)
    assert raised.value.code == "QUALITY_BLOCKED"
    assert raised.value.details["blockers"] == ["QUOTA_REQUEST_COST_MISMATCH"]


def test_timezone_naive_provider_timestamp_is_rejected_by_reference_parser(
    repository_root: Path,
) -> None:
    value = _value(repository_root)
    value[0]["bookmakers"][0]["last_update"] = "2026-08-20T11:59:00"
    with pytest.raises(IngestionError) as raised:
        parse_odds_payload(_body(value))
    assert raised.value.code == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    "target",
    (
        "http://api.the-odds-api.com/v4/sports/soccer_epl/odds?regions=uk",
        "https://unapproved.example/v4/sports/soccer_epl/odds?regions=uk",
        (
            "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?"
            "regions=uk&markets=h2h&oddsFormat=decimal&dateFormat=iso&"
            "commenceTimeFrom=2026-08-21T17%3A30%3A00Z&unexpected=1"
        ),
    ),
)
def test_output_provenance_rejects_unsafe_or_unapproved_target(
    repository_root: Path,
    target: str,
) -> None:
    with pytest.raises(ValueError):
        _build_from_value(repository_root, _value(repository_root), sanitized_target=target)
