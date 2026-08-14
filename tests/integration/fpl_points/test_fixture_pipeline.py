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
    FixtureProjectionResult,
    FixtureReadiness,
    ProjectionMode,
    SimulationStatus,
)
from dmf_pulse.fpl_points.service import FplPointsService
from tests.support.factories import (
    FIXTURE_A,
    FIXTURE_B,
    H_MID,
    REFERENCE_RULESET,
    make_request,
    mc_policy,
    reference_engine,
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
    blank = assemble_blank_gameweek(
        gameweek_id="GW-B", player_ids=single.player_ids, ruleset_hash="1" * 64
    )
    assert build_gameweek_projection(blank, mc_policy()).player_summaries[H_MID].pmf == {0: 1.0}
    second = service.project(make_request(fixture_id=FIXTURE_B, root_seed=88, scenario_count=20))
    double = assemble_gameweek((first, second))
    projection = build_gameweek_projection(double, mc_policy())
    assert double.assembly_mode.value == "SHARED_OUTCOME_DRAW"
    assert "NO_SEQUENTIAL_CROSS_FIXTURE_TRANSITION" in double.scenarios[0].approximation_labels
    assert len(projection.joint_matrix.points) == 20
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
