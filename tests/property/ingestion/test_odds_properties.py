"""Deterministic properties for exact odds parsing and public serialization."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.markets.models import canonical_decimal_text

pytestmark = pytest.mark.property


@given(
    whole=st.integers(min_value=1, max_value=10**12),
    fraction=st.integers(min_value=0, max_value=999_999),
    trailing=st.integers(min_value=0, max_value=8),
)
def test_decimal_canonical_text_preserves_exact_numeric_value(
    whole: int, fraction: int, trailing: int
) -> None:
    lexical = f"{whole}.{fraction:06d}{'0' * trailing}"
    value = Decimal(lexical)
    rendered = canonical_decimal_text(value)
    assert Decimal(rendered) == value
    assert rendered == "0" or not rendered.endswith(".")
    assert "." not in rendered or not rendered.endswith("0")


@given(
    future=st.lists(
        st.one_of(
            st.integers(min_value=-10_000, max_value=10_000),
            st.text(
                alphabet=st.characters(blacklist_categories=("Cs",)),
                min_size=0,
                max_size=20,
            ),
            st.booleans(),
            st.none(),
        ),
        min_size=1,
        max_size=12,
    )
)
def test_additive_heterogeneous_arrays_have_order_independent_type_fingerprint(
    repository_root: Path, future: list[object]
) -> None:
    source = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    source[0]["future_values"] = future
    first = parse_odds_payload(json.dumps(source, ensure_ascii=True).encode())
    source[0]["future_values"] = list(reversed(future))
    second = parse_odds_payload(json.dumps(source, ensure_ascii=True).encode())
    assert first.schema_fingerprint == second.schema_fingerprint


@given(
    offset_minutes=st.integers(min_value=1, max_value=48 * 60),
)
def test_timezone_offsets_normalize_without_changing_provider_instant(
    repository_root: Path, offset_minutes: int
) -> None:
    source = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    instant = datetime(2026, 8, 22, 14, tzinfo=UTC)
    zone = UTC
    shifted = instant.astimezone(zone) + timedelta(minutes=offset_minutes)
    shifted = shifted - timedelta(minutes=offset_minutes)
    source[0]["commence_time"] = shifted.isoformat().replace("+00:00", "Z")
    parsed = parse_odds_payload(json.dumps(source).encode())
    assert parsed.events[0].commence_time == instant
