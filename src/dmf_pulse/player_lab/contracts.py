"""Immutable, strictly typed player research contracts and prospective custody."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from math import isclose
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import POINT_COMPONENT_NAMES

Sha = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[StrictInt, Field(gt=0)]


class LabModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def utc_only(cls, value: object) -> object:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("UTC-aware timestamp required")
            return value.astimezone(UTC)
        return value


class SourceRef(LabModel):
    source_id: StrictStr
    payload_sha256: Sha
    profile_id: StrictStr
    profile_sha256: Sha
    observed_at: datetime
    usable_at: datetime

    @model_validator(mode="after")
    def temporal_source(self) -> Self:
        if self.observed_at > self.usable_at:
            raise ValueError("source cannot be usable before observation")
        return self


class Sealed(LabModel):
    semantic_sha256: Sha

    @model_validator(mode="after")
    def authenticated(self) -> Self:
        if self.semantic_sha256 != canonical_sha256(
            self.model_dump(mode="json", exclude={"semantic_sha256"})
        ):
            raise ValueError("player artifact semantic hash mismatch")
        return self


def seal[T: Sealed](value: T) -> T:
    """Construction helper; validation authenticates the entire resulting payload."""
    payload = value.model_dump(mode="python")
    payload["semantic_sha256"] = canonical_sha256(
        value.model_dump(mode="json", exclude={"semantic_sha256"})
    )
    return type(value).model_validate(payload)


class PlayerKey(LabModel):
    season: Annotated[StrictStr, Field(pattern=r"^20\d{2}/\d{2}$")]
    gameweek: Annotated[StrictInt, Field(ge=1, le=38)]
    player_id: UUID
    fixture_ids: tuple[UUID, ...]

    @model_validator(mode="after")
    def canonical_fixtures(self) -> Self:
        if self.fixture_ids != tuple(sorted(set(self.fixture_ids), key=str)):
            raise ValueError("fixture identities must be unique and canonical")
        return self

    def target_id(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class PlayerForecast(Sealed):
    schema_version: Literal["player-forecast-v1"] = "player-forecast-v1"
    key: PlayerKey
    dataset_mode: Literal["SYNTHETIC", "PROSPECTIVE_REAL"]
    model_id: StrictStr
    model_version_ids: tuple[StrictStr, ...]
    horizon_gameweeks: Literal[1] = 1
    training_cutoff: datetime | None = None
    code_sha: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{40}$")]
    ruleset_sha256: Sha
    source_summary_sha256: Sha
    input_sha256: Sha
    mean: Decimal
    pmf: dict[StrictInt, Decimal]
    pmf_conversion_policy: Literal["EXACT_DECIMAL_OR_STAGE9_18DP_HALF_EVEN_V1"] = (
        "EXACT_DECIMAL_OR_STAGE9_18DP_HALF_EVEN_V1"
    )
    components: dict[StrictStr, Decimal]
    expected_minutes: Decimal | None
    position: Literal["GK", "DEF", "MID", "FWD"]
    generated_at: datetime
    information_cutoff: datetime
    deadline_at: datetime
    label_finality_cutoff: datetime
    sources: Annotated[tuple[SourceRef, ...], Field(min_length=1)]
    retention: Literal["QUALIFIED_RESEARCH_ONLY"] = "QUALIFIED_RESEARCH_ONLY"

    @model_validator(mode="after")
    def prospective_and_reconciled(self) -> Self:
        if (
            not self.information_cutoff
            <= self.generated_at
            < self.deadline_at
            < self.label_finality_cutoff
        ):
            raise ValueError("forecast is post-hoc or has invalid cutoff")
        if any(source.usable_at > self.information_cutoff for source in self.sources):
            raise ValueError("forecast includes post-cutoff source")
        if self.training_cutoff is not None and self.training_cutoff > self.information_cutoff:
            raise ValueError("forecast includes post-cutoff training")
        if not self.model_version_ids or self.model_version_ids != tuple(
            sorted(set(self.model_version_ids))
        ):
            raise ValueError("explicit canonical model versions required")
        if not self.mean.is_finite() or set(self.components) != set(POINT_COMPONENT_NAMES):
            raise ValueError("forecast requires finite mean and all 13 components")
        if any(not value.is_finite() for value in self.components.values()):
            raise ValueError("nonfinite forecast component")
        if not self.pmf or any(
            not value.is_finite() or not 0 <= value <= 1 for value in self.pmf.values()
        ):
            raise ValueError("invalid forecast PMF")
        if sum(self.pmf.values(), Decimal(0)) != 1:
            raise ValueError("forecast PMF mass must equal one")
        pmf_mean = sum((Decimal(points) * mass for points, mass in self.pmf.items()), Decimal(0))
        if not isclose(float(pmf_mean), float(self.mean), rel_tol=0, abs_tol=1e-10) or not isclose(
            float(sum(self.components.values(), Decimal(0))),
            float(self.mean),
            rel_tol=0,
            abs_tol=1e-10,
        ):
            raise ValueError("forecast mean/components/PMF do not reconcile")
        if self.expected_minutes is not None and (
            not self.expected_minutes.is_finite()
            or not 0 <= self.expected_minutes <= 90 * len(self.key.fixture_ids)
        ):
            raise ValueError("invalid expected minutes")
        return self


class FrozenForecast(Sealed):
    forecast: PlayerForecast
    recorded_at: datetime

    @model_validator(mode="after")
    def recorded_before_deadline(self) -> Self:
        if not self.forecast.generated_at <= self.recorded_at < self.forecast.deadline_at:
            raise ValueError("forecast not frozen prospectively")
        return self


class FinalPlayerOutcome(Sealed):
    schema_version: Literal["player-final-outcome-v1"] = "player-final-outcome-v1"
    key: PlayerKey
    dataset_mode: Literal["SYNTHETIC", "PROSPECTIVE_REAL"]
    total_points: StrictInt
    components: dict[StrictStr, StrictInt]
    finalization_status: Literal["FINAL"] = "FINAL"
    finalized_at: datetime
    original_points_lock_at: datetime
    finality_evidence_sha256: Sha
    finality_policy: Literal["FPL_2026_27_NEXT_DAY_0900_LONDON_V1"] = (
        "FPL_2026_27_NEXT_DAY_0900_LONDON_V1"
    )
    retrieved_at: datetime
    usable_at: datetime
    correction_policy: Literal["APPEND_ONLY_EXTRAORDINARY_CORRECTIONS_V1"] = (
        "APPEND_ONLY_EXTRAORDINARY_CORRECTIONS_V1"
    )
    revision: Annotated[StrictInt, Field(ge=0)] = 0
    supersedes_sha256: Sha | None = None
    source: SourceRef

    @model_validator(mode="after")
    def finality_and_components(self) -> Self:
        if not self.finalized_at <= self.retrieved_at <= self.usable_at:
            raise ValueError("outcome chronology invalid")
        if self.source.observed_at != self.retrieved_at or self.source.usable_at != self.usable_at:
            raise ValueError("outcome source vintage differs")
        if (
            set(self.components) != set(POINT_COMPONENT_NAMES)
            or sum(self.components.values()) != self.total_points
        ):
            raise ValueError("official total and components disagree")
        if (self.revision == 0) != (self.supersedes_sha256 is None):
            raise ValueError("correction requires explicit predecessor")
        if (
            self.original_points_lock_at > self.finalized_at
            or (self.revision == 0 and self.original_points_lock_at != self.finalized_at)
            or (self.revision > 0 and self.finalized_at <= self.original_points_lock_at)
        ):
            raise ValueError("correction/normal finalization times inconsistent")
        return self


class Experiment(Sealed):
    experiment_id: StrictStr
    registered_at: datetime
    dataset_mode: Literal["SYNTHETIC", "PROSPECTIVE_REAL"]
    champion_id: StrictStr
    challenger_id: StrictStr
    target_ids: tuple[Sha, ...]
    holdout_start_gameweek: Annotated[StrictInt, Field(ge=2, le=38)]
    metric_policy: Literal["STAGE12_POINT_PMF_5PLUS_80COVERAGE_V1"] = (
        "STAGE12_POINT_PMF_5PLUS_80COVERAGE_V1"
    )
    baseline_policy: Literal["PREDECLARED_ZERO_POINTS_V1"] = "PREDECLARED_ZERO_POINTS_V1"
    promotion: Literal["FORBIDDEN"] = "FORBIDDEN"

    @model_validator(mode="after")
    def cohort_declared(self) -> Self:
        if not self.target_ids or self.target_ids != tuple(sorted(set(self.target_ids))):
            raise ValueError("experiment requires unique frozen target cohort")
        if self.champion_id == self.challenger_id:
            raise ValueError("champion and challenger must differ")
        return self
