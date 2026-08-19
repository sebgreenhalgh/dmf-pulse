"""Content-addressed Stage-14 decision artifacts and tamper validation."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictStr, model_validator

from dmf_pulse.chips.definitions import FrozenModel, Sha256, semantic_sha256
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.schedule_models import require_utc
from dmf_pulse.chips.service import evaluate_chip_opportunities
from dmf_pulse.chips.service_models import ChipDecisionSet, ChipServiceRequest
from dmf_pulse.evaluation.artifacts import load_verified_artifact, persist_artifact
from dmf_pulse.evaluation.errors import EvaluationError


class Stage14DecisionArtifact(FrozenModel):
    """Frozen prospective chip decision/scenario-window artifact."""

    schema_version: Literal["stage14-chip-decision-v1"] = "stage14-chip-decision-v1"
    artifact_id: StrictStr = Field(min_length=1)
    issued_at: datetime
    service_request: ChipServiceRequest
    decision_set: ChipDecisionSet
    prospective_stage12_eligible: Literal[True] = True
    historical_cutoff_only: Literal[True] = True
    artifact_hash: Sha256

    @model_validator(mode="after")
    def artifact_is_coherent(self) -> Stage14DecisionArtifact:
        issued = require_utc(self.issued_at, field_name="issued_at")
        if issued != self.service_request.forecast_origin:
            raise ValueError("Stage-14 artifact issue time differs from forecast freeze")
        if self.decision_set.request_hash != self.service_request.service_request_hash:
            raise ValueError("Stage-14 artifact decision is not bound to its request")
        if self.decision_set.lineage.information_cutoff != self.service_request.information_cutoff:
            raise ValueError("Stage-14 artifact lineage cutoff differs from its request")
        if self.artifact_id != artifact_identity(self.service_request):
            raise ValueError("Stage-14 artifact identity is not deterministic")
        payload = self.model_dump(mode="json", exclude={"artifact_hash"})
        if self.artifact_hash != "0" * 64 and semantic_sha256(payload) != self.artifact_hash:
            raise ValueError("Stage-14 artifact semantic hash mismatch")
        return self


def artifact_identity(request: ChipServiceRequest) -> str:
    """Return a deterministic portable identity for one semantic service input."""

    decision = re.sub(r"[^A-Za-z0-9._-]+", "-", request.decision_id).strip("-.")
    decision = decision[:96] or "decision"
    return f"{decision}-{request.service_request_hash[:24]}"


def seal_decision_artifact(
    request: ChipServiceRequest,
    decision_set: ChipDecisionSet | None = None,
) -> Stage14DecisionArtifact:
    """Evaluate and seal a prospective Stage-14 decision artifact."""

    checked_request = ChipServiceRequest.model_validate(request.model_dump(mode="python"))
    evaluated = decision_set or evaluate_chip_opportunities(checked_request)
    checked_decision = ChipDecisionSet.model_validate(evaluated.model_dump(mode="python"))
    value = Stage14DecisionArtifact(
        artifact_id=artifact_identity(checked_request),
        issued_at=checked_request.forecast_origin,
        service_request=checked_request,
        decision_set=checked_decision,
        artifact_hash="0" * 64,
    )
    payload = value.model_dump(mode="json", exclude={"artifact_hash"})
    return Stage14DecisionArtifact.model_validate(
        value.model_copy(update={"artifact_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def verify_decision_artifact(value: Stage14DecisionArtifact) -> None:
    """Independently recompute service semantics and every hash relationship."""

    checked = Stage14DecisionArtifact.model_validate(value.model_dump(mode="python"))
    expected = evaluate_chip_opportunities(checked.service_request)
    if expected.model_dump(mode="json") != checked.decision_set.model_dump(mode="json"):
        raise ChipError(
            "CHIP_ARTIFACT_DECISION_MISMATCH",
            "Stage-14 artifact decision differs from independent service recomputation",
        )
    payload = checked.model_dump(mode="json", exclude={"artifact_hash"})
    if semantic_sha256(payload) != checked.artifact_hash:
        raise ChipError(
            "CHIP_ARTIFACT_SEMANTIC_HASH_MISMATCH",
            "Stage-14 artifact semantic hash does not match",
        )


def persist_decision_artifact(
    value: Stage14DecisionArtifact,
    *,
    artifact_root: Path,
) -> Path:
    """Persist through the existing Stage-12 immutable artifact infrastructure."""

    checked = Stage14DecisionArtifact.model_validate(value.model_dump(mode="python"))
    verify_decision_artifact(checked)
    try:
        return persist_artifact(
            checked,
            artifact_root=artifact_root,
            category="chips",
            identity=checked.artifact_id,
        )
    except EvaluationError as exc:
        raise ChipError(
            f"CHIP_ARTIFACT_{exc.code}",
            exc.message,
        ) from exc


def load_decision_artifact(path: Path) -> Stage14DecisionArtifact:
    """Load with Stage-12 validators, then independently recompute chip semantics."""

    try:
        value = load_verified_artifact(path, Stage14DecisionArtifact)
    except EvaluationError as exc:
        code = {
            "EVALUATION_ARTIFACT_HASH_MISMATCH": "CHIP_ARTIFACT_HASH_MISMATCH",
            "EVALUATION_ARTIFACT_CONTENT_ADDRESS_MISMATCH": ("CHIP_ARTIFACT_HASH_MISMATCH"),
        }.get(exc.code, f"CHIP_ARTIFACT_{exc.code}")
        raise ChipError(code, exc.message) from exc
    verify_decision_artifact(value)
    return value


__all__ = [
    "Stage14DecisionArtifact",
    "artifact_identity",
    "load_decision_artifact",
    "persist_decision_artifact",
    "seal_decision_artifact",
    "verify_decision_artifact",
]
