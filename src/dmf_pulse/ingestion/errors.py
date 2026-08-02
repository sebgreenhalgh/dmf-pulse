"""Typed secret-safe failures for ingestion commands and services."""

from __future__ import annotations

_EXIT_CODES = {
    "VALIDATION_FAILED": 2,
    "MALFORMED_JSON": 2,
    "PAYLOAD_TOO_LARGE": 2,
    "PAYLOAD_TOO_DEEP": 2,
    "DUPLICATE_JSON_KEY": 2,
    "MAPPING_CONFLICT": 2,
    "NO_USABLE_BUNDLE": 2,
    "POST_CUTOFF": 2,
    "USAGE_INVALID": 3,
    "CONFIGURATION_INVALID": 3,
    "FIXTURE_NOT_APPROVED": 3,
    "DATABASE_REFERENCE_INVALID": 3,
    "RIGHTS_BLOCKED": 4,
    "CREDENTIAL_UNAVAILABLE": 4,
    "QUOTA_EXHAUSTED": 4,
    "QUALITY_BLOCKED": 2,
    "DATABASE_UNAVAILABLE": 5,
    "DATABASE_RETRYABLE": 5,
    "DATABASE_CONSTRAINT": 5,
    "DATABASE_SCHEMA_BEHIND": 5,
    "CONNECT_TIMEOUT": 6,
    "READ_TIMEOUT": 6,
    "HTTP_429": 6,
    "HTTP_5XX": 6,
    "SOURCE_UNAVAILABLE": 6,
    "CANCELLED": 6,
    "HTTP_4XX": 7,
    "CONTENT_TYPE_INVALID": 7,
    "REDIRECT_BLOCKED": 7,
    "TLS_ERROR": 7,
    "LIFECYCLE_INVARIANT": 8,
    "CANONICAL_INVARIANT": 8,
    "INTERNAL_INVARIANT": 8,
}


class IngestionError(RuntimeError):
    """A stable ingestion failure that never embeds source bodies or credentials."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        self.exit_code = _EXIT_CODES.get(code, 8)

    def as_error_object(self) -> dict[str, object]:
        error: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            error["details"] = self.details
        return {"error": error, "schema_version": "1.0.0", "status": "FAILED"}
