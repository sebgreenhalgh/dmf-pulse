"""Metadata-only recovery classification; no source assertion confers admission."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StrictStr, model_validator

from dmf_pulse.player_lab.contracts import LabModel, Sealed, Sha

Classification = Literal[
    "REAL_PRE_OUTCOME_FROZEN",
    "HISTORICAL_RECONSTRUCTED",
    "POST_OUTCOME",
    "SYNTHETIC",
    "UNVERIFIED_CUSTODY",
]
Retention = Literal[
    "QUALIFIED_PUBLIC_PRIVATE_USE_ONLY",
    "OWNED_SYNTHETIC_ONLY",
    "NOT_QUALIFIED_FOR_RETENTION",
    "NOT_ESTABLISHED",
]
Count = Annotated[StrictInt, Field(ge=0)]


class RecoveredFamily(LabModel):
    family_id: Annotated[StrictStr, Field(pattern=r"^[A-Z0-9_]{1,100}$")]
    level: Literal["MATCH", "PLAYER", "METADATA", "PARAMETERS"]
    classification: Classification
    retention: Retention
    evidence_sha256: Annotated[tuple[Sha, ...], Field(min_length=1)]
    artifact_byte_sha256: Sha | None = None
    artifact_semantic_sha256: Sha | None = None
    approved_locator: StrictStr | None = None
    provenance_locator: StrictStr | None = None
    model_sha256: Sha | None = None
    training_dataset_sha256: Sha | None = None
    source_lineage_sha256: Sha | None = None
    fixture_registry_sha256: Sha | None = None
    source_mode: Literal["LIVE_OBSERVED", "SYNTHETIC", "RECONSTRUCTED", "UNVERIFIED"]
    rights_profile_id: StrictStr | None = None
    rights_profile_config_byte_sha256: Sha | None = None
    rights_approval_ref: StrictStr | None = None
    target_seasons: tuple[Annotated[StrictStr, Field(pattern=r"^20\d{2}/\d{2}$")], ...]
    target_gameweeks: tuple[Annotated[StrictInt, Field(ge=1, le=38)], ...]
    scheduled_dates: tuple[date, ...]
    products: tuple[StrictStr, ...]
    forecast_origin: datetime | None = None
    information_cutoff: datetime | None = None
    training_cutoff: datetime | None = None
    frozen_at: datetime | None = None
    sample_count: Count | None = None
    sample_unit: Literal["FIXTURE", "PLAYER_GAMEWEEK", "NOT_ESTABLISHED"]
    products_per_sample: Annotated[StrictInt, Field(ge=1)] | None = None
    forecast_rows: Count | None = None
    evaluation_status: StrictStr
    blockers: tuple[StrictStr, ...]
    explanation: StrictStr
    # The recovered local inventory contains no admitted real score. Absence is
    # deliberately not represented by numeric zero or synthetic accuracy.
    real_accuracy_metrics: None = None

    @model_validator(mode="after")
    def coherent_metadata(self) -> Self:
        if self.classification == "REAL_PRE_OUTCOME_FROZEN" and (
            self.artifact_byte_sha256 is None
            or self.artifact_semantic_sha256 is None
            or self.information_cutoff is None
            or self.forecast_origin is None
            or self.frozen_at is None
            or not self.information_cutoff <= self.forecast_origin <= self.frozen_at
            or self.sample_count is None
            or self.sample_count == 0
            or self.training_cutoff is None
            or self.training_cutoff > self.information_cutoff
        ):
            raise ValueError("real freeze requires original authenticated custody metadata")
        if self.forecast_rows is not None and (
            self.sample_count is None
            or self.products_per_sample is None
            or self.forecast_rows != self.sample_count * self.products_per_sample
        ):
            raise ValueError("forecast rows must not replace distinct target count")
        if self.products and len(self.products) != self.products_per_sample:
            raise ValueError("product identities differ from the per-target product count")
        if self.sample_unit == "NOT_ESTABLISHED" and self.sample_count is not None:
            raise ValueError("unknown sample identity cannot claim a denominator")
        return self


class LastKnownP01Labels(LabModel):
    authenticated_at: datetime
    snapshot_sha256: Sha
    final_fixture_count: Count
    missing_fixture_count: Count
    fixture_count: Literal[10] = 10
    current_provider_availability: Literal["NOT_QUERIED"] = "NOT_QUERIED"

    @model_validator(mode="after")
    def denominator(self) -> Self:
        if self.final_fixture_count + self.missing_fixture_count != 10:
            raise ValueError("P01 label accounting must retain all ten frozen fixtures")
        return self


class RecoveryCoverage(LabModel):
    project_roots: Count
    considered_files: Count
    metadata_files_read: Count
    access_or_absence_gaps: Count
    archive_count: Count
    archive_gaps: Count
    path_census_sha256: Sha
    archive_census_sha256: Sha
    mtime_is_freeze_proof: Literal[False] = False
    pickle_deserialized: Literal[False] = False
    unrelated_profile_search: Literal[False] = False


class RecoveryCatalogue(Sealed):
    schema_version: Literal["recovered-forecast-catalogue-v1"] = "recovered-forecast-catalogue-v1"
    metadata_as_of: datetime = Field(
        description="Inventory observation time only; later authority review receipts are separate."
    )
    inventory_semantic_sha256: Sha
    inventory_byte_sha256: Sha
    canonical_authority_assessment_sha256: Sha
    canonical_code_policy_assessment_sha256: Sha
    independent_authority_review_sha256: Sha
    canonical_resumption: Literal["BLOCKED_EXACT_CODE_NO_REGENERATION"]
    families: Annotated[tuple[RecoveredFamily, ...], Field(min_length=1, max_length=32)]
    p01_labels: LastKnownP01Labels
    coverage: RecoveryCoverage
    additional_owner_report: Literal["UNRESOLVED_NOT_DISPROVED"] = "UNRESOLVED_NOT_DISPROVED"
    metadata_only: Literal[True] = True
    provider_requests: Literal[0] = 0
    scoring_performed: Literal[False] = False
    new_cohort_created: Literal[False] = False
    promotion: Literal["FORBIDDEN"] = "FORBIDDEN"

    @model_validator(mode="after")
    def unique_families(self) -> Self:
        if len({family.family_id for family in self.families}) != len(self.families):
            raise ValueError("duplicate recovery family")
        return self


class ArtifactVerification(LabModel):
    schema_version: Literal["recovered-artifact-verification-v1"] = (
        "recovered-artifact-verification-v1"
    )
    byte_sha256: Sha
    bytes: Count
    family_id: StrictStr | None
    classification: Classification
    retention: Retention
    catalogue_semantic_sha256: Sha
    status: Literal["MATCHED_REVIEWED_ORIGINAL_BYTES", "UNKNOWN_BYTES_NO_CUSTODY_PROOF"]
    scoring_authorized: Literal[False] = False
