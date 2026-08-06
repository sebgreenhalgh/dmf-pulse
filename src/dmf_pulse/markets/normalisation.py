"""Pure exact odds normalisation for complete mutually-exclusive markets."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import (
    ROUND_HALF_EVEN,
    Decimal,
    DecimalException,
    InvalidOperation,
    localcontext,
)
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from dmf_pulse import __version__
from dmf_pulse.markets.models import (
    ExclusiveOutcomeQuote,
    MarketOutcome,
    MarketState,
    NormalisationMethod,
    NormalisedOperatorMarket,
    NormalisedOutcome,
    Probability,
    source_decimal_text,
)
from dmf_pulse.markets.policy import (
    MarketNormalisationPolicy,
    canonical_json_sha256,
    require_authenticated_policy,
)

_ONE = Decimal(1)
_TWO = Decimal(2)
_PUBLIC_SCALE = Decimal("0.000000000001")
_OUTCOMES = tuple(MarketOutcome)


class MarketNormalisationError(ValueError):
    """Typed validation failure outside the accepted numerical domain."""


class PowerNormalisationError(ArithmeticError):
    """Typed numerical failure that alone permits proportional fallback."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _source_build_sha256(package_root: Path) -> str:
    """Hash the exact installed Python sources that define the build behavior."""

    digest = sha256()
    try:
        sources = sorted(
            package_root.rglob("*.py"),
            key=lambda path: path.relative_to(package_root).as_posix(),
        )
        if not sources:
            raise OSError("package source inventory is empty")
        for path in sources:
            relative = path.relative_to(package_root).as_posix().encode("utf-8")
            body = path.read_bytes()
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            digest.update(len(body).to_bytes(8, "big"))
            digest.update(body)
    except (OSError, ValueError) as exc:
        raise MarketNormalisationError("code build identity is unavailable") from exc
    return digest.hexdigest()


@lru_cache(maxsize=1)
def code_identity() -> str:
    """Return a content-addressed identity for the exact installed package build."""

    package_root = Path(__file__).resolve().parents[1]
    return f"dmf-pulse-{__version__}:source-sha256:{_source_build_sha256(package_root)}"


@dataclass(frozen=True, slots=True)
class _ComputedMarket:
    raw: tuple[Decimal, Decimal, Decimal]
    booksum: Decimal
    proportional: tuple[Decimal, Decimal, Decimal]
    power: tuple[Decimal, Decimal, Decimal] | None
    alpha: Decimal | None
    primary: tuple[Decimal, Decimal, Decimal]
    primary_method: NormalisationMethod
    fallback_used: bool
    fallback_diagnostic: str | None = None


def _q12(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_EVEN
        return value.quantize(_PUBLIC_SCALE)


def _overround12(booksum: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_EVEN
        return (booksum - _ONE).quantize(_PUBLIC_SCALE)


def _public_vector(
    values: tuple[Decimal, Decimal, Decimal],
) -> tuple[Decimal, Decimal, Decimal]:
    rounded = [_q12(value) for value in values]
    residual = _ONE - sum(rounded, start=Decimal(0))
    winner = max(range(3), key=lambda index: (values[index], -index))
    rounded[winner] += residual
    return rounded[0], rounded[1], rounded[2]


def raw_implied_probability(decimal_odds: Decimal) -> Probability:
    """Return exact raw implied probability under the frozen Decimal context."""

    if not isinstance(decimal_odds, Decimal):
        raise MarketNormalisationError("decimal odds must be Decimal")
    if not decimal_odds.is_finite() or decimal_odds <= _ONE:
        raise MarketNormalisationError("decimal odds must be finite and greater than one")
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_EVEN
        return _ONE / decimal_odds


def _power_vector(
    raw: tuple[Decimal, Decimal, Decimal],
) -> tuple[tuple[Decimal, Decimal, Decimal], Decimal]:
    try:
        with localcontext() as context:
            context.prec = 60
            context.rounding = ROUND_HALF_EVEN

            def residual(exponent: Decimal) -> Decimal:
                return sum((value**exponent for value in raw), start=Decimal(0)) - _ONE

            if residual(_ONE) <= 0:
                lower, upper = Decimal(0), _ONE
            else:
                lower, upper = _ONE, _TWO
                while residual(upper) >= 0:
                    upper *= _TWO
                    if upper > Decimal(1024):
                        raise PowerNormalisationError(
                            "POWER_BRACKET_EXCEEDED",
                            "power exponent bracket exceeds 1024",
                        )
            for _ in range(256):
                midpoint = (lower + upper) / _TWO
                if residual(midpoint) > 0:
                    lower = midpoint
                else:
                    upper = midpoint
            alpha = (lower + upper) / _TWO
            powered = tuple(value**alpha for value in raw)
            total = sum(powered, start=Decimal(0))
            if not total.is_finite() or total <= 0:
                raise PowerNormalisationError(
                    "POWER_TOTAL_INVALID",
                    "power vector has invalid total",
                )
            result = tuple(value / total for value in powered)
            if len(result) != 3 or any(not value.is_finite() or value <= 0 for value in result):
                raise PowerNormalisationError(
                    "POWER_VECTOR_INVALID",
                    "power vector is not finite and positive",
                )
            return (result[0], result[1], result[2]), alpha
    except PowerNormalisationError:
        raise
    except (DecimalException, InvalidOperation, OverflowError) as exc:
        raise PowerNormalisationError(
            "POWER_DECIMAL_FAILURE",
            "power method failed numerically",
        ) from exc


def _compute_market(
    odds: tuple[Decimal, Decimal, Decimal], method: NormalisationMethod
) -> _ComputedMarket:
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_EVEN
        raw = tuple(raw_implied_probability(value) for value in odds)
        booksum = sum(raw, start=Decimal(0))
        if not booksum.is_finite() or booksum <= 0:
            raise MarketNormalisationError("raw booksum must be finite and positive")
        proportional = tuple(value / booksum for value in raw)
        raw_triplet = raw[0], raw[1], raw[2]
        proportional_triplet = proportional[0], proportional[1], proportional[2]
        if method is NormalisationMethod.PROPORTIONAL:
            return _ComputedMarket(
                raw=raw_triplet,
                booksum=booksum,
                proportional=proportional_triplet,
                power=None,
                alpha=None,
                primary=proportional_triplet,
                primary_method=NormalisationMethod.PROPORTIONAL,
                fallback_used=False,
                fallback_diagnostic=None,
            )
        try:
            power, alpha = _power_vector(raw_triplet)
        except PowerNormalisationError as exc:
            return _ComputedMarket(
                raw=raw_triplet,
                booksum=booksum,
                proportional=proportional_triplet,
                power=None,
                alpha=None,
                primary=proportional_triplet,
                primary_method=NormalisationMethod.PROPORTIONAL,
                fallback_used=True,
                fallback_diagnostic=exc.code,
            )
        return _ComputedMarket(
            raw=raw_triplet,
            booksum=booksum,
            proportional=proportional_triplet,
            power=power,
            alpha=alpha,
            primary=power,
            primary_method=NormalisationMethod.POWER,
            fallback_used=False,
            fallback_diagnostic=None,
        )


def _ordered_quotes(
    quotes: Sequence[ExclusiveOutcomeQuote],
) -> tuple[ExclusiveOutcomeQuote, ExclusiveOutcomeQuote, ExclusiveOutcomeQuote]:
    if len(quotes) != 3:
        raise MarketNormalisationError("complete market requires exactly three quotes")
    by_outcome: dict[MarketOutcome, ExclusiveOutcomeQuote] = {}
    for quote in quotes:
        if quote.outcome in by_outcome:
            raise MarketNormalisationError("complete market contains a duplicate outcome")
        by_outcome[quote.outcome] = quote
    if set(by_outcome) != set(_OUTCOMES):
        raise MarketNormalisationError("complete market requires HOME, DRAW, and AWAY")
    ordered = tuple(by_outcome[outcome] for outcome in _OUTCOMES)
    first = ordered[0]
    if (
        any(
            quote.fixture_id != first.fixture_id
            or quote.market_id != first.market_id
            or quote.provider_id != first.provider_id
            or quote.operator_id != first.operator_id
            or quote.operator_key != first.operator_key
            or quote.book_observation_id != first.book_observation_id
            or quote.observed_at != first.observed_at
            or quote.received_at != first.received_at
            or quote.usable_at != first.usable_at
            or quote.market_state is not MarketState.COMPLETE
            for quote in ordered
        )
        or len({quote.selection_id for quote in ordered}) != 3
        or len({quote.odds_observation_id for quote in ordered}) != 3
    ):
        raise MarketNormalisationError("quotes do not form one complete operator market")
    return ordered[0], ordered[1], ordered[2]


def _operator_input_signature(
    quotes: tuple[ExclusiveOutcomeQuote, ExclusiveOutcomeQuote, ExclusiveOutcomeQuote],
    *,
    as_of: str,
    mapping_cutoff: str,
    method: NormalisationMethod,
    policy: MarketNormalisationPolicy,
) -> str:
    return canonical_json_sha256(
        {
            "as_of": as_of,
            "code_identity": code_identity(),
            "mapping_cutoff": mapping_cutoff,
            "method": method.value,
            "policy_sha256": policy.sha256,
            "source_observation_ids": sorted(str(quote.odds_observation_id) for quote in quotes),
        }
    )


def _build_operator_result(
    quotes: tuple[ExclusiveOutcomeQuote, ExclusiveOutcomeQuote, ExclusiveOutcomeQuote],
    computed: _ComputedMarket,
    *,
    method: NormalisationMethod,
    policy: MarketNormalisationPolicy,
    result_as_of: datetime | None = None,
    mapping_cutoff: datetime | None = None,
) -> NormalisedOperatorMarket:
    as_of = result_as_of or max(quote.usable_at for quote in quotes)
    mapping_time = mapping_cutoff or as_of
    observed_at = max(quote.observed_at for quote in quotes)
    usable_at = max(quote.usable_at for quote in quotes)
    input_signature = _operator_input_signature(
        quotes,
        as_of=as_of.isoformat(),
        mapping_cutoff=mapping_time.isoformat(),
        method=method,
        policy=policy,
    )
    proportional_public = _public_vector(computed.proportional)
    primary_public = _public_vector(computed.primary)
    raw_booksum_public = _q12(computed.booksum)
    overround_public = _overround12(computed.booksum)
    power_exponent_public = _q12(computed.alpha) if computed.alpha is not None else None
    source_observation_ids = (
        quotes[0].odds_observation_id,
        quotes[1].odds_observation_id,
        quotes[2].odds_observation_id,
    )
    outcome_rows = tuple(
        NormalisedOutcome(
            outcome=quote.outcome,
            decimal_odds=quote.decimal_odds,
            raw_implied_probability=_q12(computed.raw[index]),
            proportional_probability=proportional_public[index],
            market_probability=primary_public[index],
        )
        for index, quote in enumerate(quotes)
    )
    result_material = {
        "as_of": as_of.isoformat(),
        "fallback_used": computed.fallback_used,
        "fixture_id": str(quotes[0].fixture_id),
        "input_signature_sha256": input_signature,
        "mapping_cutoff": mapping_time.isoformat(),
        "market_id": str(quotes[0].market_id),
        "market_state": MarketState.COMPLETE.value,
        "observed_at": observed_at.isoformat(),
        "operator_id": str(quotes[0].operator_id),
        "operator_key": quotes[0].operator_key,
        "outcomes": [
            {
                "decimal_odds": source_decimal_text(item.decimal_odds),
                "market_probability": format(item.market_probability, ".12f"),
                "outcome": item.outcome.value,
                "proportional_probability": format(item.proportional_probability, ".12f"),
                "raw_implied_probability": format(item.raw_implied_probability, ".12f"),
            }
            for item in outcome_rows
        ],
        "overround": format(overround_public, ".12f"),
        "policy_id": policy.policy_id,
        "policy_sha256": policy.sha256,
        "power_exponent": (
            format(power_exponent_public, ".12f") if power_exponent_public is not None else None
        ),
        "primary_method": computed.primary_method.value,
        "provider_id": str(quotes[0].provider_id),
        "raw_booksum": format(raw_booksum_public, ".12f"),
        "source_observation_ids": [str(item) for item in source_observation_ids],
        "usable_at": usable_at.isoformat(),
    }
    if computed.fallback_diagnostic is not None:
        result_material["fallback_diagnostic"] = computed.fallback_diagnostic
    return NormalisedOperatorMarket(
        fixture_id=quotes[0].fixture_id,
        market_id=quotes[0].market_id,
        provider_id=quotes[0].provider_id,
        operator_id=quotes[0].operator_id,
        operator_key=quotes[0].operator_key,
        as_of=as_of,
        observed_at=observed_at,
        usable_at=usable_at,
        market_state=MarketState.COMPLETE,
        primary_method=computed.primary_method,
        fallback_used=computed.fallback_used,
        raw_booksum=raw_booksum_public,
        overround=overround_public,
        power_exponent=power_exponent_public,
        outcomes=(outcome_rows[0], outcome_rows[1], outcome_rows[2]),
        policy_id=policy.policy_id,
        policy_sha256=policy.sha256,
        input_signature_sha256=input_signature,
        result_sha256=canonical_json_sha256(result_material),
        source_observation_ids=source_observation_ids,
    )


def normalise_complete_market(
    quotes: Sequence[ExclusiveOutcomeQuote],
    method: NormalisationMethod,
    policy: MarketNormalisationPolicy,
) -> NormalisedOperatorMarket:
    """Normalise one complete canonical operator book without side effects."""

    require_authenticated_policy(policy)
    ordered = _ordered_quotes(quotes)
    computed = _compute_market(
        (ordered[0].decimal_odds, ordered[1].decimal_odds, ordered[2].decimal_odds),
        method,
    )
    return _build_operator_result(ordered, computed, method=method, policy=policy)


__all__ = [
    "MarketNormalisationError",
    "PowerNormalisationError",
    "code_identity",
    "normalise_complete_market",
    "raw_implied_probability",
]
