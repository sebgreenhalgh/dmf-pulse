from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from dmf_pulse.fpl_points.artifacts import (
    canonical_json_bytes,
    load_verified_model,
    semantic_sha256,
    sha256_bytes,
)
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


@pytest.mark.parametrize("tamper", ("summary", "dependence", "monte_carlo"))
def test_artifact_assurance_recomputes_all_derived_outputs_after_hash_repair(tamper: str) -> None:
    module = _load_script("check_stage9_artifact")
    result = _result()
    if tamper == "summary":
        player_id = next(iter(result.player_summaries))
        summary = result.player_summaries[player_id].model_copy(
            update={"expected_points": result.player_summaries[player_id].expected_points + 100.0}
        )
        tampered = result.model_copy(
            update={
                "player_summaries": {**result.player_summaries, player_id: summary},
                "result_sha256": None,
            }
        )
        expected = "PLAYER_SUMMARIES_TAMPERED"
    elif tamper == "dependence":
        matrix = result.joint_matrix
        assert matrix is not None
        left = matrix.player_ids[0]
        right = matrix.player_ids[1]
        dependence = matrix.dependence[left][right].model_copy(
            update={"covariance": matrix.dependence[left][right].covariance + 1.0}
        )
        rows = {player: dict(values) for player, values in matrix.dependence.items()}
        rows[left][right] = dependence
        tampered_matrix = matrix.model_copy(update={"dependence": rows})
        tampered = result.model_copy(
            update={"joint_matrix": tampered_matrix, "result_sha256": None}
        )
        expected = "JOINT_MATRIX_TAMPERED"
    else:
        assert result.monte_carlo is not None
        diagnostics = result.monte_carlo.model_copy(
            update={"max_scenario_weight": result.monte_carlo.max_scenario_weight / 2}
        )
        tampered = result.model_copy(update={"monte_carlo": diagnostics, "result_sha256": None})
        expected = "MONTE_CARLO_DIAGNOSTICS_TAMPERED"
    tampered = tampered.model_copy(update={"result_sha256": semantic_sha256(tampered)})
    assert expected in module.validate_projection(tampered, reference_engine())


def test_artifact_assurance_accepts_valid_49_scenario_result() -> None:
    module = _load_script("check_stage9_artifact")
    result = FplPointsService(reference_engine(), mc_policy()).project(
        make_request(scenario_count=49, root_seed=4900)
    )
    assert module.validate_projection(result, reference_engine()) == []


def test_old_success_artifact_without_policy_requires_recomputation() -> None:
    module = _load_script("check_stage9_artifact")
    old = _result().model_copy(update={"monte_carlo_policy": None, "result_sha256": None})
    errors = module.validate_projection(old, reference_engine())
    assert "MONTE_CARLO_POLICY_RECOMPUTE_REQUIRED" in errors


def test_old_policyless_artifact_still_loads_for_independent_assurance(tmp_path: Path) -> None:
    module = _load_script("check_stage9_artifact")
    payload = _result().model_dump(mode="json")
    payload.pop("monte_carlo_policy")
    semantic_payload = dict(payload)
    semantic_payload["result_sha256"] = None
    payload["result_sha256"] = semantic_sha256(semantic_payload)
    data = canonical_json_bytes(payload)
    artifact = tmp_path / "legacy-result.json"
    artifact.write_bytes(data)
    artifact.with_suffix(".sha256").write_text(
        f"{sha256_bytes(data)}  {artifact.name}\n", encoding="ascii"
    )
    loaded = load_verified_model(artifact, FixtureProjectionResult)
    errors = module.validate_projection(loaded, reference_engine())
    assert "MONTE_CARLO_POLICY_RECOMPUTE_REQUIRED" in errors
    assert "ARTIFACT_EMBEDDED_HASH_MISMATCH" not in errors


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


def test_scope_assurance_rejects_stage10_module_and_missing_resource(tmp_path: Path) -> None:
    module = _load_script("check_stage9_scope")
    _materialize_scope_root(tmp_path, module)
    forbidden = "src/dmf_pulse/optimisation/stage10.py"
    path = tmp_path / forbidden
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def optimise():\n    return 1\n", encoding="utf-8")
    with (tmp_path / "CHANGED_FILES.txt").open("a", encoding="utf-8") as handle:
        handle.write(forbidden + "\n")
    (tmp_path / "config/models/fpl_points_simulation.yaml").unlink()
    errors = module.validate_scope(tmp_path)
    assert f"STAGE10_PLUS_SCOPE_VIOLATION:{forbidden}" in errors
    assert "MISSING_REQUIRED_FILE:config/models/fpl_points_simulation.yaml" in errors


def test_scope_assurance_rejects_manager_state_module(tmp_path: Path) -> None:
    module = _load_script("check_stage9_scope")
    _materialize_scope_root(tmp_path, module)
    forbidden = "src/dmf_pulse/manager_state/autosubs.py"
    path = tmp_path / forbidden
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def autosub():\n    return 1\n", encoding="utf-8")
    with (tmp_path / "CHANGED_FILES.txt").open("a", encoding="utf-8") as handle:
        handle.write(forbidden + "\n")
    errors = module.validate_scope(tmp_path)
    assert f"STAGE10_PLUS_SCOPE_VIOLATION:{forbidden}" in errors


def test_scope_assurance_uses_real_git_diff_when_declaration_omits_forbidden_path(
    tmp_path: Path,
) -> None:
    module = _load_script("check_stage9_scope")
    _materialize_scope_root(tmp_path, module)
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "scope-test@example.invalid"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "scope-test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "baseline"],
        check=True,
        capture_output=True,
    )
    parent = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    forbidden = tmp_path / "src/dmf_pulse/optimisation/stage10.py"
    forbidden.parent.mkdir(parents=True, exist_ok=True)
    forbidden.write_text("def optimise():\n    return 1\n", encoding="utf-8")
    errors = module.validate_scope(tmp_path, parent_revision=parent)
    relative = "src/dmf_pulse/optimisation/stage10.py"
    assert f"SCOPE_DECLARATION_MISSING:{relative}" in errors
    assert f"STAGE10_PLUS_SCOPE_VIOLATION:{relative}" in errors


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
