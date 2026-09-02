from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli import fpl_points as cli_module
from dmf_pulse.fpl_points.artifacts import load_verified_model, persist_model_artifact
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.gameweek import assemble_blank_gameweek, assemble_gameweek
from dmf_pulse.fpl_points.gameweek_summaries import build_gameweek_projection
from dmf_pulse.fpl_points.models import (
    PENALTY_GOAL_SHARE_PROXY_WARNING,
    FixtureProjectionResult,
    FixtureReadiness,
    FixtureSimulationRequest,
    PenaltyHierarchyExhaustionPolicy,
    PenaltyTakerHierarchyEntry,
    ProjectionMode,
    SimulationStatus,
)
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter
from dmf_pulse.fpl_points.service import FplPointsService
from dmf_pulse.rules.compiler import compile_ruleset
from tests.support.factories import (
    A_FWD,
    AWAY_TEAM_ID,
    FIXTURE_A,
    FIXTURE_B,
    H_FWD,
    H_MID,
    HOME_TEAM_ID,
    REFERENCE_RULESET,
    base_profiles,
    make_request,
    mc_policy,
    reference_engine,
)


def _target_engine(repository_root: Path) -> AcceptedRulesAdapter:
    return AcceptedRulesAdapter(
        compile_ruleset(repository_root / "fixtures/rules/RUL-002/target_2026_27_partial")
    )


def test_stage7_stage8_to_fixture_points_vertical_slice() -> None:
    request = make_request(scenario_count=128)
    result = FplPointsService(reference_engine(), mc_policy()).project(request)
    assert result.status is SimulationStatus.SUCCESS
    assert len(result.scenarios) == 128
    assert result.joint_matrix is not None
    assert result.joint_matrix.points[0] == tuple(
        result.scenarios[0].players[player_id].total for player_id in result.joint_matrix.player_ids
    )
    assert result.ruleset.ruleset_hash == request.expected_ruleset_hash
    assert result.upstream_stage8_sha256 == request.score_distribution.result_sha256
    assert all(
        set(scenario.players) == set(scenario.stage7_player_projection_sha256s)
        for scenario in result.scenarios
    )


def test_target_player_points_service_routes_generated_penalties_through_rules_classifier(
    repository_root: Path,
) -> None:
    engine = _target_engine(repository_root)
    request = make_request(
        scenario_count=16,
        config=make_request().allocation_config.model_copy(
            update={
                "penalty_goal_probability": 1.0,
                "ambiguous_assist_probability": 1.0,
                "ambiguous_assist_eligible_probability": 0.0,
            }
        ),
    ).model_copy(
        update={
            "expected_ruleset_id": engine.identity.ruleset_id,
            "expected_ruleset_version": engine.identity.ruleset_version,
            "expected_ruleset_hash": engine.identity.ruleset_hash,
        }
    )
    result = FplPointsService(engine, mc_policy()).project(request)
    assert result.status is SimulationStatus.SUCCESS
    goals = [goal for scenario in result.scenarios for goal in scenario.event_scenario.goals]
    assert goals
    assert all(goal.mechanism.value == "PENALTY" for goal in goals)
    assert all(goal.assist_context is not None for goal in goals)
    assert all(goal.assist_classification.value != "AMBIGUOUS_ASSIST" for goal in goals)


def test_private_penalty_proxy_warning_reaches_fixture_and_gameweek_contracts() -> None:
    base = make_request(scenario_count=32)
    payload = base.model_dump(mode="python")
    payload.update(
        {
            "allocation_profiles": tuple(
                profile.model_copy(update={"penalty_taker_share": 0.0})
                for profile in base_profiles()
            ),
            "penalty_taker_hierarchy": (
                PenaltyTakerHierarchyEntry(
                    player_id=H_FWD,
                    team_id=HOME_TEAM_ID,
                    order=1,
                ),
                PenaltyTakerHierarchyEntry(
                    player_id=A_FWD,
                    team_id=AWAY_TEAM_ID,
                    order=1,
                ),
            ),
            "penalty_hierarchy_exhaustion_policy": (
                PenaltyHierarchyExhaustionPolicy.PRIVATE_CURRENT_PENALTY_ROLE_GOAL_SHARE_PROXY_V1
            ),
            "allocation_config": base.allocation_config.model_copy(
                update={"penalty_goal_probability": 1.0}
            ),
        }
    )
    request = FixtureSimulationRequest.model_validate(payload)

    result = FplPointsService(reference_engine(), mc_policy()).project(request)
    assert result.status is SimulationStatus.SUCCESS
    assert PENALTY_GOAL_SHARE_PROXY_WARNING in result.warnings
    assert PENALTY_GOAL_SHARE_PROXY_WARNING in assemble_gameweek((result,)).warnings


def test_fixture_bonus_is_ranked_jointly_across_complete_participant_universe() -> None:
    result = FplPointsService(reference_engine(), mc_policy()).project(
        make_request(scenario_count=32)
    )
    for scenario in result.scenarios:
        assert len(scenario.players) == len(scenario.event_scenario.players)
        ranks = [
            score.bps_competition_rank
            for score in scenario.players.values()
            if score.bps_competition_rank
        ]
        assert ranks
        assert min(ranks) == 1
        assert all(score.bonus >= 0 for score in scenario.players.values())


def test_artifact_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    result = FplPointsService(reference_engine(), mc_policy()).project(
        make_request(scenario_count=16)
    )
    path = persist_model_artifact(
        result, artifact_root=tmp_path, category="fixture", identity_parts=("GW-1", "FIX-1")
    )
    assert load_verified_model(path, FixtureProjectionResult) == result
    path.write_bytes(path.read_bytes().replace(b'"bonus":0', b'"bonus":1', 1))
    with pytest.raises(FplPointsError) as exc:
        load_verified_model(path, FixtureProjectionResult)
    assert exc.value.code == "ARTIFACT_HASH_MISMATCH"


def test_deterministic_rerun_has_same_result_and_artifact_path(tmp_path: Path) -> None:
    service = FplPointsService(reference_engine(), mc_policy())
    request = make_request(scenario_count=24, root_seed=2026)
    first = service.project(request)
    second = service.project(request)
    assert first == second
    first_path = persist_model_artifact(
        first, artifact_root=tmp_path, category="fixture", identity_parts=("GW-1", "FIX-1")
    )
    second_path = persist_model_artifact(
        second, artifact_root=tmp_path, category="fixture", identity_parts=("GW-1", "FIX-1")
    )
    assert first_path == second_path


def test_single_blank_and_double_gameweek_pipeline() -> None:
    service = FplPointsService(reference_engine(), mc_policy())
    first = service.project(make_request(fixture_id=FIXTURE_A, root_seed=88, scenario_count=20))
    single = assemble_gameweek((first,))
    assert single.assembly_mode.value == "SINGLE_FIXTURE"
    assert single.fixture_result_sha256_by_fixture == {FIXTURE_A: first.result_sha256}
    assert all(
        scenario.player_appeared[player_id] == (scenario.player_minutes[player_id] > 0)
        for scenario in single.scenarios
        for player_id in scenario.player_points
    )
    assert all(
        gameweek_scenario.player_minutes[player.player_id] == player.minutes
        for gameweek_scenario, fixture_scenario in zip(
            single.scenarios, first.scenarios, strict=True
        )
        for player in fixture_scenario.event_scenario.players
    )
    blank = assemble_blank_gameweek(
        gameweek_id="GW-B", player_ids=single.player_ids, ruleset_hash="1" * 64
    )
    assert build_gameweek_projection(blank, mc_policy()).player_summaries[H_MID].pmf == {0: 1.0}
    assert blank.fixture_result_sha256_by_fixture == {}
    assert blank.scenarios[0].player_minutes[H_MID] == 0
    assert blank.scenarios[0].player_appeared[H_MID] is False
    second = service.project(make_request(fixture_id=FIXTURE_B, root_seed=88, scenario_count=20))
    double = assemble_gameweek((first, second))
    projection = build_gameweek_projection(double, mc_policy())
    assert double.assembly_mode.value == "SHARED_OUTCOME_DRAW"
    assert "NO_SEQUENTIAL_CROSS_FIXTURE_TRANSITION" in double.scenarios[0].approximation_labels
    assert double.fixture_result_sha256_by_fixture == {
        FIXTURE_A: first.result_sha256,
        FIXTURE_B: second.result_sha256,
    }
    first_by_draw = {scenario.outcome_draw_id: scenario for scenario in first.scenarios}
    second_by_draw = {scenario.outcome_draw_id: scenario for scenario in second.scenarios}
    assert all(
        gameweek_scenario.player_minutes[H_MID]
        == next(
            player.minutes
            for player in first_by_draw[gameweek_scenario.outcome_draw_id].event_scenario.players
            if player.player_id == H_MID
        )
        + next(
            player.minutes
            for player in second_by_draw[gameweek_scenario.outcome_draw_id].event_scenario.players
            if player.player_id == H_MID
        )
        for gameweek_scenario in double.scenarios
    )
    assert len(projection.joint_matrix.points) == 20
    assert projection.result_sha256 is not None
    assert projection.player_summaries[H_MID].expected_points == pytest.approx(
        2 * single.scenarios[0].player_points[H_MID], abs=100
    )


def test_postponed_and_inactive_ruleset_paths_fail_closed() -> None:
    service = FplPointsService(reference_engine(), mc_policy())
    postponed = service.project(
        make_request(readiness=FixtureReadiness.POSTPONED, scenario_count=4)
    )
    assert postponed.status is SimulationStatus.BLOCKED
    assert postponed.error_code == "FIXTURE_NOT_PLAYABLE"
    production = service.project(make_request(mode=ProjectionMode.PRODUCTION, scenario_count=4))
    assert production.status is SimulationStatus.BLOCKED
    assert production.error_code == "RULESET_NOT_ACTIVE"


def test_public_cli_test_mode_simulate_validate_and_mc_diagnostics(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(make_request(scenario_count=12).model_dump(mode="json")), encoding="utf-8"
    )
    rules_path = tmp_path / "rules.json"
    shutil.copyfile(REFERENCE_RULESET, rules_path)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(mc_policy().model_dump(mode="json")), encoding="utf-8")
    runner = CliRunner()
    simulation = runner.invoke(
        cli_module.fpl_points_app,
        [
            "simulate-fixture",
            "--request",
            str(request_path),
            "--ruleset",
            str(rules_path),
            "--mc-policy",
            str(policy_path),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ],
    )
    assert simulation.exit_code == 0, simulation.output
    payload = json.loads(simulation.output)
    artifact = Path(payload["artifact_path"])
    validation = runner.invoke(cli_module.fpl_points_app, ["validate", "--artifact", str(artifact)])
    assert validation.exit_code == 0, validation.output
    diagnostics = runner.invoke(
        cli_module.fpl_points_app, ["mc-diagnostics", "--artifact", str(artifact)]
    )
    assert diagnostics.exit_code == 0, diagnostics.output
    assert json.loads(diagnostics.output)["monte_carlo"]["scenario_count"] == 12
