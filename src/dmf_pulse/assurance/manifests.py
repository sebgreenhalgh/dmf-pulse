"""Deterministic current-repository file manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import sha256_file

EXCLUDED_PARTS: Final = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".coverage",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "coverage.xml",
    "review_pack",
}
GENERATED_EVIDENCE_PREFIX: Final = "evidence/tickets/FND-001/"
PRESERVED_EVIDENCE: Final = {"evidence/tickets/FND-001/baseline_manifest.json"}
CURRENT_MANIFEST_PATH: Final = "evidence/tickets/FND-001/current_manifest.json"


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RepositoryFile(ManifestModel):
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RepositoryManifest(ManifestModel):
    schema_version: Literal["1.0"] = "1.0"
    ticket_id: Literal["FND-001"] = "FND-001"
    scope: Literal["repository-deliverables-excluding-generated-evidence"] = (
        "repository-deliverables-excluding-generated-evidence"
    )
    exclusions: list[str]
    files: list[RepositoryFile]

    @model_validator(mode="after")
    def unique_sorted_paths(self) -> RepositoryManifest:
        paths = [item.path for item in self.files]
        if paths != sorted(paths):
            raise ValueError("repository manifest paths must be sorted")
        if len(paths) != len(set(paths)):
            raise ValueError("repository manifest paths must be unique")
        return self


def _excluded(relative: Path) -> bool:
    path = relative.as_posix()
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return True
    if path == CURRENT_MANIFEST_PATH:
        return True
    return path.startswith(GENERATED_EVIDENCE_PREFIX) and path not in PRESERVED_EVIDENCE


def build_repository_manifest(root: Path) -> RepositoryManifest:
    """Hash every deliverable except operational output and self-referential evidence."""

    files = []
    for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root)
        if _excluded(relative):
            continue
        if candidate.is_symlink():
            raise ValueError(f"repository manifest refuses symlink: {relative.as_posix()}")
        files.append(
            RepositoryFile(
                path=relative.as_posix(),
                bytes=candidate.stat().st_size,
                sha256=sha256_file(candidate),
            )
        )
    return RepositoryManifest(
        exclusions=[
            "Git metadata, virtual environments, caches, builds, coverage HTML, and review output",
            "generated FND-001 evidence except the immutable baseline manifest",
            "the current manifest itself",
        ],
        files=files,
    )


def validate_repository_manifest(root: Path, expected: RepositoryManifest) -> list[str]:
    """Return exact current-manifest drift errors."""

    actual = build_repository_manifest(root)
    expected_by_path = {item.path: item for item in expected.files}
    actual_by_path = {item.path: item for item in actual.files}
    errors = []
    for path in sorted(expected_by_path.keys() - actual_by_path.keys()):
        errors.append(f"current manifest file missing: {path}")
    for path in sorted(actual_by_path.keys() - expected_by_path.keys()):
        errors.append(f"current manifest has unrecorded file: {path}")
    for path in sorted(expected_by_path.keys() & actual_by_path.keys()):
        expected_file = expected_by_path[path]
        actual_file = actual_by_path[path]
        if expected_file.bytes != actual_file.bytes:
            errors.append(
                f"current manifest byte mismatch: {path}: "
                f"expected {expected_file.bytes}, got {actual_file.bytes}"
            )
        if expected_file.sha256 != actual_file.sha256:
            errors.append(f"current manifest hash mismatch: {path}")
    return errors
