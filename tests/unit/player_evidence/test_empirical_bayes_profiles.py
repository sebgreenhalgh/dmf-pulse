"""Offline-only Gamma-Poisson and Stage-9 profile regression coverage."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.allocation import allocate_fixture_events
from dmf_pulse.fpl_points.models import (
    OnPitchInterval,
    PlayerPosition,
    ProjectionMode,
    ScorelineCell,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.empirical_bayes import (
    compile_posterior_artifact,
    gamma_poisson_posterior,
    resolve_role_prior,
)
from dmf_pulse.player_evidence.models import (
    EvidenceSourceLevel,
    HistoryPastSeason,
    HistorySensitivityWorld,
    OverrideKind,
    PenaltyAssignment,
    PenaltyDesignation,
    PlayerHistoryEvidence,
    PriceWorld,
    RoleOverride,
    TacticalRole,
    candidate_eb_parameters,
    candidate_price_policy,
)
from dmf_pulse.player_evidence.profiles import _price_adjustment, build_allocation_candidate
from tests.support.factories import (
    H_FWD,
    H_GK,
    H_MID,
    HOME_TEAM_ID,
    allocation_config,
    make_request,
    reference_engine,
)
from tests.unit.player_evidence.support import NOW, SHA, catalogue, eb_parameters, generic_prior


def _history(
    player_id: str,
    source_player_id: int,
    *,
    minutes: int,
    goals: int = 0,
    assists: int = 0,
    yellow_cards: int = 0,
    red_cards: int = 0,
    saves: int = 0,
    season: str = "2025/26",
) -> PlayerHistoryEvidence:
    return PlayerHistoryEvidence(
        player_id=UUID(player_id),
        source_player_id=source_player_id,
        seasons=(
            HistoryPastSeason(
                season=season,
                minutes=minutes,
                goals=goals,
                assists=assists,
                yellow_cards=yellow_cards,
                red_cards=red_cards,
                saves=saves,
            ),
        ),
    )


def _posterior(
    histories: tuple[PlayerHistoryEvidence, ...] = (),
    *,
    parameters=None,
    source_hashes=None,
    source_observed_ats=None,
):
    return compile_posterior_artifact(
        catalogue=catalogue(),
        histories=histories,
        role_priors=(generic_prior(),),
        tactical_roles={},
        parameters=parameters or eb_parameters(),
        information_cutoff=NOW,
        source_observed_at=NOW - timedelta(hours=2),
        usable_at=NOW - timedelta(hours=1),
        produced_at=NOW - timedelta(minutes=30),
        source_locator="synthetic://GW1-PLY-001/replay",
        schema_fingerprint=SHA,
        rights_profile_id="SYNTHETIC_REPLAY_ONLY",
        source_hashes=source_hashes,
        source_observed_ats=source_observed_ats,
    )


def _allocation(posterior, *, price_world: PriceWorld = PriceWorld.PRICE_OFF, **updates):
    return build_allocation_candidate(
        catalogue=catalogue(),
        posterior=posterior,
        role_priors=(generic_prior(),),
        tactical_roles={},
        information_cutoff=NOW,
        price_policy=candidate_price_policy(price_world),
        **updates,
    )


def _catalogue_player(player_id: str):
    return next(item for item in catalogue().players if str(item.player_id) == player_id)


def test_gamma_poisson_analytical_oracle_and_variance_behaviour() -> None:
    posterior = gamma_poisson_posterior(
        prior_mean_per90=0.20,
        kappa=10.0,
        exposure_full_matches=5.0,
        events=3.0,
    )
    assert posterior.mean_per90 == pytest.approx((3.0 + 2.0) / 15.0)
    assert posterior.variance_per90 == pytest.approx(5.0 / 225.0)
    sparse = gamma_poisson_posterior(
        prior_mean_per90=0.20, kappa=10.0, exposure_full_matches=1.0, events=1.0
    )
    established = gamma_poisson_posterior(
        prior_mean_per90=0.20, kappa=10.0, exposure_full_matches=20.0, events=20.0
    )
    assert established.variance_per90 < sparse.variance_per90
    assert established.mean_per90 > sparse.mean_per90


def test_no_history_returns_pooled_prior_and_rare_events_shrink() -> None:
    posterior = _posterior()
    rookie = next(row for row in posterior.players if str(row.player_id) == H_MID)
    prior = generic_prior()
    assert rookie.posterior_effective_minutes == 0.0
    assert rookie.goal_rate.mean_per90 == prior.goal_rate_per90
    assert rookie.assist_rate.mean_per90 == prior.assist_rate_per90
    assert rookie.red_rate.mean_per90 == prior.red_rate_per90
    red = gamma_poisson_posterior(
        prior_mean_per90=prior.red_rate_per90,
        kappa=30.0,
        exposure_full_matches=1.0,
        events=1.0,
    )
    assert prior.red_rate_per90 < red.mean_per90 < 1.0


def test_zero_exposure_discipline_exclusion_has_explicit_zero_rate_evidence_lineage() -> None:
    excluded_only_player = _catalogue_player(H_MID)
    valid_player = _catalogue_player(H_FWD)
    excluded_only = PlayerHistoryEvidence(
        player_id=excluded_only_player.player_id,
        source_player_id=excluded_only_player.source_player_id,
        seasons=(),
        zero_exposure_discipline_rows_excluded_count=3,
    )
    valid_with_exclusion = _history(
        H_FWD,
        valid_player.source_player_id,
        minutes=900,
        goals=4,
        assists=2,
        yellow_cards=2,
        red_cards=1,
    ).model_copy(update={"zero_exposure_discipline_rows_excluded_count": 1})
    valid_without_exclusion = valid_with_exclusion.model_copy(
        update={"zero_exposure_discipline_rows_excluded_count": 0}
    )

    posterior = _posterior((excluded_only, valid_with_exclusion))
    repeated = _posterior((excluded_only, valid_with_exclusion))
    control = _posterior((valid_without_exclusion,))
    rows = {str(row.player_id): row for row in posterior.players}
    control_rows = {str(row.player_id): row for row in control.players}
    prior = generic_prior()

    assert posterior.artifact_sha256 == repeated.artifact_sha256
    assert posterior.zero_exposure_discipline_rows_excluded_count == 4
    assert rows[H_MID].posterior_effective_minutes == 0.0
    assert rows[H_MID].yellow_rate.mean_per90 == prior.yellow_rate_per90
    assert rows[H_MID].red_rate.mean_per90 == prior.red_rate_per90
    assert rows[H_MID].history_seasons_included == ()
    assert rows[H_MID].zero_exposure_discipline_rows_excluded_count == 3
    assert rows[H_FWD].history_seasons_included == ("2025/26",)
    assert (
        rows[H_FWD].posterior_effective_minutes == control_rows[H_FWD].posterior_effective_minutes
    )
    assert rows[H_FWD].yellow_rate == control_rows[H_FWD].yellow_rate
    assert rows[H_FWD].red_rate == control_rows[H_FWD].red_rate
    assert rows[H_FWD].history_limitations == (
        "ZERO_EXPOSURE_DISCIPLINE_ONLY_EXCLUDED_FROM_RATE_MODEL",
    )

    allocation = _allocation(posterior)
    assert "ZERO_EXPOSURE_DISCIPLINE_ONLY_EXCLUDED_FROM_RATE_MODEL" in allocation.limitations
    lineage = {str(row.player_id): row for row in allocation.lineage}
    assert "ZERO_EXPOSURE_DISCIPLINE_ONLY_EXCLUDED_FROM_RATE_MODEL" in lineage[H_MID].limitations


def test_recency_and_sensitivity_worlds_are_deterministic_and_declared() -> None:
    player = _catalogue_player(H_MID)
    history = _history(
        H_MID,
        player.source_player_id,
        minutes=900,
        goals=5,
        season="2024/25",
    )
    first = _posterior((history,))
    second = _posterior((history,))
    assert first.artifact_sha256 == second.artifact_sha256
    low = candidate_eb_parameters(HistorySensitivityWorld.LOW_SHRINKAGE)
    central = candidate_eb_parameters(HistorySensitivityWorld.CENTRAL_TEMPORARY)
    high = candidate_eb_parameters(HistorySensitivityWorld.HIGH_SHRINKAGE)
    assert low.goal_kappa_full_match_equivalents < central.goal_kappa_full_match_equivalents
    assert central.goal_kappa_full_match_equivalents < high.goal_kappa_full_match_equivalents
    assert central.parameter_status == "TEMPORARY_CANDIDATE_PARAMETERS"


def test_role_position_generic_hierarchy_is_explicit_and_deterministic() -> None:
    player = _catalogue_player(H_MID)
    generic = generic_prior()
    position = generic.model_copy(
        update={
            "shrinkage_group_id": "synthetic-mid-position",
            "position": PlayerPosition.MID,
            "source_level": EvidenceSourceLevel.FPL_POSITION,
        }
    )
    role = generic.model_copy(
        update={
            "shrinkage_group_id": "synthetic-mid-am",
            "position": PlayerPosition.MID,
            "tactical_role": TacticalRole.AM,
            "source_level": EvidenceSourceLevel.TACTICAL_ROLE,
        }
    )
    assert resolve_role_prior(player, TacticalRole.AM, (generic, position, role)) == role
    assert resolve_role_prior(player, TacticalRole.UNKNOWN, (generic, position, role)) == position
    assert resolve_role_prior(player, TacticalRole.UNKNOWN, (generic,)) == generic


def test_elite_rookie_and_goalkeeper_posteriors_are_materially_distinct() -> None:
    elite = _catalogue_player(H_MID)
    ordinary = _catalogue_player(H_FWD)
    goalkeeper = _catalogue_player(H_GK)
    histories = (
        _history(H_MID, elite.source_player_id, minutes=1_800, goals=20, assists=10),
        _history(H_FWD, ordinary.source_player_id, minutes=1_800, goals=3, assists=2),
        _history(H_GK, goalkeeper.source_player_id, minutes=1_800, saves=80),
    )
    posterior = _posterior(histories)
    rows = {str(row.player_id): row for row in posterior.players}
    assert rows[H_MID].goal_rate.mean_per90 > rows[H_FWD].goal_rate.mean_per90
    assert rows[H_GK].save_rate.mean_per90 > generic_prior().save_rate_per90
    allocation = _allocation(posterior)
    profiles = {row.player_id: row for row in allocation.profiles}
    assert profiles[H_MID].goal_share > profiles[H_FWD].goal_share
    assert allocation.degraded_player_allocation is False
    assert allocation.artifact_sha256 == _allocation(posterior).artifact_sha256


def test_completed_history_and_identity_are_required() -> None:
    player = _catalogue_player(H_MID)
    current_season = _history(H_MID, player.source_player_id, minutes=90, goals=1, season="2026/27")
    with pytest.raises(IngestionError, match="completed historical seasons"):
        _posterior((current_season,))
    wrong_source_id = _history(H_MID, player.source_player_id + 10_000, minutes=90, goals=1)
    with pytest.raises(IngestionError, match="history identity"):
        _posterior((wrong_source_id,))


def test_captured_per_player_receipt_metadata_flows_only_into_posterior() -> None:
    player = _catalogue_player(H_MID)
    history = _history(H_MID, player.source_player_id, minutes=900, goals=4)
    observed_at = NOW - timedelta(hours=1, minutes=30)
    posterior = _posterior(
        (history,),
        source_hashes={player.player_id: "c" * 64},
        source_observed_ats={player.player_id: observed_at},
    )
    row = next(item for item in posterior.players if item.player_id == player.player_id)
    assert row.source_observed_at == observed_at
    assert row.source_hash == "c" * 64
    assert row.history_seasons_included == ("2025/26",)


def test_persistent_shares_are_team_normalized_and_do_not_embed_stage7_minutes() -> None:
    elite = _catalogue_player(H_MID)
    substitute = _catalogue_player(H_FWD)
    posterior = _posterior(
        (
            _history(H_MID, elite.source_player_id, minutes=900, goals=6, assists=3),
            _history(H_FWD, substitute.source_player_id, minutes=900, goals=6, assists=3),
        )
    )
    allocation = _allocation(posterior)
    profiles = {row.player_id: row for row in allocation.profiles}
    # These players have equal evidence but the inherited Stage-7 fixture gives
    # H_MID 90 official minutes and H_FWD only 30 as a bench substitute.
    assert profiles[H_MID].goal_share == pytest.approx(profiles[H_FWD].goal_share)
    assert profiles[H_MID].assist_share == pytest.approx(profiles[H_FWD].assist_share)
    for team_id in {profile.team_id for profile in allocation.profiles}:
        team = [profile for profile in allocation.profiles if profile.team_id == team_id]
        assert sum(profile.goal_share for profile in team) == pytest.approx(1.0)
        assert sum(profile.assist_share for profile in team) == pytest.approx(1.0)
        assert all(profile.assist_share >= 0.0 for profile in team)
    assert "STAGE7_MINUTES_NOT_EMBEDDED_IN_PERSISTENT_SHARES" in allocation.limitations


def _synthetic_penalty_assignment() -> PenaltyAssignment:
    player = _catalogue_player(H_MID)
    values = {
        "player_id": player.player_id,
        "team_id": player.team_id,
        "designation": PenaltyDesignation.PRIMARY,
        "allocation_weight": 1.0,
        "source_reference": "synthetic://GW1-PLY-001/penalty",
        "observed_at": NOW - timedelta(hours=3),
        "usable_at": NOW - timedelta(hours=2),
        "expires_at": NOW + timedelta(days=1),
        "reviewer": "synthetic-test-only",
        "status": "HUMAN_REVIEWED",
    }
    provisional = PenaltyAssignment.model_construct(**values, assignment_sha256="0" * 64)
    return PenaltyAssignment(
        **values,
        assignment_sha256=canonical_sha256(
            provisional.model_dump(mode="json", exclude={"assignment_sha256"})
        ),
    )


def _synthetic_override(*, kind: OverrideKind, tactical_role=None) -> RoleOverride:
    player = _catalogue_player(H_MID)
    values = {
        "player_id": player.player_id,
        "team_id": player.team_id,
        "override_kind": kind,
        "tactical_role": tactical_role,
        "source_reference": "synthetic://GW1-PLY-001/override",
        "observed_at": NOW - timedelta(hours=3),
        "usable_at": NOW - timedelta(hours=2),
        "expires_at": NOW + timedelta(days=1),
        "confidence": "HIGH",
        "reviewer": "synthetic-test-only",
        "status": "HUMAN_REVIEWED",
    }
    provisional = RoleOverride.model_construct(**values, override_sha256="0" * 64)
    return RoleOverride(
        **values,
        override_sha256=canonical_sha256(
            provisional.model_dump(mode="json", exclude={"override_sha256"})
        ),
    )


def test_penalty_assignment_is_separate_from_open_play_goal_share() -> None:
    posterior = _posterior()
    baseline = _allocation(posterior)
    primary = _synthetic_penalty_assignment()
    with_primary = _allocation(posterior, penalty_assignments=(primary,))
    baseline_profiles = {row.player_id: row for row in baseline.profiles}
    primary_profiles = {row.player_id: row for row in with_primary.profiles}
    assert baseline_profiles[H_MID].goal_share == primary_profiles[H_MID].goal_share
    assert primary_profiles[H_MID].penalty_taker_share == pytest.approx(1.0)
    assert primary_profiles[H_FWD].penalty_taker_share == pytest.approx(0.0)
    assert "PENALTY_SHARE_SEPARATE_FROM_OPEN_PLAY_GOAL_SHARE" in with_primary.limitations
    with pytest.raises(IngestionError, match="multiple active penalty assignments"):
        _allocation(posterior, penalty_assignments=(primary, primary))


def test_set_piece_override_is_governed_but_does_not_silently_change_open_play() -> None:
    posterior = _posterior()
    set_piece = _synthetic_override(kind=OverrideKind.PRIMARY_MATERIAL_SET_PIECE)
    baseline = _allocation(posterior)
    with_set_piece = _allocation(posterior, role_overrides=(set_piece,))
    baseline_profiles = {row.player_id: row for row in baseline.profiles}
    set_piece_profiles = {row.player_id: row for row in with_set_piece.profiles}
    assert baseline_profiles[H_MID].goal_share == set_piece_profiles[H_MID].goal_share
    assert "SET_PIECE_OVERRIDE_RECORDED_NO_SEPARATE_STAGE9_ALLOCATION_CHANNEL" in (
        with_set_piece.limitations
    )
    with pytest.raises(ValueError, match="requires an explicit tactical role"):
        _synthetic_override(kind=OverrideKind.NEW_TRANSFER_ROLE)


def test_price_prior_is_bounded_position_local_and_disabled_centrally() -> None:
    posterior = _posterior()
    off = _allocation(posterior, price_world=PriceWorld.PRICE_OFF)
    moderate = _allocation(posterior, price_world=PriceWorld.PRICE_MODERATE)
    off_profiles = {row.player_id: row for row in off.profiles}
    moderate_profiles = {row.player_id: row for row in moderate.profiles}
    # Both are sparse historical defenders.  Their catalogue prices differ, so
    # the declared sensitivity world is monotonic while the central world is off.
    low, high = sorted(
        (
            profile.player_id
            for profile in off.profiles
            if profile.team_id == HOME_TEAM_ID
            and _catalogue_player(profile.player_id).position is PlayerPosition.DEF
        ),
        key=lambda player_id: _catalogue_player(player_id).current_price_tenths,
    )[:2]
    assert off_profiles[low].goal_share == pytest.approx(off_profiles[high].goal_share)
    assert moderate_profiles[high].goal_share > moderate_profiles[low].goal_share
    policy = candidate_price_policy(PriceWorld.PRICE_MODERATE)
    assert 0.0 < policy.moderate_max_relative_adjustment <= 0.10
    assert policy.parameter_status == "TEMPORARY_CANDIDATE_PARAMETERS"
    established_player = _catalogue_player(H_MID)
    established = _posterior(
        (_history(H_MID, established_player.source_player_id, minutes=1_800, goals=5),)
    )
    established_strong = _allocation(established, price_world=PriceWorld.PRICE_STRONG)
    assert _price_adjustment(
        established_player,
        catalogue().players,
        posterior_minutes=1_800.0,
        policy=established_strong.price_policy,
    ) == pytest.approx(1.0)
    assert next(
        row.goal_share for row in established_strong.profiles if row.player_id == H_MID
    ) > next(row.goal_share for row in established_strong.profiles if row.player_id == H_FWD)


def test_degraded_fallback_is_complete_and_preserves_no_history_players() -> None:
    posterior = _posterior()
    degraded = _allocation(posterior, degraded_player_allocation=True)
    assert degraded.degraded_player_allocation is True
    assert len(degraded.profiles) == len(catalogue().players)
    assert all(
        profile.goal_share >= 0.0 and profile.assist_share >= 0.0 for profile in degraded.profiles
    )
    assert "DEGRADED_PLAYER_ALLOCATION_TRUE_INDIVIDUAL_HISTORY_INACTIVE" in degraded.limitations
    assert all(row.goal_source_level.value != "INDIVIDUAL" for row in degraded.lineage)


def test_stage9_renormalises_over_actual_on_pitch_players_without_off_pitch_credit() -> None:
    posterior = _posterior()
    allocation = _allocation(posterior)
    participants = tuple(
        row.model_copy(update={"official_minutes": 0, "interval": None, "starter": False})
        if row.player_id == H_MID
        else row.model_copy(
            update={
                "official_minutes": 90,
                "interval": OnPitchInterval(start_minute=0.0, end_minute=90.0),
                "starter": True,
            }
        )
        if row.player_id == H_FWD
        else row
        for row in make_request().participation_scenarios[0].participants
    )
    profiles = tuple(
        profile.model_copy(
            update={
                "goal_share": 1.0 if profile.player_id == H_FWD else 0.0,
                "assist_share": 1.0 if profile.player_id == H_GK else 0.0,
            }
        )
        if profile.team_id == HOME_TEAM_ID
        else profile
        for profile in allocation.profiles
    )
    request = make_request(
        participants=participants,
        profiles=profiles,
        config=allocation_config(goal_time_lower=70.0, goal_time_upper=71.0),
        scenario_count=1,
    )
    scenario, _ = allocate_fixture_events(
        cell=ScorelineCell(home_goals=1, away_goals=0, probability="1.000000000000"),
        participation=request.participation_scenarios[0],
        profiles=request.allocation_profiles,
        config=request.allocation_config,
        ruleset=reference_engine().identity,
        projection_mode=ProjectionMode.TEST,
        root_seed=request.root_seed,
        scenario_index=0,
    )
    goal = scenario.goals[0]
    assert goal.scorer_player_id == H_FWD
    assert goal.scorer_player_id != H_MID
    on_pitch = {
        row.player_id
        for row in participants
        if row.interval is not None and row.interval.contains(goal.minute)
    }
    assert goal.scorer_player_id in on_pitch
    assert goal.assister_player_id in on_pitch
