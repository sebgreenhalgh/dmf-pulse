"""2026/27 assist policy executes through the Stage-9 adapter boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmf_pulse.fpl_points.allocation import allocate_fixture_events
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import (
    AssistClassification,
    BpsEvents,
    DefensiveActions,
    FixtureEventScenario,
    GoalEvent,
    GoalMechanism,
    PlayerEventVector,
    PlayerPosition,
    ProjectionMode,
    ScorelineCell,
)
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter
from dmf_pulse.rules.assists import classify_assist
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.models import (
    AssistAction,
    AssistDecisionContext,
    AssistEligibility,
    AssistGoalKind,
    AssistReboundIntervention,
    AssistReceptionZone,
    AssistSetPieceRoute,
)
from tests.support.factories import H_FWD, H_MID, allocation_config, base_profiles, make_request


def _compiled(repository_root: Path):
    return compile_ruleset(repository_root / "fixtures/rules/RUL-002/target_2026_27_partial")


def _target_profiles(*, scorer_id: str = H_MID, assister_id: str = H_FWD):
    """Force model facts without putting FPL eligibility into allocation parameters."""

    profiles = []
    for profile in base_profiles():
        if profile.team_id != "20000000-0000-7000-8000-000000000001":
            profiles.append(profile)
            continue
        profiles.append(
            profile.model_copy(
                update={
                    "goal_share": float(profile.player_id == scorer_id),
                    "penalty_taker_share": float(profile.player_id == scorer_id),
                    "assist_share": float(profile.player_id == assister_id),
                }
            )
        )
    return tuple(profiles)


def _generated_target_goal(
    repository_root: Path,
    *,
    mechanism: GoalMechanism,
    scorer_id: str = H_MID,
    assister_id: str = H_FWD,
    ambiguous_probability: float = 0.0,
):
    compiled = _compiled(repository_root)
    adapter = AcceptedRulesAdapter(compiled)
    request = make_request(
        config=allocation_config(
            goal_time_lower=70.0,
            goal_time_upper=80.0,
            penalty_goal_probability=float(mechanism is GoalMechanism.PENALTY),
            direct_free_kick_goal_probability=float(mechanism is GoalMechanism.DIRECT_FREE_KICK),
            own_goal_probability=float(mechanism is GoalMechanism.OPPONENT_OWN_GOAL),
            ambiguous_assist_probability=ambiguous_probability,
            ambiguous_assist_eligible_probability=0.0,
        )
    )
    scenario, _ = allocate_fixture_events(
        cell=ScorelineCell(home_goals=1, away_goals=0, probability="1.000000000000"),
        participation=request.participation_scenarios[0],
        profiles=_target_profiles(scorer_id=scorer_id, assister_id=assister_id),
        config=request.allocation_config,
        ruleset=adapter.identity,
        projection_mode=ProjectionMode.TEST,
        root_seed=202627,
        scenario_index=0,
        assist_classifier=adapter.classify_generated_assist,
    )
    return adapter, scenario, scenario.goals[0]


def _context(**updates: object) -> AssistDecisionContext:
    value: dict[str, object] = {
        "goal_kind": AssistGoalKind.OPEN_PLAY,
        "action": AssistAction.PASS,
    }
    value.update(updates)
    return AssistDecisionContext.model_validate(value)


CASES = (
    ("A", _context(), AssistEligibility.DEFINITE_ASSIST),
    ("B", _context(defensive_touches=1), AssistEligibility.DEFINITE_ASSIST),
    ("C", _context(defensive_touches=2), AssistEligibility.DEFINITE_NO_ASSIST),
    (
        "D",
        _context(defensive_touches=1, defensive_touch_is_pass=True),
        AssistEligibility.DEFINITE_NO_ASSIST,
    ),
    (
        "E",
        _context(scorer_reception_zone=AssistReceptionZone.OUTSIDE_BOX, intended_for_scorer=False),
        AssistEligibility.DEFINITE_NO_ASSIST,
    ),
    (
        "F",
        _context(
            action=AssistAction.SHOT, rebound_intervention=AssistReboundIntervention.GOALKEEPER_SAVE
        ),
        AssistEligibility.DEFINITE_ASSIST,
    ),
    (
        "G",
        _context(
            action=AssistAction.SHOT,
            rebound_intervention=AssistReboundIntervention.GOALKEEPER_SAVE,
            defensive_touch_after_rebound=True,
        ),
        AssistEligibility.DEFINITE_NO_ASSIST,
    ),
    (
        "H",
        _context(
            action=AssistAction.SHOT,
            rebound_intervention=AssistReboundIntervention.GOALKEEPER_SAVE,
            scorer_converts_own_rebound=True,
        ),
        AssistEligibility.DEFINITE_NO_ASSIST,
    ),
    (
        "I",
        _context(goal_kind=AssistGoalKind.OWN_GOAL, action=AssistAction.FORCED_OWN_GOAL_ACTION),
        AssistEligibility.DEFINITE_ASSIST,
    ),
    (
        "J",
        _context(goal_kind=AssistGoalKind.OWN_GOAL, defensive_touches=1),
        AssistEligibility.DEFINITE_ASSIST,
    ),
    (
        "K",
        _context(goal_kind=AssistGoalKind.OWN_GOAL, defensive_touches=2),
        AssistEligibility.DEFINITE_NO_ASSIST,
    ),
    (
        "L",
        _context(
            goal_kind=AssistGoalKind.DIRECT_PENALTY,
            action=AssistAction.FOUL_WON,
            set_piece_route=AssistSetPieceRoute.FOUL_WON,
        ),
        AssistEligibility.DEFINITE_ASSIST,
    ),
    (
        "M",
        _context(
            goal_kind=AssistGoalKind.DIRECT_PENALTY,
            action=AssistAction.FOUL_WON,
            set_piece_route=AssistSetPieceRoute.FOUL_WON,
            candidate_is_scorer=True,
        ),
        AssistEligibility.DEFINITE_NO_ASSIST,
    ),
    (
        "N",
        _context(
            goal_kind=AssistGoalKind.DIRECT_FREE_KICK,
            action=AssistAction.FOUL_WON,
            set_piece_route=AssistSetPieceRoute.FOUL_WON,
        ),
        AssistEligibility.DEFINITE_ASSIST,
    ),
    (
        "O",
        _context(
            goal_kind=AssistGoalKind.DIRECT_PENALTY,
            action=AssistAction.PASS,
            set_piece_route=AssistSetPieceRoute.HANDBALL_AFTER_PASS_TOUCH,
            defensive_touches=1,
        ),
        AssistEligibility.DEFINITE_NO_ASSIST,
    ),
    (
        "P",
        _context(
            goal_kind=AssistGoalKind.DIRECT_PENALTY,
            action=AssistAction.SHOT,
            set_piece_route=AssistSetPieceRoute.HANDBALL_AFTER_SHOT,
            defensive_touches=1,
            shot_on_target_before_deflection=True,
            shot_on_target_after_deflection=True,
        ),
        AssistEligibility.DEFINITE_ASSIST,
    ),
    (
        "Q",
        _context(
            goal_kind=AssistGoalKind.DIRECT_PENALTY,
            action=AssistAction.SHOT,
            set_piece_route=AssistSetPieceRoute.HANDBALL_AFTER_SHOT,
            defensive_touches=1,
            shot_on_target_before_deflection=True,
            shot_on_target_after_deflection=False,
        ),
        AssistEligibility.DEFINITE_NO_ASSIST,
    ),
    (
        "R",
        _context(
            goal_kind=AssistGoalKind.DIRECT_FREE_KICK,
            action=AssistAction.PASS,
            set_piece_route=AssistSetPieceRoute.CORNER_OR_THROW_IN,
        ),
        AssistEligibility.DEFINITE_NO_ASSIST,
    ),
)


@pytest.mark.unit
@pytest.mark.parametrize(("label", "context", "expected"), CASES, ids=[item[0] for item in CASES])
def test_2026_27_assist_goldens_are_versioned_and_exact(
    repository_root: Path, label: str, context: AssistDecisionContext, expected: AssistEligibility
) -> None:
    assert classify_assist(_compiled(repository_root), context) is expected


def _player(
    player_id: str, team_id: str, position: PlayerPosition, **updates: object
) -> PlayerEventVector:
    payload: dict[str, object] = {
        "player_id": player_id,
        "team_id": team_id,
        "position": position,
        "minutes": 90,
        "goals_non_penalty": 0,
        "goals_penalty": 0,
        "eligible_assists": 0,
        "goals_conceded_while_eligible": 0,
        "saves": 0,
        "penalty_saves": 0,
        "penalty_misses": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "own_goals": 0,
        "defensive_actions": DefensiveActions(
            ball_recoveries=0, blocks=0, clearances=0, interceptions=0, tackles=0
        ),
        "bps": BpsEvents.model_validate({name: 0 for name in BpsEvents.model_fields}),
        "dismissed": False,
        "team_goals_after_dismissal": 0,
        "auxiliary_source_tag": "TEST_SYNTHETIC",
    }
    payload.update(updates)
    return PlayerEventVector.model_validate(payload)


@pytest.mark.unit
@pytest.mark.parametrize(("label", "context", "expected"), CASES, ids=[item[0] for item in CASES])
def test_stage9_goal_context_adapter_and_scorer_share_one_assist_truth(
    repository_root: Path, label: str, context: AssistDecisionContext, expected: AssistEligibility
) -> None:
    compiled = _compiled(repository_root)
    is_own_goal = context.goal_kind is AssistGoalKind.OWN_GOAL
    mechanism = {
        AssistGoalKind.OPEN_PLAY: GoalMechanism.OPEN_PLAY,
        AssistGoalKind.OWN_GOAL: GoalMechanism.OPPONENT_OWN_GOAL,
        AssistGoalKind.DIRECT_PENALTY: GoalMechanism.PENALTY,
        AssistGoalKind.DIRECT_FREE_KICK: GoalMechanism.DIRECT_FREE_KICK,
    }[context.goal_kind]
    awarded = expected is AssistEligibility.DEFINITE_ASSIST
    scorer_bps = BpsEvents.model_validate(
        {
            name: int(name == "match_winning_goals" and not is_own_goal)
            for name in BpsEvents.model_fields
        }
    )
    scorer = _player(
        "home-scorer",
        "HOME",
        PlayerPosition.FWD,
        goals_penalty=0 if mechanism is not GoalMechanism.PENALTY else 1,
        goals_non_penalty=0 if is_own_goal or mechanism is GoalMechanism.PENALTY else 1,
        bps=scorer_bps,
    )
    assister = _player("home-assister", "HOME", PlayerPosition.MID, eligible_assists=int(awarded))
    own_goal = _player("away-own", "AWAY", PlayerPosition.DEF, own_goals=int(is_own_goal))
    if is_own_goal:
        scorer = _player("home-scorer", "HOME", PlayerPosition.FWD)
    goal = GoalEvent(
        goal_id=f"goal-{label}",
        minute=30.0,
        scoring_team_id="HOME",
        conceding_team_id="AWAY",
        mechanism=mechanism,
        scorer_player_id=None if is_own_goal else "home-scorer",
        own_goal_player_id="away-own" if is_own_goal else None,
        assister_player_id="home-assister" if awarded else None,
        assist_classification=AssistClassification(expected.value),
        assist_awarded=awarded,
        assist_context=context,
    )
    scenario = FixtureEventScenario(
        fixture_id=f"fixture-{label}",
        gameweek_id="GW1",
        home_team_id="HOME",
        away_team_id="AWAY",
        home_goals=1,
        away_goals=0,
        participant_universe_complete=True,
        players=(scorer, assister, own_goal),
        goals=(goal,),
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
    )
    scores = AcceptedRulesAdapter(compiled).score_fixture(scenario)
    assert scores["home-assister"].assists == (3 if awarded else 0)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mechanism", "kind"),
    (
        (GoalMechanism.PENALTY, AssistGoalKind.DIRECT_PENALTY),
        (GoalMechanism.DIRECT_FREE_KICK, AssistGoalKind.DIRECT_FREE_KICK),
    ),
)
def test_generated_target_set_piece_foul_winner_assist_uses_compiled_policy(
    repository_root: Path, mechanism: GoalMechanism, kind: AssistGoalKind
) -> None:
    adapter, scenario, goal = _generated_target_goal(repository_root, mechanism=mechanism)
    assert goal.scorer_player_id == H_MID
    assert goal.assister_player_id == H_FWD
    assert goal.assist_context is not None
    assert goal.assist_context.goal_kind is kind
    assert goal.assist_context.set_piece_route is AssistSetPieceRoute.FOUL_WON
    assert goal.assist_classification is AssistClassification.DEFINITE_ASSIST
    assert goal.assist_awarded is True
    assert (
        next(player for player in scenario.players if player.player_id == H_FWD).eligible_assists
        == 1
    )
    assert adapter.score_fixture(scenario)[H_FWD].assists == 3


@pytest.mark.unit
def test_generated_target_own_goal_forcing_action_is_classified_and_reconciled(
    repository_root: Path,
) -> None:
    adapter, scenario, goal = _generated_target_goal(
        repository_root, mechanism=GoalMechanism.OPPONENT_OWN_GOAL
    )
    assert goal.scorer_player_id is None
    assert goal.own_goal_player_id is not None
    assert goal.assister_player_id == H_FWD
    assert goal.assist_context is not None
    assert goal.assist_context.goal_kind is AssistGoalKind.OWN_GOAL
    assert goal.assist_context.action is AssistAction.FORCED_OWN_GOAL_ACTION
    assert goal.assist_classification is AssistClassification.DEFINITE_ASSIST
    assert adapter.score_fixture(scenario)[H_FWD].assists == 3
    awarded = {player.player_id: 0 for player in scenario.players}
    for event in scenario.goals:
        if event.assister_player_id is not None:
            awarded[event.assister_player_id] += 1
    assert {player.player_id: player.eligible_assists for player in scenario.players} == awarded
    _, repeated, repeated_goal = _generated_target_goal(
        repository_root, mechanism=GoalMechanism.OPPONENT_OWN_GOAL
    )
    assert repeated == scenario
    assert repeated_goal == goal


@pytest.mark.unit
def test_generated_target_self_taker_and_legacy_ambiguity_flag_do_not_score_assist(
    repository_root: Path,
) -> None:
    _, scenario, goal = _generated_target_goal(
        repository_root,
        mechanism=GoalMechanism.PENALTY,
        scorer_id=H_MID,
        assister_id=H_MID,
        ambiguous_probability=1.0,
    )
    assert goal.assist_context is not None
    assert goal.assist_context.candidate_is_scorer is True
    assert goal.assist_classification is AssistClassification.DEFINITE_NO_ASSIST
    assert goal.assister_player_id is None
    assert goal.assist_awarded is False
    assert all(
        event.assist_classification is not AssistClassification.AMBIGUOUS_ASSIST
        for event in scenario.goals
    )


@pytest.mark.unit
def test_target_adapter_rejects_ambiguous_goal_without_context(repository_root: Path) -> None:
    compiled = _compiled(repository_root)
    player = _player("home", "HOME", PlayerPosition.MID, goals_non_penalty=1)
    scenario = FixtureEventScenario(
        fixture_id="ambiguous",
        gameweek_id="GW1",
        home_team_id="HOME",
        away_team_id="AWAY",
        home_goals=1,
        away_goals=0,
        participant_universe_complete=True,
        players=(player,),
        goals=(
            GoalEvent(
                goal_id="ambiguous-goal",
                minute=1.0,
                scoring_team_id="HOME",
                conceding_team_id="AWAY",
                mechanism=GoalMechanism.OPEN_PLAY,
                scorer_player_id="home",
                own_goal_player_id=None,
                assister_player_id=None,
                assist_classification=AssistClassification.AMBIGUOUS_ASSIST,
                assist_awarded=False,
            ),
        ),
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
    )
    with pytest.raises(FplPointsError) as error:
        AcceptedRulesAdapter(compiled).score_fixture(scenario)
    assert error.value.code == "RULESET_ASSIST_AMBIGUOUS"
