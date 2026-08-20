"""Deterministic operator grouping, consensus, uncertainty and confidence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from itertools import combinations
from typing import cast

from dmf_pulse.markets.models import (
    ConsensusOutcome,
    ExcludedBook,
    ExclusionReason,
    ExclusiveOutcomeQuote,
    MarketConsensus,
    MarketFreshness,
    MarketObservation,
    MarketOutcome,
    MarketState,
    NormalisationMethod,
    NormalisedOperatorMarket,
)
from dmf_pulse.markets.normalisation import (
    MarketNormalisationError,
    _build_operator_result,
    _compute_market,
    _ordered_quotes,
    _public_vector,
    _q12,
    code_identity,
)
from dmf_pulse.markets.policy import (
    CONFIDENCE_GATE_POLICY_SHA256,
    CONFIDENCE_GRADES,
    ConfidenceGrade,
    ConsensusPolicy,
    canonical_json_sha256,
    load_confidence_gate_policy,
    require_authenticated_policy,
)

_OUTCOMES = tuple(MarketOutcome)
_NON_BLOCKING_EXCLUSION_REASONS = frozenset(ExclusionReason)
_EXPLICIT_BLOCKING_WARNING_PREFIXES = (
    "BLOCKING_",
    "MODEL_BLOCKING_",
    "QUALITY_BLOCKING_",
)


class NoEligibleMarketError(MarketNormalisationError):
    """No complete, fresh, temporally eligible operator book remains."""

    def __init__(self, exclusions: tuple[ExcludedBook, ...], warnings: tuple[str, ...]) -> None:
        super().__init__("no eligible complete operator book")
        self.exclusions = exclusions
        self.warnings = warnings


@dataclass(frozen=True, slots=True)
class ConsensusEvaluation:
    consensus: MarketConsensus | None
    exclusions: tuple[ExcludedBook, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _EligibleMarket:
    result: NormalisedOperatorMarket
    power_internal: tuple[Decimal, Decimal, Decimal]
    proportional_internal: tuple[Decimal, Decimal, Decimal]
    age_seconds: int


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketNormalisationError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _reason_for_state(state: MarketState) -> ExclusionReason:
    return {
        MarketState.INCOMPLETE: ExclusionReason.INCOMPLETE,
        MarketState.SUSPENDED: ExclusionReason.SUSPENDED,
        MarketState.UNSUPPORTED: ExclusionReason.UNSUPPORTED,
        MarketState.UNAVAILABLE: ExclusionReason.UNAVAILABLE,
    }[state]


def _book_sort_key(
    quotes: Sequence[ExclusiveOutcomeQuote],
) -> tuple[datetime, datetime, str]:
    return (
        max(quote.usable_at for quote in quotes),
        max(quote.observed_at for quote in quotes),
        str(quotes[0].book_observation_id),
    )


def _tv(
    left: tuple[Decimal, Decimal, Decimal],
    right: tuple[Decimal, Decimal, Decimal],
) -> Decimal:
    return sum((abs(a - b) for a, b in zip(left, right, strict=True)), start=Decimal(0)) / 2


def _confidence_grade(
    *,
    operator_count: int,
    maximum_age_seconds: int,
    disagreement: Decimal,
    fallback_used: bool,
    policy: ConsensusPolicy,
    has_warning: bool = False,
    has_blocking_warning: bool = False,
) -> ConfidenceGrade:
    require_authenticated_policy(policy)
    gate_policy = load_confidence_gate_policy()
    if gate_policy.normalisation_policy_sha256 != policy.sha256:
        raise MarketNormalisationError("confidence gate policy identity is inconsistent")
    for grade in CONFIDENCE_GRADES:
        threshold = getattr(policy.confidence, grade)
        gate = getattr(gate_policy.grades, grade)
        if operator_count < threshold.minimum_operators:
            continue
        if (
            threshold.maximum_age_seconds is not None
            and maximum_age_seconds > threshold.maximum_age_seconds
        ):
            continue
        if threshold.maximum_disagreement is not None and disagreement > Decimal(
            threshold.maximum_disagreement
        ):
            continue
        if fallback_used and not gate.fallback_allowed:
            continue
        if has_blocking_warning and gate.maximum_warning_level != "BLOCKING":
            continue
        if has_warning and gate.maximum_warning_level == "NONE":
            continue
        return grade
    raise MarketNormalisationError("confidence policy rejects an eligible market")


def _confidence_warning_flags(
    exclusions: Sequence[ExcludedBook],
    warnings: Sequence[str],
    *,
    fallback_used: bool,
) -> tuple[bool, bool]:
    """Classify degradation evidence without making every exclusion blocking.

    Exclusions are public evidence of a degraded result, but the frozen H2
    contract makes every current exclusion reason non-blocking solely by its
    presence.  Blocking severity is reserved for a normalisation fallback or
    an explicitly typed model/quality warning.  The helper is deliberately
    pure so its policy boundary is easy to exercise without changing the
    consensus math or persistence shape.
    """

    has_warning = bool(exclusions or warnings)
    all_exclusions_are_non_blocking = all(
        exclusion.reason in _NON_BLOCKING_EXCLUSION_REASONS for exclusion in exclusions
    )
    has_explicit_blocking_warning = any(
        warning.startswith(_EXPLICIT_BLOCKING_WARNING_PREFIXES) for warning in warnings
    )
    has_blocking_warning = (
        fallback_used or has_explicit_blocking_warning or not all_exclusions_are_non_blocking
    )
    return has_warning, has_blocking_warning


def _group_observations(
    observations: Sequence[MarketObservation],
) -> dict[str, list[ExclusiveOutcomeQuote]]:
    grouped: dict[str, list[ExclusiveOutcomeQuote]] = {}
    for observation in observations:
        if not isinstance(observation, ExclusiveOutcomeQuote):
            raise MarketNormalisationError(
                "consensus requires canonical observation IDs, provider IDs, and operator keys"
            )
        key = str(observation.book_observation_id)
        grouped.setdefault(key, []).append(observation)
    return grouped


def evaluate_market_consensus(
    observations: Sequence[MarketObservation],
    *,
    as_of: datetime,
    mapping_cutoff: datetime,
    policy: ConsensusPolicy,
    initial_exclusions: Sequence[ExcludedBook] = (),
    initial_warnings: Sequence[str] = (),
) -> ConsensusEvaluation:
    """Evaluate all candidate books and retain typed degradation evidence."""

    require_authenticated_policy(policy)
    cutoff = _utc(as_of, "as_of")
    mapping_time = _utc(mapping_cutoff, "mapping_cutoff")
    if len({observation.fixture_id for observation in observations}) > 1:
        raise MarketNormalisationError("consensus observations span multiple fixtures")
    grouped = _group_observations(observations)
    exclusions = list(initial_exclusions)
    warnings = list(initial_warnings)
    candidates_by_operator: dict[str, list[list[ExclusiveOutcomeQuote]]] = {}

    for quotes in grouped.values():
        candidates_by_operator.setdefault(str(quotes[0].operator_id), []).append(quotes)

    eligible: list[_EligibleMarket] = []
    for candidates in candidates_by_operator.values():
        candidates.sort(key=_book_sort_key, reverse=True)
        selected: list[ExclusiveOutcomeQuote] | None = None
        for candidate in candidates:
            operator_key = candidate[0].operator_key
            reason: ExclusionReason | None = None
            states = {quote.market_state for quote in candidate}
            if len(states) != 1:
                reason = ExclusionReason.QUALITY_BLOCKED
            else:
                state = states.pop()
                if state is not MarketState.COMPLETE:
                    reason = _reason_for_state(state)
            if reason is None and (
                len(candidate) != 3 or {quote.outcome for quote in candidate} != set(_OUTCOMES)
            ):
                reason = ExclusionReason.INCOMPLETE
            if reason is None and any(
                quote.observed_at > cutoff or quote.usable_at > cutoff for quote in candidate
            ):
                reason = ExclusionReason.FUTURE_OBSERVATION
            if reason is None:
                latest_observed = max(quote.observed_at for quote in candidate)
                if cutoff - latest_observed > timedelta(
                    seconds=policy.freshness.stale_after_seconds
                ):
                    reason = ExclusionReason.STALE
            if reason is not None:
                exclusions.append(ExcludedBook(operator_key=operator_key, reason=reason))
                warnings.append(f"BOOK_EXCLUDED_{reason.value}")
                continue
            selected = candidate
            break
        if selected is None:
            continue
        ordered = _ordered_quotes(selected)
        computed = _compute_market(
            (ordered[0].decimal_odds, ordered[1].decimal_odds, ordered[2].decimal_odds),
            NormalisationMethod.POWER,
        )
        result = _build_operator_result(
            ordered,
            computed,
            method=NormalisationMethod.POWER,
            policy=policy,
            result_as_of=cutoff,
            mapping_cutoff=mapping_time,
        )
        if computed.fallback_used:
            warnings.append("POWER_FALLBACK_PROPORTIONAL")
            if computed.fallback_diagnostic is None:
                raise MarketNormalisationError("power fallback diagnostic is unavailable")
            warnings.append(f"POWER_FALLBACK_DIAGNOSTIC:{computed.fallback_diagnostic}")
        primary = computed.primary
        eligible.append(
            _EligibleMarket(
                result=result,
                power_internal=cast(tuple[Decimal, Decimal, Decimal], primary),
                proportional_internal=cast(tuple[Decimal, Decimal, Decimal], computed.proportional),
                age_seconds=int((cutoff - result.observed_at).total_seconds()),
            )
        )

    exclusions = sorted(set(exclusions), key=lambda item: (item.operator_key, item.reason.value))
    warnings = sorted(set(warnings))
    if not eligible:
        return ConsensusEvaluation(None, tuple(exclusions), tuple(warnings))
    eligible.sort(key=lambda item: (item.result.operator_key, str(item.result.operator_id)))

    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_EVEN
        count = Decimal(len(eligible))
        consensus_internal = tuple(
            sum((item.power_internal[index] for item in eligible), start=Decimal(0)) / count
            for index in range(3)
        )
        consensus_public = _public_vector(
            (consensus_internal[0], consensus_internal[1], consensus_internal[2])
        )
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
        market_disagreement = max(operator_disagreement, method_disagreement)

    public_vectors = [
        tuple(outcome.market_probability for outcome in item.result.outcomes) for item in eligible
    ] + [
        tuple(outcome.proportional_probability for outcome in item.result.outcomes)
        for item in eligible
    ]
    outcome_rows = tuple(
        ConsensusOutcome(
            outcome=outcome,
            consensus_probability=consensus_public[index],
            lower_bound=min(vector[index] for vector in public_vectors),
            upper_bound=max(vector[index] for vector in public_vectors),
        )
        for index, outcome in enumerate(_OUTCOMES)
    )
    ages = [item.age_seconds for item in eligible]
    fallback_used = any(item.result.fallback_used for item in eligible)
    provider_count = len({item.result.provider_id for item in eligible})
    operator_count = len({item.result.operator_id for item in eligible})
    has_warning, has_blocking_warning = _confidence_warning_flags(
        exclusions,
        warnings,
        fallback_used=fallback_used,
    )
    confidence_grade = _confidence_grade(
        operator_count=operator_count,
        maximum_age_seconds=max(ages),
        disagreement=market_disagreement,
        fallback_used=fallback_used,
        policy=policy,
        has_warning=has_warning,
        has_blocking_warning=has_blocking_warning,
    )
    exclusion_material = [item.model_dump(mode="json") for item in exclusions]
    input_signature = canonical_json_sha256(
        {
            "as_of": cutoff.isoformat(),
            "code_identity": code_identity(),
            "confidence_gate_policy_sha256": CONFIDENCE_GATE_POLICY_SHA256,
            "exclusions": exclusion_material,
            "mapping_cutoff": mapping_time.isoformat(),
            "policy_sha256": policy.sha256,
            "source_book_observation_ids": sorted(
                {
                    str(observation.book_observation_id)
                    for observation in observations
                    if isinstance(observation, ExclusiveOutcomeQuote)
                }
            ),
            "source_observation_ids": sorted(
                str(observation.odds_observation_id)
                for observation in observations
                if isinstance(observation, ExclusiveOutcomeQuote)
            ),
            "warnings": warnings,
        }
    )
    result_material = {
        "as_of": cutoff.isoformat(),
        "confidence_grade": confidence_grade,
        "eligible_operator_count": len(eligible),
        "exclusions": exclusion_material,
        "freshness": {
            "maximum_age_seconds": max(ages),
            "minimum_age_seconds": min(ages),
        },
        "fixture_id": str(eligible[0].result.fixture_id),
        "input_signature_sha256": input_signature,
        "mapping_cutoff": mapping_time.isoformat(),
        "market_definition": "FULL_TIME_1X2",
        "market_disagreement": format(_q12(market_disagreement), ".12f"),
        "method_disagreement": format(_q12(method_disagreement), ".12f"),
        "operator_count": operator_count,
        "operator_disagreement": format(_q12(operator_disagreement), ".12f"),
        "operator_result_sha256": [item.result.result_sha256 for item in eligible],
        "outcomes": [
            {
                "consensus_probability": format(row.consensus_probability, ".12f"),
                "lower_bound": format(row.lower_bound, ".12f"),
                "outcome": row.outcome.value,
                "upper_bound": format(row.upper_bound, ".12f"),
            }
            for row in outcome_rows
        ],
        "policy_sha256": policy.sha256,
        "policy_id": policy.policy_id,
        "provider_count": provider_count,
        "warnings": warnings,
    }
    consensus = MarketConsensus(
        fixture_id=eligible[0].result.fixture_id,
        as_of=cutoff,
        mapping_cutoff=mapping_time,
        market_definition="FULL_TIME_1X2",
        provider_count=provider_count,
        operator_count=operator_count,
        eligible_operator_count=len(eligible),
        operator_markets=tuple(item.result for item in eligible),
        outcomes=(outcome_rows[0], outcome_rows[1], outcome_rows[2]),
        operator_disagreement=_q12(operator_disagreement),
        method_disagreement=_q12(method_disagreement),
        market_disagreement=_q12(market_disagreement),
        freshness=MarketFreshness(minimum_age_seconds=min(ages), maximum_age_seconds=max(ages)),
        confidence_grade=confidence_grade,
        policy_id=policy.policy_id,
        policy_sha256=policy.sha256,
        input_signature_sha256=input_signature,
        result_sha256=canonical_json_sha256(result_material),
    )
    return ConsensusEvaluation(consensus, tuple(exclusions), tuple(warnings))


def build_market_consensus(
    observations: Sequence[MarketObservation],
    *,
    as_of: datetime,
    mapping_cutoff: datetime,
    policy: ConsensusPolicy,
) -> MarketConsensus:
    """Build the frozen equal-canonical-operator Stage A6 consensus."""

    evaluation = evaluate_market_consensus(
        observations,
        as_of=as_of,
        mapping_cutoff=mapping_cutoff,
        policy=policy,
    )
    if evaluation.consensus is None:
        raise NoEligibleMarketError(evaluation.exclusions, evaluation.warnings)
    return evaluation.consensus


__all__ = [
    "ConsensusEvaluation",
    "NoEligibleMarketError",
    "build_market_consensus",
    "evaluate_market_consensus",
]
