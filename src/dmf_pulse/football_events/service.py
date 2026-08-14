"""Offline Stage-8 orchestration, packaged policy loading and artifact persistence."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dmf_pulse.football_events._decimal import (
    canonical_decimal_text,
    canonical_json_sha256,
    exact_decimal,
    format_utc,
    mapping,
    nonnegative_decimal,
    parse_utc,
    positive_decimal,
    probability,
)
from dmf_pulse.football_events.coherence import assert_score_coherence
from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketConstraintSet,
    MarketFamily,
    ScoreEvent,
    cap_market_family_weights,
    constraints_from_market_consensus,
)
from dmf_pulse.football_events.minutes_context import (
    Stage7MinutesContext,
    validate_stage7_context,
)
from dmf_pulse.football_events.score_distribution import (
    JointScoreDistribution,
    compose_joint_score_distribution,
)
from dmf_pulse.football_events.score_prior import build_score_prior
from dmf_pulse.football_events.score_projection import project_to_markets
from dmf_pulse.markets.models import MarketConsensus, MarketNormalisationResult


class ScoreDistributionError(ValueError):
    """Typed fail-closed Stage-8 service error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_error_object(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        del deep
        data = self.model_dump(mode="python", exclude_none=False)
        if update:
            data.update(dict(update))
        return type(self).model_validate(data)


class ScoreGridPolicy(_FrozenModel):
    minimum_max_goals: int = Field(ge=0)
    maximum_max_goals: int = Field(ge=0)
    tail_tolerance: Decimal
    hard_tail_limit: Decimal

    @field_validator("tail_tolerance", "hard_tail_limit", mode="before")
    @classmethod
    def validate_probability(cls, value: object, info: Any) -> Decimal:
        return probability(value, label=str(info.field_name))

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.maximum_max_goals < self.minimum_max_goals:
            raise ValueError("maximum_max_goals is below minimum_max_goals")
        if self.hard_tail_limit < self.tail_tolerance:
            raise ValueError("hard_tail_limit is below tail_tolerance")
        return self


class MarketFamilyWeightCap(_FrozenModel):
    family: MarketFamily
    maximum_total_weight: Decimal

    @field_validator("family", mode="before")
    @classmethod
    def validate_family(cls, value: object) -> MarketFamily:
        try:
            return value if isinstance(value, MarketFamily) else MarketFamily(str(value))
        except ValueError as exc:
            raise ValueError("family is not a supported Stage-8 market family") from exc

    @field_validator("maximum_total_weight", mode="before")
    @classmethod
    def validate_cap(cls, value: object) -> Decimal:
        return positive_decimal(value, label="maximum_total_weight")


class ScoreProjectionPolicy(_FrozenModel):
    max_iterations: int = Field(ge=1)
    gradient_tolerance: Decimal
    line_search_min_step: Decimal
    market_uncertainty_floor: Decimal
    allow_prior_fallback: bool
    maximum_prior_goal_rate: Decimal
    family_weight_caps: tuple[MarketFamilyWeightCap, ...]

    @field_validator(
        "gradient_tolerance",
        "line_search_min_step",
        "market_uncertainty_floor",
        "maximum_prior_goal_rate",
        mode="before",
    )
    @classmethod
    def validate_positive(cls, value: object, info: Any) -> Decimal:
        return positive_decimal(value, label=str(info.field_name))

    @field_validator("family_weight_caps", mode="before")
    @classmethod
    def coerce_family_caps(cls, value: object) -> tuple[object, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("family_weight_caps must be a sequence")
        return tuple(value)

    @model_validator(mode="after")
    def validate_step(self) -> Self:
        if self.line_search_min_step >= 1:
            raise ValueError("line_search_min_step must be below one")
        if self.market_uncertainty_floor > 1:
            raise ValueError("market_uncertainty_floor must not exceed one")
        families = tuple(item.family for item in self.family_weight_caps)
        if families != tuple(MarketFamily):
            raise ValueError(
                "family_weight_caps must define every market family once in canonical order"
            )
        return self

    @property
    def family_cap_map(self) -> dict[MarketFamily, Decimal]:
        return {item.family: item.maximum_total_weight for item in self.family_weight_caps}


class DerivedOutputPolicy(_FrozenModel):
    total_goal_lines: tuple[Decimal, ...]
    top_scoreline_count: int = Field(ge=1)

    @field_validator("total_goal_lines", mode="before")
    @classmethod
    def validate_lines(cls, value: object) -> tuple[Decimal, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("total_goal_lines must be a sequence")
        lines = tuple(exact_decimal(item, label="total goal line") for item in value)
        if not lines or len(lines) != len(set(lines)):
            raise ValueError("total_goal_lines must be nonempty and unique")
        if any(line < 0 or line % 1 != Decimal("0.5") for line in lines):
            raise ValueError("total_goal_lines must be nonnegative half-goal lines")
        if lines != tuple(sorted(lines)):
            raise ValueError("total_goal_lines must be sorted")
        return lines


class ScoreBaselinePolicy(_FrozenModel):
    schema_version: Literal["score-baseline-policy-v1"]
    model_family: Literal["INDEPENDENT_POISSON_SOFT_KL_V1"]
    decimal_precision: Literal[60]
    grid: ScoreGridPolicy
    projection: ScoreProjectionPolicy
    derived_outputs: DerivedOutputPolicy

    @property
    def semantic_body(self) -> dict[str, Any]:
        return {
            "decimal_precision": self.decimal_precision,
            "derived_outputs": {
                "top_scoreline_count": self.derived_outputs.top_scoreline_count,
                "total_goal_lines": [
                    canonical_decimal_text(value) for value in self.derived_outputs.total_goal_lines
                ],
            },
            "grid": {
                "hard_tail_limit": canonical_decimal_text(self.grid.hard_tail_limit),
                "maximum_max_goals": self.grid.maximum_max_goals,
                "minimum_max_goals": self.grid.minimum_max_goals,
                "tail_tolerance": canonical_decimal_text(self.grid.tail_tolerance),
            },
            "model_family": self.model_family,
            "projection": {
                "allow_prior_fallback": self.projection.allow_prior_fallback,
                "family_weight_caps": [
                    {
                        "family": item.family.value,
                        "maximum_total_weight": canonical_decimal_text(item.maximum_total_weight),
                    }
                    for item in self.projection.family_weight_caps
                ],
                "gradient_tolerance": canonical_decimal_text(self.projection.gradient_tolerance),
                "line_search_min_step": canonical_decimal_text(
                    self.projection.line_search_min_step
                ),
                "market_uncertainty_floor": canonical_decimal_text(
                    self.projection.market_uncertainty_floor
                ),
                "max_iterations": self.projection.max_iterations,
                "maximum_prior_goal_rate": canonical_decimal_text(
                    self.projection.maximum_prior_goal_rate
                ),
            },
            "schema_version": self.schema_version,
        }

    @property
    def sha256(self) -> str:
        return canonical_json_sha256(self.semantic_body)


class ScorePriorRequest(_FrozenModel):
    model_family: Literal["INDEPENDENT_POISSON_V1"] = "INDEPENDENT_POISSON_V1"
    home_goal_rate: Decimal
    away_goal_rate: Decimal

    @field_validator("home_goal_rate", "away_goal_rate", mode="before")
    @classmethod
    def validate_rate(cls, value: object, info: Any) -> Decimal:
        return nonnegative_decimal(value, label=str(info.field_name))

    def public_dict(self) -> dict[str, str]:
        return {
            "away_goal_rate": canonical_decimal_text(self.away_goal_rate),
            "home_goal_rate": canonical_decimal_text(self.home_goal_rate),
            "model_family": self.model_family,
        }


class ScoreDistributionRequest(_FrozenModel):
    schema_version: Literal["score-distribution-request-v1"]
    fixture_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    as_of: datetime
    fixture_status: Literal["SCHEDULED", "POSTPONED", "CANCELLED", "ABANDONED"] = "SCHEDULED"
    minutes_context: Stage7MinutesContext
    prior: ScorePriorRequest
    constraints: tuple[MarketConstraint, ...] = ()
    market_consensus: MarketConsensus | MarketNormalisationResult | None = None

    @field_validator("as_of", mode="before")
    @classmethod
    def validate_as_of(cls, value: object) -> datetime:
        return parse_utc(value, field_name="as_of")

    @field_validator("market_consensus", mode="before")
    @classmethod
    def validate_market_consensus(
        cls,
        value: object,
    ) -> MarketConsensus | MarketNormalisationResult | None:
        if value is None or isinstance(value, (MarketConsensus, MarketNormalisationResult)):
            return value
        body = mapping(value, label="Stage-6 market consensus")
        serialized = json.dumps(
            body,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            if "consensus" in body:
                return MarketNormalisationResult.model_validate_json(serialized)
            return MarketConsensus.model_validate_json(serialized)
        except ValueError as exc:
            raise ValueError(
                "market_consensus violates the accepted Stage-6 public contract"
            ) from exc

    @model_validator(mode="before")
    @classmethod
    def coerce_constraints(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        if isinstance(data.get("constraints"), list):
            data["constraints"] = tuple(data["constraints"])
        return data

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("home_team_id and away_team_id must be distinct")
        validate_stage7_context(
            self.minutes_context,
            fixture_id=self.fixture_id,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
            information_cutoff=self.as_of,
        )
        if self.constraints and self.market_consensus is not None:
            raise ValueError("provide either constraints or market_consensus, not both")
        if len({item.constraint_id for item in self.constraints}) != len(self.constraints):
            raise ValueError("constraint_id values must be unique")
        if any(item.usable_at > self.as_of for item in self.constraints):
            raise ValueError("POST_CUTOFF_MARKET: constraint is after request as_of")
        return self

    def public_identity(self) -> dict[str, Any]:
        return {
            "as_of": format_utc(self.as_of),
            "away_team_id": str(self.away_team_id),
            "fixture_id": str(self.fixture_id),
            "fixture_status": self.fixture_status,
            "home_team_id": str(self.home_team_id),
            "minutes_context": self.minutes_context.public_dict(),
            "minutes_context_sha256": self.minutes_context.semantic_sha256,
            "prior": self.prior.public_dict(),
            "schema_version": self.schema_version,
        }


class ScoreDistributionResult(_FrozenModel):
    status: Literal["PROJECTED", "BLOCKED"]
    fixture_id: str
    as_of: str
    input_signature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    distribution: JointScoreDistribution | None
    error_code: str | None
    error_message: str | None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        try:
            UUID(self.fixture_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("fixture_id must be a UUID") from exc
        parse_utc(self.as_of, field_name="as_of")
        if self.status == "PROJECTED":
            if self.distribution is None or self.error_code is not None:
                raise ValueError("projected result requires distribution and no error")
            if self.error_message is not None:
                raise ValueError("projected result cannot contain error_message")
            if self.input_signature_sha256 != self.distribution.input_signature_sha256:
                raise ValueError("outer and nested input signatures differ")
            if self.fixture_id != self.distribution.fixture_id:
                raise ValueError("outer and nested fixture identities differ")
            if self.as_of != self.distribution.as_of:
                raise ValueError("outer and nested as_of values differ")
        else:
            if self.distribution is not None or not self.error_code or not self.error_message:
                raise ValueError("blocked result requires a typed error and no distribution")
        return self


def load_score_baseline_policy() -> ScoreBaselinePolicy:
    """Load only the packaged immutable policy; never resolve a mutable external path."""

    resource = files("dmf_pulse.football_events.resources").joinpath("score_baseline.yaml")
    try:
        raw = yaml.safe_load(resource.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ScoreDistributionError("POLICY_UNAVAILABLE", "score policy is unavailable") from exc
    if not isinstance(raw, dict):
        raise ScoreDistributionError("POLICY_INVALID", "score policy root must be an object")
    try:
        return ScoreBaselinePolicy.model_validate(raw)
    except ValueError as exc:
        raise ScoreDistributionError("POLICY_INVALID", "score policy failed validation") from exc


def _constraint_set(
    request: ScoreDistributionRequest,
    policy: ScoreBaselinePolicy,
) -> MarketConstraintSet:
    if request.market_consensus is not None:
        raw = constraints_from_market_consensus(
            request.market_consensus,
            fixture_id=request.fixture_id,
            as_of=request.as_of,
            uncertainty_floor=policy.projection.market_uncertainty_floor,
        )
    else:
        source_hashes = {
            item.source_result_sha256
            for item in request.constraints
            if item.source_result_sha256 is not None
        }
        source_hash = next(iter(source_hashes)) if len(source_hashes) == 1 else None
        raw = MarketConstraintSet.model_validate(
            {
                "as_of": request.as_of,
                "constraints": request.constraints,
                "source_result_sha256": source_hash,
            }
        )
    return cap_market_family_weights(raw, policy.projection.family_cap_map)


def _required_minimum_support(
    constraint_set: MarketConstraintSet,
    policy: ScoreBaselinePolicy,
) -> int:
    """Cover every quoted score/line with a two-goal safety margin."""

    required = policy.grid.minimum_max_goals
    line_events = {
        ScoreEvent.TOTAL_OVER,
        ScoreEvent.TOTAL_UNDER,
        ScoreEvent.HOME_TEAM_TOTAL_OVER,
        ScoreEvent.HOME_TEAM_TOTAL_UNDER,
        ScoreEvent.AWAY_TEAM_TOTAL_OVER,
        ScoreEvent.AWAY_TEAM_TOTAL_UNDER,
    }
    for constraint in constraint_set.constraints:
        if constraint.event is ScoreEvent.EXACT_SCORE:
            if constraint.home_goals is None or constraint.away_goals is None:
                raise ScoreDistributionError(
                    "MARKET_CONSTRAINT_INVALID",
                    "exact-score constraint lacks score coordinates",
                )
            required = max(required, constraint.home_goals + 2, constraint.away_goals + 2)
        elif constraint.event in line_events:
            if constraint.line is None:
                raise ScoreDistributionError(
                    "MARKET_CONSTRAINT_INVALID",
                    "total-market constraint lacks a line",
                )
            boundary = int(constraint.line.to_integral_value(rounding=ROUND_CEILING))
            required = max(required, boundary + 2)
    if required > policy.grid.maximum_max_goals:
        raise ScoreDistributionError(
            "MARKET_SUPPORT_OUT_OF_RANGE",
            "market line or exact score exceeds the validated score-grid support",
        )
    return required


def _input_signature(
    request: ScoreDistributionRequest,
    constraint_set: MarketConstraintSet,
    policy: ScoreBaselinePolicy,
) -> str:
    return canonical_json_sha256(
        {
            "constraints": constraint_set.public_dict(),
            "policy_sha256": policy.sha256,
            "request": request.public_identity(),
        }
    )


class ScoreDistributionService:
    """One deterministic Stage-8 application service with no network or database calls."""

    def project(
        self,
        request: ScoreDistributionRequest,
        *,
        policy: ScoreBaselinePolicy | None = None,
    ) -> ScoreDistributionResult:
        selected_policy = policy or load_score_baseline_policy()
        constraint_set = _constraint_set(request, selected_policy)
        signature = _input_signature(request, constraint_set, selected_policy)
        if request.fixture_status != "SCHEDULED":
            status_codes = {
                "POSTPONED": "FIXTURE_POSTPONED",
                "CANCELLED": "FIXTURE_CANCELLED",
                "ABANDONED": "FIXTURE_ABANDONED",
            }
            code = status_codes[request.fixture_status]
            return ScoreDistributionResult.model_validate(
                {
                    "as_of": format_utc(request.as_of),
                    "distribution": None,
                    "error_code": code,
                    "error_message": "fixture is not eligible for a pre-match score distribution",
                    "fixture_id": str(request.fixture_id),
                    "input_signature_sha256": signature,
                    "status": "BLOCKED",
                }
            )
        maximum_rate = selected_policy.projection.maximum_prior_goal_rate
        if (
            request.prior.home_goal_rate > maximum_rate
            or request.prior.away_goal_rate > maximum_rate
        ):
            raise ScoreDistributionError(
                "PRIOR_RATE_OUT_OF_RANGE",
                "prior goal rate exceeds the validated Stage-8 baseline range",
            )
        minimum_support = _required_minimum_support(constraint_set, selected_policy)
        prior = build_score_prior(
            request.prior.home_goal_rate,
            request.prior.away_goal_rate,
            minimum_max_goals=minimum_support,
            maximum_max_goals=selected_policy.grid.maximum_max_goals,
            tail_tolerance=selected_policy.grid.tail_tolerance,
            hard_tail_limit=selected_policy.grid.hard_tail_limit,
        )
        projection = project_to_markets(
            prior,
            constraint_set,
            max_iterations=selected_policy.projection.max_iterations,
            gradient_tolerance=selected_policy.projection.gradient_tolerance,
            line_search_min_step=selected_policy.projection.line_search_min_step,
            allow_prior_fallback=selected_policy.projection.allow_prior_fallback,
        )
        distribution = compose_joint_score_distribution(
            fixture_id=str(request.fixture_id),
            home_team_id=str(request.home_team_id),
            away_team_id=str(request.away_team_id),
            as_of=format_utc(request.as_of),
            minutes_context=request.minutes_context,
            input_signature_sha256=signature,
            policy_sha256=selected_policy.sha256,
            prior=prior,
            projection=projection,
            constraint_set=constraint_set,
            total_lines=selected_policy.derived_outputs.total_goal_lines,
            top_scoreline_count=selected_policy.derived_outputs.top_scoreline_count,
        )
        assert_score_coherence(distribution)
        return ScoreDistributionResult.model_validate(
            {
                "as_of": format_utc(request.as_of),
                "distribution": distribution,
                "error_code": None,
                "error_message": None,
                "fixture_id": str(request.fixture_id),
                "input_signature_sha256": signature,
                "status": "PROJECTED",
            }
        )


def load_score_distribution_request(path: Path) -> ScoreDistributionRequest:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScoreDistributionError("REQUEST_UNREADABLE", "request JSON is unreadable") from exc
    try:
        return ScoreDistributionRequest.model_validate_json(raw)
    except ValueError as exc:
        raise ScoreDistributionError("REQUEST_INVALID", "request JSON failed validation") from exc


def load_joint_score_distribution(path: Path) -> JointScoreDistribution:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScoreDistributionError("ARTIFACT_UNREADABLE", "artifact JSON is unreadable") from exc
    try:
        return JointScoreDistribution.model_validate_json(raw)
    except ValueError as exc:
        raise ScoreDistributionError("ARTIFACT_INVALID", "artifact JSON failed validation") from exc


def persist_joint_score_distribution(
    distribution: JointScoreDistribution,
    *,
    artifact_root: Path,
) -> Path:
    """Persist an immutable content-addressed artifact with exact replay identity."""

    if not artifact_root.is_absolute():
        artifact_root = artifact_root.resolve()
    safe_as_of = distribution.as_of.replace(":", "-")
    destination = (
        artifact_root
        / "football-events"
        / "score-distributions"
        / f"fixture={distribution.fixture_id}"
        / f"as_of={safe_as_of}"
        / f"input={distribution.input_signature_sha256}"
        / "score-distribution.json"
    )
    payload = (
        json.dumps(
            distribution.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_text(encoding="utf-8") != payload:
            raise ScoreDistributionError(
                "ARTIFACT_IDENTITY_CONFLICT",
                "existing content-addressed artifact has different bytes",
            )
        return destination
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.partial")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def explain_market_fit(distribution: JointScoreDistribution) -> dict[str, Any]:
    return {
        "confidence_grade": distribution.confidence_grade,
        "confidence_reasons": list(distribution.confidence_reasons),
        "diagnostics": distribution.diagnostics.model_dump(mode="json"),
        "fixture_id": distribution.fixture_id,
        "home_team_id": distribution.home_team_id,
        "away_team_id": distribution.away_team_id,
        "information_cutoff": distribution.information_cutoff,
        "market_residuals": [
            item.model_dump(mode="json") for item in distribution.market_residuals
        ],
        "result_sha256": distribution.result_sha256,
        "schema_version": "score-market-fit-explanation-v1",
        "source_away_minutes_sha256": distribution.source_away_minutes_sha256,
        "source_home_minutes_sha256": distribution.source_home_minutes_sha256,
        "source_market_sha256": distribution.source_market_sha256,
        "source_minutes_as_of": distribution.source_minutes_as_of,
        "source_minutes_context": distribution.source_minutes_context.model_dump(mode="json"),
        "source_minutes_context_sha256": distribution.source_minutes_context_sha256,
    }


__all__ = [
    "DerivedOutputPolicy",
    "MarketFamilyWeightCap",
    "ScoreBaselinePolicy",
    "ScoreDistributionError",
    "ScoreDistributionRequest",
    "ScoreDistributionResult",
    "ScoreDistributionService",
    "ScoreGridPolicy",
    "ScorePriorRequest",
    "ScoreProjectionPolicy",
    "explain_market_fit",
    "load_joint_score_distribution",
    "load_score_baseline_policy",
    "load_score_distribution_request",
    "persist_joint_score_distribution",
]
