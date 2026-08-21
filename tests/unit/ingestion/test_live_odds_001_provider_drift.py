"""LIVE-ODDS-001 provider-drift, cutoff, rights, and provenance contract."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput, build_current_odds_input
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import ParsedOddsPayload, parse_odds_payload

pytestmark = pytest.mark.unit

RECEIVED = datetime(2026, 8, 20, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
SOURCE_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000913")
SANITIZED_TARGET = (
    "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?"
    "regions=uk&markets=h2h%2Ctotals&oddsFormat=decimal&dateFormat=iso&commenceTimeFrom="
    "2026-08-21T17%3A30%3A00Z"
)


def _value(repository_root: Path) -> list[dict[str, Any]]:
    value = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, list)
    return value


def _body(value: object, *, sort_keys: bool = False) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=sort_keys,
    ).encode()


def _append_totals(value: list[dict[str, Any]]) -> None:
    for index, bookmaker in enumerate(value[0]["bookmakers"]):
        bookmaker["markets"].append(
            {
                "key": "totals",
                "last_update": bookmaker["last_update"],
                "outcomes": [
                    {"name": "Over", "price": 1.8 + index / 100, "point": 2.5},
                    {"name": "Under", "price": 2.1 - index / 100, "point": 2.5},
                ],
            }
        )


def _append_additive_market(
    value: list[dict[str, Any]],
    key: str,
    *,
    outcomes: list[dict[str, Any]] | None = None,
) -> None:
    for bookmaker in value[0]["bookmakers"]:
        bookmaker["markets"].append(
            {
                "key": key,
                "last_update": bookmaker["last_update"],
                "outcomes": (
                    [{"name": "provider-only", "price": 1.91}]
                    if outcomes is None
                    else deepcopy(outcomes)
                ),
            }
        )


def _build(
    parsed: ParsedOddsPayload,
    *,
    received_at: datetime = RECEIVED,
    usable_at: datetime = RECEIVED + timedelta(seconds=1),
) -> OddsProviderCurrentInput:
    return build_current_odds_input(
        parsed,
        profile=load_rights_profiles()["the_odds_api_private_analytics_v1"],
        source_snapshot_id=SOURCE_SNAPSHOT_ID,
        request_started_at=received_at - timedelta(seconds=1),
        received_at=received_at,
        information_cutoff=CUTOFF,
        usable_at=usable_at,
        quota=QuotaState(
            remaining=498,
            used=2,
            last_cost=2,
            observed_at=received_at,
            source=QuotaSource.RESPONSE_HEADERS,
        ),
        request_fingerprint="1" * 64,
        sanitized_target=SANITIZED_TARGET,
        attempt_count=1,
        transport_call_count=1,
        transport_id="stdlib_http_client",
        provider_request_id_sha256="2" * 64,
    )


def _blocked(value: object, expected: str) -> None:
    with pytest.raises(IngestionError) as raised:
        _build(parse_odds_payload(_body(value)))
    assert raised.value.code == "QUALITY_BLOCKED"
    assert expected in raised.value.details["blockers"]


def test_pd01_valid_h2h_preserves_explicit_totals_missingness(repository_root: Path) -> None:
    current = _build(parse_odds_payload(_body(_value(repository_root))))

    assert current.quality.status == "WARNING"
    assert current.quality.warnings == ("TOTALS_MISSING",)
    assert current.quality.additive_unsupported_markets == ()
    assert all(bookmaker.totals_markets == () for bookmaker in current.events[0].bookmakers)


def test_pd02_valid_h2h_and_totals_pass(repository_root: Path) -> None:
    value = _value(repository_root)
    _append_totals(value)

    current = _build(parse_odds_payload(_body(value)))

    assert current.quality.status == "PASS"
    assert current.quality.warnings == ()
    assert all(bookmaker.totals_markets for bookmaker in current.events[0].bookmakers)


@pytest.mark.parametrize("market_key", ("h2h_lay", "future_provider_market_913"))
def test_pd03_pd04_known_or_unknown_additive_market_warns_without_blocking(
    repository_root: Path,
    market_key: str,
) -> None:
    value = _value(repository_root)
    _append_totals(value)
    _append_additive_market(value, market_key)

    current = _build(parse_odds_payload(_body(value)))

    assert current.quality.status == "WARNING"
    assert current.quality.additive_unsupported_markets == (market_key,)
    assert f"ADDITIVE_UNSUPPORTED_MARKET:{market_key}" in current.quality.warnings
    assert {
        market.market_key
        for event in current.events
        for bookmaker in event.bookmakers
        for market in (*bookmaker.markets, *bookmaker.totals_markets)
    } == {"h2h", "totals"}


def test_pd05_multiple_additive_markets_are_unique_and_sorted(repository_root: Path) -> None:
    value = _value(repository_root)
    _append_totals(value)
    for key in ("zeta_future", "h2h_lay", "zeta_future"):
        if key == "zeta_future" and any(
            market["key"] == key for market in value[0]["bookmakers"][0]["markets"]
        ):
            continue
        _append_additive_market(value, key)

    current = _build(parse_odds_payload(_body(value)))

    assert current.quality.additive_unsupported_markets == ("h2h_lay", "zeta_future")
    assert tuple(
        warning
        for warning in current.quality.warnings
        if warning.startswith("ADDITIVE_UNSUPPORTED_MARKET:")
    ) == (
        "ADDITIVE_UNSUPPORTED_MARKET:h2h_lay",
        "ADDITIVE_UNSUPPORTED_MARKET:zeta_future",
    )


def test_pd06_source_hash_changes_but_supported_semantics_do_not(repository_root: Path) -> None:
    supported = _value(repository_root)
    _append_totals(supported)
    additive = deepcopy(supported)
    _append_additive_market(additive, "h2h_lay")

    parsed_supported = parse_odds_payload(_body(supported))
    parsed_additive = parse_odds_payload(_body(additive))
    current_supported = _build(parsed_supported)
    current_additive = _build(parsed_additive)

    assert parsed_supported.body_sha256 != parsed_additive.body_sha256
    assert current_supported.provenance.response_body_sha256 != (
        current_additive.provenance.response_body_sha256
    )
    assert current_supported.events == current_additive.events
    assert current_supported.market_semantic_sha256 == current_additive.market_semantic_sha256


def test_pd07_structurally_isolatable_malformed_additive_market_is_excluded(
    repository_root: Path,
) -> None:
    value = _value(repository_root)
    _append_totals(value)
    _append_additive_market(value, "future_empty_market", outcomes=[])

    current = _build(parse_odds_payload(_body(value)))

    assert current.quality.additive_unsupported_markets == ("future_empty_market",)
    assert all(
        market.market_key != "future_empty_market"
        for bookmaker in current.events[0].bookmakers
        for market in (*bookmaker.markets, *bookmaker.totals_markets)
    )


def test_pd08_secret_like_unexpected_material_remains_blocking(repository_root: Path) -> None:
    sentinel = "fixture-secret-sentinel-913"
    value = _value(repository_root)
    _append_totals(value)
    _append_additive_market(value, "future_market")
    value[0]["bookmakers"][0]["markets"][-1]["apiKey"] = sentinel

    parsed = parse_odds_payload(_body(value))
    assert sentinel not in repr(parsed)
    assert sentinel not in parsed.events[0].model_dump_json()

    with pytest.raises(IngestionError) as raised:
        _build(parsed)

    assert raised.value.code == "QUALITY_BLOCKED"
    assert "SECRET_LIKE_PROVIDER_FIELD" in raised.value.details["blockers"]
    assert sentinel not in repr(raised.value)


def test_pd09_mandatory_h2h_missing_remains_blocking(repository_root: Path) -> None:
    value = _value(repository_root)
    for bookmaker in value[0]["bookmakers"]:
        bookmaker["markets"] = []
    _blocked(value, "REQUESTED_MARKET_MISSING_OR_DUPLICATED")


def test_pd10_duplicate_h2h_remains_blocking_at_parser_boundary(repository_root: Path) -> None:
    value = _value(repository_root)
    value[0]["bookmakers"][0]["markets"].append(deepcopy(value[0]["bookmakers"][0]["markets"][0]))
    with pytest.raises(IngestionError) as raised:
        parse_odds_payload(_body(value))
    assert raised.value.code == "VALIDATION_FAILED"


def test_pd11_incomplete_three_way_h2h_remains_blocking(repository_root: Path) -> None:
    value = _value(repository_root)
    value[0]["bookmakers"][0]["markets"][0]["outcomes"].pop()
    _blocked(value, "THREE_WAY_H2H_INCOMPLETE")


def test_pd12_equal_duplicate_h2h_outcome_remains_blocking(repository_root: Path) -> None:
    value = _value(repository_root)
    outcomes = value[0]["bookmakers"][0]["markets"][0]["outcomes"]
    outcomes.append(deepcopy(outcomes[0]))
    _blocked(value, "DUPLICATE_OUTCOME")


def test_pd13_line_bearing_h2h_outcome_remains_blocking(repository_root: Path) -> None:
    value = _value(repository_root)
    value[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["point"] = 0.5
    _blocked(value, "LINE_BEARING_H2H_OUTCOME")


def test_pd14_provider_timestamp_after_receipt_remains_blocking(repository_root: Path) -> None:
    value = _value(repository_root)
    value[0]["bookmakers"][0]["last_update"] = "2026-08-20T12:00:01Z"
    _blocked(value, "PROVIDER_TIMESTAMP_AFTER_RECEIPT")


def test_pd15_event_not_prematch_at_cutoff_remains_blocking(repository_root: Path) -> None:
    value = _value(repository_root)
    value[0]["commence_time"] = "2026-08-21T17:30:00Z"
    _blocked(value, "EVENT_NOT_PREMATCH_AT_CUTOFF")


def test_pd16_pd17_totals_absence_and_malformedness_remain_degraded(
    repository_root: Path,
) -> None:
    absent = _build(parse_odds_payload(_body(_value(repository_root))))
    malformed_value = _value(repository_root)
    _append_totals(malformed_value)
    malformed_value[0]["bookmakers"][0]["markets"][1]["outcomes"].pop()
    malformed = _build(parse_odds_payload(_body(malformed_value)))

    assert absent.quality.warnings == ("TOTALS_MISSING",)
    assert "TOTALS_INCOMPLETE" in malformed.quality.warnings
    assert malformed.events[0].bookmakers[0].totals_markets == ()
    assert malformed.events[0].bookmakers[1].totals_markets


def test_pd18_additive_market_cannot_become_consensus_input(repository_root: Path) -> None:
    value = _value(repository_root)
    _append_totals(value)
    _append_additive_market(value, "future_market")
    current = _build(parse_odds_payload(_body(value)))

    accepted = [
        market.market_key
        for event in current.events
        for bookmaker in event.bookmakers
        for market in (*bookmaker.markets, *bookmaker.totals_markets)
    ]
    assert "future_market" not in accepted
    assert set(accepted) == {"h2h", "totals"}


def test_pd19_warning_and_hash_order_is_canonical(repository_root: Path) -> None:
    value = _value(repository_root)
    _append_totals(value)
    _append_additive_market(value, "zeta_future")
    _append_additive_market(value, "alpha_future")
    reordered = json.loads(_body(value), object_pairs_hook=lambda pairs: dict(reversed(pairs)))
    for bookmaker in reordered[0]["bookmakers"]:
        bookmaker["markets"].reverse()

    first = _build(parse_odds_payload(_body(value)))
    second = _build(parse_odds_payload(_body(reordered, sort_keys=True)))

    assert first.quality == second.quality
    assert first.events == second.events
    assert first.market_semantic_sha256 == second.market_semantic_sha256
    assert first.provenance.response_body_sha256 != second.provenance.response_body_sha256


def test_pd20_repeated_identical_payload_is_deterministic(repository_root: Path) -> None:
    value = _value(repository_root)
    _append_totals(value)
    _append_additive_market(value, "future_market")
    body = _body(value)

    first = _build(parse_odds_payload(body))
    second = _build(parse_odds_payload(body))

    assert first == second
    assert first.market_semantic_sha256 == second.market_semantic_sha256


def test_required_rights_allow_and_unknown_secondary_rights_deny(repository_root: Path) -> None:
    current = _build(parse_odds_payload(_body(_value(repository_root))))

    assert current.rights.automated_access == "ALLOW"
    assert current.rights.transient_processing == "ALLOW"
    assert current.rights.derived_storage == "ALLOW"
    assert current.rights.private_internal_use == "ALLOW"
    assert current.rights.raw_storage_declared == "UNKNOWN"
    assert current.rights.raw_storage == "DENY"
    assert current.rights.public_display == "DENY"
    assert current.rights.redistribution == "DENY"
    assert current.rights.backup_declared == "UNKNOWN"
    assert current.rights.backup == "DENY"
    assert current.rights.model_training_declared == "UNKNOWN"
    assert current.rights.model_training == "DENY"
    assert current.rights.raw_retention_seconds == 0
    assert current.rights.raw_payload_retained is False


def test_post_cutoff_receipt_and_usable_time_are_never_eligible(repository_root: Path) -> None:
    parsed = parse_odds_payload(_body(_value(repository_root)))
    with pytest.raises(IngestionError, match="not usable") as received:
        _build(parsed, received_at=CUTOFF + timedelta(seconds=1))
    assert received.value.code == "POST_CUTOFF"

    with pytest.raises(IngestionError, match="not usable") as usable:
        _build(parsed, usable_at=CUTOFF + timedelta(seconds=1))
    assert usable.value.code == "POST_CUTOFF"
