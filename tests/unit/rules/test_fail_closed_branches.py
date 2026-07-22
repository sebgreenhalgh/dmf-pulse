"""Focused fail-closed branch and mutation-probe coverage."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.rules import bps as bps_module
from dmf_pulse.rules import compiler as compiler_module
from dmf_pulse.rules import scoring as scoring_module
from dmf_pulse.rules import yaml_loader
from dmf_pulse.rules.canonical import self_hash
from dmf_pulse.rules.compiler import compile_ruleset, load_compiled_ruleset
from dmf_pulse.rules.errors import RulesIntegrityError, RulesValidationError
from dmf_pulse.rules.models import CompiledRuleset, FixtureScenario, RulesetStatus, SeasonManifest
from dmf_pulse.rules.scoring import score_fixture


@pytest.fixture
def source_copy(repository_root: Path, tmp_path: Path) -> Path:
    destination = tmp_path / "source"
    shutil.copytree(repository_root / "fixtures/rules/RUL-002/synthetic_complete", destination)
    return destination


@pytest.mark.unit
@pytest.mark.parametrize(
    ("filename", "old", "new", "code"),
    [
        ("positions.yaml", "  FWD:", "  XXX:", "RULESET_POSITION_INVALID"),
        ("scoring.yaml", "FWD: 4", 'FWD: "4"', "RULESET_GOAL_POINTS_INVALID"),
        ("bonus.yaml", "{1: 3, 2: 2, 3: 1}", "{1: 2, 2: 2, 3: 1}", "RULESET_BONUS_RANK_INVALID"),
        (
            "assists.yaml",
            '["DEFINITE_ASSIST", "DEFINITE_NO_ASSIST", "AMBIGUOUS_ASSIST"]',
            '["DEFINITE_ASSIST", "DEFINITE_NO_ASSIST"]',
            "RULESET_ASSIST_STATE_INVALID",
        ),
        ("scoring.yaml", "appearance:\n", "appearance: []\nunused:\n", "RULESET_SCHEMA_INVALID"),
    ],
)
def test_schema_mutants_are_killed(
    source_copy: Path, filename: str, old: str, new: str, code: str
) -> None:
    path = source_copy / filename
    path.write_text(path.read_text("utf-8").replace(old, new, 1), encoding="utf-8")
    with pytest.raises(RulesValidationError) as caught:
        compile_ruleset(source_copy)
    assert caught.value.code == code


@pytest.mark.unit
def test_manifest_required_order_and_unknown_status_mutants(source_copy: Path) -> None:
    manifest = source_copy / "season_manifest.yaml"
    manifest.write_text(
        manifest.read_text("utf-8").replace('  - "positions.yaml"\n', "", 1), encoding="utf-8"
    )
    with pytest.raises(RulesValidationError) as required:
        compile_ruleset(source_copy)
    assert required.value.code == "RULESET_REQUIRED_FILES"

    # Restore and insert a correctly shaped unknown under a non-draft status.
    source_copy.joinpath("season_manifest.yaml").write_text(
        (
            Path(__file__).parents[3]
            / "fixtures/rules/RUL-002/synthetic_complete/season_manifest.yaml"
        ).read_text("utf-8"),
        encoding="utf-8",
    )
    source_copy.joinpath("prices.yaml").write_text(
        'verification_status: "UNKNOWN"\nvalue: null\nsource_refs: []\n', encoding="utf-8"
    )
    with pytest.raises(RulesValidationError) as unknown:
        compile_ruleset(source_copy)
    assert unknown.value.code == "RULESET_UNKNOWN_STATUS"


@pytest.mark.unit
def test_target_requires_explicit_blocking_families(repository_root: Path, tmp_path: Path) -> None:
    source = tmp_path / "target"
    shutil.copytree(repository_root / "fixtures/rules/RUL-002/target_2026_27_partial", source)
    claims = source / "target_2026_27_claims.yaml"
    claims.write_text(
        claims.read_text("utf-8").replace("unknown_blocking_families:", "not_blockers:"),
        encoding="utf-8",
    )
    with pytest.raises(RulesValidationError) as caught:
        compile_ruleset(source)
    assert caught.value.code == "RULESET_TARGET_BLOCKERS_MISSING"


@pytest.mark.unit
def test_directory_artifact_and_yaml_size_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(RulesValidationError) as missing:
        compiler_module._safe_directory(tmp_path / "missing")
    assert missing.value.code == "RULESET_DIRECTORY_UNAVAILABLE"
    file_path = tmp_path / "file"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(RulesValidationError) as file_error:
        compiler_module._safe_directory(file_path)
    assert file_error.value.code == "RULESET_DIRECTORY_REQUIRED"

    huge_json = tmp_path / "huge.json"
    huge_json.write_bytes(b" " * (10 * 1024 * 1024 + 1))
    with pytest.raises(RulesIntegrityError) as artifact:
        load_compiled_ruleset(huge_json)
    assert artifact.value.code == "RULESET_ARTIFACT_TOO_LARGE"

    yaml_path = tmp_path / "huge.yaml"
    monkeypatch.setattr(Path, "read_bytes", lambda _self: b"x" * (1024 * 1024 + 1))
    with pytest.raises(RulesValidationError) as yaml_error:
        yaml_loader.load_rules_yaml(yaml_path)
    assert yaml_error.value.code == "RULESET_FILE_TOO_LARGE"


@pytest.mark.unit
def test_yaml_tree_and_mapping_guards(tmp_path: Path) -> None:
    with pytest.raises(RulesValidationError) as unavailable:
        yaml_loader.load_rules_yaml(tmp_path / "missing.yaml")
    assert unavailable.value.code == "RULESET_FILE_UNAVAILABLE"
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("[one, two]\n", encoding="utf-8")
    with pytest.raises(RulesValidationError) as non_mapping:
        yaml_loader.load_rules_yaml(scalar)
    assert non_mapping.value.code == "RULESET_YAML_MAPPING"
    merge = tmp_path / "merge.yaml"
    merge.write_text('"<<": {value: 1}\n', encoding="utf-8")
    with pytest.raises(RulesValidationError) as merge_error:
        yaml_loader.load_rules_yaml(merge)
    assert merge_error.value.code == "RULESET_YAML_INVALID"
    for value, code in [
        (1.2, "RULESET_YAML_FLOAT"),
        (dt.date(2026, 7, 22), "RULESET_YAML_TIMESTAMP"),
        ({1: "x"}, "RULESET_YAML_KEY"),
        (object(), "RULESET_YAML_SCALAR"),
    ]:
        with pytest.raises(RulesValidationError) as tree:
            yaml_loader._validate_scalar_tree(value)
        assert tree.value.code == code


@pytest.mark.unit
def test_model_manifest_and_pass_invariants(repository_root: Path) -> None:
    base = {
        "ruleset_id": "test-rules",
        "ruleset_version": "1.0.0",
        "schema_version": "1.0",
        "season_code": "2099/2100",
        "status": "REFERENCE_ONLY",
        "production_eligible": False,
        "required_files": ["a"],
    }
    with pytest.raises(ValidationError):
        SeasonManifest.model_validate({**base, "production_eligible": True})
    with pytest.raises(ValidationError):
        SeasonManifest.model_validate({**base, "required_files": ["a", "a"]})
    with pytest.raises(ValidationError):
        SeasonManifest.model_validate({**base, "extension_files": ["x", "x"]})
    scenario = json.loads(
        (repository_root / "fixtures/rules/RUL-002/golden_fixture_001.json").read_text("utf-8")
    )
    bps = scenario["players"][0]["bps"]
    with pytest.raises(ValidationError):
        type(FixtureScenario.model_validate(scenario).players[0].bps).model_validate(
            {**bps, "pass_attempts": 1, "passes_completed": 2}
        )


@pytest.mark.unit
def test_bps_and_scoring_config_guards(repository_root: Path) -> None:
    for operation in (
        lambda: bps_module._mapping([], "test"),
        lambda: bps_module._sequence({}, "test"),
        lambda: bps_module._integer(True, "test"),
        lambda: scoring_module._mapping([], "test"),
        lambda: scoring_module._sequence({}, "test"),
        lambda: scoring_module._integer(True, "test"),
        lambda: scoring_module._boolean(1, "test"),
    ):
        with pytest.raises(RulesIntegrityError):
            operation()
    assert bps_module._appearance_bps({}, 0) == 0
    with pytest.raises(RulesIntegrityError):
        bps_module._appearance_bps({"appearance_bands": []}, 20)
    with pytest.raises(RulesIntegrityError):
        scoring_module._appearance(
            {
                "bands": [
                    {"min_inclusive": 1, "max_exclusive": None, "points": 1},
                    {"min_inclusive": 1, "max_exclusive": None, "points": 2},
                ]
            },
            20,
        )

    root = repository_root / "fixtures/rules/RUL-002"
    ruleset = compile_ruleset(root / "synthetic_complete")
    scenario = FixtureScenario.model_validate_json((root / "golden_fixture_001.json").read_bytes())
    value = ruleset.model_dump(mode="json")
    value["status"] = RulesetStatus.DRAFT_PRELAUNCH.value
    value["ruleset_hash"] = self_hash(value)
    with pytest.raises(RulesIntegrityError) as lifecycle_tamper:
        score_fixture(CompiledRuleset.model_validate(value), scenario)
    assert lifecycle_tamper.value.code == "RULESET_SOURCE_HASH_MISMATCH"

    scoring = value["rules"]["scoring"]
    scoring["defensive_contributions"]["by_position"]["DEF"]["event_types"] = ["UNKNOWN"]
    value["status"] = RulesetStatus.REFERENCE_ONLY.value
    value["ruleset_hash"] = self_hash(value)
    with pytest.raises(RulesIntegrityError) as event:
        score_fixture(CompiledRuleset.model_validate(value), scenario)
    assert event.value.code == "RULESET_ARTIFACT_SCHEMA"
