"""Repository authority-manifest validation and negative mutation tests."""

from __future__ import annotations

import json
import runpy
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest


def _copy_validation_fixture(repository_root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repository_root / "AGENTS.md", destination / "AGENTS.md")
    for directory in ("specs", "docs/implementation", "tickets", "evidence"):
        source = repository_root / directory
        target = destination / directory
        if directory == "evidence":
            target = destination / "evidence"
            (target / "tickets/FND-001").mkdir(parents=True)
            shutil.copy2(
                source / "tickets/FND-001/baseline_manifest.json",
                target / "tickets/FND-001/baseline_manifest.json",
            )
        else:
            shutil.copytree(source, target)


def _validator(repository_root: Path) -> Callable[[Path], list[str]]:
    namespace = runpy.run_path(str(repository_root / "scripts" / "validate_repository.py"))
    return cast(Callable[[Path], list[str]], namespace["validate_repository"])


@pytest.mark.integration
def test_current_repository_manifests_are_valid(repository_root: Path) -> None:
    assert _validator(repository_root)(repository_root) == []


@pytest.mark.integration
def test_hash_duplicate_version_status_stale_and_paid_edition_failures(
    repository_root: Path, tmp_path: Path
) -> None:
    validate = _validator(repository_root)
    fixture = tmp_path / "fixture"
    _copy_validation_fixture(repository_root, fixture)
    assert validate(fixture) == []

    document_manifest_path = fixture / "specs/manifests/document_manifest.json"
    original_manifest = document_manifest_path.read_text(encoding="utf-8")
    manifest: dict[str, Any] = json.loads(original_manifest)
    manifest["documents"][0]["version"] = "not-a-version"
    manifest["documents"][1]["status"] = ""
    manifest["documents"][2]["document_id"] = manifest["documents"][1]["document_id"]
    document_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    errors = validate(fixture)
    assert any("malformed version" in error for error in errors)
    assert any("malformed status" in error for error in errors)
    assert any("duplicate document_id" in error for error in errors)

    document_manifest_path.write_text(original_manifest, encoding="utf-8")
    approved = fixture / "specs/approved/DMFP-00_MASTER_ARCHITECTURE_AND_PRODUCT_DEFINITION.txt"
    approved.write_text(approved.read_text(encoding="utf-8") + "tamper", encoding="utf-8")
    assert any("hash mismatch" in error for error in validate(fixture))

    shutil.copy2(
        repository_root / "specs/approved/DMFP-00_MASTER_ARCHITECTURE_AND_PRODUCT_DEFINITION.txt",
        approved,
    )
    authority_path = fixture / "specs/manifests/authority_manifest.json"
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    authority["scopes"][0]["documents"].append("DMFP-99")
    authority_path.write_text(json.dumps(authority), encoding="utf-8")
    assert any("stale document reference" in error for error in validate(fixture))

    authority_path.write_text(
        (repository_root / "specs/manifests/authority_manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    zero_cost = (
        fixture
        / "specs/approved/DMFP-04_DATA_SOURCES_MARKETS_APIS_AND_LICENSING_ZERO_COST_v1.0.txt"
    )
    paid_name = fixture / "specs/approved/DMFP-04_PROVIDER_SELECTION_AND_PROCUREMENT.txt"
    zero_cost.rename(paid_name)
    assert any("sole zero-paid-subscription" in error for error in validate(fixture))


@pytest.mark.integration
def test_validator_reports_missing_package_files_without_traceback(
    repository_root: Path, tmp_path: Path
) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "validate_repository.py"))
    validate_package = cast(
        Callable[[Path, list[str]], None], namespace["_validate_package_contract"]
    )
    for relative in ("pyproject.toml", "uv.lock"):
        shutil.copy2(repository_root / relative, tmp_path / relative)
    errors: list[str] = []
    validate_package(tmp_path, errors)
    assert "required repository file missing: .python-version" in errors
    assert "required repository file missing: src/dmf_pulse/__init__.py" in errors

    runtime_directory = tmp_path / "specs/manifests"
    runtime_directory.mkdir(parents=True)
    runtime_path = runtime_directory / "runtime_lock_manifest.json"
    runtime = json.loads(
        (repository_root / "specs/manifests/runtime_lock_manifest.json").read_text("utf-8")
    )
    runtime["packages"][0]["version"] = "999.0.0"
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    graph_errors: list[str] = []
    validate_package(tmp_path, graph_errors)
    assert any("does not exactly match the uv.lock graph" in error for error in graph_errors)


@pytest.mark.integration
def test_authority_reference_arrays_reject_malformed_shapes(
    repository_root: Path, tmp_path: Path
) -> None:
    validate = _validator(repository_root)
    _copy_validation_fixture(repository_root, tmp_path)
    authority_path = tmp_path / "specs/manifests/authority_manifest.json"
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    authority["scopes"][0]["documents"] = "DMFP-20"
    authority["scopes"][0]["decisions"] = {"ADR-GOV-001": True}
    authority_path.write_text(json.dumps(authority), encoding="utf-8")
    errors = validate(tmp_path)
    assert any("documents must be an array of strings" in error for error in errors)
    assert any("decisions must be an array of strings" in error for error in errors)
