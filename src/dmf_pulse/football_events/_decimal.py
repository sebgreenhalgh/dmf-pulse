"""Exact Decimal and canonical-identity helpers for GCS-008."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

DECIMAL_PRECISION = 60
PROBABILITY_SCALE = Decimal("0.000000000001")
MEASURE_SCALE = Decimal("0.000001")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RFC3339_UTC_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)


def exact_decimal(value: object, *, label: str) -> Decimal:
    """Parse an exact finite Decimal and reject binary-float boundaries."""

    if isinstance(value, (bool, float)):
        raise ValueError(f"{label} must use an exact decimal representation")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (str, int)):
        try:
            result = Decimal(str(value))
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise ValueError(f"{label} must be decimal") from exc
    else:
        raise ValueError(f"{label} must be decimal")
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def probability(value: object, *, label: str) -> Decimal:
    result = exact_decimal(value, label=label)
    if result < 0 or result > 1:
        raise ValueError(f"{label} must be in [0,1]")
    return result


def positive_decimal(value: object, *, label: str) -> Decimal:
    result = exact_decimal(value, label=label)
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def nonnegative_decimal(value: object, *, label: str) -> Decimal:
    result = exact_decimal(value, label=label)
    if result < 0:
        raise ValueError(f"{label} must be nonnegative")
    return result


def canonical_decimal_text(value: Decimal) -> str:
    """Render a Decimal by numeric value without ambient-context rounding."""

    if not value.is_finite():
        raise ValueError("decimal value must be finite")
    if value == 0:
        return "0"
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def public_probability_text(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return format(value.quantize(PROBABILITY_SCALE), ".12f")


def public_measure_text(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return format(value.quantize(MEASURE_SCALE), ".6f")


def quantize_probability(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return value.quantize(PROBABILITY_SCALE)


def quantize_measure(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return value.quantize(MEASURE_SCALE)


def rounded_simplex(values: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """Round to the public scale and deterministically restore an exact simplex."""

    if not values:
        raise ValueError("simplex must contain at least one value")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        if any(not value.is_finite() or value < 0 for value in values):
            raise ValueError("simplex values must be finite and nonnegative")
        total = sum(values, Decimal(0))
        if total <= 0:
            raise ValueError("simplex total must be positive")
        normalized = tuple(value / total for value in values)
        rounded = [value.quantize(PROBABILITY_SCALE) for value in normalized]
        residual = Decimal(1) - sum(rounded, Decimal(0))
        if residual:
            index = max(range(len(normalized)), key=lambda item: (normalized[item], -item))
            rounded[index] += residual
        if any(value < 0 for value in rounded):
            raise ValueError("simplex residual created a negative probability")
        if sum(rounded, Decimal(0)) != Decimal(1):
            raise ValueError("rounded simplex does not sum exactly to one")
        return tuple(rounded)


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def mapping(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump(mode="json")
        if isinstance(result, Mapping):
            return dict(result)
    raise TypeError(f"{label} must be a mapping or Pydantic model")


def parse_utc(value: object, *, field_name: str) -> datetime:
    """Parse an explicitly UTC RFC3339 timestamp."""

    if isinstance(value, str):
        if _RFC3339_UTC_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{field_name} must be an RFC3339 UTC timestamp")
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an RFC3339 UTC timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{field_name} must be an RFC3339 UTC timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return parsed.astimezone(UTC)


def format_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    normalized = value.astimezone(UTC)
    rendered = normalized.isoformat(
        timespec="microseconds" if normalized.microsecond else "seconds"
    )
    return rendered.replace("+00:00", "Z")


def decimal_sqrt(value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError("cannot take square root of a negative Decimal")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return value.sqrt()


__all__ = [
    "DECIMAL_PRECISION",
    "MEASURE_SCALE",
    "PROBABILITY_SCALE",
    "SHA256_PATTERN",
    "canonical_decimal_text",
    "canonical_json_sha256",
    "decimal_sqrt",
    "exact_decimal",
    "format_utc",
    "mapping",
    "nonnegative_decimal",
    "parse_utc",
    "positive_decimal",
    "probability",
    "public_measure_text",
    "public_probability_text",
    "quantize_measure",
    "quantize_probability",
    "rounded_simplex",
]
