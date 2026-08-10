"""Context-independent exact arithmetic for finite :class:`~decimal.Decimal` values."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal


def _parts(value: Decimal) -> tuple[int, int]:
    """Return the signed integer coefficient and base-ten exponent."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("exact Decimal arithmetic requires finite Decimal values")
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover - guarded by is_finite()
        raise ValueError("exact Decimal arithmetic requires finite Decimal values")
    coefficient = int("".join(str(digit) for digit in digits) or "0")
    return (-coefficient if sign else coefficient), exponent


def _from_parts(coefficient: int, exponent: int) -> Decimal:
    """Construct a finite Decimal directly from an exact coefficient/exponent pair."""

    if coefficient == 0:
        return Decimal(0)
    sign = 1 if coefficient < 0 else 0
    digits = tuple(int(digit) for digit in str(abs(coefficient)))
    return Decimal((sign, digits, exponent))


def _scaled_total(values: Iterable[Decimal]) -> tuple[int, int]:
    parts = [_parts(value) for value in values]
    if not parts:
        return 0, 0
    exponent = min(item[1] for item in parts)
    total: int = sum(
        (coefficient * 10 ** (item_exponent - exponent) for coefficient, item_exponent in parts),
        0,
    )
    return total, exponent


def exact_decimal_sum(values: Iterable[Decimal]) -> Decimal:
    """Return the exact finite-Decimal sum without using the active context."""

    coefficient, exponent = _scaled_total(values)
    return _from_parts(coefficient, exponent)


def exact_sum_equals_one(values: Iterable[Decimal]) -> bool:
    """Return whether the exact sum of finite Decimals is mathematically one."""

    parts = [_parts(value) for value in values]
    if not parts:
        return False
    exponents: list[int] = [item_exponent for _, item_exponent in parts]
    exponent: int = min([0, *exponents])
    total: int = sum(
        (coefficient * 10 ** (item_exponent - exponent) for coefficient, item_exponent in parts),
        0,
    )
    target: int = 10 ** (0 - exponent)
    return bool(total == target)


def exact_sum_leq_one(values: Iterable[Decimal]) -> bool:
    """Return whether the exact sum of finite Decimals is at most one."""

    parts = [_parts(value) for value in values]
    exponents: list[int] = [item_exponent for _, item_exponent in parts]
    exponent: int = min([0, *exponents])
    total: int = sum(
        (coefficient * 10 ** (item_exponent - exponent) for coefficient, item_exponent in parts),
        0,
    )
    target: int = 10 ** (0 - exponent)
    return bool(total <= target)


def exact_one_minus(value: Decimal) -> Decimal:
    """Construct the exact finite Decimal residual ``1 - value``."""

    coefficient, value_exponent = _parts(value)
    exponent = min(0, value_exponent)
    residual = 10 ** (0 - exponent) - coefficient * 10 ** (value_exponent - exponent)
    return _from_parts(residual, exponent)
