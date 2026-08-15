from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import FixtureProjectionResult, ProjectionMode
from dmf_pulse.fpl_points.service import FplPointsService
from tests.support.factories import make_request, mc_policy, reference_engine

ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str) -> ModuleType:
    path = ROOT / "scripts/assurance" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result() -> FixtureProjectionResult:
    return FplPointsService(reference_engine(), mc_policy()).project(
        make_request(scenario_count=8, root_seed=1919)
    )


def _rehash(result: FixtureProjectionResult) -> FixtureProjectionResult:
    unhashed = result.model_copy(update={"result_sha256": None})
    return unhashed.model_copy(update={"result_sha256": semantic_sha256(unhashed)})


def test_artifact_assurance_recomputes_rules_and_detects_bps_bonus_tampering() -> None:
    module = _load_script("check_stage9_artifact")
    result = _result()
    assert module.validate_projection(result, reference_engine()) == []
    scenario = result.scenarios[0]
    player_id = next(iter(scenario.players))
    original = scenario.players[player_id]
    tampered_score = original.model_copy(
        update={"bonus": original.bonus + 1, "total": original.total + 1}
    )
    tampered_players = dict(scenario.players)
    tampered_players[player_id] = tampered_score
    tampered_scenario = scenario.model_copy(update={"players": tampered_players})
    tampered_scenarios = (tampered_scenario, *result.scenarios[1:])
    matrix = result.joint_matrix
    assert matrix is not None
    row = list(matrix.points[0])
    row[matrix.player_ids.index(player_id)] += 1
    tampered_matrix = matrix.model_copy(update={"points": (tuple(row), *matrix.points[1:])})
    tampered = result.model_copy(
        update={
            "scenarios": tampered_scenarios,
            "joint_matrix": tampered_matrix,
            "result_sha256": None,
        }
    )
    tampered = tampered.model_copy(update={"result_sha256": semantic_sha256(tampered)})
    errors = module.validate_projection(tampered, reference_engine())
    assert any(error.startswith("BPS_OR_SCORE_TAMPERED") for error in errors)


def test_artifact_assurance_rejects_matrix_mapping_ruleset_and_upstream_tampering() -> None:
    module = _load_script("check_stage9_artifact")
    result = _result()
    matrix = result.joint_matrix
    assert matrix is not None

    mapping_tampered = result.model_copy(
        update={
            "joint_matrix": matrix.model_copy(update={"player_ids": matrix.player_ids[:-1]}),
            "result_sha256": None,
        }
    )
    assert any(
        error.startswith("JOINT_ROW_MISMATCH")
        for error in module.validate_projection(mapping_tampered, reference_engine())
    )

    rules_tampered = result.model_copy(
        update={
            "ruleset": result.ruleset.model_copy(update={"ruleset_hash": "9" * 64}),
            "result_sha256": None,
        }
    )
    assert "RULESET_IDENTITY_MISMATCH" in module.validate_projection(
        rules_tampered, reference_engine()
    )

    upstream_values = {
        name: getattr(result.upstream_score_distribution, name)
        for name in type(result.upstream_score_distribution).model_fields
    }
    upstream_values["result_sha256"] = "9" * 64
    upstream = type(result.upstream_score_distribution).model_construct(**upstream_values)
    result_values = {name: getattr(result, name) for name in type(result).model_fields}
    result_values.update(
        upstream_score_distribution=upstream,
        upstream_stage8_sha256="9" * 64,
        result_sha256=None,
    )
    upstream_tampered = type(result).model_construct(**result_values)
    errors = module.validate_projection(upstream_tampered, reference_engine())
    assert "UPSTREAM_STAGE8_IDENTITY_INVALID" in errors


def test_successful_artifact_assurance_requires_rules_recomputation() -> None:
    module = _load_script("check_stage9_artifact")
    assert "RULESET_RECOMPUTE_REQUIRED" in module.validate_projection(_result())


def test_artifact_assurance_regenerates_primitives_and_every_derivation() -> None:
    module = _load_script("check_stage9_artifact")
    result = FplPointsService(reference_engine(), mc_policy()).project(
        make_request(scenario_count=49, root_seed=1919)
    )
    assert module.validate_projection(result, reference_engine()) == []

    scenario = result.scenarios[0]
    event_player = scenario.event_scenario.players[0].model_copy(update={"minutes": 1})
    event = scenario.event_scenario.model_copy(
        update={"players": (event_player, *scenario.event_scenario.players[1:])}
    )
    primitive_tamper = _rehash(
        result.model_copy(
            update={
                "scenarios": (
                    scenario.model_copy(update={"event_scenario": event}),
                    *result.scenarios[1:],
                )
            }
        )
    )
    assert "SCENARIO_REGENERATION_MISMATCH" in module.validate_projection(
        primitive_tamper, reference_engine()
    )

    goal_scenario = next(scenario for scenario in result.scenarios if scenario.event_scenario.goals)
    moved_goal = goal_scenario.event_scenario.goals[0].model_copy(update={"minute": 129.0})
    moved_event = goal_scenario.event_scenario.model_copy(
        update={"goals": (moved_goal, *goal_scenario.event_scenario.goals[1:])}
    )
    goal_tamper = _rehash(
        result.model_copy(
            update={
                "scenarios": tuple(
                    goal_scenario.model_copy(update={"event_scenario": moved_event})
                    if scenario.scenario_id == goal_scenario.scenario_id
                    else scenario
                    for scenario in result.scenarios
                )
            }
        )
    )
    assert "SCENARIO_REGENERATION_MISMATCH" in module.validate_projection(
        goal_tamper, reference_engine()
    )

    changed_request = result.simulation_request.model_copy(
        update={
            "allocation_config": result.simulation_request.allocation_config.model_copy(
                update={"goal_time_lower": 2.0}
            )
        }
    )
    request_tamper = _rehash(
        result.model_copy(
            update={
                "simulation_request": changed_request,
                "simulation_request_sha256": semantic_sha256(changed_request),
            }
        )
    )
    assert "SCENARIO_REGENERATION_MISMATCH" in module.validate_projection(
        request_tamper, reference_engine()
    )

    player_id = next(iter(result.player_summaries))
    changed_summaries = dict(result.player_summaries)
    changed_summaries[player_id] = changed_summaries[player_id].model_copy(
        update={"expected_points": changed_summaries[player_id].expected_points + 1.0}
    )
    summary_tamper = _rehash(result.model_copy(update={"player_summaries": changed_summaries}))
    assert "SUMMARY_RECOMPUTE_MISMATCH" in module.validate_projection(
        summary_tamper, reference_engine()
    )

    matrix = result.joint_matrix
    assert matrix is not None
    left, right = matrix.player_ids[:2]
    dependence = {key: dict(row) for key, row in matrix.dependence.items()}
    dependence[left][right] = dependence[left][right].model_copy(update={"covariance": 0.123})
    dependence_tamper = _rehash(
        result.model_copy(
            update={"joint_matrix": matrix.model_copy(update={"dependence": dependence})}
        )
    )
    assert "JOINT_MATRIX_RECOMPUTE_MISMATCH" in module.validate_projection(
        dependence_tamper, reference_engine()
    )

    diagnostics = result.monte_carlo
    assert diagnostics is not None
    diagnostics_tamper = _rehash(
        result.model_copy(
            update={
                "monte_carlo": diagnostics.model_copy(
                    update={"max_scenario_weight": diagnostics.max_scenario_weight / 2}
                )
            }
        )
    )
    assert "MONTE_CARLO_RECOMPUTE_MISMATCH" in module.validate_projection(
        diagnostics_tamper, reference_engine()
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload["scenarios"][0]["players"][
                next(iter(payload["scenarios"][0]["players"]))
            ].__setitem__("total", 1.5),
            "valid integer",
        ),
        (
            lambda payload: payload["scenarios"][0]["players"][
                next(iter(payload["scenarios"][0]["players"]))
            ].__setitem__("total", 999),
            "component sum",
        ),
        (
            lambda payload: payload["scenarios"][0]["event_scenario"].__setitem__("home_goals", 99),
            "reconcile",
        ),
        (
            lambda payload: payload["scenarios"][0]["stage7_player_projection_sha256s"].pop(
                next(iter(payload["scenarios"][0]["stage7_player_projection_sha256s"]))
            ),
            "participant universes",
        ),
        (
            lambda payload: payload["scenarios"][0]["event_scenario"].__setitem__(
                "ruleset_hash", "9" * 64
            ),
            "ruleset identity",
        ),
        (lambda payload: payload.pop("upstream_score_distribution"), "Field required"),
    ],
)
def test_strict_model_rejects_semantic_mutations(mutator, message: str) -> None:
    payload = _result().model_dump(mode="python")
    mutator(payload)
    with pytest.raises(ValidationError, match=message):
        FixtureProjectionResult.model_validate(payload)


def test_inactive_ruleset_cannot_be_relabelled_as_successful_production() -> None:
    payload = _result().model_dump(mode="python")
    payload["projection_mode"] = ProjectionMode.PRODUCTION
    with pytest.raises(ValidationError, match="active approved ruleset"):
        FixtureProjectionResult.model_validate(payload)


def _materialize_scope_root(root: Path, module: ModuleType) -> None:
    for relative in module.REQUIRED_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith(".py") and not relative.endswith("/__init__.py"):
            path.write_text("def substantive():\n    return 1\n", encoding="utf-8")
        else:
            path.write_text("substantive\n", encoding="utf-8")
    changed = [
        relative for relative in module.REQUIRED_FILES if not relative.endswith("CHANGED_FILES.txt")
    ]
    (root / "CHANGED_FILES.txt").write_text("\n".join(changed) + "\n", encoding="utf-8")


def _prepare_scope_repository(root: Path, module: ModuleType) -> str:
    _materialize_scope_root(root, module)

    def git(*args: str) -> str:
        result = subprocess.run(
            ("git", *args), cwd=root, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    git("init")
    git("config", "user.email", "pts009@example.invalid")
    git("config", "user.name", "PTS-009 test")
    git("add", ".")
    git("commit", "-m", "baseline")
    return git("rev-parse", "HEAD")


def _write_scope_declaration(root: Path, entries: tuple[str, ...]) -> Path:
    declaration = root / "evidence/tickets/PTS-009-STATIC-FIX/round2/CHANGED_FILES.txt"
    declaration.parent.mkdir(parents=True, exist_ok=True)
    declaration.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return declaration


def test_scope_assurance_rejects_stage10_module_and_missing_resource(tmp_path: Path) -> None:
    module = _load_script("check_stage9_scope")
    parent = _prepare_scope_repository(tmp_path, module)
    forbidden = "src/dmf_pulse/optimisation/stage10.py"
    path = tmp_path / forbidden
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def optimise():\n    return 1\n", encoding="utf-8")
    (tmp_path / "PLANS.md").write_text("changed\n", encoding="utf-8")
    declaration = _write_scope_declaration(
        tmp_path,
        (
            "PLANS.md",
            "evidence/tickets/PTS-009-STATIC-FIX/round2/CHANGED_FILES.txt",
        ),
    )
    (tmp_path / "config/models/fpl_points_simulation.yaml").unlink()
    errors = module.validate_scope(
        tmp_path, parent_revision=parent, declaration=declaration.relative_to(tmp_path)
    )
    assert f"STAGE10_PLUS_SCOPE_VIOLATION:{forbidden}" in errors
    assert f"DECLARATION_MISSING_ACTUAL:{forbidden}" in errors
    assert "MISSING_REQUIRED_FILE:config/models/fpl_points_simulation.yaml" in errors


def test_scope_assurance_rejects_manager_state_module(tmp_path: Path) -> None:
    module = _load_script("check_stage9_scope")
    parent = _prepare_scope_repository(tmp_path, module)
    forbidden = "src/dmf_pulse/manager_state/autosubs.py"
    path = tmp_path / forbidden
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def autosub():\n    return 1\n", encoding="utf-8")
    declaration = _write_scope_declaration(
        tmp_path, ("evidence/tickets/PTS-009-STATIC-FIX/round2/CHANGED_FILES.txt",)
    )
    errors = module.validate_scope(
        tmp_path, parent_revision=parent, declaration=declaration.relative_to(tmp_path)
    )
    assert f"STAGE10_PLUS_SCOPE_VIOLATION:{forbidden}" in errors


def test_scope_assurance_rejects_extra_declared_real_diff_file(tmp_path: Path) -> None:
    module = _load_script("check_stage9_scope")
    parent = _prepare_scope_repository(tmp_path, module)
    declaration = _write_scope_declaration(
        tmp_path,
        (
            "evidence/tickets/PTS-009-STATIC-FIX/round2/CHANGED_FILES.txt",
            "not-really-changed.txt",
        ),
    )
    errors = module.validate_scope(
        tmp_path, parent_revision=parent, declaration=declaration.relative_to(tmp_path)
    )
    assert "DECLARATION_EXTRA:not-really-changed.txt" in errors


def _coverage_payload(module: ModuleType) -> dict[str, object]:
    files = {}
    for relative in module.REQUIRED_MODULES:
        files[relative] = {
            "summary": {
                "num_statements": 100,
                "covered_lines": 95,
                "missing_lines": 5,
                "percent_statements_covered": 95.0,
                "percent_covered": 100.0 * 113 / 120,
                "num_branches": 20,
                "covered_branches": 18,
                "missing_branches": 2,
                "percent_branches_covered": 90.0,
            }
        }
    count = len(module.REQUIRED_MODULES)
    return {
        "files": files,
        "totals": {
            "num_statements": 100 * count,
            "covered_lines": 95 * count,
            "missing_lines": 5 * count,
            "percent_statements_covered": 95.0,
            "num_branches": 20 * count,
            "covered_branches": 18 * count,
            "missing_branches": 2 * count,
            "percent_branches_covered": 90.0,
            "percent_covered": 100.0 * 113 / 120,
        },
    }


def test_coverage_assurance_fails_closed_on_zero_missing_malformed_and_branch_data() -> None:
    module = _load_script("check_stage9_coverage")
    good = _coverage_payload(module)
    assert module.validate_coverage(good, minimum_line_percent=85, minimum_branch_percent=70) == []
    zero = json.loads(json.dumps(good))
    first = module.REQUIRED_MODULES[0]
    zero["files"][first]["summary"]["num_statements"] = 0
    assert f"COVERAGE_ZERO_STATEMENTS:{first}" in module.validate_coverage(
        zero, minimum_line_percent=85, minimum_branch_percent=70
    )
    missing = json.loads(json.dumps(good))
    del missing["files"][module.REQUIRED_MODULES[1]]
    assert any(
        "COVERAGE_MODULE_MISSING" in item
        for item in module.validate_coverage(
            missing, minimum_line_percent=85, minimum_branch_percent=70
        )
    )
    malformed = {"files": {}, "totals": {"num_statements": "not-a-number"}}
    assert "COVERAGE_ZERO_STATEMENTS:TOTALS" in module.validate_coverage(
        malformed, minimum_line_percent=85, minimum_branch_percent=70
    )
    branchless = json.loads(json.dumps(good))
    del branchless["files"][first]["summary"]["num_branches"]
    assert f"COVERAGE_BRANCH_DATA_MISSING:{first}" in module.validate_coverage(
        branchless, minimum_line_percent=85, minimum_branch_percent=70
    )
    inconsistent = json.loads(json.dumps(good))
    inconsistent["files"][first]["summary"]["missing_lines"] = 99
    inconsistent["files"][first]["summary"]["percent_covered"] = 100.0
    errors = module.validate_coverage(
        inconsistent, minimum_line_percent=85, minimum_branch_percent=70
    )
    assert f"COVERAGE_LINE_COUNTS_INCONSISTENT:{first}" in errors
    assert f"COVERAGE_COMBINED_PERCENT_INCONSISTENT:{first}" in errors
