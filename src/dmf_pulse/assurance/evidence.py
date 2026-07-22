"""Strict Pydantic evidence contracts and safe validation failures."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024


class StrictEvidenceModel(BaseModel):
    """Forbid evidence drift and mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ResultStatus(StrEnum):
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class FileChange(StrictEvidenceModel):
    path: str
    change: str


class CommandRecord(StrictEvidenceModel):
    command: str
    exit_code: int
    duration_seconds: float | None = None
    result: str | None = None


class ReviewPackReference(StrictEvidenceModel):
    path: str
    file_count: Annotated[int, Field(ge=1, le=20)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CodexResult(StrictEvidenceModel):
    ticket_id: Literal["FND-001"]
    status: ResultStatus
    summary: Annotated[str, Field(min_length=1)]
    files_changed: list[FileChange]
    public_interfaces: list[str] = []
    commands: list[CommandRecord]
    tests: list[dict[str, JsonValue]]
    acceptance: list[dict[str, JsonValue]]
    dependency_impact: str | None = None
    migration_impact: str | None = None
    assumptions: list[str]
    exclusions_verified: list[str] = []
    risks: list[str]
    review_pack: ReviewPackReference


class EvidenceArtifact(StrictEvidenceModel):
    path: str
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    bytes: Annotated[int, Field(ge=0)]


class TicketEvidenceManifest(StrictEvidenceModel):
    ticket_id: str
    status: Literal["DRAFT", "COMPLETE", "BLOCKED", "FAILED"]
    created_at: str
    code_commit: str | None = None
    context_hash: str | None = None
    commands: list[dict[str, JsonValue]]
    artifacts: list[EvidenceArtifact]
    known_limitations: list[str] = []


class ReviewFile(StrictEvidenceModel):
    name: str
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    bytes: Annotated[int, Field(ge=0)]
    purpose: str


class ReviewManifest(StrictEvidenceModel):
    ticket_id: Literal["FND-001"]
    generated_at: str
    repository_head: str
    baseline: str | None = None
    file_count: Annotated[int, Field(ge=1, le=20)]
    files: Annotated[list[ReviewFile], Field(max_length=20)]
    acceptance_status: ResultStatus

    @model_validator(mode="after")
    def unique_file_names(self) -> ReviewManifest:
        names = [item.name for item in self.files]
        if len(names) != len(set(names)):
            raise ValueError("review manifest contains duplicate file names")
        if self.file_count < len(self.files):
            raise ValueError("file_count cannot be smaller than the detached file list")
        return self


class EvidenceKind(StrEnum):
    CODEX_RESULT = "codex_result"
    TICKET_MANIFEST = "ticket_evidence_manifest"
    REVIEW_MANIFEST = "review_manifest"


@dataclass(frozen=True, slots=True)
class ValidatedEvidence:
    """Typed evidence plus its detected contract kind."""

    kind: EvidenceKind
    model: StrictEvidenceModel


class EvidenceValidationError(Exception):
    """Safe actionable evidence failure without rejected input values."""

    def __init__(self, code: str, message: str, *, issues: tuple[dict[str, str], ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.issues = issues

    def as_error_object(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "issues": list(self.issues),
                "message": self.message,
            },
            "ok": False,
        }


def _safe_validation_issues(error: ValidationError) -> tuple[dict[str, str], ...]:
    issues = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        issues.append(
            {
                "location": ".".join(str(part) for part in item.get("loc", ())) or "$",
                "message": str(item.get("msg", "invalid value")),
                "type": str(item.get("type", "value_error")),
            }
        )
    return tuple(sorted(issues, key=lambda item: (item["location"], item["type"], item["message"])))


def _detect_model(value: dict[str, Any]) -> tuple[EvidenceKind, type[StrictEvidenceModel]]:
    if "review_pack" in value:
        return EvidenceKind.CODEX_RESULT, CodexResult
    if "acceptance_status" in value and "repository_head" in value:
        return EvidenceKind.REVIEW_MANIFEST, ReviewManifest
    if "artifacts" in value and "created_at" in value:
        return EvidenceKind.TICKET_MANIFEST, TicketEvidenceManifest
    raise EvidenceValidationError(
        "EVIDENCE_TYPE_UNKNOWN",
        "evidence does not match a supported result, ticket-manifest, or review-manifest shape",
    )


def validate_evidence_data(value: object) -> ValidatedEvidence:
    """Detect and strictly validate one supported JSON evidence object."""

    if not isinstance(value, dict):
        raise EvidenceValidationError("EVIDENCE_OBJECT_REQUIRED", "evidence must be a JSON object")
    kind, model_type = _detect_model(value)
    try:
        model = model_type.model_validate(value)
    except ValidationError as exc:
        raise EvidenceValidationError(
            "EVIDENCE_SCHEMA_INVALID",
            "evidence failed its strict schema",
            issues=_safe_validation_issues(exc),
        ) from exc
    return ValidatedEvidence(kind=kind, model=model)


def validate_evidence_file(path: Path) -> ValidatedEvidence:
    """Read bounded UTF-8 JSON and validate its detected evidence contract."""

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise EvidenceValidationError(
            "EVIDENCE_FILE_MISSING", "evidence file is unavailable"
        ) from exc
    if size > MAX_EVIDENCE_BYTES:
        raise EvidenceValidationError(
            "EVIDENCE_FILE_TOO_LARGE", "evidence exceeds the 10 MiB limit"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError(
            "EVIDENCE_JSON_INVALID", "evidence is not valid UTF-8 JSON"
        ) from exc
    return validate_evidence_data(value)
