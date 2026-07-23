"""Strict Pydantic evidence contracts and safe validation failures."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    ValidationError,
    model_validator,
)

from dmf_pulse.assurance.tickets import validate_ticket_id

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024
DAT_REQUIRED_BASELINE = "f9b51e965aad1bc94796c17c897f0d99b4c16e1b"
DAT_REQUIRED_BRANCH = "stage/A3/DAT-003-canonical-foundation"
DAT_REVIEW_PATH = "review_pack/DAT-003/DMF_PULSE_DAT-003_REVIEW.zip"
DAT_DETACHED_REVIEW_NAMES = {
    "01_REVIEW_INDEX.md",
    "02_CODEX_RESULT.json",
    "04_FULL_DIFF.patch",
    "05_DIFF_STAT.txt",
    "06_GIT_STATUS.txt",
    "07_FILE_TREE.txt",
    "08_COMMANDS_LOG.txt",
    "09_TEST_COVERAGE_MUTATION_ORACLES.md",
    "10_ACCEPTANCE_MATRIX.md",
    "11_RUL002_REMEDIATION_MATRIX.md",
    "12_SCHEMA_MIGRATION.md",
    "13_TEMPORAL_IDENTITY_ASOF_CONCURRENCY.md",
    "14_PROVENANCE_IMMUTABILITY_RULES_REGISTRY.md",
    "15_DEPENDENCY_DOCKER_CI_SECURITY.md",
    "16_KNOWN_LIMITATIONS.md",
    "17_DATA_MODEL_PUBLIC_CONTRACTS_MODELS.txt",
    "18_INITIAL_MIGRATION_CRITICAL_SQL.txt",
    "19_REPOSITORY_CLI_CONFIG_COMPOSE_CI.txt",
}
TicketId = Annotated[
    str,
    Field(min_length=3, max_length=40, pattern=r"^[A-Z0-9]+(?:[-.][A-Z0-9]+)*$"),
    AfterValidator(validate_ticket_id),
]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


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
    exit_code: StrictInt
    duration_seconds: StrictFloat | StrictInt | None = None
    result: str | None = None


class ReviewPackReference(StrictEvidenceModel):
    path: str
    file_count: Annotated[StrictInt, Field(ge=1, le=20)]
    payload_sha256: Sha256 | None = None
    archive_sha256: Sha256 | None = None
    sha256: Sha256 | None = None

    @model_validator(mode="after")
    def digest_semantics(self) -> ReviewPackReference:
        if self.payload_sha256 is None and self.sha256 is None:
            raise ValueError("review pack requires payload_sha256 (or legacy sha256)")
        if self.payload_sha256 is not None and self.sha256 is not None:
            raise ValueError("legacy sha256 cannot be combined with payload_sha256")
        return self

    @property
    def effective_payload_sha256(self) -> str:
        """Return the stable payload digest, including the legacy FND field."""

        value = self.payload_sha256 if self.payload_sha256 is not None else self.sha256
        if value is None:  # pragma: no cover - guarded by validation
            raise ValueError("review payload digest is unavailable")
        return value


class RepositoryState(StrictEvidenceModel):
    branch: str
    head: GitCommit
    baseline: GitCommit | None = None
    clean: StrictBool
    pushed: StrictBool
    merged: StrictBool


class CodexResult(StrictEvidenceModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "status": {"const": "COMPLETE"},
                            "ticket_id": {"not": {"const": "FND-001"}},
                        },
                        "required": ["status", "ticket_id"],
                    },
                    "then": {
                        "properties": {
                            "code_commit": {"pattern": "^[0-9a-f]{40}$", "type": "string"}
                        },
                        "required": ["code_commit"],
                    },
                },
                {
                    "if": {
                        "properties": {"ticket_id": {"const": "RUL-002"}},
                        "required": ["ticket_id"],
                    },
                    "then": {
                        "properties": {
                            "code_commit": {"pattern": "^[0-9a-f]{40}$", "type": "string"},
                            "repository": {
                                "properties": {
                                    "baseline": {
                                        "const": "12049a7de23a4a8fcca3d219dbcab1bf5e1027ea"
                                    },
                                    "branch": {"const": "stage/A2/RUL-002-rules-foundation"},
                                    "clean": {"const": True},
                                    "merged": {"const": False},
                                    "pushed": {"const": False},
                                },
                                "required": [
                                    "baseline",
                                    "branch",
                                    "clean",
                                    "head",
                                    "merged",
                                    "pushed",
                                ],
                                "type": "object",
                            },
                            "review_pack": {
                                "properties": {
                                    "archive_sha256": {"type": "null"},
                                    "file_count": {"const": 20},
                                    "path": {
                                        "const": "review_pack/RUL-002/DMF_PULSE_RUL-002_REVIEW.zip"
                                    },
                                    "sha256": {"type": "null"},
                                },
                                "required": ["file_count", "path", "payload_sha256"],
                            },
                        },
                        "required": ["code_commit", "repository"],
                    },
                },
                {
                    "if": {
                        "properties": {"ticket_id": {"const": "DAT-003"}},
                        "required": ["ticket_id"],
                    },
                    "then": {
                        "properties": {
                            "code_commit": {"pattern": "^[0-9a-f]{40}$", "type": "string"},
                            "repository": {
                                "properties": {
                                    "baseline": {"const": DAT_REQUIRED_BASELINE},
                                    "branch": {"const": DAT_REQUIRED_BRANCH},
                                    "clean": {"const": True},
                                    "merged": {"const": False},
                                    "pushed": {"const": False},
                                },
                                "required": [
                                    "baseline",
                                    "branch",
                                    "clean",
                                    "head",
                                    "merged",
                                    "pushed",
                                ],
                                "type": "object",
                            },
                            "review_pack": {
                                "properties": {
                                    "archive_sha256": {"type": "null"},
                                    "file_count": {"const": 20},
                                    "path": {"const": DAT_REVIEW_PATH},
                                    "sha256": {"type": "null"},
                                },
                                "required": ["file_count", "path", "payload_sha256"],
                            },
                        },
                        "required": ["code_commit", "repository"],
                    },
                },
            ]
        },
    )

    ticket_id: TicketId
    status: ResultStatus
    code_commit: GitCommit | None = None
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
    repository: RepositoryState | None = None
    review_pack: ReviewPackReference

    @model_validator(mode="after")
    def complete_result_has_commit(self) -> CodexResult:
        legacy_fnd = self.ticket_id == "FND-001" and self.review_pack.sha256 is not None
        if self.status is ResultStatus.COMPLETE and self.code_commit is None and not legacy_fnd:
            raise ValueError("COMPLETE evidence requires an exact Git commit")
        if self.ticket_id == "RUL-002":
            expected_path = "review_pack/RUL-002/DMF_PULSE_RUL-002_REVIEW.zip"
            if (
                self.review_pack.payload_sha256 is None
                or self.review_pack.sha256 is not None
                or self.review_pack.archive_sha256 is not None
                or self.review_pack.path != expected_path
                or self.review_pack.file_count != 20
            ):
                raise ValueError("RUL-002 requires the exact detached 20-file review reference")
            if (
                self.repository is None
                or self.repository.branch != "stage/A2/RUL-002-rules-foundation"
                or self.repository.head != self.code_commit
                or self.repository.baseline != "12049a7de23a4a8fcca3d219dbcab1bf5e1027ea"
                or not self.repository.clean
                or self.repository.pushed
                or self.repository.merged
            ):
                raise ValueError("RUL-002 requires exact clean repository provenance")
        if self.ticket_id == "DAT-003":
            if (
                self.review_pack.payload_sha256 is None
                or self.review_pack.sha256 is not None
                or self.review_pack.archive_sha256 is not None
                or self.review_pack.path != DAT_REVIEW_PATH
                or self.review_pack.file_count != 20
            ):
                raise ValueError("DAT-003 requires the exact detached 20-file review reference")
            if (
                self.repository is None
                or self.repository.branch != DAT_REQUIRED_BRANCH
                or self.repository.head != self.code_commit
                or self.repository.baseline != DAT_REQUIRED_BASELINE
                or not self.repository.clean
                or self.repository.pushed
                or self.repository.merged
            ):
                raise ValueError("DAT-003 requires exact clean repository provenance")
        return self


class EvidenceArtifact(StrictEvidenceModel):
    path: str
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    bytes: Annotated[StrictInt, Field(ge=0)]


class TicketEvidenceManifest(StrictEvidenceModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "status": {"const": "COMPLETE"},
                            "ticket_id": {"not": {"const": "FND-001"}},
                        },
                        "required": ["status", "ticket_id"],
                    },
                    "then": {
                        "properties": {
                            "code_commit": {"pattern": "^[0-9a-f]{40}$", "type": "string"}
                        },
                        "required": ["code_commit"],
                    },
                }
            ]
        },
    )

    ticket_id: TicketId
    status: Literal["DRAFT", "COMPLETE", "BLOCKED", "FAILED"]
    created_at: str
    code_commit: GitCommit | None = None
    context_hash: str | None = None
    commands: list[dict[str, JsonValue]]
    artifacts: list[EvidenceArtifact]
    known_limitations: list[str] = []

    @model_validator(mode="after")
    def complete_manifest_has_commit(self) -> TicketEvidenceManifest:
        if self.status == "COMPLETE" and self.code_commit is None and self.ticket_id != "FND-001":
            raise ValueError("COMPLETE evidence manifest requires an exact Git commit")
        return self


class ReviewFile(StrictEvidenceModel):
    name: str
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    bytes: Annotated[StrictInt, Field(ge=0)]
    purpose: str


class ReviewManifest(StrictEvidenceModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"ticket_id": {"const": "RUL-002"}},
                        "required": ["ticket_id"],
                    },
                    "then": {
                        "properties": {
                            "archive_sha256": {"type": "null"},
                            "baseline": {"const": "12049a7de23a4a8fcca3d219dbcab1bf5e1027ea"},
                            "file_count": {"const": 20},
                        },
                        "required": ["baseline", "payload_sha256"],
                    },
                },
                {
                    "if": {
                        "properties": {"ticket_id": {"const": "DAT-003"}},
                        "required": ["ticket_id"],
                    },
                    "then": {
                        "properties": {
                            "archive_sha256": {"type": "null"},
                            "baseline": {"const": DAT_REQUIRED_BASELINE},
                            "file_count": {"const": 20},
                            "files": {"maxItems": 18, "minItems": 18},
                        },
                        "required": ["baseline", "payload_sha256"],
                    },
                },
            ]
        },
    )

    ticket_id: TicketId
    generated_at: str
    repository_head: GitCommit
    baseline: str | None = None
    file_count: Annotated[StrictInt, Field(ge=1, le=20)]
    files: Annotated[list[ReviewFile], Field(max_length=20)]
    acceptance_status: ResultStatus
    payload_sha256: Sha256 | None = None
    archive_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def unique_file_names(self) -> ReviewManifest:
        names = [item.name for item in self.files]
        if len(names) != len(set(names)):
            raise ValueError("review manifest contains duplicate file names")
        if self.file_count < len(self.files):
            raise ValueError("file_count cannot be smaller than the detached file list")
        if self.ticket_id == "RUL-002" and (
            self.baseline != "12049a7de23a4a8fcca3d219dbcab1bf5e1027ea"
            or self.file_count != 20
            or self.payload_sha256 is None
            or self.archive_sha256 is not None
        ):
            raise ValueError("RUL-002 review manifest provenance is invalid")
        if self.ticket_id == "DAT-003" and (
            self.baseline != DAT_REQUIRED_BASELINE
            or self.file_count != 20
            or self.payload_sha256 is None
            or self.archive_sha256 is not None
            or set(names) != DAT_DETACHED_REVIEW_NAMES
            or len(names) != len(DAT_DETACHED_REVIEW_NAMES)
        ):
            raise ValueError("DAT-003 review manifest provenance is invalid")
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
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant is prohibited: {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise EvidenceValidationError(
            "EVIDENCE_JSON_INVALID", "evidence is not valid UTF-8 JSON"
        ) from exc
    return validate_evidence_data(value)
