from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.gameweek import assemble_blank_gameweek, assemble_gameweek
from dmf_pulse.fpl_points.models import (
    AssistClassification,
    BpsCompletenessMode,
    BpsEvents,
    EventAllocationConfig,
    FixtureEventScenario,
    FixturePointScenario,
    FixtureProjectionResult,
    GameweekPointScenario,
    GameweekScenarioSet,
    GoalEvent,
    GoalMechanism,
    JointScenarioMatrix,
    OnPitchInterval,
    PairDependence,
    ParticipantState,
    ParticipationScenario,
    PlayerPosition,
)
from dmf_pulse.fpl_points.service import FplPointsService
from tests.support.factories import (
    A_FWD,
    FIXTURE_A,
    FIXTURE_B,
    H_FWD,
    H_MID,
    HOME_TEAM_ID,
    allocation_config,
    empty_bps,
    event_fixture,
    event_player,
    make_request,
    mc_policy,
    participant,
    reference_engine,
)


def _validation(model_type, payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        model_type.model_validate(payload)


def test_interval_participant_and_bps_contracts_fail_closed() -> None:
    with pytest.raises(ValidationError, match="positive length"):
        OnPitchInterval(start_minute=10, end_minute=10)
    invalid = participant(H_MID, HOME_TEAM_ID, PlayerPosition.MID).model_dump(mode="python")
    for update, message in (
        ({"hard_ineligible": True}, "hard-ineligible"),
        ({"official_minutes": 0}, "zero-minute"),
        ({"interval": None}, "positive minutes"),
    ):
        _validation(ParticipantState, {**invalid, **update}, message)
    hard_out = participant(
        H_FWD, HOME_TEAM_ID, PlayerPosition.FWD, minutes=0, starter=False
    ).model_copy(update={"hard_ineligible": True})
    assert hard_out.interval is None
    with pytest.raises(ValidationError, match="passes completed"):
        BpsEvents.model_validate(
            {**empty_bps().model_dump(mode="python"), "pass_attempts": 1, "passes_completed": 2}
        )


def test_participation_contract_rejects_identity_cutoff_hash_and_universe_mutations() -> None:
    base = make_request().participation_scenarios[0].model_dump(mode="python")
    mutations = []
    value = copy.deepcopy(base)
    value["away_team_id"] = value["home_team_id"]
    mutations.append((value, "fixture teams"))
    value = copy.deepcopy(base)
    value["participants"][1]["player_id"] = value["participants"][0]["player_id"]
    mutations.append((value, "participant IDs"))
    value = copy.deepcopy(base)
    value["participants"][0]["team_id"] = "20000000-0000-7000-8000-000000000099"
    mutations.append((value, "neither fixture team"))
    value = copy.deepcopy(base)
    value["stage7_player_projection_sha256s"].pop(
        next(iter(value["stage7_player_projection_sha256s"]))
    )
    mutations.append((value, "one-to-one"))
    value = copy.deepcopy(base)
    value["participants"] = value["participants"][:10] + value["participants"][11:]
    removed = set(base["stage7_player_projection_sha256s"]) - {
        row["player_id"] for row in value["participants"]
    }
    for player_id in removed:
        value["stage7_player_projection_sha256s"].pop(player_id)
    mutations.append((value, "at least 11"))
    value = copy.deepcopy(base)
    for row in value["participants"]:
        if row["team_id"] == HOME_TEAM_ID and row["position"] == "GK":
            row["position"] = "DEF"
    mutations.append((value, "exact Stage-7 projection"))
    for payload, message in mutations:
        _validation(ParticipationScenario, payload, message)


def test_event_allocation_config_modes_and_bounds_are_strict() -> None:
    base = allocation_config().model_dump(mode="python")
    for update, message in (
        ({"goal_time_lower": 90.0}, "goal-time bounds"),
        (
            {
                "penalty_goal_probability": 0.5,
                "set_piece_goal_probability": 0.5,
                "direct_free_kick_goal_probability": 0.5,
            },
            "mechanism probabilities",
        ),
        (
            {
                "bps_completeness_mode": BpsCompletenessMode.EVENT_LINKED_ONLY,
                "auxiliary_source_tag": "TEMP-PTS-001",
            },
            "must not claim auxiliary",
        ),
        ({"auxiliary_source_tag": "NONE"}, "requires an explicit source"),
    ):
        _validation(EventAllocationConfig, {**base, **update}, message)


def test_goal_and_fixture_records_reconcile_all_cross_mappings() -> None:
    with pytest.raises(ValidationError, match="definite assist"):
        GoalEvent(
            goal_id="g",
            minute=10,
            scoring_team_id="HOME",
            conceding_team_id="AWAY",
            mechanism=GoalMechanism.OPEN_PLAY,
            scorer_player_id="h",
            own_goal_player_id=None,
            assister_player_id=None,
            assist_classification=AssistClassification.DEFINITE_ASSIST,
            assist_awarded=False,
        )
    fixture = event_fixture(
        home_goals=1,
        away_goals=0,
        players=(
            event_player(H_MID, "HOME", PlayerPosition.MID, goals_non_penalty=1),
            event_player(A_FWD, "AWAY", PlayerPosition.FWD, conceded=1),
        ),
    )
    payload = fixture.model_dump(mode="python")
    payload["goals"][0]["scorer_player_id"] = A_FWD
    _validation(FixtureEventScenario, payload, "outside the scoring team")
    payload = fixture.model_dump(mode="python")
    payload["goals"][0]["goal_id"] = "duplicate"
    payload["goals"] = [*payload["goals"], copy.deepcopy(payload["goals"][0])]
    payload["home_goals"] = 2
    _validation(FixtureEventScenario, payload, "goal event IDs")
    payload = fixture.model_dump(mode="python")
    payload["goals"][0]["mechanism"] = GoalMechanism.PENALTY
    _validation(FixtureEventScenario, payload, "do not reconcile")


def test_fixture_result_scenario_and_joint_matrix_reject_lineage_and_mapping_mutations() -> None:
    result = FplPointsService(reference_engine(), mc_policy()).project(
        make_request(scenario_count=8)
    )
    scenario = result.scenarios[0]
    payload = scenario.model_dump(mode="python")
    for mutate, message in (
        (lambda value: value["event_scenario"].update(gameweek_id="WRONG"), "fixture/Gameweek"),
        (lambda value: value.update(upstream_scoreline=[99, 99]), "upstream scoreline"),
        (
            lambda value: value["event_scenario"].update(ruleset_hash="9" * 64),
            "ruleset identity",
        ),
        (lambda value: value["players"].pop(next(iter(value["players"]))), "participant universes"),
    ):
        changed = copy.deepcopy(payload)
        mutate(changed)
        _validation(FixturePointScenario, changed, message)

    matrix = result.joint_matrix
    assert matrix is not None
    matrix_payload = matrix.model_dump(mode="python")
    matrix_payload["scenario_ids"] = (
        matrix_payload["scenario_ids"][0],
        matrix_payload["scenario_ids"][0],
        *matrix_payload["scenario_ids"][2:],
    )
    _validation(JointScenarioMatrix, matrix_payload, "scenario IDs")
    with pytest.raises(ValidationError, match="exactly one reason"):
        PairDependence(covariance=0.0, correlation=None, correlation_undefined_reason=None)

    result_payload = result.model_dump(mode="python")
    result_payload["upstream_stage8_sha256"] = "9" * 64
    result_payload["result_sha256"] = None
    _validation(FixtureProjectionResult, result_payload, "Stage-8 distribution identity")


def test_gameweek_models_reject_mixed_and_incomplete_scenarios() -> None:
    service = FplPointsService(reference_engine(), mc_policy())
    with pytest.raises(Exception, match="blank Gameweek"):
        assemble_gameweek(())
    first = service.project(make_request(fixture_id=FIXTURE_A, scenario_count=4))
    second = service.project(make_request(fixture_id=FIXTURE_B, scenario_count=4))
    with pytest.raises(FplPointsError) as duplicate:
        assemble_gameweek((first, first))
    assert duplicate.value.code == "GAMEWEEK_FIXTURE_DUPLICATE"
    single = assemble_gameweek((first,))
    duplicate_payload = single.scenarios[0].model_dump(mode="python")
    duplicate_payload["fixture_ids"] = (FIXTURE_A, FIXTURE_A)
    _validation(GameweekPointScenario, duplicate_payload, "fixture IDs must be unique")
    with pytest.raises(Exception, match="different Gameweeks"):
        changed = second.model_copy(update={"gameweek_id": "GW-OTHER"})
        assemble_gameweek((first, changed))
    with pytest.raises(Exception, match="all fixture projections"):
        blocked = service.project(make_request(fixture_id=FIXTURE_B, mode="PRODUCTION"))
        assemble_gameweek((first, blocked))

    blank = assemble_blank_gameweek(gameweek_id="GW-B", player_ids=(H_MID,), ruleset_hash="1" * 64)
    point_payload = blank.scenarios[0].model_dump(mode="python")
    point_payload["player_components"][H_MID].pop("bonus")
    _validation(GameweekPointScenario, point_payload, "component vector")
    set_payload = blank.model_dump(mode="python")
    set_payload["scenarios"] = []
    _validation(GameweekScenarioSet, set_payload, "cannot be empty")


def test_new_ruleset_and_gameweek_contract_branches_fail_closed() -> None:
    result = FplPointsService(reference_engine(), mc_policy()).project(
        make_request(scenario_count=4)
    )
    identity = result.ruleset.model_dump(mode="python")
    identity["human_approval_recorded"] = True
    _validation(type(result.ruleset), identity, "only through activation evidence")

    blank = assemble_blank_gameweek(gameweek_id="GW-B", player_ids=(H_MID,), ruleset_hash="1" * 64)
    point = blank.scenarios[0].model_dump(mode="python")
    point["player_appeared"][H_MID] = True
    _validation(GameweekPointScenario, point, "derived from official minutes")
    point = blank.scenarios[0].model_dump(mode="python")
    point["fixture_ids"] = ("fixture",)
    _validation(GameweekPointScenario, point, "blank Gameweek")

    blank_set = blank.model_dump(mode="python")
    blank_set["fixture_result_sha256_by_fixture"] = {"fixture": "1" * 64}
    _validation(GameweekScenarioSet, blank_set, "must not have fixture-result lineage")

    single = assemble_gameweek((result,)).model_dump(mode="python")
    single["fixture_result_sha256_by_fixture"] = {}
    _validation(GameweekScenarioSet, single, "requires fixture-result lineage")
