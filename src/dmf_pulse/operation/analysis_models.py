"""Allowlisted derived-only snapshot; no raw execution input or secret fields."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard.views import DeskView
from dmf_pulse.operation.analysis_optimizer import AnalysisOptimizerEvidence
from dmf_pulse.operation.diagnostics import DiagnosticReport
from dmf_pulse.private_v1.models import PrivateV1Decision
from dmf_pulse.private_v1.presentation import PresentationModel, PrivatePresentation

ProvenanceClass = Literal["NORMAL_STANDING", "GW10_DIAGNOSTIC", "OWNED_SYNTHETIC"]
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AnalysisSnapshot(PresentationModel):
    schema_version: Literal["analysis-snapshot-v1"] = "analysis-snapshot-v1"
    run_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    provenance_class: ProvenanceClass
    validation: Literal["UNVALIDATED"] = "UNVALIDATED"
    rights: Literal["PRIVATE_DERIVED_ONLY_NO_RAW_NO_PUBLIC_SHARING_NO_REPLAY"] = (
        "PRIVATE_DERIVED_ONLY_NO_RAW_NO_PUBLIC_SHARING_NO_REPLAY"
    )
    permission_origin: Literal["OWNER_ATTESTED_NOT_ISSUER_AUTHENTICATED", "OWNED_FIXTURE"]
    source_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] | None = None
    implementation_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    policy_sha256: Sha
    wheel_sha256: Sha
    recorded_at: datetime
    view: DeskView
    presentation: PrivatePresentation | None = None
    diagnostics: DiagnosticReport | None = None
    optimizer_evidence: AnalysisOptimizerEvidence | None = None
    captaincy_explanation: Literal["UNAVAILABLE_IN_RETAINED_ENGINE_OUTPUT"] = (
        "UNAVAILABLE_IN_RETAINED_ENGINE_OUTPUT"
    )
    # Actual comparison/frontier remains in decision; this does not infer causation.
    original_artifact_sha256: Sha | None = None

    @field_validator("recorded_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ANALYSIS_UTC_REQUIRED")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.provenance_class == "NORMAL_STANDING" and self.optimizer_evidence is None:
            raise ValueError("ANALYSIS_OPTIMIZER_EVIDENCE_REQUIRED")
        if self.optimizer_evidence is not None:
            if not isinstance(self.view.team.decision, PrivateV1Decision):
                raise ValueError("ANALYSIS_OPTIMIZER_DECISION_BINDING_INVALID")
            self.optimizer_evidence.require_bound_to(self.view.team.decision)
        if self.run_id != self.view.job_id:
            raise ValueError("ANALYSIS_RUN_VIEW_ID_MISMATCH")
        for value in (
            self.view.generated_at,
            self.view.information_cutoff,
            self.view.source_captured_at,
            self.view.deadline_at,
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("ANALYSIS_UTC_REQUIRED")
        synthetic = self.provenance_class == "OWNED_SYNTHETIC"
        if synthetic != (self.permission_origin == "OWNED_FIXTURE") or synthetic != (
            self.view.dataset_mode in {"SYNTHETIC_DEMONSTRATION", "SYNTHETIC_CURRENT_MODE"}
        ):
            raise ValueError("ANALYSIS_PROVENANCE_MISMATCH")
        if self.presentation is not None and (
            self.presentation.catalogue != tuple(p.catalogue for p in self.view.players)
            or self.presentation.current_squad != self.view.team.current_squad
            or self.presentation.source_vintages != self.view.source_vintages
            or self.presentation.market_quota_receipt != self.view.market_quota_receipt
        ):
            raise ValueError("ANALYSIS_PRESENTATION_MISMATCH")
        if len({p.catalogue.official_id for p in self.view.players}) != len(self.view.players):
            raise ValueError("ANALYSIS_DUPLICATE_PLAYER")
        return self

    @property
    def semantic_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))
