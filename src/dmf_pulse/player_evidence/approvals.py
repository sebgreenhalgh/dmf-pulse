"""Strict adapters for consumed and exact approved GW1 history records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.history import approved_history_schema_fingerprint
from dmf_pulse.player_evidence.models import (
    CaptureAccessMode,
    PlayerHistoryRightsApproval,
    RetentionMode,
)

_ACCEPTED_APPROVAL_SHA256 = "d946552f2a55df7ed400bb43cff6bf85b4bdf8cbfe804044d08d9c9a96f8e2fd"
SECOND_RETRY_APPROVAL_SHA256 = "6d094bd94217d227f946bdee769a46227312d78bae455464a4fd41d191e8c935"
POST_DIAGNOSTIC_FULL_APPROVAL_SHA256 = (
    "2a4561b3ad7fa24cbe3b40f5a56e8b58251b3d6e8ec68881ed4d78c0d8579b4b"
)
_ACCEPTED_TERMS_FINGERPRINT = "ad62cb745459df3282f8900117b85352a01d75754e080d06aa3836dcd2b2b246"
_SECOND_RETRY_CATALOGUE_SHA256 = "9d655a2dc8e60eca0898f4bc04e8caf7b264887af1d62bfe61c5288cbdd75f11"
_ALLOWED_HISTORY_FIELDS = (
    "season_name",
    "minutes",
    "goals_scored",
    "assists",
    "yellow_cards",
    "red_cards",
    "saves_FOR_GOALKEEPERS_ONLY",
)
_TERMS_PROPOSITIONS = (
    "REASONABLE_PRIVATE_PERSONAL_DOWNLOADING_PERMITTED",
    "BROADER_REPRODUCTION_REUTILISATION_REDISTRIBUTION_AND_DATABASE_CREATION_RESTRICTED",
    "NO_EXPRESS_RESOLUTION_OF_THIS_BOUNDED_TRANSIENT_POSTERIOR_ONLY_TRANSFORMATION",
)


class _RecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _CaptureConstraints(_RecordModel):
    actual_requested_count_must_not_exceed_exact_mapped_catalogue_count: Literal[True]
    information_cutoff: Literal["2026-08-21T17:30:00Z"]
    maximum_player_requests: Literal[650]
    minimum_serial_interval_seconds: float = Field(ge=1.0, le=1.0)
    no_browser_automation: Literal[True]
    session_free: Literal[True] = Field(validation_alias="no_cookie_or_session")
    login_free: Literal[True] = Field(validation_alias="no_credential")
    no_historical_player_discovery: Literal[True]
    stop_immediately_on_http: tuple[Literal[401], Literal[403], Literal[429]]
    stop_on_material_schema_drift: Literal[True]
    stop_on_post_cutoff_response: Literal[True]


class _SecondRetryCaptureConstraints(_RecordModel):
    actual_requested_count_must_not_exceed_exact_mapped_catalogue_count: Literal[True]
    information_cutoff: Literal["2026-08-21T17:30:00Z"]
    maximum_player_requests: Literal[599]
    minimum_serial_interval_seconds: float = Field(ge=1.0, le=1.0)
    no_browser_automation: Literal[True]
    session_free: Literal[True] = Field(validation_alias="no_cookie_or_session")
    login_free: Literal[True] = Field(validation_alias="no_credential")
    no_historical_player_discovery: Literal[True]
    no_parallel_requests: Literal[True]
    no_retry_loop: Literal[True]
    stop_immediately_on_http: tuple[Literal[401], Literal[403], Literal[429]]
    stop_on_material_schema_drift: Literal[True]
    stop_on_network_failure: Literal[True]
    stop_on_other_non_success_response: Literal[True]
    stop_on_post_cutoff_response: Literal[True]
    stop_on_typed_parser_or_model_failure: Literal[True]


class _PostDiagnosticCaptureConstraints(_RecordModel):
    actual_requested_count_must_equal_exact_mapped_catalogue_count: Literal[True]
    information_cutoff: Literal["2026-08-21T17:30:00Z"]
    maximum_player_requests: Literal[599]
    minimum_serial_interval_seconds: float = Field(ge=1.0, le=1.0)
    no_browser_automation: Literal[True]
    session_free: Literal[True] = Field(validation_alias="no_cookie_or_session")
    login_free: Literal[True] = Field(validation_alias="no_credential")
    no_historical_player_discovery: Literal[True]
    no_parallel_requests: Literal[True]
    no_retry_loop: Literal[True]
    stop_immediately_on_http: tuple[Literal[401], Literal[403], Literal[429]]
    stop_on_material_schema_drift: Literal[True]
    stop_on_network_failure: Literal[True]
    stop_on_other_non_success_response: Literal[True]
    stop_on_post_cutoff_response: Literal[True]
    stop_on_typed_parser_or_model_failure: Literal[True]


class _ApprovedSource(_RecordModel):
    current_element_id_binding: Literal[
        "ONLY_ALREADY_GOVERNED_CURRENT_2026_27_MAPPED_FPL_CATALOGUE"
    ]
    url_template: Literal[
        "https://fantasy.premierleague.com/api/element-summary/{current_element_id}/"
    ]


class _ApprovedPostDiagnosticSource(_RecordModel):
    current_element_id_binding: Literal["ONLY_EXACT_APPROVED_599_PLAYER_2026_27_GW1_CATALOGUE"]
    url_template: Literal[
        "https://fantasy.premierleague.com/api/element-summary/{current_element_id}/"
    ]


class _TermsReview(_RecordModel):
    current_terms_materially_consistent_with_reviewed_basis: Literal[True]
    reviewed_at: datetime
    snapshot_sha256: Literal["ad62cb745459df3282f8900117b85352a01d75754e080d06aa3836dcd2b2b246"]
    source_url: Literal["https://www.premierleague.com/en/terms-and-conditions"]
    verified_propositions: tuple[
        Literal["REASONABLE_PRIVATE_PERSONAL_DOWNLOADING_PERMITTED"],
        Literal[
            "BROADER_REPRODUCTION_REUTILISATION_REDISTRIBUTION_AND_DATABASE_CREATION_RESTRICTED"
        ],
        Literal["NO_EXPRESS_RESOLUTION_OF_THIS_BOUNDED_TRANSIENT_POSTERIOR_ONLY_TRANSFORMATION"],
    ]

    @field_validator("reviewed_at")
    @classmethod
    def reviewed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def propositions_are_exact(self) -> Self:
        if self.verified_propositions != _TERMS_PROPOSITIONS:
            raise ValueError("terms propositions are not the accepted set")
        return self


class _AcceptedV2RightsRecord(_RecordModel):
    schema_version: Literal["gw1-player-history-rights-approval-v2"]
    status: Literal["HUMAN_ACCEPTED_ONE_OFF_ONLY"]
    scope: Literal["PRIVATE_2026_27_GW1_ONLY"]
    purpose: Literal["PRIVATE_2026_27_GW1_DECISION_SUPPORT_ONLY"]
    access_mode: Literal[CaptureAccessMode.HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT]
    allowed_history_fields: tuple[
        Literal["season_name"],
        Literal["minutes"],
        Literal["goals_scored"],
        Literal["assists"],
        Literal["yellow_cards"],
        Literal["red_cards"],
        Literal["saves_FOR_GOALKEEPERS_ONLY"],
    ]
    allowed_node: Literal["history_past"]
    capture_constraints: _CaptureConstraints
    derived_retention: Literal[RetentionMode.POSTERIOR_ONLY]
    raw_retention: Literal["FORBIDDEN"]
    redistribution: Literal["NONE"]
    repeat_collection: Literal["REQUIRES_NEW_HUMAN_APPROVAL"]
    source: _ApprovedSource
    source_body_sha256_retention: Literal["PERMITTED_NONREVERSIBLE_PROVENANCE_ONLY"]
    terms_review: _TermsReview
    approval_source: Literal["USER_DIRECTIVE"]
    approved_at: datetime
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("approved_at")
    @classmethod
    def approved_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approved_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def record_is_exact(self) -> Self:
        if self.allowed_history_fields != _ALLOWED_HISTORY_FIELDS:
            raise ValueError("allowed history fields are not the accepted set")
        return self


class _AcceptedV3SecondRetryRightsRecord(_RecordModel):
    schema_version: Literal["gw1-player-history-rights-approval-v3"]
    status: Literal["HUMAN_ACCEPTED_SECOND_ONE_OFF_RETRY_ONLY"]
    scope: Literal["PRIVATE_2026_27_GW1_ONLY"]
    purpose: Literal["PRIVATE_2026_27_GW1_DECISION_SUPPORT_ONLY"]
    access_mode: Literal[CaptureAccessMode.HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT]
    allowed_history_fields: tuple[
        Literal["season_name"],
        Literal["minutes"],
        Literal["goals_scored"],
        Literal["assists"],
        Literal["yellow_cards"],
        Literal["red_cards"],
        Literal["saves_FOR_GOALKEEPERS_ONLY"],
    ]
    allowed_node: Literal["history_past"]
    capture_constraints: _SecondRetryCaptureConstraints
    derived_retention: Literal[RetentionMode.POSTERIOR_ONLY]
    raw_retention: Literal["FORBIDDEN"]
    redistribution: Literal["NONE"]
    repeat_collection: Literal["REQUIRES_ANOTHER_NEW_HUMAN_APPROVAL"]
    source: _ApprovedSource
    source_body_sha256_retention: Literal["PERMITTED_NONREVERSIBLE_PROVENANCE_ONLY"]
    terms_review: _TermsReview
    approval_source: Literal["USER_DIRECTIVE"]
    approved_at: datetime
    previous_consumed_approval_sha256: Literal[
        "d946552f2a55df7ed400bb43cff6bf85b4bdf8cbfe804044d08d9c9a96f8e2fd"
    ]
    required_capture_code_sha: Literal["bb003141f2ba197453a8f88e2565a98ca7dca712"]
    retry_ordinal: Literal[2]
    retry_reason: Literal["FIRST_ATTEMPT_FAILED_ATOMICALLY_WITH_DIAGNOSTICS_PREVIOUSLY_MASKED"]
    expected_catalogue_semantic_sha256: Literal[
        "9d655a2dc8e60eca0898f4bc04e8caf7b264887af1d62bfe61c5288cbdd75f11"
    ]
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("approved_at")
    @classmethod
    def approved_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approved_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def record_is_exact(self) -> Self:
        if self.allowed_history_fields != _ALLOWED_HISTORY_FIELDS:
            raise ValueError("allowed history fields are not the accepted set")
        return self


class _ZeroExposureDisciplinePolicy(_RecordModel):
    classification: Literal["ZERO_EXPOSURE_DISCIPLINE_ONLY"]
    exclude_entire_row_from_rate_evidence: Literal[True]
    excluded_row_contributes_event_numerator: Literal[False]
    excluded_row_contributes_exposure: Literal[False]
    excluded_row_imputes_minutes: Literal[False]
    lineage: Literal["ZERO_EXPOSURE_DISCIPLINE_ONLY_EXCLUDED_FROM_RATE_MODEL"]
    zero_minute_assist_fails_closed: Literal[True]
    zero_minute_goal_fails_closed: Literal[True]
    zero_minute_save_fails_closed: Literal[True]


class _AcceptedV4PostDiagnosticRightsRecord(_RecordModel):
    schema_version: Literal["gw1-player-history-rights-approval-v4"]
    status: Literal["HUMAN_ACCEPTED_POST_DIAGNOSTIC_FULL_CAPTURE_ONLY"]
    scope: Literal["PRIVATE_2026_27_GW1_ONLY"]
    purpose: Literal["PRIVATE_2026_27_GW1_DECISION_SUPPORT_ONLY"]
    access_mode: Literal[CaptureAccessMode.HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT]
    allowed_history_fields: tuple[
        Literal["season_name"],
        Literal["minutes"],
        Literal["goals_scored"],
        Literal["assists"],
        Literal["yellow_cards"],
        Literal["red_cards"],
        Literal["saves_FOR_GOALKEEPERS_ONLY"],
    ]
    allowed_node: Literal["history_past"]
    capture_constraints: _PostDiagnosticCaptureConstraints
    current_catalogue_retention: Literal["FORBIDDEN"]
    derived_retention: Literal[RetentionMode.POSTERIOR_ONLY]
    raw_retention: Literal["FORBIDDEN"]
    redistribution: Literal["NONE"]
    repeat_collection: Literal["REQUIRES_ANOTHER_NEW_HUMAN_APPROVAL"]
    source: _ApprovedPostDiagnosticSource
    source_body_sha256_retention: Literal["PERMITTED_NONREVERSIBLE_PROVENANCE_ONLY"]
    terms_review: _TermsReview
    approval_source: Literal["USER_DIRECTIVE"]
    approved_at: datetime
    consumed_prior_approval_sha256s: tuple[
        Literal["d946552f2a55df7ed400bb43cff6bf85b4bdf8cbfe804044d08d9c9a96f8e2fd"],
        Literal["6d094bd94217d227f946bdee769a46227312d78bae455464a4fd41d191e8c935"],
        Literal["7e299bb4d88a0260d8f67bda9e81b09649452fddbe027f52270634945597cb20"],
    ]
    diagnostic_result_sha256: Literal[
        "9711ad20221f66c0fd761f52ccf751f73358066d69869a28e908586bfc8acae5"
    ]
    diagnostic_source_body_sha256: Literal[
        "81aff2cbb2b44b9baa516e84a017f25fbc17c986057c9be8714080bff921422d"
    ]
    expected_catalogue_semantic_sha256: Literal[
        "9d655a2dc8e60eca0898f4bc04e8caf7b264887af1d62bfe61c5288cbdd75f11"
    ]
    required_remediation_sha: Literal["afe02852ef4456c632835e85dd4cfe8333812d5f"]
    zero_exposure_discipline_policy: _ZeroExposureDisciplinePolicy
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("approved_at")
    @classmethod
    def approved_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approved_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def record_is_exact(self) -> Self:
        if self.allowed_history_fields != _ALLOWED_HISTORY_FIELDS:
            raise ValueError("allowed history fields are not the accepted set")
        return self


def _as_capture_approval(
    record: (
        _AcceptedV2RightsRecord
        | _AcceptedV3SecondRetryRightsRecord
        | _AcceptedV4PostDiagnosticRightsRecord
    ),
) -> PlayerHistoryRightsApproval:
    rights_profile_id = {
        _AcceptedV2RightsRecord: "GW1_PLY003_ONE_OFF_HISTORY_POSTERIOR_ONLY_V1",
        _AcceptedV3SecondRetryRightsRecord: "GW1_PLY003_SECOND_ONE_OFF_HISTORY_POSTERIOR_ONLY_V1",
        _AcceptedV4PostDiagnosticRightsRecord: (
            "GW1_PLY003_POST_DIAGNOSTIC_FULL_HISTORY_POSTERIOR_ONLY_V1"
        ),
    }[type(record)]

    def build(approval_sha256: str) -> PlayerHistoryRightsApproval:
        return PlayerHistoryRightsApproval(
            status="HUMAN_ACCEPTED",
            scope="PRIVATE_2026_27_GW1_ONLY",
            rights_profile_id=rights_profile_id,
            source_url_template="https://fantasy.premierleague.com/api/element-summary/{current_element_id}/",
            allowed_node="history_past",
            access_mode=CaptureAccessMode.HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT,
            raw_retention="FORBIDDEN",
            derived_retention=RetentionMode.POSTERIOR_ONLY,
            redistribution="NONE",
            repeat_collection="REQUIRES_NEW_APPROVAL",
            source_hash_permitted=True,
            terms_fingerprint=record.terms_review.snapshot_sha256,
            history_past_schema_fingerprint=approved_history_schema_fingerprint(),
            approved_by=record.approval_source,
            approved_at=record.approved_at,
            governance_approval_sha256=record.approval_sha256,
            maximum_player_requests=record.capture_constraints.maximum_player_requests,
            approval_sha256=approval_sha256,
        )

    provisional = PlayerHistoryRightsApproval.model_construct(
        status="HUMAN_ACCEPTED",
        scope="PRIVATE_2026_27_GW1_ONLY",
        rights_profile_id=rights_profile_id,
        source_url_template="https://fantasy.premierleague.com/api/element-summary/{current_element_id}/",
        allowed_node="history_past",
        access_mode=CaptureAccessMode.HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT,
        raw_retention="FORBIDDEN",
        derived_retention=RetentionMode.POSTERIOR_ONLY,
        redistribution="NONE",
        repeat_collection="REQUIRES_NEW_APPROVAL",
        source_hash_permitted=True,
        terms_fingerprint=record.terms_review.snapshot_sha256,
        history_past_schema_fingerprint=approved_history_schema_fingerprint(),
        approved_by=record.approval_source,
        approved_at=record.approved_at,
        governance_approval_sha256=record.approval_sha256,
        maximum_player_requests=record.capture_constraints.maximum_player_requests,
        approval_sha256="0" * 64,
    )
    return build(canonical_sha256(provisional.model_dump(mode="json", exclude={"approval_sha256"})))


def load_player_history_rights_approval(
    path: Path, *, expected_approval_sha256: str
) -> PlayerHistoryRightsApproval:
    """Load only the known consumed records or exact post-diagnostic approval.

    Both returned v1 capture contracts remain hash-bound to their immutable
    governance record.  This deliberately accepts no arbitrary self-consistent
    approval file.
    """

    if expected_approval_sha256 not in {
        _ACCEPTED_APPROVAL_SHA256,
        SECOND_RETRY_APPROVAL_SHA256,
        POST_DIAGNOSTIC_FULL_APPROVAL_SHA256,
    }:
        raise IngestionError("RIGHTS_APPROVAL_HASH_MISMATCH", "unexpected rights approval hash")
    try:
        raw_text = path.read_text(encoding="utf-8")
        raw_record = json.loads(raw_text)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError(
            "RIGHTS_APPROVAL_INVALID", "rights approval record is invalid"
        ) from exc
    if not isinstance(raw_record, dict):
        raise IngestionError("RIGHTS_APPROVAL_INVALID", "rights approval record is invalid")
    record: (
        _AcceptedV2RightsRecord
        | _AcceptedV3SecondRetryRightsRecord
        | _AcceptedV4PostDiagnosticRightsRecord
    )
    try:
        if expected_approval_sha256 == _ACCEPTED_APPROVAL_SHA256:
            record = _AcceptedV2RightsRecord.model_validate_json(raw_text)
        elif expected_approval_sha256 == SECOND_RETRY_APPROVAL_SHA256:
            record = _AcceptedV3SecondRetryRightsRecord.model_validate_json(raw_text)
        else:
            record = _AcceptedV4PostDiagnosticRightsRecord.model_validate_json(raw_text)
    except (ValidationError, ValueError) as exc:
        raise IngestionError(
            "RIGHTS_APPROVAL_INVALID", "rights approval record is invalid"
        ) from exc
    raw_without_hash = dict(raw_record)
    raw_without_hash.pop("approval_sha256", None)
    if canonical_sha256(raw_without_hash) != record.approval_sha256:
        raise IngestionError("RIGHTS_APPROVAL_INVALID", "rights approval record hash is invalid")
    if record.approval_sha256 != expected_approval_sha256:
        raise IngestionError("RIGHTS_APPROVAL_HASH_MISMATCH", "rights approval hash does not match")
    return _as_capture_approval(record)


def validate_second_retry_capture_authorization(
    approval: PlayerHistoryRightsApproval,
    *,
    expected_approval_sha256: str,
    catalogue_semantic_sha256: str,
) -> None:
    """Require the second directive for the live current-catalogue command."""

    if expected_approval_sha256 != SECOND_RETRY_APPROVAL_SHA256:
        raise IngestionError(
            "RIGHTS_APPROVAL_HASH_MISMATCH", "second retry requires its new approval hash"
        )
    if approval.governance_approval_sha256 != SECOND_RETRY_APPROVAL_SHA256:
        raise IngestionError(
            "RIGHTS_APPROVAL_HASH_MISMATCH", "second retry approval lineage is invalid"
        )
    if approval.maximum_player_requests != 599:
        raise IngestionError("REQUEST_BOUND_INVALID", "second retry request bound is invalid")
    if catalogue_semantic_sha256 != _SECOND_RETRY_CATALOGUE_SHA256:
        raise IngestionError(
            "CATALOGUE_HASH_MISMATCH",
            "current catalogue does not match the approved retry universe",
        )


def validate_post_diagnostic_capture_authorization(
    approval: PlayerHistoryRightsApproval,
    *,
    expected_approval_sha256: str,
    catalogue_semantic_sha256: str,
    maximum_player_count: int,
) -> None:
    """Require the exact v4 directive and its full 599-player universe."""

    if expected_approval_sha256 != POST_DIAGNOSTIC_FULL_APPROVAL_SHA256:
        raise IngestionError(
            "RIGHTS_APPROVAL_HASH_MISMATCH",
            "post-diagnostic capture requires its new approval hash",
        )
    if approval.governance_approval_sha256 != POST_DIAGNOSTIC_FULL_APPROVAL_SHA256:
        raise IngestionError(
            "RIGHTS_APPROVAL_HASH_MISMATCH", "post-diagnostic approval lineage is invalid"
        )
    if approval.maximum_player_requests != 599 or maximum_player_count != 599:
        raise IngestionError(
            "REQUEST_BOUND_INVALID", "post-diagnostic request bound must equal 599"
        )
    if catalogue_semantic_sha256 != _SECOND_RETRY_CATALOGUE_SHA256:
        raise IngestionError(
            "CATALOGUE_HASH_MISMATCH",
            "current catalogue does not match the approved post-diagnostic universe",
        )


__all__ = [
    "POST_DIAGNOSTIC_FULL_APPROVAL_SHA256",
    "SECOND_RETRY_APPROVAL_SHA256",
    "load_player_history_rights_approval",
    "validate_post_diagnostic_capture_authorization",
    "validate_second_retry_capture_authorization",
]
