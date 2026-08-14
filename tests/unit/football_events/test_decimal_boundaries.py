from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import BaseModel

from dmf_pulse.football_events._decimal import (
    canonical_decimal_text,
    canonical_json_sha256,
    decimal_sqrt,
    exact_decimal,
    format_utc,
    mapping,
    nonnegative_decimal,
    parse_utc,
    positive_decimal,
    probability,
    public_measure_text,
    public_probability_text,
    rounded_simplex,
)

pytestmark = pytest.mark.unit


class Example(BaseModel):
    value: int


@pytest.mark.parametrize("bad", [True, 0.5, "NaN", "Infinity", object()])
def test_exact_decimal_rejects_inexact_or_nonfinite_boundaries(bad: object) -> None:
    with pytest.raises(ValueError):
        exact_decimal(bad, label="value")


def test_decimal_domains_and_rendering() -> None:
    assert exact_decimal(2, label="value") == Decimal(2)
    assert probability("0.25", label="p") == Decimal("0.25")
    assert positive_decimal("0.1", label="x") == Decimal("0.1")
    assert nonnegative_decimal(0, label="x") == Decimal(0)
    assert canonical_decimal_text(Decimal("1.2300")) == "1.23"
    assert canonical_decimal_text(Decimal("0.000")) == "0"
    assert public_probability_text(Decimal("0.125")) == "0.125000000000"
    assert public_measure_text(Decimal("1.2345678")) == "1.234568"
    assert decimal_sqrt(Decimal("4")) == Decimal(2)


@pytest.mark.parametrize(
    ("call", "value"),
    [
        (probability, "-0.1"),
        (probability, "1.1"),
        (positive_decimal, "0"),
        (nonnegative_decimal, "-1"),
    ],
)
def test_decimal_domain_failures(call, value: str) -> None:
    with pytest.raises(ValueError):
        call(value, label="x")


def test_simplex_rounding_is_exact_and_deterministic() -> None:
    values = rounded_simplex((Decimal("0.3333333333333"),) * 3)
    assert sum(values, Decimal(0)) == Decimal(1)
    assert values[0] == Decimal("0.333333333334")
    with pytest.raises(ValueError):
        rounded_simplex(())
    with pytest.raises(ValueError):
        rounded_simplex((Decimal("-0.1"), Decimal("1.1")))
    with pytest.raises(ValueError):
        rounded_simplex((Decimal(0), Decimal(0)))


def test_mapping_and_canonical_hash_contract() -> None:
    assert mapping({"value": 1}, label="x") == {"value": 1}
    assert mapping(Example(value=2), label="x") == {"value": 2}
    with pytest.raises(TypeError):
        mapping(object(), label="x")
    assert canonical_json_sha256({"b": 2, "a": 1}) == canonical_json_sha256({"a": 1, "b": 2})


def test_utc_parser_rejects_naive_non_utc_and_malformed_values() -> None:
    parsed = parse_utc("2026-08-20T12:00:00Z", field_name="as_of")
    assert format_utc(parsed) == "2026-08-20T12:00:00Z"
    assert format_utc(parsed.replace(microsecond=123)) == "2026-08-20T12:00:00.000123Z"
    for bad in (
        "2026-08-20 12:00:00",
        "2026-08-20T12:00:00+01:00",
        datetime(2026, 8, 20, 12),
        datetime(2026, 8, 20, 12, tzinfo=timezone(timedelta(hours=1))),
        7,
    ):
        with pytest.raises(ValueError):
            parse_utc(bad, field_name="as_of")
    assert parse_utc(datetime(2026, 8, 20, 12, tzinfo=UTC), field_name="as_of") == parsed


def test_utc_formatter_rejects_naive_and_non_utc_values() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        format_utc(datetime(2026, 8, 20, 12))
    with pytest.raises(ValueError, match="must be UTC"):
        format_utc(datetime(2026, 8, 20, 12, tzinfo=timezone(timedelta(hours=1))))


def test_nonfinite_render_and_negative_sqrt_fail() -> None:
    with pytest.raises(ValueError):
        canonical_decimal_text(Decimal("NaN"))
    with pytest.raises(ValueError):
        decimal_sqrt(Decimal("-1"))
