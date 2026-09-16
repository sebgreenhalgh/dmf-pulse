"""R9B fixed historical Gamma--Poisson shadow contracts; no active model binding."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
from math import isfinite
from typing import Annotated, Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import PlayerAllocationProfile
from dmf_pulse.fpl_points.player_prior import CurrentGwPlayerPriorBindingEntry

HISTORICAL_SHA = "b4353dbdcebd31f2a807bee90ec04b3ee8b07389"
RESOURCE_SHA = "ca3084edded94fda8b0818f4277aca335f25e8112bb9379f47c11c2ad4b29909"
SOURCE_HASHES = (
    "537b2ab3c19aba381e6020972cd037b3f62665309c423037049020f0d4f0239f",
    "2bba62e765c83ba0ed114e78d168311e1f33aa144143b121703af2e5acfedbec",
    "b876b34d8669cf0acbaaa1a8136e90058573b4292c6dc016b7bf59e52992595e",
)
World = Literal["CENTRAL_TEMPORARY", "LOW_SHRINKAGE", "HIGH_SHRINKAGE"]
WORLDS: tuple[World, ...] = ("CENTRAL_TEMPORARY", "LOW_SHRINKAGE", "HIGH_SHRINKAGE")
Channel = Literal["assist", "yellow", "red", "save", "total_goal_diagnostic"]
CHANNELS: tuple[Channel, ...] = ("assist", "yellow", "red", "save", "total_goal_diagnostic")
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Rate = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]
RateStatus = Literal[
    "UPDATED",
    "NO_CURRENT_EXPOSURE",
    "CURRENT_HISTORY_UNAVAILABLE",
    "CURRENT_HISTORY_FIELD_PARTIAL_NO_UPDATE",
    "HISTORICAL_RATE_DEGENERATE_NO_UPDATE",
    "STRUCTURAL_NON_GK_ZERO",
]
ALLOWED_PROFILE_FIELDS = (
    "assist_share",
    "yellow_cards_per90",
    "red_cards_per90",
    "goalkeeper_saves_per90",
)
GOAL_STATUS: Final = "GOAL_SHARE_CURRENT_HISTORY_UPDATE_BLOCKED_NO_NONPENALTY_DECOMPOSITION"


class StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", validate_default=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        del deep  # Every child is revalidated from its Python representation.
        return type(self).model_validate(self.model_dump(mode="python") | dict(update or {}))


class SealedModel(StrictModel):
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def verify_seal(self) -> Self:
        if self.semantic_sha256 != canonical_sha256(
            self.model_dump(mode="json", exclude={"semantic_sha256"})
        ):
            raise ValueError("shadow semantic hash mismatch")
        return self


def seal[T: SealedModel](value: T) -> T:
    """Constructors use model_construct only immediately before this strict boundary."""
    payload = value.model_dump(mode="python")
    payload["semantic_sha256"] = canonical_sha256(
        value.model_dump(mode="json", exclude={"semantic_sha256"})
    )
    return type(value).model_validate(payload)


class HistoricalRateRow(StrictModel):
    source_official_fpl_player_id: int = Field(gt=0)
    goal_mean_per90: Rate
    goal_variance_per90: Rate
    assist_mean_per90: Rate
    assist_variance_per90: Rate
    yellow_mean_per90: Rate
    yellow_variance_per90: Rate
    red_mean_per90: Rate
    red_variance_per90: Rate
    save_mean_per90: Rate
    save_variance_per90: Rate


class HistoricalRateWorld(StrictModel):
    sensitivity_world: World
    source_posterior_artifact_sha256: Sha256
    rates: tuple[HistoricalRateRow, ...] = Field(min_length=599, max_length=599)

    @model_validator(mode="after")
    def ordered_unique(self) -> Self:
        ids = tuple(row.source_official_fpl_player_id for row in self.rates)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("historical donor IDs must be sorted and unique")
        if (
            self.source_posterior_artifact_sha256
            != SOURCE_HASHES[WORLDS.index(self.sensitivity_world)]
        ):
            raise ValueError("historical source hash differs")
        return self


class HistoricalRateResource(SealedModel):
    schema_version: Literal["r9b-historical-rate-priors-v1"]
    originating_implementation_sha: Literal["b4353dbdcebd31f2a807bee90ec04b3ee8b07389"]
    central_source_posterior_artifact_sha256: Literal[
        "537b2ab3c19aba381e6020972cd037b3f62665309c423037049020f0d4f0239f"
    ]
    worlds: tuple[HistoricalRateWorld, ...]

    @model_validator(mode="after")
    def pinned_resource(self) -> Self:
        if tuple(world.sensitivity_world for world in self.worlds) != WORLDS:
            raise ValueError("historical worlds incomplete or unordered")
        if (
            len({tuple(row.source_official_fpl_player_id for row in w.rates) for w in self.worlds})
            != 1
        ):
            raise ValueError("historical world donor catalogues differ")
        if self.semantic_sha256 != RESOURCE_SHA:
            raise ValueError("historical resource differs from immutable pinned artifact")
        return self


@lru_cache(maxsize=1)
def load_historical_rate_resource() -> HistoricalRateResource:
    """One explicit resource read, never I/O at import or per current player."""
    return HistoricalRateResource.model_validate_json(
        files("dmf_pulse.fpl_points.resources")
        .joinpath("r9b_historical_rate_priors_v1.json")
        .read_bytes()
    )


def gamma_poisson_update(
    mean: float, variance: float, events: int, minutes: int
) -> tuple[float, float]:
    """Reuse a historical posterior as a prior; kappa is NOT applied twice."""
    if (
        type(events) is not int
        or type(minutes) is not int
        or events < 0
        or minutes < 0
        or not isfinite(mean)
        or not isfinite(variance)
        or mean <= 0
        or variance <= 0
    ):
        raise ValueError("invalid Gamma-Poisson arguments")
    if minutes == 0:
        if events:
            raise ValueError("positive rate events with zero exposure")
        return mean, variance  # Preserve exact prior bits, not a reconstructive round trip.
    try:
        beta = mean / variance
        alpha = mean * beta
        beta_post = beta + minutes / 90
        alpha_post = alpha + events
        updated_mean = alpha_post / beta_post
        updated_variance = updated_mean / beta_post
    except (OverflowError, ZeroDivisionError) as exc:
        raise ValueError("unrepresentable posterior arithmetic") from exc
    if not all(isfinite(v) and v > 0 for v in (alpha, beta, updated_mean, updated_variance)):
        raise ValueError("unrepresentable posterior arithmetic")
    return updated_mean, updated_variance


class CurrentPlayerPosteriorRate(StrictModel):
    channel: Channel
    status: RateStatus
    historical_mean_per90: Rate
    historical_variance_per90: Rate
    posterior_mean_per90: Rate
    posterior_variance_per90: Rate
    observed_rows: Count
    applicable_rows: Count
    included_minutes: Count
    included_events: Count | None
    zero_exposure_discipline_excluded_rows: Count = 0
    zero_exposure_discipline_excluded_events: Count = 0

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.observed_rows > self.applicable_rows:
            raise ValueError("rate coverage exceeds available rows")
        if self.status == "UPDATED":
            if self.included_events is None or self.included_minutes == 0:
                raise ValueError("updated rate requires observed positive exposure")
            expected = gamma_poisson_update(
                self.historical_mean_per90,
                self.historical_variance_per90,
                self.included_events,
                self.included_minutes,
            )
        else:
            expected = (self.historical_mean_per90, self.historical_variance_per90)
        if (self.posterior_mean_per90, self.posterior_variance_per90) != expected:
            raise ValueError("posterior is not the declared conjugate update")
        if self.status == "STRUCTURAL_NON_GK_ZERO" and expected != (0.0, 0.0):
            raise ValueError("non-GK saves must be structural zero")
        return self


class CurrentPlayerPosteriorEntry(SealedModel):
    binding: CurrentGwPlayerPriorBindingEntry
    current_history_entry_sha256: Sha256
    observed_minutes: Count
    rates: tuple[CurrentPlayerPosteriorRate, ...]

    @model_validator(mode="after")
    def channels_complete(self) -> Self:
        if tuple(rate.channel for rate in self.rates) != CHANNELS:
            raise ValueError("posterior channels incomplete or unordered")
        return self


class CurrentPlayerPosteriorArtifact(SealedModel):
    sensitivity_world: World
    information_cutoff: datetime
    target_gameweek: int = Field(gt=1)
    source_gameweeks: tuple[int, ...]
    historical_resource_sha256: Sha256
    source_posterior_sha256: Sha256
    current_history_sha256: Sha256
    current_binding_sha256: Sha256
    current_catalogue_sha256: Sha256
    entries: tuple[CurrentPlayerPosteriorEntry, ...]
    model_input_status: Literal["SHADOW_NOT_MODEL_INPUT"] = "SHADOW_NOT_MODEL_INPUT"
    confidence: Literal[
        "CURRENT_HISTORY_PRESENT_SHADOW_NOT_ACCEPTED",
        "CURRENT_HISTORY_UNAVAILABLE_SHADOW_NOT_ACCEPTED",
    ] = "CURRENT_HISTORY_PRESENT_SHADOW_NOT_ACCEPTED"
    evidence_grade: Literal["E"] = "E"
    hyperparameter_status: Literal["TEMPORARY_CANDIDATE_PARAMETERS"] = (
        "TEMPORARY_CANDIDATE_PARAMETERS"
    )
    shrinkage_strength_calibrated: Literal[False] = False
    model_training_performed: Literal[False] = False
    persistence_performed: Literal[False] = False

    @field_validator("information_cutoff")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cutoff must be aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def source_and_order(self) -> Self:
        ids = tuple(row.binding.source_player_id for row in self.entries)
        if not ids or ids != tuple(sorted(set(ids))):
            raise ValueError("posterior current IDs must be complete, unique and ordered")
        if (
            self.historical_resource_sha256 != RESOURCE_SHA
            or self.source_posterior_sha256 != SOURCE_HASHES[WORLDS.index(self.sensitivity_world)]
        ):
            raise ValueError("posterior historical lineage differs")
        if self.source_gameweeks != tuple(sorted(set(self.source_gameweeks))) or any(
            gw <= 0 or gw >= self.target_gameweek for gw in self.source_gameweeks
        ):
            raise ValueError("posterior source window differs")
        return self


def shadow_profile(
    stale: PlayerAllocationProfile, entry: CurrentPlayerPosteriorEntry
) -> PlayerAllocationProfile:
    """Whitelist construction: total-goal diagnostic has NO route into goal_share."""
    rates: dict[str, CurrentPlayerPosteriorRate] = {rate.channel: rate for rate in entry.rates}
    values = stale.model_dump(mode="python")
    for channel, field in (
        ("assist", "assist_share"),
        ("yellow", "yellow_cards_per90"),
        ("red", "red_cards_per90"),
        ("save", "goalkeeper_saves_per90"),
    ):
        rate = rates[channel]
        if rate.status == "UPDATED":
            values[field] = (
                stale.assist_share * (rate.posterior_mean_per90 / rate.historical_mean_per90)
                if channel == "assist"
                else rate.posterior_mean_per90
            )
    if any(not isfinite(float(values[field])) for field in ALLOWED_PROFILE_FIELDS):
        raise ValueError("unrepresentable shadow allocation weight")
    return PlayerAllocationProfile.model_validate(values)


class CurrentPlayerAllocationShadowWorld(SealedModel):
    posterior: CurrentPlayerPosteriorArtifact
    stale_profiles: tuple[PlayerAllocationProfile, ...]
    profiles: tuple[PlayerAllocationProfile, ...]
    goal_share_status: Literal[
        "GOAL_SHARE_CURRENT_HISTORY_UPDATE_BLOCKED_NO_NONPENALTY_DECOMPOSITION"
    ] = GOAL_STATUS

    @model_validator(mode="after")
    def whitelist_only(self) -> Self:
        entries = self.posterior.entries
        if len(self.stale_profiles) != len(entries) or len(self.profiles) != len(entries):
            raise ValueError("shadow profile coverage differs")
        for entry, stale, profile in zip(entries, self.stale_profiles, self.profiles, strict=True):
            if (stale.player_id, stale.team_id) != (
                entry.binding.current_player_id,
                entry.binding.current_team_id,
            ):
                raise ValueError("shadow profile identity differs")
            if profile != shadow_profile(stale, entry):
                raise ValueError("shadow profile contains unsupported or inconsistent mutation")
        return self


class CurrentPlayerAllocationShadow(SealedModel):
    worlds: tuple[CurrentPlayerAllocationShadowWorld, ...]
    model_input_status: Literal["SHADOW_NOT_MODEL_INPUT"] = "SHADOW_NOT_MODEL_INPUT"
    persistence_performed: Literal[False] = False
    model_training_performed: Literal[False] = False
    new_network_requests: Literal[0] = 0
    limitations: tuple[str, ...] = (
        "CURRENT_FPL_ASSIST_TO_HISTORICAL_BROAD_ASSIST_SEMANTIC_BRIDGE",
        "OFFICIAL_FPL_CBI_NOT_COMPONENT_SPLIT",
        "DIAGNOSTIC_ONLY_NOT_ALLOCATION_COMPONENT_EVIDENCE",
        "HISTORICAL_TEAM_MEMBERSHIP_NOT_PROVEN_BY_CURRENT_BOOTSTRAP",
        "ZERO_EXPOSURE_DISCIPLINE_ONLY_EXCLUDED_FROM_RATE_MODEL",
        "SHRINKAGE_STRENGTH_NOT_CALIBRATED",
    )

    @model_validator(mode="after")
    def all_worlds_common_likelihood(self) -> Self:
        if tuple(w.posterior.sensitivity_world for w in self.worlds) != WORLDS:
            raise ValueError("shadow worlds incomplete or unordered")
        first = self.worlds[0]
        for world in self.worlds[1:]:
            if (
                world.stale_profiles != first.stale_profiles
                or world.posterior.model_dump(
                    exclude={
                        "sensitivity_world",
                        "source_posterior_sha256",
                        "entries",
                        "semantic_sha256",
                    }
                )
                != first.posterior.model_dump(
                    exclude={
                        "sensitivity_world",
                        "source_posterior_sha256",
                        "entries",
                        "semantic_sha256",
                    }
                )
                or tuple(
                    (e.binding, e.current_history_entry_sha256) for e in world.posterior.entries
                )
                != tuple(
                    (e.binding, e.current_history_entry_sha256) for e in first.posterior.entries
                )
            ):
                raise ValueError("shadow worlds do not share current likelihood identity")
        return self
