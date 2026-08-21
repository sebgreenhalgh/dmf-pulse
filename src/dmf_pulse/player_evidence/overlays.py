"""Governed current-penalty overlays and three-world allocation sensitivity."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import PlayerAllocationProfile
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.models import (
    CurrentPlayerCatalogue,
    HistorySensitivityWorld,
    PenaltyAssignment,
    PenaltyDesignation,
    PlayerAllocationCandidateArtifact,
    PlayerPosteriorArtifact,
    PriceAdjustmentPolicy,
    RoleOverride,
    RolePooledPrior,
)
from dmf_pulse.player_evidence.profiles import build_allocation_candidate


class _OverlayModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PenaltyResponsibilityClassification(StrEnum):
    CLEAR_PRIMARY = "CLEAR_PRIMARY"
    PRIMARY_WITH_BACKUP = "PRIMARY_WITH_BACKUP"
    MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
    UNKNOWN = "UNKNOWN"


class ReviewConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PrivatePenaltyCandidateReview(_OverlayModel):
    """Private display metadata bound to exact current identities.

    Display names are review aids only. Compilation resolves and validates the
    explicit source ID and UUID fields; it never searches by name.
    """

    source_player_id: int = Field(gt=0)
    player_id: UUID
    team_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    designation: PenaltyDesignation
    allocation_weight: float = Field(gt=0.0, le=1.0)
    source_reference: str = Field(min_length=1, max_length=1000)


class PrivateTeamPenaltyReview(_OverlayModel):
    provider_team_id: int = Field(gt=0)
    team_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    classification: PenaltyResponsibilityClassification
    confidence: ReviewConfidence
    uncertainty_flag: bool
    reason: str = Field(min_length=1, max_length=1000)
    evidence_source_references: tuple[str, ...] = Field(min_length=1)
    observed_at: datetime
    usable_at: datetime
    expires_at: datetime
    candidates: tuple[PrivatePenaltyCandidateReview, ...] = ()

    @field_validator("observed_at", "usable_at", "expires_at")
    @classmethod
    def times_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("penalty-review times must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("evidence_source_references")
    @classmethod
    def sources_are_public_https_urls(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("penalty-review source references must be unique and sorted")
        if any(urlsplit(value).scheme != "https" or not urlsplit(value).netloc for value in values):
            raise ValueError("penalty-review source references must be HTTPS URLs")
        return values

    @model_validator(mode="after")
    def classification_and_candidates_are_coherent(self) -> PrivateTeamPenaltyReview:
        if self.usable_at < self.observed_at or self.expires_at <= self.usable_at:
            raise ValueError("penalty-review temporal bounds are invalid")
        if any(candidate.team_id != self.team_id for candidate in self.candidates):
            raise ValueError("penalty-review candidate has the wrong team identity")
        player_ids = [candidate.player_id for candidate in self.candidates]
        source_ids = [candidate.source_player_id for candidate in self.candidates]
        if len(player_ids) != len(set(player_ids)) or len(source_ids) != len(set(source_ids)):
            raise ValueError("penalty-review candidates must have unique identities")
        if any(
            candidate.source_reference not in self.evidence_source_references
            for candidate in self.candidates
        ):
            raise ValueError("penalty-review candidate source is not in the reviewed source set")
        if self.classification is PenaltyResponsibilityClassification.UNKNOWN:
            if self.candidates or not self.uncertainty_flag:
                raise ValueError("UNKNOWN penalty responsibility must be empty and explicit")
            return self
        if not math.isclose(
            sum(candidate.allocation_weight for candidate in self.candidates),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("penalty-review candidate weights must sum to one")
        designations = [candidate.designation for candidate in self.candidates]
        if self.classification is PenaltyResponsibilityClassification.CLEAR_PRIMARY:
            if len(self.candidates) != 1 or designations != [PenaltyDesignation.PRIMARY]:
                raise ValueError("CLEAR_PRIMARY requires one primary candidate")
        elif self.classification is PenaltyResponsibilityClassification.PRIMARY_WITH_BACKUP:
            if (
                designations.count(PenaltyDesignation.PRIMARY) != 1
                or not any(value is PenaltyDesignation.BACKUP for value in designations)
                or any(
                    value not in {PenaltyDesignation.PRIMARY, PenaltyDesignation.BACKUP}
                    for value in designations
                )
            ):
                raise ValueError("PRIMARY_WITH_BACKUP requires one primary and backups")
        elif len(self.candidates) < 2 or any(
            value is not PenaltyDesignation.CANDIDATE for value in designations
        ):
            raise ValueError("MULTIPLE_CANDIDATES requires at least two candidate designations")
        return self


class PrivateAllocationOverlayReview(_OverlayModel):
    schema_version: str = Field(pattern=r"^gw1-player-allocation-overlay-private-review-v1$")
    status: str = Field(pattern=r"^PRIVATE_OPERATOR_REVIEW_NOT_FOR_PUBLICATION$")
    scope: str = Field(pattern=r"^PRIVATE_2026_27_GW1_ONLY$")
    catalogue_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_player_count: int = Field(gt=0)
    expected_team_count: int = Field(gt=0)
    information_cutoff: datetime
    reviewer: str = Field(min_length=1, max_length=200)
    role_review_rationale: str = Field(min_length=1, max_length=2000)
    teams: tuple[PrivateTeamPenaltyReview, ...] = Field(min_length=1)
    role_overrides: tuple[RoleOverride, ...] = ()
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("information_cutoff")
    @classmethod
    def cutoff_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("overlay information cutoff must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def review_is_complete_and_hash_bound(self) -> PrivateAllocationOverlayReview:
        if len(self.teams) != self.expected_team_count:
            raise ValueError("private penalty review has the wrong team count")
        provider_ids = [team.provider_team_id for team in self.teams]
        team_ids = [team.team_id for team in self.teams]
        if (
            provider_ids != sorted(provider_ids)
            or len(provider_ids) != len(set(provider_ids))
            or len(team_ids) != len(set(team_ids))
        ):
            raise ValueError("private penalty-review teams must be unique and provider-sorted")
        candidate_ids = [
            candidate.player_id for team in self.teams for candidate in team.candidates
        ]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("one player cannot hold two current penalty assignments")
        if any(
            team.observed_at > team.usable_at
            or team.usable_at > self.information_cutoff
            or team.expires_at <= self.information_cutoff
            for team in self.teams
        ):
            raise ValueError("private penalty review is outside the decision information set")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"review_sha256"}))
        if self.review_sha256 != expected:
            raise ValueError("private overlay review hash is invalid")
        return self


class AllocationWorldBinding(_OverlayModel):
    world: HistorySensitivityWorld
    posterior_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    allocation_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_count: int = Field(gt=0)


class SensitivityMetric(_OverlayModel):
    median_absolute_movement: float = Field(ge=0.0)
    p90_absolute_movement: float = Field(ge=0.0)
    maximum_absolute_movement: float = Field(ge=0.0)
    material_threshold: float = Field(gt=0.0)
    players_at_or_above_material_threshold: int = Field(ge=0)


class TeamInstability(_OverlayModel):
    team_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    maximum_pairwise_total_variation: float = Field(ge=0.0)


class AllocationSensitivitySummary(_OverlayModel):
    schema_version: str = Field(pattern=r"^gw1-player-allocation-sensitivity-summary-v1$")
    status: str = Field(pattern=r"^CANDIDATE_NOT_HUMAN_ACCEPTED$")
    information_cutoff: datetime
    player_count: int = Field(gt=0)
    team_count: int = Field(gt=0)
    allocation_bindings: tuple[AllocationWorldBinding, ...] = Field(min_length=3, max_length=3)
    goal_share: SensitivityMetric
    assist_share: SensitivityMetric
    players_materially_unstable_on_either_metric: int = Field(ge=0)
    largest_team_goal_instability: TeamInstability
    largest_team_assist_instability: TeamInstability
    penalty_profiles_invariant_across_worlds: int = Field(ge=0)
    penalty_clubs_invariant_across_worlds: int = Field(ge=0)
    raw_fpl_history_persisted: bool
    current_fpl_catalogue_persisted: bool
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("information_cutoff")
    @classmethod
    def cutoff_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("sensitivity cutoff must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def summary_is_hash_bound(self) -> AllocationSensitivitySummary:
        worlds = [binding.world for binding in self.allocation_bindings]
        if set(worlds) != set(HistorySensitivityWorld) or len(worlds) != len(set(worlds)):
            raise ValueError("sensitivity summary must bind the three declared worlds")
        if self.raw_fpl_history_persisted or self.current_fpl_catalogue_persisted:
            raise ValueError("sensitivity summary violates the derived-only boundary")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected:
            raise ValueError("sensitivity summary hash is invalid")
        return self


class PenaltyOverlayReceipt(_OverlayModel):
    schema_version: str = Field(pattern=r"^gw1-current-penalty-role-overlay-receipt-v1$")
    status: str = Field(pattern=r"^CANDIDATE_NOT_HUMAN_ACCEPTED$")
    information_cutoff: datetime
    produced_at: datetime
    catalogue_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    player_count: int = Field(gt=0)
    team_count: int = Field(gt=0)
    private_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    penalty_assignment_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    penalty_assignment_status: str = Field(pattern=r"^REVIEWED_CANDIDATE_NOT_HUMAN_ACCEPTED$")
    penalty_assignment_count: int = Field(ge=0)
    classification_counts: dict[str, int]
    unknown_team_identity_sha256s: tuple[str, ...]
    reviewed_source_domains: tuple[str, ...]
    reviewed_source_references_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role_override_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role_override_count: int = Field(ge=0)
    role_review_rationale: str = Field(min_length=1, max_length=2000)
    allocation_bindings: tuple[AllocationWorldBinding, ...] = Field(min_length=3, max_length=3)
    sensitivity_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_stage7_player_identity_equality: bool
    exact_stage7_team_identity_equality: bool
    stage7_expected_minutes_separate: bool
    penalty_assignments_affect_penalty_share_only: bool
    whole_roster_uniform_fallback_only_when_explicit_unknown: bool
    zero_exposure_discipline_lineage_preserved: bool
    defensive_contribution_model_completeness: str = Field(pattern=r"^PARTIAL$")
    raw_fpl_history_persisted: bool
    current_fpl_catalogue_persisted: bool
    history_network_request_count: int = Field(ge=0)
    player_allocation_human_accepted: bool
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("information_cutoff", "produced_at")
    @classmethod
    def times_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("overlay receipt times must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def receipt_is_safe_and_hash_bound(self) -> PenaltyOverlayReceipt:
        if self.produced_at > self.information_cutoff:
            raise ValueError("overlay receipt is post-cutoff")
        if (
            self.raw_fpl_history_persisted
            or self.current_fpl_catalogue_persisted
            or self.history_network_request_count != 0
            or self.player_allocation_human_accepted
        ):
            raise ValueError("overlay receipt violates the bounded review state")
        if not all(
            (
                self.exact_stage7_player_identity_equality,
                self.exact_stage7_team_identity_equality,
                self.stage7_expected_minutes_separate,
                self.penalty_assignments_affect_penalty_share_only,
                self.whole_roster_uniform_fallback_only_when_explicit_unknown,
                self.zero_exposure_discipline_lineage_preserved,
            )
        ):
            raise ValueError("overlay receipt cannot report an unvalidated allocation")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("overlay receipt hash is invalid")
        return self


class PlayerSensitivityRow(_OverlayModel):
    player_id: UUID
    team_id: UUID
    central_goal_share: float = Field(ge=0.0)
    low_goal_share: float = Field(ge=0.0)
    high_goal_share: float = Field(ge=0.0)
    central_assist_share: float = Field(ge=0.0)
    low_assist_share: float = Field(ge=0.0)
    high_assist_share: float = Field(ge=0.0)
    maximum_absolute_goal_share_movement: float = Field(ge=0.0)
    maximum_absolute_assist_share_movement: float = Field(ge=0.0)


@dataclass(frozen=True)
class CompiledAllocationOverlay:
    assignments: tuple[PenaltyAssignment, ...]
    assignment_artifact_sha256: str
    role_override_artifact_sha256: str
    allocations: Mapping[HistorySensitivityWorld, PlayerAllocationCandidateArtifact]
    sensitivity_rows: tuple[PlayerSensitivityRow, ...]
    sensitivity_summary: AllocationSensitivitySummary
    receipt: PenaltyOverlayReceipt


def load_private_overlay_review(path: Path) -> PrivateAllocationOverlayReview:
    try:
        return PrivateAllocationOverlayReview.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise IngestionError(
            "OVERLAY_REVIEW_INVALID", "private penalty/role review is invalid"
        ) from exc


def _compile_assignments(
    review: PrivateAllocationOverlayReview,
) -> tuple[tuple[PenaltyAssignment, ...], str]:
    assignments: list[PenaltyAssignment] = []
    for team in review.teams:
        for candidate in team.candidates:
            provisional = PenaltyAssignment.model_construct(
                player_id=candidate.player_id,
                team_id=candidate.team_id,
                designation=candidate.designation,
                allocation_weight=candidate.allocation_weight,
                source_reference=candidate.source_reference,
                observed_at=team.observed_at,
                usable_at=team.usable_at,
                expires_at=team.expires_at,
                reviewer=review.reviewer,
                status="REVIEWED_CANDIDATE_NOT_HUMAN_ACCEPTED",
                assignment_sha256="0" * 64,
            )
            assignments.append(
                PenaltyAssignment(
                    player_id=candidate.player_id,
                    team_id=candidate.team_id,
                    designation=candidate.designation,
                    allocation_weight=candidate.allocation_weight,
                    source_reference=candidate.source_reference,
                    observed_at=team.observed_at,
                    usable_at=team.usable_at,
                    expires_at=team.expires_at,
                    reviewer=review.reviewer,
                    status="REVIEWED_CANDIDATE_NOT_HUMAN_ACCEPTED",
                    assignment_sha256=canonical_sha256(
                        provisional.model_dump(mode="json", exclude={"assignment_sha256"})
                    ),
                )
            )
    ordered = tuple(sorted(assignments, key=lambda item: str(item.player_id)))
    artifact_sha256 = canonical_sha256(
        {
            "schema_version": "gw1-current-penalty-assignment-private-artifact-v1",
            "private_review_sha256": review.review_sha256,
            "assignments": [item.model_dump(mode="json") for item in ordered],
        }
    )
    return ordered, artifact_sha256


def _pairwise_movement(values: tuple[float, float, float]) -> float:
    return max(
        abs(values[0] - values[1]),
        abs(values[0] - values[2]),
        abs(values[1] - values[2]),
    )


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("cannot calculate an empty percentile")
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _team_instability(
    rows: Sequence[PlayerSensitivityRow],
    *,
    metric: str,
) -> TeamInstability:
    by_team: dict[UUID, list[PlayerSensitivityRow]] = defaultdict(list)
    for row in rows:
        by_team[row.team_id].append(row)
    best_team: UUID | None = None
    best_value = -1.0
    for team_id, team_rows in by_team.items():
        worlds = (
            [getattr(row, f"central_{metric}_share") for row in team_rows],
            [getattr(row, f"low_{metric}_share") for row in team_rows],
            [getattr(row, f"high_{metric}_share") for row in team_rows],
        )
        maximum = max(
            sum(abs(left - right) for left, right in zip(worlds[a], worlds[b], strict=True)) / 2.0
            for a, b in ((0, 1), (0, 2), (1, 2))
        )
        if maximum > best_value or (
            math.isclose(maximum, best_value)
            and best_team is not None
            and str(team_id) < str(best_team)
        ):
            best_team = team_id
            best_value = maximum
    if best_team is None:
        raise ValueError("cannot calculate team instability without teams")
    return TeamInstability(
        team_identity_sha256=canonical_sha256({"team_id": str(best_team)}),
        maximum_pairwise_total_variation=best_value,
    )


def _model_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for child in value.values():
            keys.update(_model_keys(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            keys.update(_model_keys(child))
    return keys


def compile_current_allocation_overlay(
    *,
    review: PrivateAllocationOverlayReview,
    catalogue: CurrentPlayerCatalogue,
    team_ids_by_provider: Mapping[int, UUID],
    posteriors: Mapping[HistorySensitivityWorld, PlayerPosteriorArtifact],
    role_priors: Sequence[RolePooledPrior],
    price_policy: PriceAdjustmentPolicy,
    produced_at: datetime,
    goal_material_threshold: float = 0.02,
    assist_material_threshold: float = 0.02,
) -> CompiledAllocationOverlay:
    """Compile one reviewed overlay without transport or posterior mutation."""

    if produced_at.tzinfo is None or produced_at.utcoffset() is None:
        raise IngestionError("TEMPORAL_INVALID", "overlay produced_at must be timezone-aware")
    produced = produced_at.astimezone(UTC)
    if produced > review.information_cutoff:
        raise IngestionError("POST_CUTOFF", "overlay produced_at exceeds information cutoff")
    catalogue_hash = catalogue.semantic_sha256 or catalogue.source_catalogue_semantic_sha256
    if catalogue_hash != review.catalogue_semantic_sha256:
        raise IngestionError("IDENTITY_CONFLICT", "overlay review catalogue hash does not match")
    if len(catalogue.players) != review.expected_player_count:
        raise IngestionError("IDENTITY_CONFLICT", "overlay review player count does not match")
    if dict(team_ids_by_provider) != {team.provider_team_id: team.team_id for team in review.teams}:
        raise IngestionError("IDENTITY_CONFLICT", "overlay review team identities do not match")
    known_by_source = {player.source_player_id: player for player in catalogue.players}
    for team in review.teams:
        for candidate in team.candidates:
            player = known_by_source.get(candidate.source_player_id)
            if (
                player is None
                or player.player_id != candidate.player_id
                or player.team_id != candidate.team_id
            ):
                raise IngestionError(
                    "IDENTITY_CONFLICT", "overlay candidate is not an exact current identity"
                )
    if set(posteriors) != set(HistorySensitivityWorld):
        raise IngestionError("OVERLAY_INPUT_INVALID", "all three posterior worlds are required")
    expected_player_ids = {str(player.player_id) for player in catalogue.players}
    expected_team_by_player = {
        str(player.player_id): str(player.team_id) for player in catalogue.players
    }
    assignments, assignment_artifact_sha256 = _compile_assignments(review)
    role_override_artifact_sha256 = canonical_sha256(
        {
            "schema_version": "gw1-current-role-override-private-artifact-v1",
            "private_review_sha256": review.review_sha256,
            "role_overrides": [
                item.model_dump(mode="json")
                for item in sorted(review.role_overrides, key=lambda row: str(row.player_id))
            ],
        }
    )
    allocations: dict[HistorySensitivityWorld, PlayerAllocationCandidateArtifact] = {}
    for world in HistorySensitivityWorld:
        posterior = posteriors[world]
        if posterior.parameters.sensitivity_world is not world:
            raise IngestionError("OVERLAY_INPUT_INVALID", "posterior world label does not match")
        if posterior.information_cutoff != review.information_cutoff:
            raise IngestionError("POST_CUTOFF", "posterior cutoff does not match overlay review")
        allocation = build_allocation_candidate(
            catalogue=catalogue,
            posterior=posterior,
            role_priors=role_priors,
            tactical_roles={},
            role_overrides=review.role_overrides,
            penalty_assignments=assignments,
            information_cutoff=review.information_cutoff,
            price_policy=price_policy,
            degraded_player_allocation=False,
        )
        baseline = build_allocation_candidate(
            catalogue=catalogue,
            posterior=posterior,
            role_priors=role_priors,
            tactical_roles={},
            role_overrides=review.role_overrides,
            penalty_assignments=(),
            information_cutoff=review.information_cutoff,
            price_policy=price_policy,
            degraded_player_allocation=False,
        )
        baseline_by_id = {profile.player_id: profile for profile in baseline.profiles}
        for profile in allocation.profiles:
            if profile.model_dump(mode="json", exclude={"penalty_taker_share"}) != baseline_by_id[
                profile.player_id
            ].model_dump(mode="json", exclude={"penalty_taker_share"}):
                raise IngestionError(
                    "OVERLAY_EFFECT_INVALID", "penalty assignment changed a non-penalty field"
                )
        if {profile.player_id for profile in allocation.profiles} != expected_player_ids:
            raise IngestionError("IDENTITY_CONFLICT", "overlay allocation player IDs differ")
        if {
            profile.player_id: profile.team_id for profile in allocation.profiles
        } != expected_team_by_player:
            raise IngestionError("IDENTITY_CONFLICT", "overlay allocation team IDs differ")
        allocations[world] = allocation

    classification_by_team = {team.team_id: team.classification for team in review.teams}
    for allocation in allocations.values():
        profiles_by_team: dict[str, list[PlayerAllocationProfile]] = defaultdict(list)
        for profile in allocation.profiles:
            profiles_by_team[profile.team_id].append(profile)
        for team_id_value, profiles in profiles_by_team.items():
            if not math.isclose(
                sum(profile.penalty_taker_share for profile in profiles),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise IngestionError("PENALTY_PROPENSITY_EMPTY", "team penalty shares do not sum")
            team_id = UUID(team_id_value)
            positive = [profile for profile in profiles if profile.penalty_taker_share > 0.0]
            if classification_by_team[
                team_id
            ] is not PenaltyResponsibilityClassification.UNKNOWN and len(positive) == len(profiles):
                raise IngestionError(
                    "OVERLAY_EFFECT_INVALID", "reviewed team retained whole-roster penalty mass"
                )

    central = allocations[HistorySensitivityWorld.CENTRAL_TEMPORARY]
    low = allocations[HistorySensitivityWorld.LOW_SHRINKAGE]
    high = allocations[HistorySensitivityWorld.HIGH_SHRINKAGE]
    low_by_id = {profile.player_id: profile for profile in low.profiles}
    high_by_id = {profile.player_id: profile for profile in high.profiles}
    sensitivity_rows: list[PlayerSensitivityRow] = []
    for profile in central.profiles:
        low_profile = low_by_id[profile.player_id]
        high_profile = high_by_id[profile.player_id]
        goal_values = (profile.goal_share, low_profile.goal_share, high_profile.goal_share)
        assist_values = (profile.assist_share, low_profile.assist_share, high_profile.assist_share)
        sensitivity_rows.append(
            PlayerSensitivityRow(
                player_id=UUID(profile.player_id),
                team_id=UUID(profile.team_id),
                central_goal_share=profile.goal_share,
                low_goal_share=low_profile.goal_share,
                high_goal_share=high_profile.goal_share,
                central_assist_share=profile.assist_share,
                low_assist_share=low_profile.assist_share,
                high_assist_share=high_profile.assist_share,
                maximum_absolute_goal_share_movement=_pairwise_movement(goal_values),
                maximum_absolute_assist_share_movement=_pairwise_movement(assist_values),
            )
        )
    ordered_rows = tuple(sorted(sensitivity_rows, key=lambda row: str(row.player_id)))
    goal_movements = [row.maximum_absolute_goal_share_movement for row in ordered_rows]
    assist_movements = [row.maximum_absolute_assist_share_movement for row in ordered_rows]
    material_ids = {
        row.player_id
        for row in ordered_rows
        if row.maximum_absolute_goal_share_movement >= goal_material_threshold
        or row.maximum_absolute_assist_share_movement >= assist_material_threshold
    }
    central_penalties = {
        profile.player_id: profile.penalty_taker_share for profile in central.profiles
    }
    low_penalties = {profile.player_id: profile.penalty_taker_share for profile in low.profiles}
    high_penalties = {profile.player_id: profile.penalty_taker_share for profile in high.profiles}
    penalty_profiles_invariant = sum(
        central_penalties[player_id] == low_penalties[player_id] == high_penalties[player_id]
        for player_id in central_penalties
    )
    bindings = tuple(
        AllocationWorldBinding(
            world=world,
            posterior_artifact_sha256=posteriors[world].artifact_sha256,
            allocation_artifact_sha256=allocations[world].artifact_sha256,
            profile_count=len(allocations[world].profiles),
        )
        for world in HistorySensitivityWorld
    )
    goal_metric = SensitivityMetric(
        median_absolute_movement=_percentile(goal_movements, 0.5),
        p90_absolute_movement=_percentile(goal_movements, 0.9),
        maximum_absolute_movement=max(goal_movements),
        material_threshold=goal_material_threshold,
        players_at_or_above_material_threshold=sum(
            value >= goal_material_threshold for value in goal_movements
        ),
    )
    assist_metric = SensitivityMetric(
        median_absolute_movement=_percentile(assist_movements, 0.5),
        p90_absolute_movement=_percentile(assist_movements, 0.9),
        maximum_absolute_movement=max(assist_movements),
        material_threshold=assist_material_threshold,
        players_at_or_above_material_threshold=sum(
            value >= assist_material_threshold for value in assist_movements
        ),
    )
    largest_team_goal_instability = _team_instability(ordered_rows, metric="goal")
    largest_team_assist_instability = _team_instability(ordered_rows, metric="assist")
    provisional_summary = AllocationSensitivitySummary.model_construct(
        schema_version="gw1-player-allocation-sensitivity-summary-v1",
        status="CANDIDATE_NOT_HUMAN_ACCEPTED",
        information_cutoff=review.information_cutoff,
        player_count=len(catalogue.players),
        team_count=len(review.teams),
        allocation_bindings=bindings,
        goal_share=goal_metric,
        assist_share=assist_metric,
        players_materially_unstable_on_either_metric=len(material_ids),
        largest_team_goal_instability=largest_team_goal_instability,
        largest_team_assist_instability=largest_team_assist_instability,
        penalty_profiles_invariant_across_worlds=penalty_profiles_invariant,
        penalty_clubs_invariant_across_worlds=len(review.teams),
        raw_fpl_history_persisted=False,
        current_fpl_catalogue_persisted=False,
        artifact_sha256="0" * 64,
    )
    summary = AllocationSensitivitySummary(
        schema_version="gw1-player-allocation-sensitivity-summary-v1",
        status="CANDIDATE_NOT_HUMAN_ACCEPTED",
        information_cutoff=review.information_cutoff,
        player_count=len(catalogue.players),
        team_count=len(review.teams),
        allocation_bindings=bindings,
        goal_share=goal_metric,
        assist_share=assist_metric,
        players_materially_unstable_on_either_metric=len(material_ids),
        largest_team_goal_instability=largest_team_goal_instability,
        largest_team_assist_instability=largest_team_assist_instability,
        penalty_profiles_invariant_across_worlds=penalty_profiles_invariant,
        penalty_clubs_invariant_across_worlds=len(review.teams),
        raw_fpl_history_persisted=False,
        current_fpl_catalogue_persisted=False,
        artifact_sha256=canonical_sha256(
            provisional_summary.model_dump(mode="json", exclude={"artifact_sha256"})
        ),
    )
    source_references = tuple(
        sorted({source for team in review.teams for source in team.evidence_source_references})
    )
    counts = {
        classification.value: sum(team.classification is classification for team in review.teams)
        for classification in PenaltyResponsibilityClassification
    }
    unknown_team_hashes = tuple(
        sorted(
            canonical_sha256({"team_id": str(team.team_id)})
            for team in review.teams
            if team.classification is PenaltyResponsibilityClassification.UNKNOWN
        )
    )
    reviewed_source_domains = tuple(
        sorted({urlsplit(source).netloc.lower() for source in source_references})
    )
    zero_exposure_lineage_preserved = all(
        ("ZERO_EXPOSURE_DISCIPLINE_ONLY_EXCLUDED_FROM_RATE_MODEL" in allocation.limitations)
        == (posteriors[world].zero_exposure_discipline_rows_excluded_count > 0)
        for world, allocation in allocations.items()
    )
    forbidden_keys = {"p_start", "p_appearance", "expected_minutes", "history_past"}
    if any(
        not _model_keys(allocation.model_dump(mode="json")).isdisjoint(forbidden_keys)
        for allocation in allocations.values()
    ):
        raise IngestionError("OVERLAY_EFFECT_INVALID", "overlay contains forbidden fields")
    provisional_receipt = PenaltyOverlayReceipt.model_construct(
        schema_version="gw1-current-penalty-role-overlay-receipt-v1",
        status="CANDIDATE_NOT_HUMAN_ACCEPTED",
        information_cutoff=review.information_cutoff,
        produced_at=produced,
        catalogue_semantic_sha256=catalogue_hash,
        player_count=len(catalogue.players),
        team_count=len(review.teams),
        private_review_sha256=review.review_sha256,
        penalty_assignment_artifact_sha256=assignment_artifact_sha256,
        penalty_assignment_status="REVIEWED_CANDIDATE_NOT_HUMAN_ACCEPTED",
        penalty_assignment_count=len(assignments),
        classification_counts=counts,
        unknown_team_identity_sha256s=unknown_team_hashes,
        reviewed_source_domains=reviewed_source_domains,
        reviewed_source_references_sha256=canonical_sha256(source_references),
        role_override_artifact_sha256=role_override_artifact_sha256,
        role_override_count=len(review.role_overrides),
        role_review_rationale=review.role_review_rationale,
        allocation_bindings=bindings,
        sensitivity_artifact_sha256=summary.artifact_sha256,
        exact_stage7_player_identity_equality=True,
        exact_stage7_team_identity_equality=True,
        stage7_expected_minutes_separate=True,
        penalty_assignments_affect_penalty_share_only=True,
        whole_roster_uniform_fallback_only_when_explicit_unknown=True,
        zero_exposure_discipline_lineage_preserved=zero_exposure_lineage_preserved,
        defensive_contribution_model_completeness="PARTIAL",
        raw_fpl_history_persisted=False,
        current_fpl_catalogue_persisted=False,
        history_network_request_count=0,
        player_allocation_human_accepted=False,
        receipt_sha256="0" * 64,
    )
    receipt = PenaltyOverlayReceipt(
        schema_version="gw1-current-penalty-role-overlay-receipt-v1",
        status="CANDIDATE_NOT_HUMAN_ACCEPTED",
        information_cutoff=review.information_cutoff,
        produced_at=produced,
        catalogue_semantic_sha256=catalogue_hash,
        player_count=len(catalogue.players),
        team_count=len(review.teams),
        private_review_sha256=review.review_sha256,
        penalty_assignment_artifact_sha256=assignment_artifact_sha256,
        penalty_assignment_status="REVIEWED_CANDIDATE_NOT_HUMAN_ACCEPTED",
        penalty_assignment_count=len(assignments),
        classification_counts=counts,
        unknown_team_identity_sha256s=unknown_team_hashes,
        reviewed_source_domains=reviewed_source_domains,
        reviewed_source_references_sha256=canonical_sha256(source_references),
        role_override_artifact_sha256=role_override_artifact_sha256,
        role_override_count=len(review.role_overrides),
        role_review_rationale=review.role_review_rationale,
        allocation_bindings=bindings,
        sensitivity_artifact_sha256=summary.artifact_sha256,
        exact_stage7_player_identity_equality=True,
        exact_stage7_team_identity_equality=True,
        stage7_expected_minutes_separate=True,
        penalty_assignments_affect_penalty_share_only=True,
        whole_roster_uniform_fallback_only_when_explicit_unknown=True,
        zero_exposure_discipline_lineage_preserved=zero_exposure_lineage_preserved,
        defensive_contribution_model_completeness="PARTIAL",
        raw_fpl_history_persisted=False,
        current_fpl_catalogue_persisted=False,
        history_network_request_count=0,
        player_allocation_human_accepted=False,
        receipt_sha256=canonical_sha256(
            provisional_receipt.model_dump(mode="json", exclude={"receipt_sha256"})
        ),
    )
    return CompiledAllocationOverlay(
        assignments=assignments,
        assignment_artifact_sha256=assignment_artifact_sha256,
        role_override_artifact_sha256=role_override_artifact_sha256,
        allocations=allocations,
        sensitivity_rows=ordered_rows,
        sensitivity_summary=summary,
        receipt=receipt,
    )


__all__ = [
    "AllocationSensitivitySummary",
    "CompiledAllocationOverlay",
    "PenaltyOverlayReceipt",
    "PenaltyResponsibilityClassification",
    "PrivateAllocationOverlayReview",
    "PrivatePenaltyCandidateReview",
    "PrivateTeamPenaltyReview",
    "ReviewConfidence",
    "compile_current_allocation_overlay",
    "load_private_overlay_review",
]
