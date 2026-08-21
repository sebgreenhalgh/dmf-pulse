"""Fail-closed authority for the single GW1 zero-minute diagnostic request."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError

DIAGNOSTIC_APPROVAL_SHA256 = "7e299bb4d88a0260d8f67bda9e81b09649452fddbe027f52270634945597cb20"
DIAGNOSTIC_CATALOGUE_SHA256 = "9d655a2dc8e60eca0898f4bc04e8caf7b264887af1d62bfe61c5288cbdd75f11"
DIAGNOSTIC_TARGET_IDENTITY_SHA256 = (
    "32cbe879f9c063a8a8467c7bf3241a370901dc463072eb15e93ecaa0ed683269"
)
DIAGNOSTIC_TERMS_FINGERPRINT = "ad62cb745459df3282f8900117b85352a01d75754e080d06aa3836dcd2b2b246"
DIAGNOSTIC_TARGET_ORDINAL = 348
DIAGNOSTIC_INFORMATION_CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)

_ALLOWED_FIELDS = (
    "season_name",
    "minutes",
    "goals_scored",
    "assists",
    "yellow_cards",
    "red_cards",
    "saves",
)
_CONSUMED_APPROVALS = (
    "d946552f2a55df7ed400bb43cff6bf85b4bdf8cbfe804044d08d9c9a96f8e2fd",
    "6d094bd94217d227f946bdee769a46227312d78bae455464a4fd41d191e8c935",
)


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _Constraints(_Record):
    information_cutoff: Literal["2026-08-21T17:30:00Z"]
    maximum_official_history_requests: Literal[1]
    no_browser_automation: Literal[True]
    no_bulk_capture: Literal[True]
    session_free: Literal[True] = Field(validation_alias="no_cookie_or_session")
    credential_free: Literal[True] = Field(validation_alias="no_credential")
    no_historical_catalogue_discovery: Literal[True]
    no_login: Literal[True]
    no_other_player: Literal[True]
    no_retry: Literal[True]
    stop_on_any_request_failure: Literal[True]
    stop_on_post_cutoff_response: Literal[True]


class _Binding(_Record):
    expected_catalogue_semantic_sha256: Literal[
        "9d655a2dc8e60eca0898f4bc04e8caf7b264887af1d62bfe61c5288cbdd75f11"
    ]
    failed_request_ordinal: Literal[348]
    observed_failure_code: Literal["HISTORY_MODEL_VALIDATION_FAILED"]
    observed_failure_stage: Literal["MODEL"]
    observed_model_validation_reason: Literal["ZERO_MINUTE_POSITIVE_EVENT"]
    player_position: Literal["GK"]
    transient_player_identity_sha256: Literal[
        "32cbe879f9c063a8a8467c7bf3241a370901dc463072eb15e93ecaa0ed683269"
    ]


class _Source(_Record):
    current_element_id_binding: Literal[
        "EXACT_TARGET_RESOLVED_FROM_APPROVED_TRANSIENT_CURRENT_CATALOGUE"
    ]
    url_template: Literal[
        "https://fantasy.premierleague.com/api/element-summary/{current_element_id}/"
    ]


class _TermsReview(_Record):
    snapshot_sha256: Literal["ad62cb745459df3282f8900117b85352a01d75754e080d06aa3836dcd2b2b246"]
    source_url: Literal["https://www.premierleague.com/en/terms-and-conditions"]


class ZeroMinuteDiagnosticApproval(_Record):
    """The exact single-request authority; never adaptable to bulk capture."""

    schema_version: Literal["gw1-player-history-zero-minute-diagnostic-approval-v1"]
    status: Literal["HUMAN_ACCEPTED_SINGLE_ROW_DIAGNOSTIC_ONLY"]
    scope: Literal["PRIVATE_2026_27_GW1_ZERO_MINUTE_DIAGNOSTIC_ONLY"]
    access_mode: Literal["HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT"]
    allowed_history_fields: tuple[
        Literal["season_name"],
        Literal["minutes"],
        Literal["goals_scored"],
        Literal["assists"],
        Literal["yellow_cards"],
        Literal["red_cards"],
        Literal["saves"],
    ]
    allowed_node: Literal["history_past"]
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_source: Literal["USER_DIRECTIVE"]
    approved_at: datetime
    bulk_capture_authority: Literal["NONE"]
    capture_constraints: _Constraints
    consumed_bulk_approval_sha256s: tuple[str, str]
    current_catalogue_retention: Literal["FORBIDDEN"]
    diagnostic_binding: _Binding
    diagnostic_parser_mode: Literal["PERMITTED_FIELDS_BEFORE_HISTORY_PAST_SEASON_MODEL"]
    diagnostic_remediation_parent_sha: Literal["bb003141f2ba197453a8f88e2565a98ca7dca712"]
    raw_retention: Literal["FORBIDDEN"]
    redistribution: Literal["NONE"]
    repeat_diagnostic: Literal["REQUIRES_NEW_HUMAN_APPROVAL"]
    required_branch_start_sha: Literal["cde6ad7031089dabaccf2d94e18a26eff7b414ee"]
    source: _Source
    source_body_sha256_retention: Literal["PERMITTED_NONREVERSIBLE_PROVENANCE_ONLY"]
    terms_review: _TermsReview

    @field_validator("approved_at")
    @classmethod
    def approved_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approved_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def exact_sets_are_bound(self) -> Self:
        if self.allowed_history_fields != _ALLOWED_FIELDS:
            raise ValueError("diagnostic fields differ from the directive")
        if self.consumed_bulk_approval_sha256s != _CONSUMED_APPROVALS:
            raise ValueError("consumed bulk approval lineage differs from the directive")
        return self


def load_zero_minute_diagnostic_approval(
    path: Path, *, expected_approval_sha256: str
) -> ZeroMinuteDiagnosticApproval:
    """Load only the exact immutable diagnostic record."""

    if expected_approval_sha256 != DIAGNOSTIC_APPROVAL_SHA256:
        raise IngestionError(
            "DIAGNOSTIC_APPROVAL_HASH_MISMATCH", "unexpected diagnostic approval hash"
        )
    try:
        raw_text = path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        record = ZeroMinuteDiagnosticApproval.model_validate_json(raw_text)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError(
            "DIAGNOSTIC_APPROVAL_INVALID", "diagnostic approval record is invalid"
        ) from exc
    if not isinstance(raw, dict):
        raise IngestionError("DIAGNOSTIC_APPROVAL_INVALID", "diagnostic approval record is invalid")
    without_hash = dict(raw)
    without_hash.pop("approval_sha256", None)
    if canonical_sha256(without_hash) != record.approval_sha256:
        raise IngestionError(
            "DIAGNOSTIC_APPROVAL_INVALID", "diagnostic approval record hash is invalid"
        )
    if record.approval_sha256 != DIAGNOSTIC_APPROVAL_SHA256:
        raise IngestionError(
            "DIAGNOSTIC_APPROVAL_HASH_MISMATCH", "diagnostic approval hash does not match"
        )
    return record


__all__ = [
    "DIAGNOSTIC_APPROVAL_SHA256",
    "DIAGNOSTIC_CATALOGUE_SHA256",
    "DIAGNOSTIC_INFORMATION_CUTOFF",
    "DIAGNOSTIC_TARGET_IDENTITY_SHA256",
    "DIAGNOSTIC_TARGET_ORDINAL",
    "DIAGNOSTIC_TERMS_FINGERPRINT",
    "ZeroMinuteDiagnosticApproval",
    "load_zero_minute_diagnostic_approval",
]
