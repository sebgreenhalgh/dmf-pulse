"""Deterministic current-repository file manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import sha256_file
from dmf_pulse.assurance.tickets import validate_ticket_id

EXCLUDED_PARTS: Final = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".coverage",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
    "htmlcov",
    "coverage.xml",
    "review_pack",
}
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
    ticket_id: str = "FND-001"
    scope: Literal["repository-deliverables-excluding-generated-evidence"] = (
        "repository-deliverables-excluding-generated-evidence"
    )
    exclusions: list[str]
    files: list[RepositoryFile]

    @model_validator(mode="after")
    def unique_sorted_paths(self) -> RepositoryManifest:
        validate_ticket_id(self.ticket_id)
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
    if path.endswith("/current_manifest.json") and path.startswith("evidence/tickets/"):
        return True
    return path.startswith("evidence/tickets/") and path not in PRESERVED_EVIDENCE


def build_repository_manifest(root: Path, *, ticket_id: str = "FND-001") -> RepositoryManifest:
    """Hash every deliverable except operational output and self-referential evidence."""

    validated_ticket = validate_ticket_id(ticket_id)
    files = []
    for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = candidate.relative_to(root)
        if _excluded(relative):
            continue
        if candidate.is_symlink():
            raise ValueError(f"repository manifest refuses symlink: {relative.as_posix()}")
        if not candidate.is_file():
            continue
        files.append(
            RepositoryFile(
                path=relative.as_posix(),
                bytes=candidate.stat().st_size,
                sha256=sha256_file(candidate),
            )
        )
    return RepositoryManifest(
        ticket_id=validated_ticket,
        exclusions=[
            "Git metadata, virtual environments, caches, generated artifacts/builds, coverage HTML, and review output",
            "generated ticket evidence except the immutable FND-001 baseline manifest",
            "the current manifest itself",
        ],
        files=files,
    )


def validate_repository_manifest(root: Path, expected: RepositoryManifest) -> list[str]:
    """Return exact current-manifest drift errors."""

    actual = build_repository_manifest(root, ticket_id=expected.ticket_id)
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
