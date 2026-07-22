"""Deterministic current-manifest generation and drift detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmf_pulse.assurance.manifests import (
    RepositoryFile,
    RepositoryManifest,
    build_repository_manifest,
    validate_repository_manifest,
)


@pytest.mark.unit
def test_repository_manifest_is_sorted_deterministic_and_excludes_generated_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/z.py").write_text("z\n", encoding="utf-8")
    (tmp_path / "src/a.py").write_text("a\n", encoding="utf-8")
    evidence = tmp_path / "evidence/tickets/FND-001"
    evidence.mkdir(parents=True)
    (evidence / "baseline_manifest.json").write_text("{}\n", encoding="utf-8")
    (evidence / "commands.log").write_text("generated\n", encoding="utf-8")
    (tmp_path / ".coverage").write_bytes(b"sqlite\x00generated")
    (tmp_path / "coverage.xml").write_text("<generated/>\n", encoding="utf-8")
    first = build_repository_manifest(tmp_path)
    second = build_repository_manifest(tmp_path)
    assert first == second
    paths = [item.path for item in first.files]
    assert paths == sorted(paths)
    assert "evidence/tickets/FND-001/baseline_manifest.json" in paths
    assert "evidence/tickets/FND-001/commands.log" not in paths
    assert ".coverage" not in paths
    assert "coverage.xml" not in paths


@pytest.mark.unit
def test_repository_manifest_reports_missing_new_byte_and_hash_drift(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one\n", encoding="utf-8")
    (tmp_path / "two.txt").write_text("two\n", encoding="utf-8")
    expected = build_repository_manifest(tmp_path)
    (tmp_path / "one.txt").write_text("changed-size\n", encoding="utf-8")
    (tmp_path / "two.txt").write_text("six\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")
    errors = validate_repository_manifest(tmp_path, expected)
    assert any("unrecorded file: new.txt" in error for error in errors)
    assert any("byte mismatch: one.txt" in error for error in errors)
    assert any("hash mismatch: two.txt" in error for error in errors)

    (tmp_path / "two.txt").unlink()
    errors = validate_repository_manifest(tmp_path, expected)
    assert any("file missing: two.txt" in error for error in errors)


@pytest.mark.unit
@pytest.mark.parametrize("paths", [("z", "a"), ("same", "same")])
def test_repository_manifest_rejects_unsorted_or_duplicate_paths(paths: tuple[str, str]) -> None:
    files = [RepositoryFile(path=path, bytes=0, sha256="0" * 64) for path in paths]
    with pytest.raises(ValueError, match=r"sorted|unique"):
        RepositoryManifest(exclusions=[], files=files)
