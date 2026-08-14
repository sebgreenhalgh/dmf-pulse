"""Deterministic factories for Stage-9 semantic tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from dmf_pulse.football_events import JointScoreDistribution
from dmf_pulse.football_events._decimal import canonical_json_sha256
from dmf_pulse.fpl_points.models import (
    BpsAuxiliaryRates,
    BpsCompletenessMode,
    BpsEvents,
    DefensiveActions,
    EventAllocationConfig,
    FixtureEventScenario,
    FixtureReadiness,
    FixtureSimulationRequest,
    OnPitchInterval,
    ParticipantState,
    ParticipationScenario,
    PlayerAllocationProfile,
    PlayerEventVector,
    PlayerPosition,
    ProjectionMode,
)
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter
from tests.support.reference_rules import load_reference_rules

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_RULESET = ROOT / "fixtures/points/PTS-009/reference_ruleset_test_only.json"
RULESET_ID = "fpl-reference-2025-26"
RULESET_VERSION = "1.0.0"
RULESET_HASH = "12271ab0b32a461baa3778f2e914f45744ccf9d5302c37c4a5f2ffb89e0c1139"
CHECKSUM = "3" * 64
FIXTURE_ID = "10000000-0000-7000-8000-000000000801"
FIXTURE_A = "10000000-0000-7000-8000-000000000811"
FIXTURE_B = "10000000-0000-7000-8000-000000000812"
HOME_TEAM_ID = "20000000-0000-7000-8000-000000000001"
AWAY_TEAM_ID = "20000000-0000-7000-8000-000000000002"
H_GK = "40000000-0000-7000-8000-000000000001"
H_DEF = "40000000-0000-7000-8000-000000000002"
H_MID = "40000000-0000-7000-8000-000000000003"
H_FWD = "40000000-0000-7000-8000-000000000004"
A_GK = "50000000-0000-7000-8000-000000000001"
A_DEF = "50000000-0000-7000-8000-000000000002"
A_MID = "50000000-0000-7000-8000-000000000003"
A_FWD = "50000000-0000-7000-8000-000000000004"
STAGE8_TEMPLATE = ROOT / "fixtures/events/score/GCS-008/balanced_fixture.expected.json"


def stage8_distribution(
    *,
    fixture_id: str = FIXTURE_ID,
    home_team_id: str = HOME_TEAM_ID,
    away_team_id: str = AWAY_TEAM_ID,
) -> JointScoreDistribution:
    payload = copy.deepcopy(json.loads(STAGE8_TEMPLATE.read_text(encoding="utf-8")))
    payload["fixture_id"] = fixture_id
    payload["home_team_id"] = home_team_id
    payload["away_team_id"] = away_team_id
    payload["source_minutes_context"]["home"]["fixture_id"] = fixture_id
    payload["source_minutes_context"]["away"]["fixture_id"] = fixture_id
    payload["source_minutes_context"]["home"]["team_id"] = home_team_id
    payload["source_minutes_context"]["away"]["team_id"] = away_team_id
    payload["source_minutes_context_sha256"] = canonical_json_sha256(
        payload["source_minutes_context"]
    )
    payload["result_sha256"] = ""
    payload["result_sha256"] = canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "result_sha256"}
    )
    return JointScoreDistribution.model_validate(payload)


def reference_engine() -> AcceptedRulesAdapter:
    return load_reference_rules(REFERENCE_RULESET)


def zero_bps_rates(**updates: Any) -> BpsAuxiliaryRates:
    values: dict[str, Any] = {
        "big_chances_created_per90": 0.0,
        "big_chances_missed_per90": 0.0,
        "errors_leading_attempt_per90": 0.0,
        "errors_leading_goal_per90": 0.0,
        "fouls_conceded_per90": 0.0,
        "fouls_won_per90": 0.0,
        "goal_line_clearances_per90": 0.0,
        "key_passes_per90": 0.0,
        "offsides_per90": 0.0,
        "pass_attempts_per90": 0.0,
        "pass_completion_probability": 0.0,
        "recoveries_per90": 0.0,
        "shots_off_target_per90": 0.0,
        "shots_on_target_non_goal_per90": 0.0,
        "successful_dribbles_per90": 0.0,
        "successful_open_play_crosses_per90": 0.0,
        "times_tackled_per90": 0.0,
    }
    values.update(updates)
    return BpsAuxiliaryRates(**values)


def participant(
    player_id: str,
    team_id: str,
    position: PlayerPosition,
    *,
    minutes: int = 90,
    start: float = 0.0,
    end: float = 90.0,
    starter: bool = True,
) -> ParticipantState:
    return ParticipantState(
        player_id=player_id,
        team_id=team_id,
        position=position,
        official_minutes=minutes,
        interval=OnPitchInterval(start_minute=start, end_minute=end) if minutes else None,
        hard_ineligible=False,
        starter=starter if minutes else False,
    )


def base_participants() -> tuple[ParticipantState, ...]:
    home = (
        participant(H_GK, HOME_TEAM_ID, PlayerPosition.GK),
        participant(H_DEF, HOME_TEAM_ID, PlayerPosition.DEF),
        participant(H_MID, HOME_TEAM_ID, PlayerPosition.MID),
        participant(
            H_FWD, HOME_TEAM_ID, PlayerPosition.FWD, minutes=30, start=60.0, end=90.0, starter=False
        ),
        *(
            participant(f"40000000-0000-7000-8000-{index:012d}", HOME_TEAM_ID, PlayerPosition.DEF)
            for index in range(5, 12)
        ),
    )
    away = (
        participant(A_GK, AWAY_TEAM_ID, PlayerPosition.GK),
        participant(A_DEF, AWAY_TEAM_ID, PlayerPosition.DEF),
        participant(A_MID, AWAY_TEAM_ID, PlayerPosition.MID),
        participant(A_FWD, AWAY_TEAM_ID, PlayerPosition.FWD, minutes=0, starter=False),
        *(
            participant(f"50000000-0000-7000-8000-{index:012d}", AWAY_TEAM_ID, PlayerPosition.DEF)
            for index in range(5, 12)
        ),
    )
    return (*home, *away)


def profile(
    player_id: str,
    team_id: str,
    *,
    goal_share: float,
    assist_share: float,
    penalty_share: float = 0.0,
    own_goal_share: float = 0.01,
    saves: float = 0.0,
    yellow: float = 0.0,
    red: float = 0.0,
    clearances: float = 0.0,
    blocks: float = 0.0,
    interceptions: float = 0.0,
    tackles: float = 0.0,
    recoveries: float = 0.0,
    bps: BpsAuxiliaryRates | None = None,
) -> PlayerAllocationProfile:
    return PlayerAllocationProfile(
        player_id=player_id,
        team_id=team_id,
        goal_share=goal_share,
        assist_share=assist_share,
        penalty_taker_share=penalty_share,
        own_goal_share=own_goal_share,
        goalkeeper_saves_per90=saves,
        saves_inside_box_fraction=0.75,
        yellow_cards_per90=yellow,
        red_cards_per90=red,
        clearances_per90=clearances,
        blocks_per90=blocks,
        interceptions_per90=interceptions,
        tackles_per90=tackles,
        ball_recoveries_per90=recoveries,
        bps_auxiliary=bps or zero_bps_rates(),
    )


def base_profiles() -> tuple[PlayerAllocationProfile, ...]:
    primary = (
        profile(H_GK, HOME_TEAM_ID, goal_share=0.01, assist_share=0.01, own_goal_share=0.01),
        profile(
            H_DEF,
            HOME_TEAM_ID,
            goal_share=0.10,
            assist_share=0.10,
            own_goal_share=0.30,
            clearances=4.0,
            blocks=2.0,
            interceptions=2.0,
            tackles=2.0,
        ),
        profile(
            H_MID,
            HOME_TEAM_ID,
            goal_share=0.55,
            assist_share=0.60,
            penalty_share=1.0,
            own_goal_share=0.10,
        ),
        profile(H_FWD, HOME_TEAM_ID, goal_share=0.34, assist_share=0.29, own_goal_share=0.01),
        profile(
            A_GK, AWAY_TEAM_ID, goal_share=0.01, assist_share=0.01, own_goal_share=0.01, saves=3.0
        ),
        profile(
            A_DEF,
            AWAY_TEAM_ID,
            goal_share=0.10,
            assist_share=0.10,
            own_goal_share=0.30,
            clearances=4.0,
            blocks=2.0,
            interceptions=2.0,
            tackles=2.0,
        ),
        profile(
            A_MID,
            AWAY_TEAM_ID,
            goal_share=0.79,
            assist_share=0.89,
            penalty_share=1.0,
            own_goal_share=0.10,
        ),
        profile(A_FWD, AWAY_TEAM_ID, goal_share=0.10, assist_share=0.00, own_goal_share=0.01),
    )
    primary_ids = {item.player_id for item in primary}
    fillers = tuple(
        profile(item.player_id, item.team_id, goal_share=0.01, assist_share=0.01)
        for item in base_participants()
        if item.player_id not in primary_ids
    )
    return (*primary, *fillers)


def allocation_config(**updates: Any) -> EventAllocationConfig:
    values: dict[str, Any] = {
        "model_version_id": "allocation-test-v1",
        "source_tag": "TEST_SYNTHETIC",
        "bps_completeness_mode": BpsCompletenessMode.EVENT_LINKED_PLUS_AUXILIARY_BASELINE,
        "auxiliary_source_tag": "TEST_SYNTHETIC",
        "match_minutes": 90.0,
        "goal_time_lower": 1.0,
        "goal_time_upper": 89.0,
        "penalty_goal_probability": 0.0,
        "set_piece_goal_probability": 0.0,
        "direct_free_kick_goal_probability": 0.0,
        "own_goal_probability": 0.0,
        "assistable_probability": 1.0,
        "ambiguous_assist_probability": 0.0,
        "ambiguous_assist_eligible_probability": 1.0,
        "extra_penalty_attempt_probability": 0.0,
        "extra_penalty_save_probability": 0.0,
    }
    values.update(updates)
    return EventAllocationConfig(**values)


def make_request(
    *,
    fixture_id: str = FIXTURE_ID,
    gameweek_id: str = "GW-1",
    home_team_id: str = HOME_TEAM_ID,
    away_team_id: str = AWAY_TEAM_ID,
    participants: tuple[ParticipantState, ...] | None = None,
    profiles: tuple[PlayerAllocationProfile, ...] | None = None,
    config: EventAllocationConfig | None = None,
    scenario_count: int = 64,
    root_seed: int = 12345,
    mode: ProjectionMode = ProjectionMode.TEST,
    readiness: FixtureReadiness = FixtureReadiness.SCHEDULED,
    cutoff: str = "2026-08-20T12:00:00Z",
) -> FixtureSimulationRequest:
    participants = participants or base_participants()
    profiles = profiles or base_profiles()
    stage8 = stage8_distribution(
        fixture_id=fixture_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
    )
    participation = ParticipationScenario(
        scenario_id=f"participation-{fixture_id}",
        fixture_id=fixture_id,
        gameweek_id=gameweek_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        probability=1.0,
        participant_universe_complete=True,
        participants=participants,
        stage7_minutes_context=stage8.source_minutes_context,
        stage7_player_projection_sha256s={item.player_id: CHECKSUM for item in participants},
        information_cutoff_utc=cutoff,
    )
    return FixtureSimulationRequest(
        schema_version="fpl-points-fixture-request-v1",
        gameweek_id=gameweek_id,
        projection_mode=mode,
        as_of_utc=cutoff,
        information_cutoff_utc=cutoff,
        root_seed=root_seed,
        scenario_count=scenario_count,
        fixture_readiness=readiness,
        score_distribution=stage8,
        participation_scenarios=(participation,),
        allocation_profiles=profiles,
        allocation_config=config or allocation_config(),
        expected_ruleset_id=RULESET_ID,
        expected_ruleset_version=RULESET_VERSION,
        expected_ruleset_hash=RULESET_HASH,
    )


def empty_bps(**updates: Any) -> BpsEvents:
    values = {name: 0 for name in BpsEvents.model_fields}
    values.update(updates)
    return BpsEvents(**values)


def empty_defensive(**updates: Any) -> DefensiveActions:
    values = {name: 0 for name in DefensiveActions.model_fields}
    values.update(updates)
    return DefensiveActions(**values)


def event_player(
    player_id: str,
    team_id: str,
    position: PlayerPosition,
    *,
    minutes: int = 90,
    goals_non_penalty: int = 0,
    goals_penalty: int = 0,
    assists: int = 0,
    conceded: int = 0,
    saves: int = 0,
    penalty_saves: int = 0,
    penalty_misses: int = 0,
    yellow: int = 0,
    red: int = 0,
    own_goals: int = 0,
    defensive: DefensiveActions | None = None,
    bps: BpsEvents | None = None,
    team_goals_after_dismissal: int = 0,
) -> PlayerEventVector:
    return PlayerEventVector(
        player_id=player_id,
        team_id=team_id,
        position=position,
        minutes=minutes,
        goals_non_penalty=goals_non_penalty,
        goals_penalty=goals_penalty,
        eligible_assists=assists,
        goals_conceded_while_eligible=conceded,
        saves=saves,
        penalty_saves=penalty_saves,
        penalty_misses=penalty_misses,
        yellow_cards=yellow,
        red_cards=red,
        own_goals=own_goals,
        defensive_actions=defensive or empty_defensive(),
        bps=bps or empty_bps(),
        dismissed=red > 0,
        team_goals_after_dismissal=team_goals_after_dismissal,
        auxiliary_source_tag="TEST_SYNTHETIC",
    )


def event_fixture(
    *,
    home_goals: int,
    away_goals: int,
    players: tuple[PlayerEventVector, ...],
    fixture_id: str = "FIX-GOLDEN",
    gameweek_id: str = "GW-GOLDEN",
) -> FixtureEventScenario:
    from dmf_pulse.fpl_points.models import AssistClassification, GoalEvent, GoalMechanism

    winner = "HOME" if home_goals > away_goals else "AWAY" if away_goals > home_goals else None
    losing_team = "AWAY" if winner == "HOME" else "HOME"
    own_goal_winner = bool(
        winner and any(player.team_id == losing_team and player.own_goals for player in players)
    )
    if (
        winner
        and not own_goal_winner
        and not any(player.bps.match_winning_goals for player in players)
    ):
        winning_scorer = next(
            player
            for player in players
            if player.team_id == winner and player.goals_non_penalty + player.goals_penalty > 0
        )
        players = tuple(
            player.model_copy(
                update={"bps": player.bps.model_copy(update={"match_winning_goals": 1})}
            )
            if player.player_id == winning_scorer.player_id
            else player
            for player in players
        )
    goals: list[GoalEvent] = []
    home_credited = [
        player
        for player in players
        if player.team_id == "HOME"
        for _ in range(player.goals_non_penalty + player.goals_penalty)
    ]
    home_own = [
        player for player in players if player.team_id == "AWAY" for _ in range(player.own_goals)
    ]
    away_credited = [
        player
        for player in players
        if player.team_id == "AWAY"
        for _ in range(player.goals_non_penalty + player.goals_penalty)
    ]
    away_own = [
        player for player in players if player.team_id == "HOME" for _ in range(player.own_goals)
    ]
    minute = 10.0
    for scoring_team, conceding_team, credited, own in (
        *(("HOME", "AWAY", player, None) for player in home_credited),
        *(("HOME", "AWAY", None, player) for player in home_own),
        *(("AWAY", "HOME", player, None) for player in away_credited),
        *(("AWAY", "HOME", None, player) for player in away_own),
    ):
        goals.append(
            GoalEvent(
                goal_id=f"g-{len(goals) + 1}",
                minute=minute,
                scoring_team_id=scoring_team,
                conceding_team_id=conceding_team,
                mechanism=(GoalMechanism.OPPONENT_OWN_GOAL if own else GoalMechanism.OPEN_PLAY),
                scorer_player_id=credited.player_id if credited else None,
                own_goal_player_id=own.player_id if own else None,
                assister_player_id=None,
                assist_classification=AssistClassification.DEFINITE_NO_ASSIST,
                assist_awarded=False,
            )
        )
        minute += 10.0
    for team_id in ("HOME", "AWAY"):
        assistants = [
            player
            for player in players
            if player.team_id == team_id
            for _ in range(player.eligible_assists)
        ]
        available_goal_indexes = [
            index
            for index, goal in enumerate(goals)
            if goal.scoring_team_id == team_id and goal.scorer_player_id is not None
        ]
        for assistant in assistants:
            goal_index = next(
                index
                for index in available_goal_indexes
                if goals[index].scorer_player_id != assistant.player_id
                and goals[index].assister_player_id is None
            )
            goals[goal_index] = goals[goal_index].model_copy(
                update={
                    "assister_player_id": assistant.player_id,
                    "assist_classification": AssistClassification.DEFINITE_ASSIST,
                    "assist_awarded": True,
                }
            )
    return FixtureEventScenario(
        fixture_id=fixture_id,
        gameweek_id=gameweek_id,
        home_team_id="HOME",
        away_team_id="AWAY",
        home_goals=home_goals,
        away_goals=away_goals,
        participant_universe_complete=True,
        players=players,
        goals=tuple(goals),
        ruleset_id=RULESET_ID,
        ruleset_version=RULESET_VERSION,
        ruleset_hash=RULESET_HASH,
    )


def mc_policy(
    *,
    minimum_effective_scenarios: float = 1.0,
    maximum_mean_mcse: float = 10.0,
    maximum_probability_se: float = 1.0,
    maximum_quantile_span: int = 100,
):
    from dmf_pulse.fpl_points.models import MonteCarloPolicy

    return MonteCarloPolicy(
        minimum_effective_scenarios=minimum_effective_scenarios,
        maximum_mean_mcse=maximum_mean_mcse,
        maximum_probability_se=maximum_probability_se,
        maximum_quantile_span=maximum_quantile_span,
        quantiles=(0.10, 0.50, 0.90),
        thresholds=(5, 10, 15),
        batch_count=4,
    )
