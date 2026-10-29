"""Remove only the explicitly approved ACCEL-002 additions from legacy freezes."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from textwrap import dedent

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.models import RightsProfile

OWNED_PROFILE_ID = "accel002_synthetic_player_lab_v1"
OWNED_PROFILE_SHA256 = "3c3661abeb6f7887f97979368174b609c7931ebe0ba1052aebd6f5eb01a102eb"
LEGACY_PROFILE_IDS = (
    "synthetic_test_v1",
    "fpl_official_private_manual_v1",
    "fpl_official_private_operator_initiated_read_v1",
)
OWNED_CAPABILITIES = {
    "automated_access": "DENY",
    "backup": "ALLOW",
    "cache": "DENY",
    "derived_storage": "ALLOW",
    "manual_import": "ALLOW",
    "model_training": "DENY",
    "private_internal_use": "ALLOW",
    "public_display": "DENY",
    "raw_storage": "ALLOW",
    "redistribution": "DENY",
    "transient_processing": "ALLOW",
}


def assert_owned_synthetic_profile(profile: RightsProfile) -> None:
    """The fourth loaded profile is exact owned data authority, never transport."""
    payload = profile.model_dump(mode="json", exclude={"capabilities"})
    payload["capabilities"] = {
        key.value: value.value for key, value in profile.capabilities.items()
    }
    assert canonical_sha256(payload) == OWNED_PROFILE_SHA256
    assert profile.rights_profile_id == OWNED_PROFILE_ID
    assert profile.provider_key == "synthetic_fpl"
    assert payload["capabilities"] == OWNED_CAPABILITIES


def original_fpl_registry_bytes(path: Path) -> bytes:
    """Authenticate the one owned addition, then reconstruct the original file."""
    value = json.loads(path.read_text(encoding="utf-8"))
    assert set(value) == {"profiles", "schema_version"}
    assert value["schema_version"] == "1.0.0"
    assert tuple(profile["rights_profile_id"] for profile in value["profiles"]) == (
        *LEGACY_PROFILE_IDS,
        OWNED_PROFILE_ID,
    )
    owned = value["profiles"][-1]
    assert canonical_sha256(owned) == OWNED_PROFILE_SHA256
    assert owned["rights_profile_id"] == OWNED_PROFILE_ID
    assert owned["provider_key"] == "synthetic_fpl"
    assert owned["account_scope"] == (
        "ACCEL-002 manifest-verified repository-owned synthetic player-lab assets only"
    )
    assert owned["approved_purpose"] == (
        "offline synthetic adapter, prospective custody simulation and evaluation acceptance only"
    )
    assert owned["capabilities"] == OWNED_CAPABILITIES
    assert owned["human_approval_id"] == "DMF-PULSE-ACCEL-002#synthetic-acceptance"
    # Remove precisely the authenticated owned profile; every original field is
    # retained for the caller's unchanged parent-byte or legacy digest assertion.
    original = {
        **value,
        "profiles": [
            profile
            for profile in value["profiles"]
            if profile["rights_profile_id"] != OWNED_PROFILE_ID
        ],
    }
    assert len(original["profiles"]) == len(LEGACY_PROFILE_IDS)
    return (json.dumps(original, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _same_ast(actual: ast.AST, expected: ast.AST) -> None:
    assert ast.dump(actual) == ast.dump(expected)


def _one_class(module: ast.Module, name: str) -> ast.ClassDef:
    matches = [node for node in module.body if isinstance(node, ast.ClassDef) and node.name == name]
    assert len(matches) == 1
    return matches[0]


def _remove_once(source: str, addition: str) -> str:
    assert source.count(addition) == 1
    return source.replace(addition, "", 1)


def without_accel002_presentation(source: str, relative: str) -> str:
    """Assert exact added syntax and scope; preserve all other source characters."""
    assert relative in {
        "src/dmf_pulse/private_v1/service.py",
        "src/dmf_pulse/private_v1/rolling.py",
    }
    rolling = relative.endswith("/rolling.py")
    result_name = "PrivateV1RollingRunResult" if rolling else "PrivateV1RunResult"
    service_name = (
        "PrivateV1RollingRecommendationService" if rolling else "PrivateV1RecommendationService"
    )
    fixture_value = "presentation_fixtures" if rolling else "fixture_results"
    module = ast.parse(source)
    result = _one_class(module, result_name)
    field = result.body[-1]
    _same_ast(
        field,
        ast.parse("fixture_projections: tuple[FixtureProjectionResult, ...] = ()").body[0],
    )
    assert (
        sum(
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "fixture_projections"
            for node in ast.walk(module)
        )
        == 1
    )
    service = _one_class(module, service_name)
    runs = [
        node for node in service.body if isinstance(node, ast.FunctionDef) and node.name == "run"
    ]
    assert len(runs) == 1
    run = runs[0]
    returns = [
        node
        for node in ast.walk(run)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == result_name
    ]
    assert len(returns) == 1
    returned = returns[0].value
    assert isinstance(returned, ast.Call)
    _same_ast(
        returned.keywords[-1],
        ast.parse(f"result(fixture_projections={fixture_value})").body[0].value.keywords[0],
    )
    assert (
        sum(
            isinstance(node, ast.keyword) and node.arg == "fixture_projections"
            for node in ast.walk(module)
        )
        == 1
    )
    source = _remove_once(
        source, "    fixture_projections: tuple[FixtureProjectionResult, ...] = ()\n"
    )
    return_indent = "                " if rolling else "            "
    source = _remove_once(source, f"{return_indent}fixture_projections={fixture_value},\n")
    if rolling:
        imports = [
            node
            for node in module.body
            if isinstance(node, ast.ImportFrom) and node.module == "dmf_pulse.fpl_points.models"
        ]
        assert len(imports) == 1
        _same_ast(
            imports[0],
            ast.parse(
                "from dmf_pulse.fpl_points.models import "
                "FixtureProjectionResult, GameweekProjectionResult, GameweekScenarioSet"
            ).body[0],
        )
        capture = (
            "        presentation_fixtures = tuple(\n"
            "            fixture\n"
            "            for gameweek in execution.horizon_gameweeks\n"
            "            for fixture in fixture_results_by_gameweek[gameweek]\n"
            "        )\n"
        )
        captures = [
            index
            for index, node in enumerate(run.body)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "presentation_fixtures"
                for target in node.targets
            )
        ]
        assert len(captures) == 1
        index = captures[0]
        _same_ast(run.body[index], ast.parse(dedent(capture)).body[0])
        _same_ast(
            run.body[index - 1], ast.parse('record("report_and_comparator", started)').body[0]
        )
        _same_ast(
            run.body[index + 1],
            ast.parse(
                "del (fixture_results_by_gameweek, stage7_contexts_by_gameweek, "
                "stage8_hashes_by_gameweek, binding_hashes_by_gameweek, fallback_player_ids)"
            ).body[0],
        )
        imported = (
            "from dmf_pulse.fpl_points.models import (\n"
            "    FixtureProjectionResult,\n"
            "    GameweekProjectionResult,\n"
            "    GameweekScenarioSet,\n"
            ")\n"
        )
        assert source.count(imported) == 1
        source = source.replace(
            imported,
            "from dmf_pulse.fpl_points.models import GameweekProjectionResult, GameweekScenarioSet\n",
            1,
        )
        source = _remove_once(source, capture)
        assert "presentation_fixtures" not in source
    assert "fixture_projections" not in source
    return source
