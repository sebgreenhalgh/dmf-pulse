from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.text import Text
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.cli.rank import rank_app
from dmf_pulse.evaluation.artifacts import canonical_json_bytes
from dmf_pulse.rank_strategy.artifacts import persist_decision_artifact, seal_decision_artifact
from dmf_pulse.rank_strategy.manager_multipliers import calculate_manager_multipliers
from dmf_pulse.rank_strategy.service import (
    evaluate_effective_ownership,
    evaluate_exact_mini_league,
    evaluate_opponent_actions,
    evaluate_rank_plans,
    evaluate_synthetic_cohort,
)
from tests.support.opponent_action_fixtures import (
    baseline_candidates,
    behaviour_profile,
    observed_state,
)
from tests.support.rank_service_fixtures import service_request, write_service_request
from tests.support.rank_strategy_fixtures import (
    cohort,
    exact_named_league,
    manager_plan,
    multiplier_policy,
    rank_players,
    rank_rules,
    rank_tie_policy,
    scenario_set,
)
from tests.support.synthetic_field_fixtures import (
    multiplier_sets_for_population,
    tiny_known_truth_population,
)

runner = CliRunner()


def _write(path: Path, payload) -> None:
    if hasattr(payload, "model_dump"):
        path.write_bytes(canonical_json_bytes(payload))
    else:
        path.write_bytes(canonical_json_bytes(payload))


def test_top_level_rank_help_exposes_complete_vertical_slice() -> None:
    result = runner.invoke(app, ["rank", "--help"])

    assert result.exit_code == 0
    for command in (
        "validate",
        "eo",
        "mini-league",
        "opponents",
        "cohort",
        "evaluate",
        "compare",
    ):
        assert command in result.stdout


@pytest.mark.parametrize(
    "arguments",
    (
        ("eo", "--input", "unused.json", "--output", "yaml"),
        ("mini-league", "--input", "unused.json", "--output", "yaml"),
        ("opponents", "--input", "unused.json", "--output", "yaml"),
        ("cohort", "--input", "unused.json", "--output", "yaml"),
        ("evaluate", "--input", "unused.json", "--output", "yaml"),
        ("compare", "--input", "unused.json", "--output", "yaml"),
        ("validate", "--output", "yaml"),
    ),
)
def test_every_rank_command_rejects_unsupported_output_format(
    arguments: tuple[str, ...],
) -> None:
    result = runner.invoke(rank_app, list(arguments))

    plain_output = Text.from_ansi(result.stdout + result.stderr).plain
    assert result.exit_code != 0
    assert "--output must be json" in plain_output


def test_validate_reports_installed_fail_closed_capability() -> None:
    result = runner.invoke(rank_app, ["validate"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "REVIEW_READY_PENDING_HUMAN_ACCEPTANCE"
    assert payload["fail_closed_to_pure_points"] is True
    assert payload["raw_projection_mutation_permitted"] is False


def test_evaluate_and_compare_match_shared_library_semantics(tmp_path: Path) -> None:
    request = service_request()
    path = tmp_path / "rank-request.json"
    write_service_request(path, request)
    expected = evaluate_rank_plans(request)

    evaluated = runner.invoke(rank_app, ["evaluate", "--input", str(path)])
    compared = runner.invoke(rank_app, ["compare", "--input", str(path)])

    assert evaluated.exit_code == 0, evaluated.stdout
    assert compared.exit_code == 0, compared.stdout
    assert json.loads(evaluated.stdout)["result_hash"] == expected.result_hash
    comparison = json.loads(compared.stdout)
    assert comparison["points_optimal_plan_id"] == expected.points_optimal_plan.plan_id
    assert comparison["rank_optimal_plan_id"] == expected.rank_optimal_plan.plan_id
    assert comparison["selected_plan_id"] == expected.selected_plan.plan_id
    assert comparison["expected_points_difference"] == expected.expected_points_difference


def test_evaluate_can_persist_and_validate_artifact(tmp_path: Path) -> None:
    request = service_request()
    path = tmp_path / "request.json"
    artifact_root = tmp_path / "artifacts"
    write_service_request(path, request)

    evaluated = runner.invoke(
        rank_app,
        ["evaluate", "--input", str(path), "--artifact-root", str(artifact_root)],
    )

    assert evaluated.exit_code == 0, evaluated.stdout
    payload = json.loads(evaluated.stdout)
    persisted = next(artifact_root.rglob("*.json"))
    validated = runner.invoke(rank_app, ["validate", "--artifact", str(persisted)])
    assert validated.exit_code == 0, validated.stdout
    assert json.loads(validated.stdout)["artifact_hash"] == payload["artifact_hash"]


def test_validate_accepts_inline_service_request_and_artifact(tmp_path: Path) -> None:
    request = service_request()
    request_path = tmp_path / "request.json"
    write_service_request(request_path, request)

    validated_request = runner.invoke(
        rank_app,
        ["validate", "--input", str(request_path)],
    )
    assert validated_request.exit_code == 0
    assert json.loads(validated_request.stdout)["status"] == "VALID"

    artifact = seal_decision_artifact(request)
    artifact_path = tmp_path / "inline-artifact.json"
    _write(artifact_path, artifact)
    validated_artifact = runner.invoke(
        rank_app,
        ["validate", "--input", str(artifact_path)],
    )
    assert validated_artifact.exit_code == 0
    assert json.loads(validated_artifact.stdout)["artifact_hash"] == artifact.artifact_hash


def test_effective_ownership_cli_matches_shared_service(tmp_path: Path) -> None:
    sebastian = manager_plan("sebastian", captain="p12")
    rival = manager_plan("rival", captain="p13")
    sample = cohort(sebastian, rival)
    scenarios = scenario_set(
        {"p12": 8, "p13": 2},
        {"p12": 1, "p13": 9},
        weights=(0.4, 0.6),
    )
    players = rank_players()
    rules = rank_rules()
    policy = multiplier_policy()
    expected = evaluate_effective_ownership(
        sample,
        scenarios,
        players,
        rules,
        policy,
        sebastian_plan=sebastian,
    )
    path = tmp_path / "eo.json"
    _write(
        path,
        {
            "sample": sample.model_dump(mode="json"),
            "scenario_set": scenarios.model_dump(mode="json"),
            "players": {key: value.model_dump(mode="json") for key, value in players.items()},
            "rules": rules.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"),
            "sebastian_plan": sebastian.model_dump(mode="json"),
        },
    )

    result = runner.invoke(rank_app, ["eo", "--input", str(path)])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["report_hash"] == expected.report_hash


def test_exact_mini_league_cli_matches_shared_service(tmp_path: Path) -> None:
    sebastian = manager_plan("sebastian", captain="p12", cumulative_points=100)
    rival = manager_plan("rival", captain="p13", cumulative_points=101)
    sample = exact_named_league(sebastian, rival)
    scenarios = scenario_set(
        {"p12": 8, "p13": 2},
        {"p12": 1, "p13": 9},
        weights=(0.5, 0.5),
    )
    multiplier_sets = tuple(
        calculate_manager_multipliers(
            plan,
            scenarios,
            rank_players(),
            rank_rules(),
            multiplier_policy(),
        )
        for plan in (sebastian, rival)
    )
    tie_policy = rank_tie_policy()
    expected = evaluate_exact_mini_league(
        sample,
        multiplier_sets,
        tie_policy,
        target_manager_id="sebastian",
        target_rank=1,
    )
    path = tmp_path / "mini.json"
    _write(
        path,
        {
            "sample": sample.model_dump(mode="json"),
            "multiplier_sets": [item.model_dump(mode="json") for item in multiplier_sets],
            "tie_policy": tie_policy.model_dump(mode="json"),
            "target_manager_id": "sebastian",
            "target_rank": 1,
        },
    )

    result = runner.invoke(rank_app, ["mini-league", "--input", str(path)])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["distribution_hash"] == expected.distribution_hash


def test_opponents_cli_matches_shared_service(tmp_path: Path) -> None:
    state = observed_state()
    candidates = baseline_candidates()
    profile = behaviour_profile()
    expected = evaluate_opponent_actions(state, candidates, profile)
    path = tmp_path / "opponents.json"
    _write(
        path,
        {
            "observed_state": state.model_dump(mode="json"),
            "candidates": [item.model_dump(mode="json") for item in candidates],
            "profile": profile.model_dump(mode="json"),
            "additional_distributions": [],
            "max_joint_scenarios": 100,
        },
    )

    result = runner.invoke(rank_app, ["opponents", "--input", str(path)])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["distribution_hash"] == expected.distribution_hash


def test_synthetic_cohort_cli_matches_shared_service(tmp_path: Path) -> None:
    population = tiny_known_truth_population()
    scenarios = scenario_set(
        {"p12": 8, "p13": 2, "p14": 1},
        {"p12": 1, "p13": 9, "p14": 7},
        weights=(0.5, 0.5),
    )
    multiplier_sets = multiplier_sets_for_population(population, scenarios)
    tie_policy = rank_tie_policy()
    expected = evaluate_synthetic_cohort(
        population,
        multiplier_sets,
        tie_policy,
        target_rank=2,
    )
    path = tmp_path / "cohort.json"
    _write(
        path,
        {
            "population": population.model_dump(mode="json"),
            "multiplier_sets": [item.model_dump(mode="json") for item in multiplier_sets],
            "tie_policy": tie_policy.model_dump(mode="json"),
            "target_rank": 2,
        },
    )

    result = runner.invoke(rank_app, ["cohort", "--input", str(path)])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["result_hash"] == expected.result_hash


def test_invalid_input_is_typed_nonzero_without_traceback(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"not":"a rank service request"}\n', encoding="utf-8")

    result = runner.invoke(rank_app, ["evaluate", "--input", str(path)])

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "RANK_INPUT_INVALID"
    assert "Traceback" not in result.stdout


def test_tampered_artifact_is_typed_failure(tmp_path: Path) -> None:
    artifact = seal_decision_artifact(service_request())
    path = persist_decision_artifact(artifact, artifact_root=tmp_path)
    path.write_bytes(path.read_bytes().replace(b'"confidence":"A"', b'"confidence":"B"', 1))

    result = runner.invoke(rank_app, ["validate", "--artifact", str(path)])

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"].startswith("RANK_")
    assert "Traceback" not in result.stdout
