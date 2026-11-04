"""Authenticated success-only derived planning evidence; no source execution inputs."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekOptimisationResult,
    MultiGameweekResultStatus,
    verify_result_hash,
)
from dmf_pulse.private_v1.models import PrivateV1Decision
from dmf_pulse.private_v1.presentation import PresentationModel


class AnalysisOptimizerEvidence(PresentationModel):
    schema_version: Literal["derived-optimizer-evidence-v1"] = "derived-optimizer-evidence-v1"
    decision_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    optimiser_result: MultiGameweekOptimisationResult

    @model_validator(mode="after")
    def success_only(self) -> Self:
        if self.optimiser_result.status is not MultiGameweekResultStatus.SUCCESS or (
            self.optimiser_result.error_code is not None
            or self.optimiser_result.error_message is not None
        ):
            raise ValueError("ANALYSIS_OPTIMIZER_SUCCESS_REQUIRED")
        verify_result_hash(self.optimiser_result)
        return self

    def require_bound_to(self, decision: PrivateV1Decision) -> None:
        checked = type(self).model_validate_json(self.model_dump_json())
        if (
            checked.decision_sha256 != decision.semantic_sha256
            or checked.optimiser_result.result_sha256 != decision.lineage.optimiser_result_sha256
            or checked.optimiser_result.lineage.request_sha256
            != decision.lineage.optimiser_request_sha256
        ):
            raise ValueError("ANALYSIS_OPTIMIZER_DECISION_BINDING_INVALID")

    @property
    def semantic_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))
