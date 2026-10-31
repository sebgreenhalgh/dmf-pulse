"""Complete response-header metadata stays distinct from reserved/configured cost."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from dmf_pulse.dashboard.synthetic import DEMO_TIME, demo_inputs
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
from dmf_pulse.private_v1.presentation import MarketQuotaReceipt, SourceVintage

pytestmark = pytest.mark.unit


def values(**updates):
    return {
        "remaining_credits": 497,
        "used_credits": 3,
        "last_request_cost": 2,
        "observed_at": DEMO_TIME,
        "received_at": DEMO_TIME,
        "request_fingerprint": "a" * 64,
        "transport_call_count": 1,
        **updates,
    }


def vintage(**updates):
    return SourceVintage(
        **{
            "source": "MARKETS",
            "identity_sha256": "b" * 64,
            "received_at": DEMO_TIME,
            "usable_at": DEMO_TIME,
            "source_mode": "CURRENT_TRANSIENT",
            "requests": 1,
            **updates,
        }
    )


def test_exact_parsed_source_headers_and_transport_provenance_are_copied():
    # This is authenticated packaged owned source evidence, never a real call.
    odds = OddsProviderCurrentInput.model_validate_json(demo_inputs()["odds.json"])
    receipt = MarketQuotaReceipt.from_odds(odds)
    assert receipt.model_dump(mode="python") == {
        "source": "PROVIDER_RESPONSE_HEADERS",
        "remaining_credits": odds.quota.remaining,
        "used_credits": odds.quota.used,
        "last_request_cost": odds.quota.provider_last_request_cost,
        "observed_at": odds.quota.observed_at,
        "received_at": odds.temporal.received_at,
        "request_fingerprint": odds.provenance.request_fingerprint,
        "transport_call_count": odds.provenance.transport_call_count,
    }


def test_zero_observed_cost_is_preserved_even_when_reserved_or_configured_cost_is_two():
    # The adapter-only owned object does not claim to qualify an upstream input.
    # This verifies metadata copying without weakening its existing cost gate.
    owned = SimpleNamespace(
        quota=SimpleNamespace(
            source="RESPONSE_HEADERS",
            remaining=0,
            used=0,
            provider_last_request_cost=0,
            configured_request_cost=2,
            observed_at=DEMO_TIME,
        ),
        temporal=SimpleNamespace(received_at=DEMO_TIME),
        provenance=SimpleNamespace(request_fingerprint="a" * 64, transport_call_count=3),
        reserved_credits=2,
    )
    receipt = MarketQuotaReceipt.from_odds(owned)
    assert receipt.last_request_cost == receipt.remaining_credits == receipt.used_credits == 0
    assert receipt.transport_call_count == 3
    assert "reserved_credits" not in receipt.model_dump()
    assert "configured_request_cost" not in receipt.model_dump()


def test_operator_reported_balance_cannot_be_labelled_as_response_headers():
    owned = SimpleNamespace(quota=SimpleNamespace(source="OPERATOR_REPORTED"))
    with pytest.raises(ValueError, match="actual response-header provenance"):
        MarketQuotaReceipt.from_odds(owned)


@pytest.mark.parametrize(
    "field,value",
    [
        *[
            (field, value)
            for field in ("remaining_credits", "used_credits", "last_request_cost")
            for value in (-1, True, "2", 2.0)
        ],
        ("transport_call_count", 0),
        ("transport_call_count", True),
        ("transport_call_count", "1"),
        ("transport_call_count", 1.0),
        ("request_fingerprint", "short"),
        ("request_fingerprint", "A" * 64),
        ("source", "OPERATOR_REPORTED"),
    ],
)
def test_strict_complete_nonnegative_header_contract(field, value):
    with pytest.raises(ValidationError):
        MarketQuotaReceipt(**values(**{field: value}))


@pytest.mark.parametrize("field", tuple(values()))
def test_every_observed_fact_is_required_with_no_cost_or_count_defaults(field):
    payload = values()
    payload.pop(field)
    with pytest.raises(ValidationError):
        MarketQuotaReceipt(**payload)


@pytest.mark.parametrize("field", ["observed_at", "received_at"])
def test_naive_receipt_times_are_rejected(field):
    with pytest.raises(ValidationError):
        MarketQuotaReceipt(**values(**{field: datetime(2026, 9, 1, 12)}))


def test_header_observation_must_equal_the_actual_response_receipt_time():
    with pytest.raises(ValidationError):
        MarketQuotaReceipt(**values(observed_at=DEMO_TIME - timedelta(seconds=1)))
    with pytest.raises(ValidationError):
        MarketQuotaReceipt(**values(last_request_cost=4))


def test_offset_times_normalize_to_utc():
    offset = DEMO_TIME.astimezone(datetime.fromisoformat("2026-09-01T14:00:00+02:00").tzinfo)
    receipt = MarketQuotaReceipt(**values(observed_at=offset, received_at=offset))
    assert receipt.received_at == receipt.observed_at == DEMO_TIME
    assert receipt.received_at.tzinfo is UTC


@pytest.mark.parametrize(
    "rows",
    [
        (),
        (vintage(), vintage()),
        (vintage(source="FPL"),),
        (vintage(requests=2),),
        (vintage(received_at=DEMO_TIME + timedelta(seconds=1)),),
        (vintage(source_mode="HISTORICAL_RECONSTRUCTED"),),
    ],
)
def test_receipt_cannot_attach_to_another_or_ambiguous_market_acquisition(rows):
    with pytest.raises(ValueError, match="market source vintage"):
        MarketQuotaReceipt(**values()).require_market_vintage(rows)


def test_complete_receipt_matches_one_exact_market_acquisition():
    MarketQuotaReceipt(**values()).require_market_vintage((vintage(),))
