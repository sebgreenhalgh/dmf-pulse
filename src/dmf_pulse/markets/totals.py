"""Bounded Stage-6 full-time 90-minute two-way totals normalisation.

This module deliberately supplements, rather than changes, the frozen
``FULL_TIME_1X2`` persistence contracts.  It is used by the private transient
GW1 bridge and keeps every totals quote bound to one exact half-goal line.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
from itertools import combinations
from uuid import UUID

from pydantic import Field, field_serializer, field_validator, model_validator

from dmf_pulse.markets.consensus import _confidence_grade, _confidence_warning_flags
from dmf_pulse.markets.models import (
    ExcludedBook,
    ExclusionReason,
    MarketFreshness,
    MarketState,
    NormalisationMethod,
    Probability,
    PublicDecimal12,
    _FrozenModel,
    source_decimal_text,
)
from dmf_pulse.markets.normalisation import (
    MarketNormalisationError,
    _compute_market,
    _overround12,
    _public_vector,
    _q12,
    code_identity,
)
from dmf_pulse.markets.policy import (
    ConsensusPolicy,
    canonical_json_sha256,
    require_authenticated_policy,
)


class TotalsOutcome(StrEnum):
    OVER = "OVER"
    UNDER = "UNDER"


_OUTCOMES = (TotalsOutcome.OVER, TotalsOutcome.UNDER)


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketNormalisationError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _half_goal(value: Decimal, label: str) -> Decimal:
    if not value.is_finite() or value < 0 or value % 1 != Decimal("0.5"):
        raise MarketNormalisationError(f"{label} must be a nonnegative half-goal line")
    return value


class FullTimeTotalsQuote(_FrozenModel):
    """A raw, immutable, line-specific provider observation for O/U totals."""

    fixture_id: UUID
    market_id: UUID
    selection_id: UUID
    operator_id: UUID
    operator_key: str = Field(min_length=1)
    provider_id: UUID
    outcome: TotalsOutcome
    line: Decimal
    decimal_odds: Decimal = Field(gt=Decimal("1"))
    observed_at: datetime
    received_at: datetime
    usable_at: datetime
    source_snapshot_id: UUID
    book_observation_id: UUID
    odds_observation_id: UUID
    market_state: MarketState = MarketState.COMPLETE
    period: str = "FULL_TIME"
    settlement_profile: str = "FULL_TIME_90"
    contract_version: str = Field(min_length=1, max_length=120)

    @field_validator("line")
    @classmethod
    def validate_line(cls, value: Decimal) -> Decimal:
        return _half_goal(value, "line")

    @field_validator("decimal_odds", mode="before")
    @classmethod
    def validate_odds(cls, value: object) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, str):
            return Decimal(value)
        raise ValueError("decimal odds must be source-scale Decimal text")

    @field_serializer("decimal_odds")
    def serialize_odds(self, value: Decimal) -> str:
        return source_decimal_text(value)

    @model_validator(mode="after")
    def validate_quote(self) -> FullTimeTotalsQuote:
        if (
            not self.decimal_odds.is_finite()
            or self.market_state is not MarketState.COMPLETE
            or self.period != "FULL_TIME"
            or self.settlement_profile != "FULL_TIME_90"
            or not self.observed_at <= self.received_at <= self.usable_at
        ):
            raise ValueError("totals quote violates the bounded full-time contract")
        return self


class NormalisedTotalsOutcome(_FrozenModel):
    outcome: TotalsOutcome
    decimal_odds: Decimal = Field(gt=Decimal("1"))
    raw_implied_probability: Probability
    proportional_probability: Probability
    market_probability: Probability

    @field_serializer("decimal_odds")
    def serialize_odds(self, value: Decimal) -> str:
        return source_decimal_text(value)


class NormalisedTotalsOperatorMarket(_FrozenModel):
    fixture_id: UUID
    market_id: UUID
    provider_id: UUID
    operator_id: UUID
    operator_key: str = Field(min_length=1)
    as_of: datetime
    observed_at: datetime
    usable_at: datetime
    period: str = "FULL_TIME"
    settlement_profile: str = "FULL_TIME_90"
    line: Decimal
    market_state: MarketState = MarketState.COMPLETE
    primary_method: NormalisationMethod
    fallback_used: bool
    raw_booksum: PublicDecimal12
    overround: PublicDecimal12
    power_exponent: PublicDecimal12 | None
    outcomes: tuple[NormalisedTotalsOutcome, NormalisedTotalsOutcome]
    policy_id: str = Field(min_length=1)
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_signature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_observation_ids: tuple[UUID, UUID]

    @field_validator("line")
    @classmethod
    def validate_line(cls, value: Decimal) -> Decimal:
        return _half_goal(value, "line")

    @model_validator(mode="after")
    def validate_result(self) -> NormalisedTotalsOperatorMarket:
        if (
            tuple(item.outcome for item in self.outcomes) != _OUTCOMES
            or len(set(self.source_observation_ids)) != 2
            or self.period != "FULL_TIME"
            or self.settlement_profile != "FULL_TIME_90"
            or self.market_state is not MarketState.COMPLETE
            or self.observed_at > self.usable_at
            or self.usable_at > self.as_of
            or sum(item.proportional_probability for item in self.outcomes) != Decimal(1)
            or sum(item.market_probability for item in self.outcomes) != Decimal(1)
        ):
            raise ValueError("normalised totals result is inconsistent")
        if self.fallback_used and (
            self.primary_method is not NormalisationMethod.PROPORTIONAL
            or self.power_exponent is not None
            or any(
                item.market_probability != item.proportional_probability for item in self.outcomes
            )
        ):
            raise ValueError("totals power fallback is inconsistent")
        return self


class TotalsConsensusOutcome(_FrozenModel):
    outcome: TotalsOutcome
    consensus_probability: Probability
    lower_bound: Probability
    upper_bound: Probability

    @model_validator(mode="after")
    def validate_bounds(self) -> TotalsConsensusOutcome:
        if not self.lower_bound <= self.consensus_probability <= self.upper_bound:
            raise ValueError("totals consensus is outside its bounds")
        return self


class FullTimeTotalsConsensus(_FrozenModel):
    """Auditable two-way consensus for a single full-time half-goal line."""

    fixture_id: UUID
    as_of: datetime
    mapping_cutoff: datetime
    market_definition: str = "FULL_TIME_TOTALS"
    period: str = "FULL_TIME"
    settlement_profile: str = "FULL_TIME_90"
    line: Decimal
    provider_count: int = Field(ge=1)
    operator_count: int = Field(ge=1)
    eligible_operator_count: int = Field(ge=1)
    operator_markets: tuple[NormalisedTotalsOperatorMarket, ...] = Field(min_length=1)
    outcomes: tuple[TotalsConsensusOutcome, TotalsConsensusOutcome]
    operator_disagreement: Probability
    method_disagreement: Probability
    market_disagreement: Probability
    freshness: MarketFreshness
    confidence_grade: str = Field(pattern=r"^[ABCD]$")
    policy_id: str = Field(min_length=1)
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_signature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("line")
    @classmethod
    def validate_line(cls, value: Decimal) -> Decimal:
        return _half_goal(value, "line")

    @model_validator(mode="after")
    def validate_consensus(self) -> FullTimeTotalsConsensus:
        if (
            self.market_definition != "FULL_TIME_TOTALS"
            or self.period != "FULL_TIME"
            or self.settlement_profile != "FULL_TIME_90"
            or self.mapping_cutoff > self.as_of
            or tuple(item.outcome for item in self.outcomes) != _OUTCOMES
            or sum(item.consensus_probability for item in self.outcomes) != Decimal(1)
            or self.eligible_operator_count != len(self.operator_markets)
            or self.operator_count != len({item.operator_id for item in self.operator_markets})
            or self.provider_count != len({item.provider_id for item in self.operator_markets})
            or self.market_disagreement != max(self.operator_disagreement, self.method_disagreement)
            or any(item.line != self.line for item in self.operator_markets)
        ):
            raise ValueError("full-time totals consensus is inconsistent")
        return self


@dataclass(frozen=True, slots=True)
class TotalsConsensusEvaluation:
    consensus: FullTimeTotalsConsensus | None
    exclusions: tuple[ExcludedBook, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _EligibleTotals:
    result: NormalisedTotalsOperatorMarket
    power_internal: tuple[Decimal, Decimal]
    proportional_internal: tuple[Decimal, Decimal]
    age_seconds: int


def _tv(left: tuple[Decimal, Decimal], right: tuple[Decimal, Decimal]) -> Decimal:
    return sum((abs(a - b) for a, b in zip(left, right, strict=True)), Decimal(0)) / Decimal(2)


def _book_sort_key(quotes: Sequence[FullTimeTotalsQuote]) -> tuple[datetime, datetime, str]:
    return (
        max(quote.usable_at for quote in quotes),
        max(quote.observed_at for quote in quotes),
        str(quotes[0].book_observation_id),
    )


def _ordered_book(
    quotes: Sequence[FullTimeTotalsQuote],
) -> tuple[FullTimeTotalsQuote, FullTimeTotalsQuote] | None:
    if len(quotes) != 2:
        return None
    first = quotes[0]
    by_outcome = {quote.outcome: quote for quote in quotes}
    if set(by_outcome) != set(_OUTCOMES) or len(by_outcome) != len(quotes):
        return None
    ordered = (by_outcome[TotalsOutcome.OVER], by_outcome[TotalsOutcome.UNDER])
    if (
        len({quote.fixture_id for quote in ordered}) != 1
        or len({quote.market_id for quote in ordered}) != 1
        or len({quote.provider_id for quote in ordered}) != 1
        or len({quote.operator_id for quote in ordered}) != 1
        or len({quote.operator_key for quote in ordered}) != 1
        or len({quote.book_observation_id for quote in ordered}) != 1
        or len({quote.line for quote in ordered}) != 1
        or len({quote.observed_at for quote in ordered}) != 1
        or len({quote.received_at for quote in ordered}) != 1
        or len({quote.usable_at for quote in ordered}) != 1
        or len({quote.source_snapshot_id for quote in ordered}) != 1
        or len({quote.period for quote in ordered}) != 1
        or len({quote.settlement_profile for quote in ordered}) != 1
        or first.market_state is not MarketState.COMPLETE
    ):
        return None
    return ordered


def _operator_result(
    quotes: tuple[FullTimeTotalsQuote, FullTimeTotalsQuote],
    *,
    as_of: datetime,
    mapping_cutoff: datetime,
    policy: ConsensusPolicy,
) -> tuple[NormalisedTotalsOperatorMarket, tuple[Decimal, Decimal], tuple[Decimal, Decimal]]:
    computed = _compute_market(
        (quotes[0].decimal_odds, quotes[1].decimal_odds), NormalisationMethod.POWER
    )
    proportional = _public_vector(computed.proportional)
    primary = _public_vector(computed.primary)
    if len(proportional) != 2 or len(primary) != 2:  # pragma: no cover - numerical invariant
        raise MarketNormalisationError("two-way totals vector has invalid length")
    input_signature = canonical_json_sha256(
        {
            "as_of": as_of.isoformat(),
            "code_identity": code_identity(),
            "line": format(quotes[0].line, "f"),
            "mapping_cutoff": mapping_cutoff.isoformat(),
            "market_definition": "FULL_TIME_TOTALS",
            "method": NormalisationMethod.POWER.value,
            "policy_sha256": policy.sha256,
            "source_observation_ids": sorted(str(item.odds_observation_id) for item in quotes),
        }
    )
    result_material = {
        "as_of": as_of.isoformat(),
        "fixture_id": str(quotes[0].fixture_id),
        "input_signature_sha256": input_signature,
        "line": format(quotes[0].line, "f"),
        "mapping_cutoff": mapping_cutoff.isoformat(),
        "market_definition": "FULL_TIME_TOTALS",
        "operator_id": str(quotes[0].operator_id),
        "operator_key": quotes[0].operator_key,
        "outcomes": [
            {
                "decimal_odds": source_decimal_text(quote.decimal_odds),
                "market_probability": format(primary[index], ".12f"),
                "outcome": quote.outcome.value,
                "proportional_probability": format(proportional[index], ".12f"),
                "raw_implied_probability": format(_q12(computed.raw[index]), ".12f"),
            }
            for index, quote in enumerate(quotes)
        ],
        "overround": format(_overround12(computed.booksum), ".12f"),
        "policy_id": policy.policy_id,
        "policy_sha256": policy.sha256,
        "power_exponent": (
            format(_q12(computed.alpha), ".12f") if computed.alpha is not None else None
        ),
        "primary_method": computed.primary_method.value,
        "provider_id": str(quotes[0].provider_id),
        "raw_booksum": format(_q12(computed.booksum), ".12f"),
        "source_observation_ids": [str(item.odds_observation_id) for item in quotes],
        "usable_at": quotes[0].usable_at.isoformat(),
    }
    result = NormalisedTotalsOperatorMarket(
        fixture_id=quotes[0].fixture_id,
        market_id=quotes[0].market_id,
        provider_id=quotes[0].provider_id,
        operator_id=quotes[0].operator_id,
        operator_key=quotes[0].operator_key,
        as_of=as_of,
        observed_at=quotes[0].observed_at,
        usable_at=quotes[0].usable_at,
        line=quotes[0].line,
        primary_method=computed.primary_method,
        fallback_used=computed.fallback_used,
        raw_booksum=_q12(computed.booksum),
        overround=_overround12(computed.booksum),
        power_exponent=_q12(computed.alpha) if computed.alpha is not None else None,
        outcomes=tuple(
            NormalisedTotalsOutcome(
                outcome=quote.outcome,
                decimal_odds=quote.decimal_odds,
                raw_implied_probability=_q12(computed.raw[index]),
                proportional_probability=proportional[index],
                market_probability=primary[index],
            )
            for index, quote in enumerate(quotes)
        ),  # type: ignore[arg-type]
        policy_id=policy.policy_id,
        policy_sha256=policy.sha256,
        input_signature_sha256=input_signature,
        result_sha256=canonical_json_sha256(result_material),
        source_observation_ids=(quotes[0].odds_observation_id, quotes[1].odds_observation_id),
    )
    return (
        result,
        (computed.primary[0], computed.primary[1]),
        (
            computed.proportional[0],
            computed.proportional[1],
        ),
    )


def evaluate_full_time_totals_consensus(
    quotes: Sequence[FullTimeTotalsQuote],
    *,
    as_of: datetime,
    mapping_cutoff: datetime,
    policy: ConsensusPolicy,
    initial_warnings: Sequence[str] = (),
) -> TotalsConsensusEvaluation:
    """Normalise eligible O/U books and produce one line-specific consensus."""

    require_authenticated_policy(policy)
    cutoff = _utc(as_of, "as_of")
    mapping = _utc(mapping_cutoff, "mapping_cutoff")
    warnings = set(initial_warnings)
    exclusions: list[ExcludedBook] = []
    if not quotes:
        return TotalsConsensusEvaluation(None, (), tuple(sorted(warnings | {"TOTALS_UNAVAILABLE"})))
    if len({quote.fixture_id for quote in quotes}) != 1:
        raise MarketNormalisationError("totals quotes span multiple fixtures")
    if len({quote.line for quote in quotes}) != 1:
        raise MarketNormalisationError("totals quotes span multiple lines")
    grouped: dict[UUID, list[FullTimeTotalsQuote]] = {}
    for quote in quotes:
        grouped.setdefault(quote.book_observation_id, []).append(quote)
    by_operator: dict[UUID, list[list[FullTimeTotalsQuote]]] = {}
    for book in grouped.values():
        by_operator.setdefault(book[0].operator_id, []).append(book)

    eligible: list[_EligibleTotals] = []
    for candidates in by_operator.values():
        candidates.sort(key=_book_sort_key, reverse=True)
        for candidate in candidates:
            operator_key = candidate[0].operator_key
            ordered = _ordered_book(candidate)
            reason: ExclusionReason | None = None
            if ordered is None:
                reason = ExclusionReason.INCOMPLETE
            elif any(item.observed_at > cutoff or item.usable_at > cutoff for item in ordered):
                reason = ExclusionReason.FUTURE_OBSERVATION
            elif cutoff - ordered[0].observed_at > timedelta(
                seconds=policy.freshness.stale_after_seconds
            ):
                reason = ExclusionReason.STALE
            if reason is not None:
                exclusions.append(ExcludedBook(operator_key=operator_key, reason=reason))
                warnings.add(f"TOTALS_BOOK_EXCLUDED_{reason.value}")
                continue
            if ordered is None:  # pragma: no cover - guarded by the reason branch above
                raise MarketNormalisationError("totals book is unexpectedly absent")
            result, power, proportional = _operator_result(
                ordered,
                as_of=cutoff,
                mapping_cutoff=mapping,
                policy=policy,
            )
            if result.fallback_used:
                warnings.add("TOTALS_POWER_FALLBACK_PROPORTIONAL")
            eligible.append(
                _EligibleTotals(
                    result=result,
                    power_internal=power,
                    proportional_internal=proportional,
                    age_seconds=int((cutoff - result.observed_at).total_seconds()),
                )
            )
            break

    exclusions = sorted(set(exclusions), key=lambda item: (item.operator_key, item.reason.value))
    ordered_warnings = tuple(sorted(warnings))
    if not eligible:
        return TotalsConsensusEvaluation(None, tuple(exclusions), ordered_warnings)
    eligible.sort(key=lambda item: (item.result.operator_key, str(item.result.operator_id)))
    with localcontext() as context:
        context.prec = 60
        count = Decimal(len(eligible))
        consensus_internal = tuple(
            sum((item.power_internal[index] for item in eligible), Decimal(0)) / count
            for index in range(2)
        )
        consensus_public = _public_vector(consensus_internal)
        operator_disagreement = max(
            (
                _tv(left.power_internal, right.power_internal)
                for left, right in combinations(eligible, 2)
            ),
            default=Decimal(0),
        )
        method_disagreement = max(
            (_tv(item.power_internal, item.proportional_internal) for item in eligible),
            default=Decimal(0),
        )
        disagreement = max(operator_disagreement, method_disagreement)
    public_vectors = [
        tuple(row.market_probability for row in item.result.outcomes) for item in eligible
    ] + [tuple(row.proportional_probability for row in item.result.outcomes) for item in eligible]
    rows = tuple(
        TotalsConsensusOutcome(
            outcome=outcome,
            consensus_probability=consensus_public[index],
            lower_bound=min(vector[index] for vector in public_vectors),
            upper_bound=max(vector[index] for vector in public_vectors),
        )
        for index, outcome in enumerate(_OUTCOMES)
    )
    ages = [item.age_seconds for item in eligible]
    fallback = any(item.result.fallback_used for item in eligible)
    has_warning, has_blocking_warning = _confidence_warning_flags(
        exclusions, ordered_warnings, fallback_used=fallback
    )
    confidence = _confidence_grade(
        operator_count=len(eligible),
        maximum_age_seconds=max(ages),
        disagreement=disagreement,
        fallback_used=fallback,
        policy=policy,
        has_warning=has_warning,
        has_blocking_warning=has_blocking_warning,
    )
    input_signature = canonical_json_sha256(
        {
            "as_of": cutoff.isoformat(),
            "code_identity": code_identity(),
            "line": format(eligible[0].result.line, "f"),
            "mapping_cutoff": mapping.isoformat(),
            "market_definition": "FULL_TIME_TOTALS",
            "policy_sha256": policy.sha256,
            "source_observation_ids": sorted(str(quote.odds_observation_id) for quote in quotes),
            "warnings": list(ordered_warnings),
        }
    )
    result_material = {
        "as_of": cutoff.isoformat(),
        "confidence_grade": confidence,
        "eligible_operator_count": len(eligible),
        "freshness": {"maximum_age_seconds": max(ages), "minimum_age_seconds": min(ages)},
        "fixture_id": str(eligible[0].result.fixture_id),
        "input_signature_sha256": input_signature,
        "line": format(eligible[0].result.line, "f"),
        "mapping_cutoff": mapping.isoformat(),
        "market_definition": "FULL_TIME_TOTALS",
        "market_disagreement": format(_q12(disagreement), ".12f"),
        "method_disagreement": format(_q12(method_disagreement), ".12f"),
        "operator_count": len(eligible),
        "operator_disagreement": format(_q12(operator_disagreement), ".12f"),
        "operator_result_sha256": [item.result.result_sha256 for item in eligible],
        "outcomes": [
            {
                "consensus_probability": format(row.consensus_probability, ".12f"),
                "lower_bound": format(row.lower_bound, ".12f"),
                "outcome": row.outcome.value,
                "upper_bound": format(row.upper_bound, ".12f"),
            }
            for row in rows
        ],
        "policy_id": policy.policy_id,
        "policy_sha256": policy.sha256,
        "provider_count": len({item.result.provider_id for item in eligible}),
        "warnings": list(ordered_warnings),
    }
    return TotalsConsensusEvaluation(
        FullTimeTotalsConsensus(
            fixture_id=eligible[0].result.fixture_id,
            as_of=cutoff,
            mapping_cutoff=mapping,
            line=eligible[0].result.line,
            provider_count=len({item.result.provider_id for item in eligible}),
            operator_count=len({item.result.operator_id for item in eligible}),
            eligible_operator_count=len(eligible),
            operator_markets=tuple(item.result for item in eligible),
            outcomes=(rows[0], rows[1]),
            operator_disagreement=_q12(operator_disagreement),
            method_disagreement=_q12(method_disagreement),
            market_disagreement=_q12(disagreement),
            freshness=MarketFreshness(minimum_age_seconds=min(ages), maximum_age_seconds=max(ages)),
            confidence_grade=confidence,
            policy_id=policy.policy_id,
            policy_sha256=policy.sha256,
            input_signature_sha256=input_signature,
            result_sha256=canonical_json_sha256(result_material),
        ),
        tuple(exclusions),
        ordered_warnings,
    )


__all__ = [
    "FullTimeTotalsConsensus",
    "FullTimeTotalsQuote",
    "NormalisedTotalsOperatorMarket",
    "TotalsConsensusEvaluation",
    "TotalsOutcome",
    "evaluate_full_time_totals_consensus",
]
