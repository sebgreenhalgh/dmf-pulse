"""Boundary coverage for the provider-native LIVE-ODDS-001 contract."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import permutations
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import (
    CapabilityValue,
    ImmutableCapabilities,
    RightsCapability,
)
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.current import (
    CurrentOddsBookmaker,
    CurrentOddsEvent,
    CurrentOddsMarket,
    CurrentOddsOutcome,
    CurrentOddsQualityState,
    CurrentOddsQuotaState,
    CurrentOddsRightsState,
    CurrentOddsTemporalState,
    CurrentOddsTotalsMarket,
    CurrentOddsTotalsOutcome,
    OddsProviderCurrentInput,
    build_current_odds_input,
    current_odds_market_semantic_sha256,
)
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import OddsBookmaker, ParsedOddsPayload, parse_odds_payload

pytestmark = pytest.mark.unit

RECEIVED = datetime(2026, 8, 20, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
SOURCE_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000914")
TARGET = (
    "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?"
    "regions=uk&markets=h2h%2Ctotals&oddsFormat=decimal&dateFormat=iso&"
    "commenceTimeFrom=2026-08-21T17%3A30%3A00Z"
)
BOUNDED_TARGET = TARGET + "&commenceTimeTo=2026-08-23T00%3A00%3A00Z"


def _value(repository_root: Path) -> list[dict[str, Any]]:
    value = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, list)
    return value


def _body(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":")).encode()


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


def _build(
    parsed: ParsedOddsPayload,
    *,
    request_started_at: datetime = RECEIVED - timedelta(seconds=1),
    received_at: datetime = RECEIVED,
    usable_at: datetime = RECEIVED + timedelta(seconds=1),
    quota_observed_at: datetime = RECEIVED,
    last_cost: int = 2,
    quota_source: QuotaSource = QuotaSource.RESPONSE_HEADERS,
    target: str = TARGET,
    attempt_count: int = 1,
    transport_call_count: int = 1,
) -> OddsProviderCurrentInput:
    return build_current_odds_input(
        parsed,
        profile=load_rights_profiles()["the_odds_api_private_analytics_v1"],
        source_snapshot_id=SOURCE_SNAPSHOT_ID,
        request_started_at=request_started_at,
        received_at=received_at,
        information_cutoff=CUTOFF,
        usable_at=usable_at,
        quota=QuotaState(
            remaining=498,
            used=2,
            last_cost=last_cost,
            observed_at=quota_observed_at,
            source=quota_source,
        ),
        request_fingerprint="1" * 64,
        sanitized_target=target,
        attempt_count=attempt_count,
        transport_call_count=transport_call_count,
        transport_id="stdlib_http_client",
        provider_request_id_sha256="2" * 64,
    )


def _rehash_supported_markets(
    value: OddsProviderCurrentInput,
    *,
    events: tuple[CurrentOddsEvent, ...],
) -> OddsProviderCurrentInput:
    provisional = value.model_copy(update={"events": events, "market_semantic_sha256": "0" * 64})
    rehashed = provisional.model_copy(
        update={"market_semantic_sha256": current_odds_market_semantic_sha256(provisional)}
    )
    return OddsProviderCurrentInput.model_validate(rehashed.model_dump(mode="python"))


def _totals_at_line(
    market: CurrentOddsTotalsMarket,
    line: Decimal,
) -> CurrentOddsTotalsMarket:
    return market.model_copy(
        update={
            "line": line,
            "outcomes": tuple(
                outcome.model_copy(update={"point": line}) for outcome in market.outcomes
            ),
        }
    )


def _with_first_bookmaker_totals(
    value: OddsProviderCurrentInput,
    lines: tuple[Decimal, ...],
    *,
    reverse_outcomes: bool = False,
) -> OddsProviderCurrentInput:
    events = list(value.events)
    bookmakers = list(events[0].bookmakers)
    template = bookmakers[0].totals_markets[0]
    totals = tuple(_totals_at_line(template, line) for line in lines)
    if reverse_outcomes:
        totals = tuple(
            market.model_copy(update={"outcomes": tuple(reversed(market.outcomes))})
            for market in totals
        )
    bookmakers[0] = bookmakers[0].model_copy(update={"totals_markets": totals})
    events[0] = events[0].model_copy(update={"bookmakers": tuple(bookmakers)})
    return _rehash_supported_markets(value, events=tuple(events))


def test_cmr_ir_011_totals_line_and_outcome_order_are_semantically_canonical(
    repository_root: Path,
) -> None:
    raw = _value(repository_root)
    _append_totals(raw)
    current = _build(parse_odds_payload(_body(raw)))
    first = _with_first_bookmaker_totals(
        current,
        (Decimal("1.5"), Decimal("2.5")),
    )
    reversed_lines = _with_first_bookmaker_totals(
        current,
        (Decimal("2.5"), Decimal("1.5")),
    )
    reversed_outcomes = _with_first_bookmaker_totals(
        current,
        (Decimal("1.5"), Decimal("2.5")),
        reverse_outcomes=True,
    )

    assert first.market_semantic_sha256 == reversed_lines.market_semantic_sha256
    assert first.market_semantic_sha256 == reversed_outcomes.market_semantic_sha256


def test_cmr_ir_011_three_totals_lines_are_invariant_across_all_permutations(
    repository_root: Path,
) -> None:
    raw = _value(repository_root)
    _append_totals(raw)
    current = _build(parse_odds_payload(_body(raw)))
    line_orders = tuple(permutations((Decimal("1.5"), Decimal("2.5"), Decimal("3.5"))))

    hashes = {
        _with_first_bookmaker_totals(current, order).market_semantic_sha256 for order in line_orders
    }

    assert len(hashes) == 1


def test_cmr_ir_011_bookmaker_and_event_order_remain_semantically_canonical(
    repository_root: Path,
) -> None:
    raw = _value(repository_root)
    _append_totals(raw)
    current = _build(parse_odds_payload(_body(raw)))
    event = current.events[0]
    bookmaker_reordered_event = event.model_copy(
        update={"bookmakers": tuple(reversed(event.bookmakers))}
    )
    bookmaker_reordered = _rehash_supported_markets(
        current,
        events=(bookmaker_reordered_event,),
    )
    second_event = event.model_copy(update={"provider_event_id": "todapi-event-002"})
    ordered_events = _rehash_supported_markets(current, events=(event, second_event))
    reversed_events = _rehash_supported_markets(current, events=(second_event, event))

    assert bookmaker_reordered.market_semantic_sha256 == current.market_semantic_sha256
    assert ordered_events.market_semantic_sha256 == reversed_events.market_semantic_sha256


def test_cmr_ir_011_totals_line_set_and_price_mutations_remain_material(
    repository_root: Path,
) -> None:
    raw = _value(repository_root)
    _append_totals(raw)
    current = _build(parse_odds_payload(_body(raw)))
    line_1_5 = _with_first_bookmaker_totals(current, (Decimal("1.5"),))
    line_2_5 = _with_first_bookmaker_totals(current, (Decimal("2.5"),))
    price_events = list(line_1_5.events)
    bookmakers = list(price_events[0].bookmakers)
    market = bookmakers[0].totals_markets[0]
    changed_outcomes = tuple(
        outcome.model_copy(update={"decimal_price": Decimal("1.91")})
        if outcome.outcome == "OVER"
        else outcome
        for outcome in market.outcomes
    )
    bookmakers[0] = bookmakers[0].model_copy(
        update={"totals_markets": (market.model_copy(update={"outcomes": changed_outcomes}),)}
    )
    price_events[0] = price_events[0].model_copy(update={"bookmakers": tuple(bookmakers)})
    changed_price = _rehash_supported_markets(line_1_5, events=tuple(price_events))

    assert line_1_5.market_semantic_sha256 != line_2_5.market_semantic_sha256
    assert line_1_5.market_semantic_sha256 != changed_price.market_semantic_sha256


@pytest.mark.parametrize(
    ("mutation", "warning"),
    (
        (
            lambda market: market["outcomes"][0].__setitem__("name", "Sideways"),
            "TOTALS_MALFORMED_OUTCOME",
        ),
        (
            lambda market: market["outcomes"][0].__setitem__("point", 2),
            "TOTALS_NON_HALF_GOAL_LINE",
        ),
        (
            lambda market: market["outcomes"][1].__setitem__("point", 3.5),
            "TOTALS_LINE_MISMATCH",
        ),
        (
            lambda market: market["outcomes"][1].__setitem__("name", " over "),
            "TOTALS_DUPLICATE_OUTCOME",
        ),
        (
            lambda market: [outcome.__setitem__("point", 3.5) for outcome in market["outcomes"]],
            "TOTALS_PREFERRED_LINE_2_5_UNAVAILABLE",
        ),
        (
            lambda market: market.__setitem__("last_update", "2026-08-20T12:00:01Z"),
            "TOTALS_TIMESTAMP_INVALID",
        ),
    ),
)
def test_optional_totals_failures_degrade_valid_h2h(
    repository_root: Path,
    mutation: Callable[[dict[str, Any]], object],
    warning: str,
) -> None:
    value = _value(repository_root)
    _append_totals(value)
    mutation(value[0]["bookmakers"][0]["markets"][1])

    current = _build(parse_odds_payload(_body(value)))

    assert warning in current.quality.warnings
    assert current.events[0].bookmakers[0].totals_markets == ()
    assert current.events[0].bookmakers[0].markets[0].market_key == "h2h"


def test_preferred_totals_line_is_selected_without_mixing_extra_lines(
    repository_root: Path,
) -> None:
    value = _value(repository_root)
    _append_totals(value)
    value[0]["bookmakers"][0]["markets"][1]["outcomes"].extend(
        [
            {"name": "Over", "price": 2.4, "point": 3.5},
            {"name": "Under", "price": 1.6, "point": 3.5},
        ]
    )

    current = _build(parse_odds_payload(_body(value)))

    assert current.events[0].bookmakers[0].totals_markets[0].line == Decimal("2.5")


@pytest.mark.parametrize(
    ("mutation", "blocker"),
    (
        (lambda value: value.clear(), "EMPTY_PROVIDER_RESPONSE"),
        (lambda value: value[0].__setitem__("bookmakers", []), "BOOKMAKER_MISSING"),
        (
            lambda value: value[0]["bookmakers"][0]["markets"][0]["outcomes"][0].__setitem__(
                "name", "Unknown participant"
            ),
            "MALFORMED_OUTCOME",
        ),
        (
            lambda value: value[0]["bookmakers"][0]["markets"][0].__setitem__(
                "last_update", "2026-08-20T11:59:31Z"
            ),
            "MARKET_TIMESTAMP_AFTER_BOOKMAKER",
        ),
    ),
)
def test_additional_mandatory_market_fail_closed_cases(
    repository_root: Path,
    mutation: Callable[[list[dict[str, Any]]], object],
    blocker: str,
) -> None:
    value = _value(repository_root)
    mutation(value)

    with pytest.raises(IngestionError) as raised:
        _build(parse_odds_payload(_body(value)))

    assert blocker in raised.value.details["blockers"]


def test_duplicate_event_and_bookmaker_identities_block(repository_root: Path) -> None:
    parsed = parse_odds_payload(_body(_value(repository_root)))
    duplicate_event = replace(parsed, events=(parsed.events[0], parsed.events[0]))
    with pytest.raises(IngestionError) as event_error:
        _build(duplicate_event)
    assert "DUPLICATE_PROVIDER_EVENT_ID" in event_error.value.details["blockers"]

    event = parsed.events[0]
    duplicate_bookmaker = event.model_copy(
        update={"bookmakers": (event.bookmakers[0], event.bookmakers[0])}
    )
    duplicate_payload = replace(parsed, events=(duplicate_bookmaker,))
    with pytest.raises(IngestionError) as bookmaker_error:
        _build(duplicate_payload)
    assert "DUPLICATE_BOOKMAKER" in bookmaker_error.value.details["blockers"]

    equal_teams = parsed.events[0].model_copy(update={"home_team": parsed.events[0].away_team})
    equal_team_payload = replace(parsed, events=(equal_teams,))
    with pytest.raises(IngestionError) as team_error:
        _build(equal_team_payload)
    assert "HOME_EQUALS_AWAY" in team_error.value.details["blockers"]


def test_equal_duplicate_h2h_outcome_blocks_after_parser_dedup(repository_root: Path) -> None:
    value = _value(repository_root)
    value[0]["bookmakers"][0]["markets"][0]["outcomes"].append(
        dict(value[0]["bookmakers"][0]["markets"][0]["outcomes"][0])
    )

    with pytest.raises(IngestionError) as raised:
        _build(parse_odds_payload(_body(value)))

    assert "DUPLICATE_OUTCOME" in raised.value.details["blockers"]


@pytest.mark.parametrize(
    ("kwargs", "code", "blocker"),
    (
        ({"request_started_at": RECEIVED.replace(tzinfo=None)}, "VALIDATION_FAILED", None),
        ({"request_started_at": RECEIVED + timedelta(seconds=1)}, "CLOCK_REGRESSION", None),
        ({"usable_at": RECEIVED - timedelta(seconds=1)}, "CLOCK_REGRESSION", None),
        (
            {"quota_observed_at": RECEIVED + timedelta(seconds=1)},
            "QUALITY_BLOCKED",
            "QUOTA_TIMESTAMP_MISMATCH",
        ),
        ({"last_cost": 1}, "QUALITY_BLOCKED", "QUOTA_REQUEST_COST_MISMATCH"),
        (
            {"quota_source": QuotaSource.SYNTHETIC_FIXTURE},
            "QUALITY_BLOCKED",
            "QUOTA_SOURCE_INVALID",
        ),
    ),
)
def test_builder_temporal_and_quota_boundaries(
    repository_root: Path,
    kwargs: dict[str, object],
    code: str,
    blocker: str | None,
) -> None:
    with pytest.raises(IngestionError) as raised:
        _build(parse_odds_payload(_body(_value(repository_root))), **kwargs)  # type: ignore[arg-type]

    assert raised.value.code == code
    if blocker is not None:
        assert raised.value.details["blockers"] == [blocker]


@pytest.mark.parametrize(
    "target",
    (
        TARGET.replace("https://", "http://"),
        TARGET.replace("api.the-odds-api.com", "unapproved.example"),
        TARGET.replace("/v4/sports/soccer_epl/odds", "/v4/sports/soccer_epl/scores"),
        TARGET.replace("regions=uk", "regions=us"),
        TARGET.replace("markets=h2h%2Ctotals", "markets=h2h"),
        TARGET + "&apiKey=forbidden",
    ),
)
def test_provenance_rejects_host_path_parameter_or_secret_drift(
    repository_root: Path,
    target: str,
) -> None:
    with pytest.raises(ValidationError):
        _build(parse_odds_payload(_body(_value(repository_root))), target=target)


def test_provenance_rejects_attempt_count_mismatch(repository_root: Path) -> None:
    with pytest.raises(ValidationError):
        _build(
            parse_odds_payload(_body(_value(repository_root))),
            attempt_count=2,
            transport_call_count=1,
        )


def test_provenance_accepts_required_only_and_bounded_request_shapes(
    repository_root: Path,
) -> None:
    parsed = parse_odds_payload(_body(_value(repository_root)))

    required_only = _build(parsed)
    bounded = _build(parsed, target=BOUNDED_TARGET)

    assert "commenceTimeTo" not in required_only.provenance.sanitized_target
    assert "commenceTimeTo" in bounded.provenance.sanitized_target


@pytest.mark.parametrize(
    ("target", "message"),
    [
        (
            BOUNDED_TARGET + "&commenceTimeTo=2026-08-24T00%3A00%3A00Z",
            "transport provenance is inconsistent",
        ),
        (
            TARGET + "&unexpected=safe-but-unsupported",
            "transport provenance is inconsistent",
        ),
        (
            TARGET + "&commenceTimeTo=2026-08-21T17%3A30%3A00Z",
            "upper bound must be later",
        ),
        (
            TARGET.replace("17%3A30%3A00Z", "17%3A30%3A00.123456Z"),
            "canonical whole-second",
        ),
        (
            TARGET + "&commenceTimeTo=2026-08-23T00%3A00%3A00.1Z",
            "canonical whole-second",
        ),
    ],
)
def test_provenance_rejects_duplicate_unknown_or_invalid_commence_windows(
    repository_root: Path,
    target: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _build(parse_odds_payload(_body(_value(repository_root))), target=target)


def test_outer_contract_rejects_invalid_cutoff_and_semantic_hash(repository_root: Path) -> None:
    current = _build(parse_odds_payload(_body(_value(repository_root))))
    invalid_cutoff = current.model_dump(mode="python")
    invalid_cutoff["provenance"]["sanitized_target"] = TARGET.replace(
        "2026-08-21T17%3A30%3A00Z", "not-a-timestamp"
    )
    with pytest.raises(ValidationError, match="cutoff is invalid"):
        OddsProviderCurrentInput.model_validate(invalid_cutoff)

    mismatched_cutoff = current.model_dump(mode="python")
    mismatched_cutoff["provenance"]["sanitized_target"] = TARGET.replace(
        "2026-08-21T17%3A30%3A00Z", "2026-08-21T17%3A29%3A00Z"
    )
    with pytest.raises(ValidationError, match="contradicts input cutoff"):
        OddsProviderCurrentInput.model_validate(mismatched_cutoff)

    wrong_hash = current.model_dump(mode="python")
    wrong_hash["market_semantic_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="semantic hash is inconsistent"):
        OddsProviderCurrentInput.model_validate(wrong_hash)


def _valid_model_parts(repository_root: Path) -> dict[str, object]:
    current = _build(parse_odds_payload(_body(_value(repository_root))))
    bookmaker = current.events[0].bookmakers[0]
    return {
        "bookmaker": bookmaker,
        "event": current.events[0],
        "market": bookmaker.markets[0],
        "outcome": bookmaker.markets[0].outcomes[0],
        "quality": current.quality,
        "quota": current.quota,
        "rights": current.rights,
        "temporal": current.temporal,
    }


def test_nested_model_invariants_reject_contradictory_values(repository_root: Path) -> None:
    parts = _valid_model_parts(repository_root)
    outcome = parts["outcome"]
    market = parts["market"]
    bookmaker = parts["bookmaker"]
    event = parts["event"]
    temporal = parts["temporal"]
    quota = parts["quota"]
    assert isinstance(outcome, CurrentOddsOutcome)
    assert isinstance(market, CurrentOddsMarket)
    assert isinstance(bookmaker, CurrentOddsBookmaker)
    assert isinstance(event, CurrentOddsEvent)
    assert isinstance(temporal, CurrentOddsTemporalState)
    assert isinstance(quota, CurrentOddsQuotaState)

    invalid_factories: tuple[Callable[[], object], ...] = (
        lambda: CurrentOddsOutcome(provider_name="x", outcome="HOME", decimal_price=Decimal("1")),
        lambda: market.model_validate(
            {
                **market.model_dump(),
                "provider_last_update_state": (
                    "NOT_PUBLISHED" if market.provider_last_update is not None else "PUBLISHED"
                ),
            }
        ),
        lambda: market.model_validate(
            {**market.model_dump(), "outcomes": (outcome, outcome, outcome)}
        ),
        lambda: bookmaker.model_validate(
            {**bookmaker.model_dump(), "totals_markets": (_totals(), _totals())}
        ),
        lambda: event.model_validate(
            {**event.model_dump(), "provider_away_team": event.provider_home_team}
        ),
        lambda: event.model_validate({**event.model_dump(), "bookmakers": (bookmaker, bookmaker)}),
        lambda: temporal.model_validate(
            {**temporal.model_dump(), "captured_at": temporal.received_at + timedelta(seconds=1)}
        ),
        lambda: temporal.model_validate(
            {**temporal.model_dump(), "usable_at": temporal.received_at - timedelta(seconds=1)}
        ),
        lambda: quota.model_validate({**quota.model_dump(), "provider_last_request_cost": 1}),
    )
    for factory in invalid_factories:
        with pytest.raises(ValidationError):
            factory()


def _totals() -> CurrentOddsTotalsMarket:
    over = CurrentOddsTotalsOutcome(
        provider_name="Over", outcome="OVER", decimal_price=Decimal("1.9"), point=Decimal("2.5")
    )
    under = CurrentOddsTotalsOutcome(
        provider_name="Under", outcome="UNDER", decimal_price=Decimal("1.9"), point=Decimal("2.5")
    )
    return CurrentOddsTotalsMarket(
        line=Decimal("2.5"),
        provider_last_update=None,
        provider_last_update_state="NOT_PUBLISHED",
        outcomes=(over, under),
    )


def test_totals_models_reject_invalid_prices_lines_and_composition() -> None:
    totals = _totals()
    over, under = totals.outcomes
    factories: tuple[Callable[[], object], ...] = (
        lambda: CurrentOddsTotalsOutcome(
            provider_name="Over", outcome="OVER", decimal_price=Decimal("1"), point=Decimal("2.5")
        ),
        lambda: CurrentOddsTotalsOutcome(
            provider_name="Over", outcome="OVER", decimal_price=Decimal("1.9"), point=Decimal("2")
        ),
        lambda: totals.model_validate({**totals.model_dump(), "line": Decimal("2")}),
        lambda: totals.model_validate(
            {**totals.model_dump(), "provider_last_update_state": "PUBLISHED"}
        ),
        lambda: totals.model_validate({**totals.model_dump(), "outcomes": (over, over)}),
        lambda: totals.model_validate(
            {
                **totals.model_dump(),
                "outcomes": (
                    over,
                    under.model_copy(update={"point": Decimal("3.5")}),
                ),
            }
        ),
    )
    for factory in factories:
        with pytest.raises(ValidationError):
            factory()


def test_quality_and_rights_models_reject_policy_contradictions(repository_root: Path) -> None:
    parts = _valid_model_parts(repository_root)
    quality = parts["quality"]
    rights = parts["rights"]
    assert isinstance(quality, CurrentOddsQualityState)
    assert isinstance(rights, CurrentOddsRightsState)

    invalid_quality: tuple[dict[str, object], ...] = (
        {"status": "PASS", "warnings": ("TOTALS_MISSING",)},
        {"status": "WARNING", "warnings": ("z", "a")},
        {
            "status": "WARNING",
            "warnings": ("ADDITIVE_UNSUPPORTED_MARKET:z",),
            "additive_unsupported_markets": ("z", "z"),
        },
        {
            "status": "WARNING",
            "warnings": ("ADDITIVE_UNSUPPORTED_MARKET:h2h",),
            "additive_unsupported_markets": ("h2h",),
        },
        {
            "status": "WARNING",
            "warnings": ("ADDITIVE_UNSUPPORTED_MARKET:z",),
            "additive_unsupported_markets": ("different",),
        },
    )
    for value in invalid_quality:
        with pytest.raises(ValidationError):
            CurrentOddsQualityState.model_validate(value)

    for update in (
        {"automated_access": "DENY"},
        {"raw_storage": "ALLOW"},
        {"public_display": "ALLOW"},
        {"backup": "ALLOW"},
    ):
        with pytest.raises(ValidationError):
            CurrentOddsRightsState.model_validate({**rights.model_dump(), **update})


def test_denied_required_right_is_enforced_before_output(repository_root: Path) -> None:
    parsed = parse_odds_payload(_body(_value(repository_root)))
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    denied = profile.model_copy(
        update={
            "capabilities": ImmutableCapabilities(
                {
                    **profile.capabilities,
                    RightsCapability.AUTOMATED_ACCESS: CapabilityValue.DENY,
                }
            )
        }
    )
    with pytest.raises(IngestionError) as raised:
        build_current_odds_input(
            parsed,
            profile=denied,
            source_snapshot_id=SOURCE_SNAPSHOT_ID,
            request_started_at=RECEIVED - timedelta(seconds=1),
            received_at=RECEIVED,
            information_cutoff=CUTOFF,
            usable_at=RECEIVED + timedelta(seconds=1),
            quota=QuotaState(
                remaining=498,
                used=2,
                last_cost=2,
                observed_at=RECEIVED,
                source=QuotaSource.RESPONSE_HEADERS,
            ),
            request_fingerprint="1" * 64,
            sanitized_target=TARGET,
            attempt_count=1,
            transport_call_count=1,
            transport_id="stdlib_http_client",
            provider_request_id_sha256=None,
        )
    assert raised.value.code == "RIGHTS_BLOCKED"


def test_model_rejects_naive_datetime_at_output_boundary(repository_root: Path) -> None:
    parts = _valid_model_parts(repository_root)
    temporal = parts["temporal"]
    assert isinstance(temporal, CurrentOddsTemporalState)
    with pytest.raises(ValidationError, match="timezone-aware"):
        CurrentOddsTemporalState.model_validate(
            {**temporal.model_dump(), "received_at": RECEIVED.replace(tzinfo=None)}
        )


def test_duplicate_bookmaker_fixture_uses_provider_model_not_mapping(
    repository_root: Path,
) -> None:
    parsed = parse_odds_payload(_body(_value(repository_root)))
    assert isinstance(parsed.events[0].bookmakers[0], OddsBookmaker)
