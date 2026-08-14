"""Market-event design rows and Stage-6 consensus adapter for GCS-008."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from dmf_pulse.football_events._decimal import (
    DECIMAL_PRECISION,
    PROBABILITY_SCALE,
    SHA256_PATTERN,
    exact_decimal,
    format_utc,
    mapping,
    parse_utc,
    positive_decimal,
    probability,
)


class MarketFamily(StrEnum):
    ONE_X_TWO = "1X2"
    TOTALS = "TOTALS"
    TEAM_TOTAL = "TEAM_TOTAL"
    CLEAN_SHEET = "CLEAN_SHEET"
    BTTS = "BTTS"
    CORRECT_SCORE = "CORRECT_SCORE"


class ScoreEvent(StrEnum):
    HOME_WIN = "HOME_WIN"
    DRAW = "DRAW"
    AWAY_WIN = "AWAY_WIN"
    TOTAL_OVER = "TOTAL_OVER"
    TOTAL_UNDER = "TOTAL_UNDER"
    HOME_TEAM_TOTAL_OVER = "HOME_TEAM_TOTAL_OVER"
    HOME_TEAM_TOTAL_UNDER = "HOME_TEAM_TOTAL_UNDER"
    AWAY_TEAM_TOTAL_OVER = "AWAY_TEAM_TOTAL_OVER"
    AWAY_TEAM_TOTAL_UNDER = "AWAY_TEAM_TOTAL_UNDER"
    HOME_CLEAN_SHEET = "HOME_CLEAN_SHEET"
    AWAY_CLEAN_SHEET = "AWAY_CLEAN_SHEET"
    BTTS_YES = "BTTS_YES"
    BTTS_NO = "BTTS_NO"
    EXACT_SCORE = "EXACT_SCORE"


CANONICAL_PROBABILITY_PATTERN = r"^(?:0\.\d{12}|1\.000000000000)$"
CANONICAL_POSITIVE_12_PATTERN = r"^\d+\.\d{12}$"
CANONICAL_HALF_GOAL_PATTERN = r"^\d+\.5$"
ProbabilityJsonInput = Annotated[str, Field(pattern=CANONICAL_PROBABILITY_PATTERN)]
PositiveDecimal12JsonInput = Annotated[
    str,
    Field(pattern=CANONICAL_POSITIVE_12_PATTERN),
]
HalfGoalJsonInput = Annotated[str, Field(pattern=CANONICAL_HALF_GOAL_PATTERN)]


def _require_canonical_json_decimal(
    value: object,
    *,
    info: ValidationInfo,
    pattern: str,
    label: str,
) -> None:
    if info.mode == "json" and (not isinstance(value, str) or re.fullmatch(pattern, value) is None):
        raise ValueError(f"{label} must use its canonical public decimal string")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _rounded_weight_vector(
    values: tuple[Decimal, ...],
    *,
    target_total: Decimal,
) -> tuple[Decimal, ...]:
    """Publish a deterministic 12-decimal positive vector with an exact target sum."""

    if not values:
        return ()
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        rounded = [value.quantize(PROBABILITY_SCALE) for value in values]
        residual = target_total - sum(rounded, Decimal(0))
        index = max(range(len(values)), key=lambda position: (values[position], -position))
        rounded[index] += residual
    if any(value <= 0 for value in rounded):
        raise ValueError("family cap is too small for positive public evidence weights")
    if sum(rounded, Decimal(0)) != target_total:
        raise ValueError("rounded family evidence weights do not match their target total")
    return tuple(rounded)


class MarketConstraint(_FrozenModel):
    """One soft score-matrix event target with explicit uncertainty."""

    constraint_id: str = Field(min_length=1, max_length=128)
    family: MarketFamily
    event: ScoreEvent
    target_probability: Decimal
    uncertainty: Decimal
    weight: Decimal = Decimal(1)
    usable_at: datetime
    period: Literal["FULL_TIME"] = "FULL_TIME"
    settlement_profile: Literal["FULL_TIME_90"] = "FULL_TIME_90"
    line: Decimal | None = None
    home_goals: int | None = Field(default=None, ge=0)
    away_goals: int | None = Field(default=None, ge=0)
    source_result_sha256: str | None = None
    provider_count: int = Field(default=0, ge=0)
    operator_count: int = Field(default=0, ge=0)
    maximum_age_seconds: int | None = Field(default=None, ge=0)
    market_disagreement: Decimal = Decimal(0)
    confidence_grade: Literal["A", "B", "C", "D"] = "D"

    @field_validator(
        "target_probability",
        mode="before",
        json_schema_input_type=ProbabilityJsonInput,
    )
    @classmethod
    def validate_target(cls, value: object, info: ValidationInfo) -> Decimal:
        _require_canonical_json_decimal(
            value,
            info=info,
            pattern=CANONICAL_PROBABILITY_PATTERN,
            label="target_probability",
        )
        return probability(value, label="target_probability")

    @field_validator(
        "market_disagreement",
        mode="before",
        json_schema_input_type=ProbabilityJsonInput,
    )
    @classmethod
    def validate_disagreement(cls, value: object, info: ValidationInfo) -> Decimal:
        _require_canonical_json_decimal(
            value,
            info=info,
            pattern=CANONICAL_PROBABILITY_PATTERN,
            label="market_disagreement",
        )
        return probability(value, label="market_disagreement")

    @field_validator(
        "uncertainty",
        "weight",
        mode="before",
        json_schema_input_type=PositiveDecimal12JsonInput,
    )
    @classmethod
    def validate_positive_decimal(cls, value: object, info: ValidationInfo) -> Decimal:
        _require_canonical_json_decimal(
            value,
            info=info,
            pattern=CANONICAL_POSITIVE_12_PATTERN,
            label=str(info.field_name),
        )
        return positive_decimal(value, label=str(info.field_name))

    @field_validator(
        "line",
        mode="before",
        json_schema_input_type=HalfGoalJsonInput | None,
    )
    @classmethod
    def validate_line(cls, value: object, info: ValidationInfo) -> Decimal | None:
        if value is not None:
            _require_canonical_json_decimal(
                value,
                info=info,
                pattern=CANONICAL_HALF_GOAL_PATTERN,
                label="line",
            )
        return None if value is None else exact_decimal(value, label="line")

    @field_validator("usable_at", mode="before")
    @classmethod
    def validate_usable_at(cls, value: object) -> datetime:
        return parse_utc(value, field_name="usable_at")

    @field_validator("source_result_sha256")
    @classmethod
    def validate_source_hash(cls, value: str | None) -> str | None:
        if value is not None and SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("source_result_sha256 must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_event_shape(self) -> Self:
        line_events = {
            ScoreEvent.TOTAL_OVER,
            ScoreEvent.TOTAL_UNDER,
            ScoreEvent.HOME_TEAM_TOTAL_OVER,
            ScoreEvent.HOME_TEAM_TOTAL_UNDER,
            ScoreEvent.AWAY_TEAM_TOTAL_OVER,
            ScoreEvent.AWAY_TEAM_TOTAL_UNDER,
        }
        if self.event in line_events:
            if self.line is None or self.line < 0:
                raise ValueError("total-market event requires a nonnegative line")
            if self.line % 1 != Decimal("0.5"):
                raise ValueError("Stage-8 total lines must be half-goal lines")
        elif self.line is not None:
            raise ValueError("line is only valid for total-market events")
        if self.event is ScoreEvent.EXACT_SCORE:
            if self.home_goals is None or self.away_goals is None:
                raise ValueError("EXACT_SCORE requires home_goals and away_goals")
        elif self.home_goals is not None or self.away_goals is not None:
            raise ValueError("score coordinates are only valid for EXACT_SCORE")
        family_events = {
            MarketFamily.ONE_X_TWO: {
                ScoreEvent.HOME_WIN,
                ScoreEvent.DRAW,
                ScoreEvent.AWAY_WIN,
            },
            MarketFamily.TOTALS: {ScoreEvent.TOTAL_OVER, ScoreEvent.TOTAL_UNDER},
            MarketFamily.TEAM_TOTAL: {
                ScoreEvent.HOME_TEAM_TOTAL_OVER,
                ScoreEvent.HOME_TEAM_TOTAL_UNDER,
                ScoreEvent.AWAY_TEAM_TOTAL_OVER,
                ScoreEvent.AWAY_TEAM_TOTAL_UNDER,
            },
            MarketFamily.CLEAN_SHEET: {
                ScoreEvent.HOME_CLEAN_SHEET,
                ScoreEvent.AWAY_CLEAN_SHEET,
            },
            MarketFamily.BTTS: {ScoreEvent.BTTS_YES, ScoreEvent.BTTS_NO},
            MarketFamily.CORRECT_SCORE: {ScoreEvent.EXACT_SCORE},
        }
        if self.event not in family_events[self.family]:
            raise ValueError("event is incompatible with market family")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {
            "away_goals": self.away_goals,
            "confidence_grade": self.confidence_grade,
            "constraint_id": self.constraint_id,
            "event": self.event.value,
            "family": self.family.value,
            "home_goals": self.home_goals,
            "line": None if self.line is None else format(self.line, "f"),
            "market_disagreement": format(self.market_disagreement, "f"),
            "maximum_age_seconds": self.maximum_age_seconds,
            "operator_count": self.operator_count,
            "provider_count": self.provider_count,
            "period": self.period,
            "settlement_profile": self.settlement_profile,
            "source_result_sha256": self.source_result_sha256,
            "target_probability": format(self.target_probability, "f"),
            "uncertainty": format(self.uncertainty, "f"),
            "usable_at": format_utc(self.usable_at),
            "weight": format(self.weight, "f"),
        }


class MarketConstraintSet(_FrozenModel):
    schema_version: Literal["score-market-constraint-set-v1"] = "score-market-constraint-set-v1"
    as_of: datetime
    constraints: tuple[MarketConstraint, ...]
    source_result_sha256: str | None = None

    @field_validator("as_of", mode="before")
    @classmethod
    def validate_as_of(cls, value: object) -> datetime:
        return parse_utc(value, field_name="as_of")

    @field_validator("source_result_sha256")
    @classmethod
    def validate_source_hash(cls, value: str | None) -> str | None:
        if value is not None and SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("source_result_sha256 must be lowercase SHA-256")
        return value

    @model_validator(mode="before")
    @classmethod
    def coerce_constraints(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if isinstance(data.get("constraints"), list):
            data["constraints"] = tuple(data["constraints"])
        return data

    @model_validator(mode="after")
    def validate_set(self) -> Self:
        ids = [item.constraint_id for item in self.constraints]
        if len(ids) != len(set(ids)):
            raise ValueError("constraint_id values must be unique")
        if any(item.usable_at > self.as_of for item in self.constraints):
            raise ValueError("POST_CUTOFF_MARKET: constraint usable_at is after as_of")
        semantic_keys = [
            (item.family, item.event, item.line, item.home_goals, item.away_goals)
            for item in self.constraints
        ]
        if len(semantic_keys) != len(set(semantic_keys)):
            raise ValueError("duplicate semantic market constraint")
        one_x_two = [item for item in self.constraints if item.family is MarketFamily.ONE_X_TWO]
        if one_x_two:
            expected = {
                ScoreEvent.HOME_WIN,
                ScoreEvent.DRAW,
                ScoreEvent.AWAY_WIN,
            }
            if len(one_x_two) != 3 or {item.event for item in one_x_two} != expected:
                raise ValueError("1X2 constraints must contain HOME_WIN, DRAW and AWAY_WIN")
            with localcontext() as context:
                context.prec = DECIMAL_PRECISION
                total = sum(
                    (item.target_probability for item in one_x_two),
                    Decimal(0),
                )
            if total != Decimal(1):
                raise ValueError("1X2 target probabilities must sum exactly to one")
        complementary_pairs = (
            (ScoreEvent.BTTS_YES, ScoreEvent.BTTS_NO),
            (ScoreEvent.TOTAL_OVER, ScoreEvent.TOTAL_UNDER),
            (ScoreEvent.HOME_TEAM_TOTAL_OVER, ScoreEvent.HOME_TEAM_TOTAL_UNDER),
            (ScoreEvent.AWAY_TEAM_TOTAL_OVER, ScoreEvent.AWAY_TEAM_TOTAL_UNDER),
        )
        for first_event, second_event in complementary_pairs:
            lines = {
                item.line for item in self.constraints if item.event in {first_event, second_event}
            }
            for line in lines:
                pair = [
                    item
                    for item in self.constraints
                    if item.event in {first_event, second_event} and item.line == line
                ]
                if len(pair) == 2 and (
                    {item.event for item in pair} != {first_event, second_event}
                    or sum((item.target_probability for item in pair), Decimal(0)) != Decimal(1)
                ):
                    raise ValueError("complementary market targets must sum exactly to one")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {
            "as_of": format_utc(self.as_of),
            "constraints": [item.public_dict() for item in self.constraints],
            "schema_version": self.schema_version,
            "source_result_sha256": self.source_result_sha256,
        }


def cap_market_family_weights(
    constraint_set: MarketConstraintSet,
    family_caps: Mapping[MarketFamily, Decimal],
) -> MarketConstraintSet:
    """Cap aggregate evidence weight within each correlated market family."""

    expected_families = set(MarketFamily)
    if set(family_caps) != expected_families:
        raise ValueError("family caps must define every market family exactly once")
    validated_caps = {
        family: positive_decimal(value, label=f"{family.value} family cap")
        for family, value in family_caps.items()
    }
    effective_by_id: dict[str, Decimal] = {}
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        for family in MarketFamily:
            members = tuple(item for item in constraint_set.constraints if item.family is family)
            if not members:
                continue
            total = sum((item.weight for item in members), Decimal(0))
            cap = validated_caps[family]
            if total <= cap:
                weights = [item.weight for item in members]
            else:
                weights = list(
                    _rounded_weight_vector(
                        tuple(item.weight * cap / total for item in members),
                        target_total=cap,
                    )
                )
            for item, weight in zip(members, weights, strict=True):
                effective_by_id[item.constraint_id] = weight
    effective: list[MarketConstraint] = []
    for item in constraint_set.constraints:
        data = item.model_dump(mode="python")
        data["weight"] = effective_by_id[item.constraint_id]
        effective.append(MarketConstraint.model_validate(data))
    return MarketConstraintSet.model_validate(
        {
            "as_of": constraint_set.as_of,
            "constraints": tuple(effective),
            "source_result_sha256": constraint_set.source_result_sha256,
        }
    )


def event_matches(constraint: MarketConstraint, home_goals: int, away_goals: int) -> bool:
    event = constraint.event
    if event is ScoreEvent.HOME_WIN:
        return home_goals > away_goals
    if event is ScoreEvent.DRAW:
        return home_goals == away_goals
    if event is ScoreEvent.AWAY_WIN:
        return home_goals < away_goals
    if event is ScoreEvent.HOME_CLEAN_SHEET:
        return away_goals == 0
    if event is ScoreEvent.AWAY_CLEAN_SHEET:
        return home_goals == 0
    if event is ScoreEvent.BTTS_YES:
        return home_goals > 0 and away_goals > 0
    if event is ScoreEvent.BTTS_NO:
        return home_goals == 0 or away_goals == 0
    if event is ScoreEvent.EXACT_SCORE:
        return home_goals == constraint.home_goals and away_goals == constraint.away_goals
    if constraint.line is None:
        raise ValueError("total-market event has no line")
    total = Decimal(home_goals + away_goals)
    if event is ScoreEvent.TOTAL_OVER:
        return total > constraint.line
    if event is ScoreEvent.TOTAL_UNDER:
        return total < constraint.line
    if event is ScoreEvent.HOME_TEAM_TOTAL_OVER:
        return Decimal(home_goals) > constraint.line
    if event is ScoreEvent.HOME_TEAM_TOTAL_UNDER:
        return Decimal(home_goals) < constraint.line
    if event is ScoreEvent.AWAY_TEAM_TOTAL_OVER:
        return Decimal(away_goals) > constraint.line
    if event is ScoreEvent.AWAY_TEAM_TOTAL_UNDER:
        return Decimal(away_goals) < constraint.line
    raise ValueError(f"unsupported score event: {event}")


def build_design_matrix(
    constraints: tuple[MarketConstraint, ...],
    *,
    home_max: int,
    away_max: int,
) -> tuple[tuple[Decimal, ...], ...]:
    """Map each score cell to each compatible market event."""

    cells = tuple(
        (home_goals, away_goals)
        for home_goals in range(home_max + 1)
        for away_goals in range(away_max + 1)
    )
    return tuple(
        tuple(
            Decimal(1) if event_matches(constraint, home_goals, away_goals) else Decimal(0)
            for home_goals, away_goals in cells
        )
        for constraint in constraints
    )


def _consensus_body(
    consensus: object,
) -> tuple[dict[str, Any], object | None, object | None]:
    body = mapping(consensus, label="market consensus")
    outer_fixture_id: object | None = None
    outer_as_of: object | None = None
    if "consensus" in body:
        status = str(body.get("status"))
        if status not in {"NORMALISED", "DEGRADED"}:
            raise ValueError("market normalisation result has no usable consensus")
        outer_fixture_id = body.get("fixture_id")
        outer_as_of = body.get("as_of")
        if outer_fixture_id is None or outer_as_of is None:
            raise ValueError("market normalisation result requires fixture_id and as_of")
        nested = body.get("consensus")
        if nested is None:
            raise ValueError("market normalisation result has no consensus")
        body = mapping(nested, label="market consensus")
    return body, outer_fixture_id, outer_as_of


def _validated_fixture_id(value: object, *, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as exc:
            raise ValueError(f"{label} must be a UUID") from exc
    raise ValueError(f"{label} must be a UUID")


def constraints_from_market_consensus(
    consensus: object,
    *,
    fixture_id: UUID | str,
    as_of: datetime,
    uncertainty_floor: Decimal,
) -> MarketConstraintSet:
    """Adapt the accepted Stage-6 FULL_TIME_1X2 public contract without rematching."""

    cutoff = parse_utc(as_of, field_name="as_of")
    floor = positive_decimal(uncertainty_floor, label="uncertainty_floor")
    expected_fixture_id = _validated_fixture_id(fixture_id, label="fixture_id")
    body, outer_fixture_id, outer_as_of = _consensus_body(consensus)
    nested_fixture_id = _validated_fixture_id(
        body.get("fixture_id"),
        label="market consensus fixture_id",
    )
    if nested_fixture_id != expected_fixture_id:
        raise ValueError("MARKET_FIXTURE_MISMATCH: Stage-6 consensus is for another fixture")
    if outer_fixture_id is not None:
        validated_outer = _validated_fixture_id(
            outer_fixture_id,
            label="market normalisation result fixture_id",
        )
        if validated_outer != nested_fixture_id:
            raise ValueError(
                "MARKET_FIXTURE_MISMATCH: outer and nested market fixture identities differ"
            )
    if body.get("market_definition") != "FULL_TIME_1X2":
        raise ValueError("Stage-8 baseline accepts only FULL_TIME_1X2 consensus")
    consensus_as_of = parse_utc(body.get("as_of"), field_name="market consensus as_of")
    mapping_cutoff = parse_utc(
        body.get("mapping_cutoff"),
        field_name="market consensus mapping_cutoff",
    )
    if mapping_cutoff > consensus_as_of:
        raise ValueError("market consensus mapping_cutoff is after its as_of")
    if outer_fixture_id is not None:
        result_as_of = parse_utc(
            outer_as_of,
            field_name="market normalisation result as_of",
        )
        if consensus_as_of > result_as_of:
            raise ValueError(
                "market normalisation timestamp envelope is inconsistent: "
                "consensus as_of is after result as_of"
            )
        if result_as_of > cutoff:
            raise ValueError(
                "POST_CUTOFF_MARKET: Stage-6 normalisation result is after Stage-8 cutoff"
            )
    if consensus_as_of > cutoff or mapping_cutoff > cutoff:
        raise ValueError("POST_CUTOFF_MARKET: Stage-6 consensus is after Stage-8 cutoff")
    eligible_operator_count = body.get("eligible_operator_count")
    if (
        isinstance(eligible_operator_count, bool)
        or not isinstance(eligible_operator_count, int)
        or eligible_operator_count < 1
    ):
        raise ValueError("market consensus eligible_operator_count must be positive")
    provider_count = body.get("provider_count")
    if (
        isinstance(provider_count, bool)
        or not isinstance(provider_count, int)
        or provider_count < 1
    ):
        raise ValueError("market consensus provider_count must be positive")
    freshness = body.get("freshness")
    if not isinstance(freshness, Mapping):
        raise ValueError("market consensus freshness must be an object")
    minimum_age = freshness.get("minimum_age_seconds")
    maximum_age = freshness.get("maximum_age_seconds")
    if (
        isinstance(minimum_age, bool)
        or isinstance(maximum_age, bool)
        or not isinstance(minimum_age, int)
        or not isinstance(maximum_age, int)
        or minimum_age < 0
        or maximum_age < minimum_age
    ):
        raise ValueError("market consensus freshness range is invalid")
    market_disagreement = probability(body.get("market_disagreement"), label="market disagreement")
    source_hash = body.get("result_sha256")
    if not isinstance(source_hash, str) or SHA256_PATTERN.fullmatch(source_hash) is None:
        raise ValueError("market consensus result_sha256 is invalid")
    outcomes = body.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 3:
        raise ValueError("market consensus must contain three 1X2 outcomes")
    outcome_to_event = {
        "HOME": ScoreEvent.HOME_WIN,
        "DRAW": ScoreEvent.DRAW,
        "AWAY": ScoreEvent.AWAY_WIN,
    }
    confidence = str(body.get("confidence_grade", "D"))
    confidence_weights = {
        "A": Decimal("1"),
        "B": Decimal("0.75"),
        "C": Decimal("0.50"),
        "D": Decimal("0.25"),
    }
    if confidence not in confidence_weights:
        raise ValueError("market consensus confidence grade is invalid")
    total_weight = confidence_weights[confidence]
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        equal_weight = total_weight / Decimal(len(outcomes))
    outcome_weights = _rounded_weight_vector(
        tuple(equal_weight for _ in outcomes),
        target_total=total_weight,
    )
    constraints: list[MarketConstraint] = []
    seen: set[str] = set()
    for index, outcome in enumerate(outcomes):
        if not isinstance(outcome, dict):
            raise ValueError("market consensus outcome must be an object")
        outcome_name = str(outcome.get("outcome"))
        if outcome_name not in outcome_to_event or outcome_name in seen:
            raise ValueError("market consensus outcomes are duplicated or unsupported")
        seen.add(outcome_name)
        target = probability(outcome.get("consensus_probability"), label="consensus probability")
        lower = probability(outcome.get("lower_bound"), label="lower bound")
        upper = probability(outcome.get("upper_bound"), label="upper bound")
        if not lower <= target <= upper:
            raise ValueError("market consensus probability lies outside its bounds")
        uncertainty = max(
            (upper - lower) / Decimal(2),
            market_disagreement,
            floor,
        )
        constraints.append(
            MarketConstraint.model_validate(
                {
                    "confidence_grade": confidence,
                    "constraint_id": f"stage6-1x2-{outcome_name.lower()}",
                    "event": outcome_to_event[outcome_name],
                    "family": MarketFamily.ONE_X_TWO,
                    "market_disagreement": market_disagreement,
                    "maximum_age_seconds": maximum_age,
                    "operator_count": eligible_operator_count,
                    "provider_count": provider_count,
                    "source_result_sha256": source_hash,
                    "target_probability": target,
                    "uncertainty": uncertainty,
                    "usable_at": consensus_as_of,
                    "weight": outcome_weights[index],
                }
            )
        )
    return MarketConstraintSet.model_validate(
        {
            "as_of": cutoff,
            "constraints": tuple(constraints),
            "source_result_sha256": source_hash,
        }
    )


__all__ = [
    "MarketConstraint",
    "MarketConstraintSet",
    "MarketFamily",
    "ScoreEvent",
    "build_design_matrix",
    "cap_market_family_weights",
    "constraints_from_market_consensus",
    "event_matches",
]
