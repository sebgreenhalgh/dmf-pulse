"""Strict YAML, canonical compiler, diff, and integrity tests."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from dmf_pulse.rules.canonical import normalize_json, pretty_rules_json, self_hash
from dmf_pulse.rules.compiler import (
    compile_ruleset,
    ensure_compiled_ruleset_integrity,
    load_compiled_ruleset,
    validate_ruleset_directory,
    write_compiled_ruleset,
)
from dmf_pulse.rules.diff import diff_rulesets
from dmf_pulse.rules.errors import RulesIntegrityError, RulesValidationError
from dmf_pulse.rules.models import CompiledRuleset
from dmf_pulse.rules.yaml_loader import load_rules_yaml


@pytest.fixture
def rules_fixture(repository_root: Path) -> Path:
    return repository_root / "fixtures/rules/RUL-002"


@pytest.mark.unit
def test_synthetic_and_partial_target_validate_compile_and_diff(rules_fixture: Path) -> None:
    synthetic = validate_ruleset_directory(rules_fixture / "synthetic_complete")
    assert synthetic.valid and not synthetic.unknown_blockers
    target = validate_ruleset_directory(rules_fixture / "target_2026_27_partial")
    assert target.valid and not target.production_eligible
    assert "target:complete_scoring_table" in target.unknown_blockers
    difference = diff_rulesets(
        rules_fixture / "reference_2025_26", rules_fixture / "target_2026_27_partial"
    )
    assert difference.changes == tuple(sorted(difference.changes, key=lambda item: item.path))
    assert any(item.path == "$.status" for item in difference.changes)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("filename", "code"),
    [
        ("invalid_duplicate_key.yaml", "RULESET_YAML_INVALID"),
        ("invalid_alias.yaml", "RULESET_YAML_ALIAS"),
        ("invalid_custom_tag.yaml", "RULESET_YAML_TAG"),
    ],
)
def test_supplied_invalid_yaml_is_rejected(rules_fixture: Path, filename: str, code: str) -> None:
    with pytest.raises(RulesValidationError) as caught:
        load_rules_yaml(rules_fixture / filename)
    assert caught.value.code == code


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("value: 1.5\n", "RULESET_YAML_FLOAT"),
        ("value: 2026-07-22\n", "RULESET_YAML_TIMESTAMP"),
        ("value: yes\n", "RULESET_YAML_IMPLICIT_BOOLEAN"),
        ("4: value\n", "RULESET_YAML_INVALID"),
        ("? [a, b]\n: value\n", "RULESET_YAML_INVALID"),
    ],
)
def test_unsafe_yaml_scalar_and_key_forms_fail(tmp_path: Path, text: str, code: str) -> None:
    path = tmp_path / "unsafe.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RulesValidationError) as caught:
        load_rules_yaml(path)
    assert caught.value.code == code


@pytest.mark.unit
def test_compilation_is_semantic_and_canonical(rules_fixture: Path, tmp_path: Path) -> None:
    source = rules_fixture / "synthetic_complete"
    copied = tmp_path / "copied"
    shutil.copytree(source, copied)
    first = compile_ruleset(source)
    scoring = copied / "scoring.yaml"
    scoring.write_text(
        "# formatting-only comment\n" + scoring.read_text("utf-8").replace("\n", "\r\n"),
        encoding="utf-8",
    )
    second = compile_ruleset(copied)
    assert second.ruleset_hash == first.ruleset_hash
    assert second.source_hashes == first.source_hashes

    changed_text = scoring.read_text("utf-8").replace("save_points: 5", "save_points: 6")
    scoring.write_text(changed_text, encoding="utf-8")
    changed = compile_ruleset(copied)
    assert changed.ruleset_hash != first.ruleset_hash
    diff = diff_rulesets(first, changed)
    assert [item.path for item in diff.changes] == ["$.rules.scoring.penalties.save_points"]


@pytest.mark.unit
def test_compiled_write_load_collision_and_tamper(rules_fixture: Path, tmp_path: Path) -> None:
    compiled = compile_ruleset(rules_fixture / "synthetic_complete")
    output = tmp_path / "compiled.json"
    write_compiled_ruleset(compiled, output)
    write_compiled_ruleset(compiled, output)
    assert load_compiled_ruleset(output) == compiled

    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RulesIntegrityError) as collision:
        write_compiled_ruleset(compiled, output)
    assert collision.value.code == "RULESET_OUTPUT_COLLISION"
    with pytest.raises(RulesIntegrityError) as invalid:
        load_compiled_ruleset(output)
    assert invalid.value.code == "RULESET_ARTIFACT_INVALID"

    value = compiled.model_dump(mode="json")
    value["ruleset_hash"] = "0" * 64
    output.write_text(pretty_rules_json(value), encoding="utf-8")
    with pytest.raises(RulesIntegrityError) as mismatch:
        load_compiled_ruleset(output)
    assert mismatch.value.code == "RULESET_HASH_MISMATCH"

    value["ruleset_hash"] = self_hash(value)
    output.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    with pytest.raises(RulesIntegrityError) as canonical:
        load_compiled_ruleset(output)
    assert canonical.value.code == "RULESET_CANONICAL_MISMATCH"


@pytest.mark.unit
def test_directory_rejects_missing_unknown_and_unsupported_extensions(
    rules_fixture: Path, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    shutil.copytree(rules_fixture / "synthetic_complete", source)
    (source / "assists.yaml").unlink()
    with pytest.raises(RulesValidationError) as missing:
        compile_ruleset(source)
    assert missing.value.code == "RULESET_FILE_MISSING"
    shutil.copy2(rules_fixture / "synthetic_complete/assists.yaml", source / "assists.yaml")
    (source / "extra.yaml").write_text("value: 1\n", encoding="utf-8")
    with pytest.raises(RulesValidationError) as unknown:
        compile_ruleset(source)
    assert unknown.value.code == "RULESET_FILE_UNKNOWN"
    (source / "extra.yaml").unlink()
    manifest = source / "season_manifest.yaml"
    manifest.write_text(
        manifest.read_text("utf-8") + 'extension_files: ["unsupported.yaml"]\n', encoding="utf-8"
    )
    with pytest.raises(RulesValidationError) as extension:
        compile_ruleset(source)
    assert extension.value.code == "RULESET_EXTENSION_UNSUPPORTED"


@pytest.mark.unit
def test_source_authored_active_status_is_prohibited(rules_fixture: Path, tmp_path: Path) -> None:
    source = tmp_path / "active-source"
    shutil.copytree(rules_fixture / "synthetic_complete", source)
    manifest = source / "season_manifest.yaml"
    manifest.write_text(
        manifest.read_text("utf-8")
        .replace('status: "REFERENCE_ONLY"', 'status: "ACTIVE"')
        .replace("production_eligible: false", "production_eligible: true"),
        encoding="utf-8",
    )
    with pytest.raises(RulesValidationError) as active:
        compile_ruleset(source)
    assert active.value.code == "RULESET_SOURCE_ACTIVE_PROHIBITED"


def _mutated_compiled(compiled: CompiledRuleset, mutation) -> CompiledRuleset:
    value = compiled.model_dump(mode="json")
    mutation(value)
    value["ruleset_hash"] = self_hash(value)
    return CompiledRuleset.model_validate(value)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda value: value["source_hashes"].update({"unsupported.yaml": "0" * 64}),
            "RULESET_ARTIFACT_SCHEMA",
        ),
        (
            lambda value: value["source_hashes"].pop("assists.yaml"),
            "RULESET_SOURCE_HASH_MISMATCH",
        ),
        (lambda value: value["rules"].pop("assists"), "RULESET_ARTIFACT_SCHEMA"),
        (lambda value: value["rules"].update(assists=[]), "RULESET_ARTIFACT_SCHEMA"),
        (
            lambda value: value.update(source_bundle_sha256="0" * 64),
            "RULESET_SOURCE_HASH_MISMATCH",
        ),
        (lambda value: value.update(season_code="2100/2101"), "RULESET_SOURCE_HASH_MISMATCH"),
    ],
)
def test_in_memory_artifact_metadata_mutants_fail_integrity(
    rules_fixture: Path, mutation, code: str
) -> None:
    compiled = compile_ruleset(rules_fixture / "synthetic_complete")
    changed = _mutated_compiled(compiled, mutation)
    with pytest.raises(RulesIntegrityError) as caught:
        ensure_compiled_ruleset_integrity(changed)
    assert caught.value.code == code


@pytest.mark.unit
def test_canonical_keys_reject_non_string_and_nfc_collisions(rules_fixture: Path) -> None:
    with pytest.raises(ValueError, match="must be strings"):
        normalize_json({1: "value"})
    with pytest.raises(ValueError, match="collide"):
        normalize_json({"\u00e9": 1, "e\u0301": 2})

    compiled = compile_ruleset(rules_fixture / "synthetic_complete")
    value = compiled.model_dump(mode="json")
    value["rules"]["\u00e9"] = {}
    value["rules"]["e\u0301"] = {}
    colliding = CompiledRuleset.model_validate(value)
    with pytest.raises(RulesIntegrityError) as caught:
        ensure_compiled_ruleset_integrity(colliding)
    assert caught.value.code == "RULESET_ARTIFACT_SCHEMA"


@pytest.mark.unit
def test_atomic_write_failure_cleans_temporary_file(
    rules_fixture: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compiled = compile_ruleset(rules_fixture / "synthetic_complete")

    def fail_link(_source: object, _destination: object) -> None:
        raise OSError("constructed publication failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(RulesIntegrityError) as caught:
        write_compiled_ruleset(compiled, tmp_path / "compiled.json")
    assert caught.value.code == "RULESET_OUTPUT_UNAVAILABLE"
    assert list(tmp_path.glob(".rules-*")) == []


@pytest.mark.unit
def test_rules_directory_rejects_symbolic_linked_yaml(
    rules_fixture: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linked = (rules_fixture / "synthetic_complete/assists.yaml").resolve()
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda candidate: candidate.resolve() == linked or original(candidate),
    )
    with pytest.raises(RulesValidationError) as caught:
        compile_ruleset(rules_fixture / "synthetic_complete")
    assert caught.value.code == "RULESET_FILE_SYMLINK"
