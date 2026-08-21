"""Typed, posterior-only contracts for the GW1 player-evidence candidate.

The module intentionally accepts only mapped current-catalogue identities and
retains derived posterior parameters.  It has no raw provider-body persistence
surface and no implicit network behaviour.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import BpsAuxiliaryRates, PlayerAllocationProfile, PlayerPosition


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TacticalRole(StrEnum):
    GK = "GK"
    CB = "CB"
    FB_WB = "FB_WB"
    DM = "DM"
    CM = "CM"
    AM = "AM"
    WINGER = "WINGER"
    CF = "CF"
    UNKNOWN = "UNKNOWN"


class EvidenceSourceLevel(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    TACTICAL_ROLE = "TACTICAL_ROLE"
    FPL_POSITION = "FPL_POSITION"
    LEAGUE_GENERIC = "LEAGUE_GENERIC"


class PriceWorld(StrEnum):
    PRICE_OFF = "PRICE_OFF"
    PRICE_MODERATE = "PRICE_MODERATE"
    PRICE_STRONG = "PRICE_STRONG"


class CaptureAccessMode(StrEnum):
    HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT = (
        "HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT"
    )


class RetentionMode(StrEnum):
    POSTERIOR_ONLY = "POSTERIOR_ONLY"


class CurrentPlayerIdentityMode(StrEnum):
    """Identity authority for a current-player catalogue.

    ``GW1_STAGE7_TRANSIENT_SURROGATE`` is deliberately not a canonical database
    identity.  It is the exact short-lived UUID convention consumed by the
    current Stage-7 and Stage-9 paths.
    """

    EXTERNALLY_MAPPED = "EXTERNALLY_MAPPED"
    GW1_STAGE7_TRANSIENT_SURROGATE = "GW1_STAGE7_TRANSIENT_SURROGATE"


class HistorySensitivityWorld(StrEnum):
    CENTRAL_TEMPORARY = "CENTRAL_TEMPORARY"
    LOW_SHRINKAGE = "LOW_SHRINKAGE"
    HIGH_SHRINKAGE = "HIGH_SHRINKAGE"


class PenaltyDesignation(StrEnum):
    PRIMARY = "PRIMARY"
    BACKUP = "BACKUP"
    CANDIDATE = "CANDIDATE"


class OverrideKind(StrEnum):
    TACTICAL_ROLE = "TACTICAL_ROLE"
    PRIMARY_MATERIAL_SET_PIECE = "PRIMARY_MATERIAL_SET_PIECE"
    MAJOR_ROLE_CHANGE = "MAJOR_ROLE_CHANGE"
    NEW_TRANSFER_ROLE = "NEW_TRANSFER_ROLE"


class CurrentPlayer(_Model):
    """A current-stage player row; names are intentionally not identifiers."""

    player_id: UUID
    source_player_id: int = Field(gt=0)
    team_id: UUID
    position: PlayerPosition
    current_price_tenths: int = Field(gt=0)
    source_player_identity_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_team_identity_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CurrentPlayerCatalogue(_Model):
    schema_version: Literal[
        "gw1-player-history-catalogue-v1", "gw1-player-history-catalogue-v2"
    ] = "gw1-player-history-catalogue-v1"
    season_code: Literal["2026/27"] = "2026/27"
    identity_mode: CurrentPlayerIdentityMode = CurrentPlayerIdentityMode.EXTERNALLY_MAPPED
    source_catalogue_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_bundle_semantic_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_bootstrap_semantic_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    players: tuple[CurrentPlayer, ...] = Field(min_length=1)
    semantic_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def identities_are_unique_and_mode_is_explicit(self) -> Self:
        player_ids = [player.player_id for player in self.players]
        source_ids = [player.source_player_id for player in self.players]
        if (
            player_ids != sorted(player_ids, key=str)
            or len(player_ids) != len(set(player_ids))
            or len(source_ids) != len(set(source_ids))
        ):
            raise ValueError("current catalogue identities must be unique and sorted")
        if self.identity_mode is CurrentPlayerIdentityMode.GW1_STAGE7_TRANSIENT_SURROGATE:
            if (
                self.schema_version != "gw1-player-history-catalogue-v2"
                or self.source_bundle_semantic_sha256 is None
                or self.source_bootstrap_semantic_sha256 is None
                or self.semantic_sha256 is None
                or self.source_catalogue_semantic_sha256 != self.source_bundle_semantic_sha256
                or any(
                    player.source_player_identity_sha256 is None
                    or player.source_team_identity_sha256 is None
                    for player in self.players
                )
            ):
                raise ValueError("GW1 transient catalogue lineage is incomplete")
            expected = canonical_sha256(self.model_dump(mode="json", exclude={"semantic_sha256"}))
            if self.semantic_sha256 != expected:
                raise ValueError("GW1 transient catalogue hash is invalid")
        elif (
            self.schema_version != "gw1-player-history-catalogue-v1"
            or self.source_bundle_semantic_sha256 is not None
            or self.source_bootstrap_semantic_sha256 is not None
            or self.semantic_sha256 is not None
            or any(
                player.source_player_identity_sha256 is not None
                or player.source_team_identity_sha256 is not None
                for player in self.players
            )
        ):
            raise ValueError("legacy mapped catalogue must not claim transient source lineage")
        return self


class HistoryPastSeason(_Model):
    """Ephemeral, synthetic-schema-equivalent history-past interpretation only."""

    season: str = Field(pattern=r"^20\d{2}/\d{2}$")
    minutes: int = Field(ge=0)
    goals: int = Field(ge=0)
    assists: int = Field(ge=0)
    yellow_cards: int = Field(ge=0)
    red_cards: int = Field(ge=0)
    saves: int = Field(ge=0)

    @model_validator(mode="after")
    def season_is_complete_and_counts_are_coherent(self) -> Self:
        start = int(self.season[:4])
        if int(self.season[-2:]) != (start + 1) % 100:
            raise ValueError("history season is malformed")
        if self.minutes == 0 and any(value > 0 for value in (self.goals, self.assists, self.saves)):
            raise ValueError("zero-minute rate events are invalid")
        if self.minutes == 0 and any(value > 0 for value in (self.yellow_cards, self.red_cards)):
            raise ValueError("zero-exposure discipline must be excluded before the rate model")
        return self


class PlayerHistoryEvidence(_Model):
    player_id: UUID
    source_player_id: int = Field(gt=0)
    seasons: tuple[HistoryPastSeason, ...]
    zero_exposure_discipline_rows_excluded_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def seasons_are_unique_and_sorted(self) -> Self:
        values = [season.season for season in self.seasons]
        if values != sorted(values) or len(values) != len(set(values)):
            raise ValueError("history seasons must be unique and sorted")
        return self


class TacticalRoleAssignment(_Model):
    player_id: UUID
    tactical_role: TacticalRole


class SyntheticReplayRequest(_Model):
    """Offline-only command input; it cannot represent a live FPL capture."""

    schema_version: Literal["gw1-player-evidence-synthetic-replay-v1"] = (
        "gw1-player-evidence-synthetic-replay-v1"
    )
    source_classification: Literal["SYNTHETIC_REPLAY"] = "SYNTHETIC_REPLAY"
    catalogue: CurrentPlayerCatalogue
    histories: tuple[PlayerHistoryEvidence, ...] = ()
    role_priors: tuple[RolePooledPrior, ...] = Field(min_length=1)
    tactical_roles: tuple[TacticalRoleAssignment, ...] = ()
    information_cutoff: datetime
    source_observed_at: datetime
    usable_at: datetime
    produced_at: datetime
    schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    eb_parameters: EmpiricalBayesParameters
    price_policy: PriceAdjustmentPolicy

    @field_validator("information_cutoff", "source_observed_at", "usable_at", "produced_at")
    @classmethod
    def replay_times_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("replay times must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def replay_is_bounded(self) -> Self:
        ids = [row.player_id for row in self.tactical_roles]
        catalogue_ids = {player.player_id for player in self.catalogue.players}
        if len(ids) != len(set(ids)) or any(item not in catalogue_ids for item in ids):
            raise ValueError("tactical-role replay identities are invalid")
        if self.source_observed_at > self.usable_at or self.usable_at > self.information_cutoff:
            raise ValueError("replay temporal order is invalid")
        return self


class EmpiricalBayesParameters(_Model):
    """Temporary, explicitly sensitivity-scoped Gamma-Poisson parameters."""

    model_version: Literal["GW1_EB_GAMMA_POISSON_V1"] = "GW1_EB_GAMMA_POISSON_V1"
    parameter_status: Literal["TEMPORARY_CANDIDATE_PARAMETERS"] = "TEMPORARY_CANDIDATE_PARAMETERS"
    sensitivity_world: HistorySensitivityWorld
    goal_kappa_full_match_equivalents: float = Field(gt=0.0)
    assist_kappa_full_match_equivalents: float = Field(gt=0.0)
    yellow_kappa_full_match_equivalents: float = Field(gt=0.0)
    red_kappa_full_match_equivalents: float = Field(gt=0.0)
    save_kappa_full_match_equivalents: float = Field(gt=0.0)
    recency_half_life_seasons: float = Field(gt=0.0)


def candidate_eb_parameters(world: HistorySensitivityWorld) -> EmpiricalBayesParameters:
    """Return declared candidate worlds, never a production calibration claim."""

    multiplier = {
        HistorySensitivityWorld.CENTRAL_TEMPORARY: 1.0,
        HistorySensitivityWorld.LOW_SHRINKAGE: 0.5,
        HistorySensitivityWorld.HIGH_SHRINKAGE: 2.0,
    }[world]
    return EmpiricalBayesParameters(
        sensitivity_world=world,
        goal_kappa_full_match_equivalents=10.0 * multiplier,
        assist_kappa_full_match_equivalents=10.0 * multiplier,
        yellow_kappa_full_match_equivalents=7.0 * multiplier,
        red_kappa_full_match_equivalents=30.0 * multiplier,
        save_kappa_full_match_equivalents=7.0 * multiplier,
        recency_half_life_seasons=2.0,
    )


class RolePooledPrior(_Model):
    """Complete governed fallback values; real calibration remains a separate gate."""

    shrinkage_group_id: str = Field(min_length=1, max_length=160)
    position: PlayerPosition | None = None
    tactical_role: TacticalRole | None = None
    source_level: EvidenceSourceLevel
    fallback_reason: str = Field(min_length=1, max_length=400)
    prior_version: str = Field(min_length=1, max_length=120)
    source_reference: str = Field(min_length=1, max_length=1000)
    goal_rate_per90: float = Field(ge=0.0)
    assist_rate_per90: float = Field(ge=0.0)
    yellow_rate_per90: float = Field(ge=0.0)
    red_rate_per90: float = Field(ge=0.0)
    save_rate_per90: float = Field(ge=0.0)
    goal_role_adjustment: float = Field(gt=0.0, le=3.0)
    assist_role_adjustment: float = Field(gt=0.0, le=3.0)
    penalty_weight: float = Field(ge=0.0)
    own_goal_weight: float = Field(ge=0.0)
    saves_inside_box_fraction: float = Field(ge=0.0, le=1.0)
    clearances_per90: float = Field(ge=0.0)
    blocks_per90: float = Field(ge=0.0)
    interceptions_per90: float = Field(ge=0.0)
    tackles_per90: float = Field(ge=0.0)
    ball_recoveries_per90: float = Field(ge=0.0)
    bps_auxiliary: BpsAuxiliaryRates


class PriceAdjustmentPolicy(_Model):
    policy_version: Literal["GW1_PRICE_SPARSE_PRIOR_V1"] = "GW1_PRICE_SPARSE_PRIOR_V1"
    parameter_status: Literal["TEMPORARY_CANDIDATE_PARAMETERS"] = "TEMPORARY_CANDIDATE_PARAMETERS"
    world: PriceWorld = PriceWorld.PRICE_OFF
    sparse_evidence_minutes: float = Field(gt=0.0)
    moderate_max_relative_adjustment: float = Field(ge=0.0, le=0.25)
    strong_max_relative_adjustment: float = Field(ge=0.0, le=0.35)


def candidate_price_policy(world: PriceWorld) -> PriceAdjustmentPolicy:
    return PriceAdjustmentPolicy(
        world=world,
        sparse_evidence_minutes=900.0,
        moderate_max_relative_adjustment=0.10,
        strong_max_relative_adjustment=0.20,
    )


class RoleOverride(_Model):
    player_id: UUID
    team_id: UUID
    override_kind: OverrideKind
    tactical_role: TacticalRole | None = None
    source_reference: str = Field(min_length=1, max_length=1000)
    observed_at: datetime
    usable_at: datetime
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    expires_at: datetime
    reviewer: str = Field(min_length=1, max_length=200)
    status: Literal["HUMAN_REVIEWED"]
    override_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at", "usable_at", "expires_at")
    @classmethod
    def times_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("override times must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def hash_and_times_are_bound(self) -> Self:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"override_sha256"}))
        if self.usable_at < self.observed_at or self.expires_at <= self.usable_at:
            raise ValueError("override temporal bounds are invalid")
        if (
            self.override_kind
            in {
                OverrideKind.TACTICAL_ROLE,
                OverrideKind.MAJOR_ROLE_CHANGE,
                OverrideKind.NEW_TRANSFER_ROLE,
            }
            and self.tactical_role is None
        ):
            raise ValueError("role-changing override requires an explicit tactical role")
        if (
            self.override_kind is OverrideKind.PRIMARY_MATERIAL_SET_PIECE
            and self.tactical_role is not None
        ):
            raise ValueError("set-piece override must not silently reclassify tactical role")
        if self.override_sha256 != expected:
            raise ValueError("override hash is invalid")
        return self


class PenaltyAssignment(_Model):
    player_id: UUID
    team_id: UUID
    designation: PenaltyDesignation
    allocation_weight: float = Field(gt=0.0)
    source_reference: str = Field(min_length=1, max_length=1000)
    observed_at: datetime
    usable_at: datetime
    expires_at: datetime
    reviewer: str = Field(min_length=1, max_length=200)
    status: Literal["HUMAN_REVIEWED"]
    assignment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at", "usable_at", "expires_at")
    @classmethod
    def times_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("penalty assignment times must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def hash_and_times_are_bound(self) -> Self:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"assignment_sha256"}))
        if self.usable_at < self.observed_at or self.expires_at <= self.usable_at:
            raise ValueError("penalty assignment temporal bounds are invalid")
        if self.assignment_sha256 != expected:
            raise ValueError("penalty assignment hash is invalid")
        return self


class PosteriorRate(_Model):
    mean_per90: float = Field(ge=0.0)
    variance_per90: float = Field(ge=0.0)


class PlayerPosterior(_Model):
    player_id: UUID
    source_player_id: int = Field(gt=0)
    history_seasons_included: tuple[str, ...]
    zero_exposure_discipline_rows_excluded_count: int = Field(default=0, ge=0)
    history_limitations: tuple[
        Literal["ZERO_EXPOSURE_DISCIPLINE_ONLY_EXCLUDED_FROM_RATE_MODEL"], ...
    ] = ()
    goal_rate: PosteriorRate
    assist_rate: PosteriorRate
    yellow_rate: PosteriorRate
    red_rate: PosteriorRate
    save_rate: PosteriorRate
    posterior_effective_minutes: float = Field(ge=0.0)
    shrinkage_group_id: str = Field(min_length=1)
    prior_version: str = Field(min_length=1)
    model_version: Literal["GW1_EB_GAMMA_POISSON_V1"] = "GW1_EB_GAMMA_POISSON_V1"
    source_locator: str = Field(min_length=1, max_length=1000)
    source_observed_at: datetime
    usable_at: datetime
    schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rights_profile_id: str = Field(min_length=1)
    access_mode: CaptureAccessMode
    retention_mode: Literal[RetentionMode.POSTERIOR_ONLY] = RetentionMode.POSTERIOR_ONLY

    @field_validator("source_observed_at", "usable_at")
    @classmethod
    def times_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("posterior times must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def temporal_order_is_valid(self) -> Self:
        if self.usable_at < self.source_observed_at:
            raise ValueError("posterior usable_at precedes source observation")
        expected_limitation = (
            ("ZERO_EXPOSURE_DISCIPLINE_ONLY_EXCLUDED_FROM_RATE_MODEL",)
            if self.zero_exposure_discipline_rows_excluded_count > 0
            else ()
        )
        if self.history_limitations != expected_limitation:
            raise ValueError("posterior history exclusion lineage is inconsistent")
        return self


class PlayerPosteriorArtifact(_Model):
    schema_version: Literal["gw1-player-posterior-artifact-v1"] = "gw1-player-posterior-artifact-v1"
    status: Literal["CANDIDATE_NOT_ACCEPTED"] = "CANDIDATE_NOT_ACCEPTED"
    role_prior_real_calibration: Literal["SEPARATE_CHECKPOINT"] = "SEPARATE_CHECKPOINT"
    replay_limitation: Literal["RAW_HISTORY_NOT_RETAINED_BYTE_REPLAY_UNAVAILABLE"] = (
        "RAW_HISTORY_NOT_RETAINED_BYTE_REPLAY_UNAVAILABLE"
    )
    information_cutoff: datetime
    produced_at: datetime
    parameters: EmpiricalBayesParameters
    players: tuple[PlayerPosterior, ...] = Field(min_length=1)
    zero_exposure_discipline_rows_excluded_count: int = Field(ge=0)
    raw_history_persisted: Literal[False] = False
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("information_cutoff", "produced_at")
    @classmethod
    def times_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("artifact times must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def artifact_is_bound_and_safe(self) -> Self:
        ids = [player.player_id for player in self.players]
        if ids != sorted(ids, key=str) or len(ids) != len(set(ids)):
            raise ValueError("posterior players must be unique and sorted")
        if any(player.usable_at > self.information_cutoff for player in self.players):
            raise ValueError("posterior is post-cutoff")
        if self.zero_exposure_discipline_rows_excluded_count != sum(
            player.zero_exposure_discipline_rows_excluded_count for player in self.players
        ):
            raise ValueError("posterior history exclusion count is inconsistent")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected:
            raise ValueError("posterior artifact hash is invalid")
        return self


class ProfileLineage(_Model):
    player_id: UUID
    source_player_id: int = Field(gt=0)
    goal_source_level: EvidenceSourceLevel
    assist_source_level: EvidenceSourceLevel
    auxiliary_source_level: EvidenceSourceLevel
    fallback_reason: str = Field(min_length=1, max_length=400)
    prior_version: str = Field(min_length=1)
    limitations: tuple[str, ...]


class PlayerAllocationCandidateArtifact(_Model):
    schema_version: Literal["gw1-player-allocation-candidate-v1"] = (
        "gw1-player-allocation-candidate-v1"
    )
    status: Literal["CANDIDATE_NOT_ACCEPTED"] = "CANDIDATE_NOT_ACCEPTED"
    information_cutoff: datetime
    posterior_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    price_policy: PriceAdjustmentPolicy
    degraded_player_allocation: bool
    profiles: tuple[PlayerAllocationProfile, ...] = Field(min_length=1)
    lineage: tuple[ProfileLineage, ...] = Field(min_length=1)
    limitations: tuple[str, ...]
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("information_cutoff")
    @classmethod
    def cutoff_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("information cutoff must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def profiles_are_complete_and_bound(self) -> Self:
        profile_ids = [profile.player_id for profile in self.profiles]
        lineage_ids = [str(lineage.player_id) for lineage in self.lineage]
        if (
            profile_ids != sorted(profile_ids)
            or len(profile_ids) != len(set(profile_ids))
            or set(profile_ids) != set(lineage_ids)
        ):
            raise ValueError("allocation profiles and lineage must be one-to-one and sorted")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected:
            raise ValueError("allocation artifact hash is invalid")
        return self


class PlayerHistoryRightsApproval(_Model):
    """Future human-signed decision, deliberately absent from this ticket."""

    schema_version: Literal["gw1-player-history-rights-approval-v1"] = (
        "gw1-player-history-rights-approval-v1"
    )
    status: Literal["HUMAN_ACCEPTED"]
    scope: Literal["PRIVATE_2026_27_GW1_ONLY"]
    rights_profile_id: str = Field(min_length=1)
    source_url_template: Literal[
        "https://fantasy.premierleague.com/api/element-summary/{current_element_id}/"
    ]
    allowed_node: Literal["history_past"]
    access_mode: Literal[CaptureAccessMode.HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT]
    raw_retention: Literal["FORBIDDEN"]
    derived_retention: Literal[RetentionMode.POSTERIOR_ONLY]
    redistribution: Literal["NONE"]
    repeat_collection: Literal["REQUIRES_NEW_APPROVAL"]
    source_hash_permitted: bool
    terms_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    history_past_schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    governance_approval_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    maximum_player_requests: int | None = Field(default=None, gt=0, le=650)
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("approved_at")
    @classmethod
    def approval_time_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approval time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def approval_is_hash_bound(self) -> Self:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))
        if self.approval_sha256 != expected:
            raise ValueError("rights approval hash is invalid")
        return self


class DeletionManifest(_Model):
    run_id: UUID
    temporary_object_identifiers: tuple[str, ...]
    deletion_timestamp: datetime
    deletion_outcome: Literal["NOT_RUN", "SUCCESS", "FAILED"]
    posterior_artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    raw_history_persisted: Literal[False] = False
    current_catalogue_persisted: Literal[False] = False

    @field_validator("deletion_timestamp")
    @classmethod
    def deletion_time_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deletion time must be timezone-aware")
        return value.astimezone(UTC)


class HistoryCaptureSummary(_Model):
    status: Literal["BLOCKED", "CAPTURED_POSTERIOR_ONLY"]
    approval_present: bool
    rights_mode: str
    expected_count: int = Field(ge=0)
    requested_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    fallback_count: int = Field(ge=0)
    posterior_artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    raw_persistence: Literal[False] = False
    deletion_status: Literal["NOT_RUN", "SUCCESS", "FAILED"]
