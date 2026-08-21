"""Build persistent Stage-9 allocation profiles from posterior-only evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import UUID

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.allocation import (
    validate_assist_share_constraints,
    validate_goal_share_simplex,
)
from dmf_pulse.fpl_points.models import PlayerAllocationProfile
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.empirical_bayes import resolve_role_prior
from dmf_pulse.player_evidence.models import (
    CurrentPlayer,
    CurrentPlayerCatalogue,
    EvidenceSourceLevel,
    OverrideKind,
    PenaltyAssignment,
    PlayerAllocationCandidateArtifact,
    PlayerPosterior,
    PlayerPosteriorArtifact,
    PriceAdjustmentPolicy,
    PriceWorld,
    ProfileLineage,
    RoleOverride,
    RolePooledPrior,
    TacticalRole,
)


def _active_role(
    player: CurrentPlayer,
    *,
    requested: TacticalRole,
    overrides: Sequence[RoleOverride],
    information_cutoff: datetime,
) -> TacticalRole:
    matching = [
        override
        for override in overrides
        if override.player_id == player.player_id
        and override.team_id == player.team_id
        and override.tactical_role is not None
        and override.usable_at <= information_cutoff < override.expires_at
    ]
    if len(matching) > 1:
        raise IngestionError("OVERRIDE_AMBIGUOUS", "multiple active tactical-role overrides")
    if not matching:
        return requested
    resolved = matching[0].tactical_role
    if resolved is None:
        raise IngestionError("OVERRIDE_INVALID", "active role override lacks a tactical role")
    return resolved


def _price_adjustment(
    player: CurrentPlayer,
    players: Sequence[CurrentPlayer],
    posterior_minutes: float,
    policy: PriceAdjustmentPolicy,
) -> float:
    """A bounded, position-local sparse-evidence adjustment—not an xP model."""

    if policy.world is PriceWorld.PRICE_OFF or posterior_minutes >= policy.sparse_evidence_minutes:
        return 1.0
    same_position = [row.current_price_tenths for row in players if row.position == player.position]
    low, high = min(same_position), max(same_position)
    if low == high:
        return 1.0
    max_adjustment = (
        policy.moderate_max_relative_adjustment
        if policy.world is PriceWorld.PRICE_MODERATE
        else policy.strong_max_relative_adjustment
    )
    percentile = (player.current_price_tenths - low) / (high - low)
    sparse_fraction = max(0.0, 1.0 - posterior_minutes / policy.sparse_evidence_minutes)
    return 1.0 + sparse_fraction * max_adjustment * (2.0 * percentile - 1.0)


def _normalise(values: Mapping[str, float], *, code: str) -> dict[str, float]:
    total = sum(values.values())
    if total <= 0.0:
        raise IngestionError(code, "team allocation has no positive propensity")
    return {player_id: value / total for player_id, value in values.items()}


def _penalty_weights(
    players: Sequence[CurrentPlayer],
    priors: Mapping[UUID, RolePooledPrior],
    assignments: Sequence[PenaltyAssignment],
    information_cutoff: datetime,
) -> dict[str, float]:
    by_team: dict[UUID, list[PenaltyAssignment]] = defaultdict(list)
    known_players = {player.player_id: player for player in players}
    for assignment in assignments:
        player = known_players.get(assignment.player_id)
        if player is None or player.team_id != assignment.team_id:
            raise IngestionError(
                "IDENTITY_CONFLICT", "penalty assignment is not in current catalogue"
            )
        if assignment.usable_at <= information_cutoff < assignment.expires_at:
            by_team[assignment.team_id].append(assignment)
    values: dict[str, float] = {}
    for player in players:
        active = by_team.get(player.team_id, [])
        if len({assignment.player_id for assignment in active}) != len(active):
            raise IngestionError(
                "PENALTY_ASSIGNMENT_AMBIGUOUS",
                "multiple active penalty assignments exist for one player",
            )
        values[str(player.player_id)] = (
            next(
                (
                    assignment.allocation_weight
                    for assignment in active
                    if assignment.player_id == player.player_id
                ),
                0.0,
            )
            if active
            else priors[player.player_id].penalty_weight
        )
    return values


def _build_profiles(
    *,
    catalogue: CurrentPlayerCatalogue,
    posterior: PlayerPosteriorArtifact,
    role_priors: Sequence[RolePooledPrior],
    tactical_roles: Mapping[UUID, TacticalRole],
    role_overrides: Sequence[RoleOverride],
    penalty_assignments: Sequence[PenaltyAssignment],
    price_policy: PriceAdjustmentPolicy,
    information_cutoff: datetime,
) -> tuple[tuple[PlayerAllocationProfile, ...], tuple[ProfileLineage, ...]]:
    posterior_by_id: dict[UUID, PlayerPosterior] = {row.player_id: row for row in posterior.players}
    if set(posterior_by_id) != {player.player_id for player in catalogue.players}:
        raise IngestionError("IDENTITY_CONFLICT", "posterior does not cover the current catalogue")
    priors: dict[UUID, RolePooledPrior] = {}
    for player in catalogue.players:
        role = _active_role(
            player,
            requested=tactical_roles.get(player.player_id, TacticalRole.UNKNOWN),
            overrides=role_overrides,
            information_cutoff=information_cutoff,
        )
        priors[player.player_id] = resolve_role_prior(player, role, role_priors)
    penalties = _penalty_weights(catalogue.players, priors, penalty_assignments, information_cutoff)
    goal_props: dict[str, float] = {}
    assist_props: dict[str, float] = {}
    own_goal_props: dict[str, float] = {}
    for player in catalogue.players:
        value = posterior_by_id[player.player_id]
        prior = priors[player.player_id]
        price = _price_adjustment(
            player, catalogue.players, value.posterior_effective_minutes, price_policy
        )
        player_id = str(player.player_id)
        goal_props[player_id] = value.goal_rate.mean_per90 * prior.goal_role_adjustment * price
        assist_props[player_id] = (
            value.assist_rate.mean_per90 * prior.assist_role_adjustment * price
        )
        own_goal_props[player_id] = prior.own_goal_weight
    goal_shares: dict[str, float] = {}
    assist_shares: dict[str, float] = {}
    penalty_shares: dict[str, float] = {}
    for team_id in {player.team_id for player in catalogue.players}:
        team_ids = [
            str(player.player_id) for player in catalogue.players if player.team_id == team_id
        ]
        goal_shares.update(
            _normalise({key: goal_props[key] for key in team_ids}, code="GOAL_PROPENSITY_EMPTY")
        )
        assist_shares.update(
            _normalise({key: assist_props[key] for key in team_ids}, code="ASSIST_PROPENSITY_EMPTY")
        )
        penalty_shares.update(
            _normalise({key: penalties[key] for key in team_ids}, code="PENALTY_PROPENSITY_EMPTY")
        )
    profiles: list[PlayerAllocationProfile] = []
    lineage: list[ProfileLineage] = []
    for player in catalogue.players:
        row = posterior_by_id[player.player_id]
        prior = priors[player.player_id]
        player_id = str(player.player_id)
        history_active = row.posterior_effective_minutes > 0.0
        event_level = EvidenceSourceLevel.INDIVIDUAL if history_active else prior.source_level
        profiles.append(
            PlayerAllocationProfile(
                player_id=player_id,
                team_id=str(player.team_id),
                goal_share=goal_shares[player_id],
                assist_share=assist_shares[player_id],
                penalty_taker_share=penalty_shares[player_id],
                own_goal_share=own_goal_props[player_id],
                goalkeeper_saves_per90=row.save_rate.mean_per90,
                saves_inside_box_fraction=prior.saves_inside_box_fraction,
                yellow_cards_per90=row.yellow_rate.mean_per90,
                red_cards_per90=row.red_rate.mean_per90,
                clearances_per90=prior.clearances_per90,
                blocks_per90=prior.blocks_per90,
                interceptions_per90=prior.interceptions_per90,
                tackles_per90=prior.tackles_per90,
                ball_recoveries_per90=prior.ball_recoveries_per90,
                bps_auxiliary=prior.bps_auxiliary,
            )
        )
        lineage.append(
            ProfileLineage(
                player_id=player.player_id,
                source_player_id=player.source_player_id,
                goal_source_level=event_level,
                assist_source_level=event_level,
                auxiliary_source_level=prior.source_level,
                fallback_reason=prior.fallback_reason,
                prior_version=prior.prior_version,
                limitations=(
                    "ROLE_PRIOR_REAL_CALIBRATION_SEPARATE_CHECKPOINT",
                    "BPS_AUXILIARY_ROLE_POOLED_NOT_INDIVIDUAL_RECONSTRUCTION",
                    "STAGE7_PARTICIPATION_OWNS_MINUTES_AND_ON_PITCH_ELIGIBILITY",
                ),
            )
        )
    ordered_profiles = tuple(sorted(profiles, key=lambda item: item.player_id))
    ordered_lineage = tuple(sorted(lineage, key=lambda item: str(item.player_id)))
    for profile_team_id in sorted({profile.team_id for profile in ordered_profiles}):
        validate_goal_share_simplex(ordered_profiles, profile_team_id)
        validate_assist_share_constraints(ordered_profiles, profile_team_id)
    return ordered_profiles, ordered_lineage


def build_allocation_candidate(
    *,
    catalogue: CurrentPlayerCatalogue,
    posterior: PlayerPosteriorArtifact,
    role_priors: Sequence[RolePooledPrior],
    tactical_roles: Mapping[UUID, TacticalRole],
    information_cutoff: datetime,
    price_policy: PriceAdjustmentPolicy,
    role_overrides: Sequence[RoleOverride] = (),
    penalty_assignments: Sequence[PenaltyAssignment] = (),
    degraded_player_allocation: bool = False,
) -> PlayerAllocationCandidateArtifact:
    """Build Stage-9 profiles without Stage-7 starts, probabilities, or minutes.

    Persistent shares use only posterior rates and current allocation priors.
    Stage 9 later renormalises these weights over each simulated on-pitch set.
    """

    if information_cutoff.tzinfo is None or information_cutoff.utcoffset() is None:
        raise IngestionError("TEMPORAL_INVALID", "information cutoff must be timezone-aware")
    cutoff = information_cutoff.astimezone(UTC)
    if posterior.information_cutoff != cutoff:
        raise IngestionError("POST_CUTOFF", "posterior cutoff does not match allocation cutoff")
    profiles, lineage = _build_profiles(
        catalogue=catalogue,
        posterior=posterior,
        role_priors=role_priors,
        tactical_roles=tactical_roles,
        role_overrides=role_overrides,
        penalty_assignments=penalty_assignments,
        price_policy=price_policy,
        information_cutoff=cutoff,
    )
    limitations = {
        "CANDIDATE_NOT_HUMAN_ACCEPTED",
        "ROLE_PRIOR_REAL_CALIBRATION_SEPARATE_CHECKPOINT",
        "PENALTY_SHARE_SEPARATE_FROM_OPEN_PLAY_GOAL_SHARE",
        "STAGE7_MINUTES_NOT_EMBEDDED_IN_PERSISTENT_SHARES",
        "BPS_DEFENSIVE_AUXILIARY_ROLE_POOLED",
    }
    if degraded_player_allocation:
        limitations.add("DEGRADED_PLAYER_ALLOCATION_TRUE_INDIVIDUAL_HISTORY_INACTIVE")
    if any(
        override.override_kind is OverrideKind.PRIMARY_MATERIAL_SET_PIECE
        and override.usable_at <= cutoff < override.expires_at
        for override in role_overrides
    ):
        limitations.add("SET_PIECE_OVERRIDE_RECORDED_NO_SEPARATE_STAGE9_ALLOCATION_CHANNEL")
    provisional = PlayerAllocationCandidateArtifact.model_construct(
        information_cutoff=cutoff,
        posterior_artifact_sha256=posterior.artifact_sha256,
        price_policy=price_policy,
        degraded_player_allocation=degraded_player_allocation,
        profiles=profiles,
        lineage=lineage,
        limitations=tuple(sorted(limitations)),
        artifact_sha256="0" * 64,
    )
    return PlayerAllocationCandidateArtifact(
        information_cutoff=cutoff,
        posterior_artifact_sha256=posterior.artifact_sha256,
        price_policy=price_policy,
        degraded_player_allocation=degraded_player_allocation,
        profiles=profiles,
        lineage=lineage,
        limitations=tuple(sorted(limitations)),
        artifact_sha256=canonical_sha256(
            provisional.model_dump(mode="json", exclude={"artifact_sha256"})
        ),
    )


__all__ = ["build_allocation_candidate"]
