"""Content-addressed Stage-15 decision artifacts and tamper validation."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictStr, model_validator

from dmf_pulse.evaluation.artifacts import (
    hash_without,
    load_verified_artifact,
    persist_artifact,
)
from dmf_pulse.evaluation.errors import EvaluationError
from dmf_pulse.prices.models import require_utc
from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.models import RankModel, Sha256
from dmf_pulse.rank_strategy.service import evaluate_rank_plans
from dmf_pulse.rank_strategy.service_models import RankServiceRequest, RankServiceResult

_ZERO_HASH = "0" * 64


class Stage15DecisionArtifact(RankModel):
    """Frozen rank-aware plan comparison with complete executable lineage."""

    schema_version: Literal["stage15-rank-decision-v1"] = "stage15-rank-decision-v1"
    artifact_id: StrictStr = Field(min_length=1, max_length=240)
    issued_at: datetime
    service_request: RankServiceRequest
    service_result: RankServiceResult
    raw_projections_preserved: Literal[True] = True
    automatic_fpl_execution_permitted: Literal[False] = False
    artifact_hash: Sha256

    @model_validator(mode="after")
    def artifact_is_coherent(self) -> Stage15DecisionArtifact:
        issued = require_utc(self.issued_at, field_name="issued_at")
        if issued != self.service_request.forecast_origin:
            raise ValueError("Stage-15 artifact issue time differs from forecast origin")
        if self.service_result.request_hash != self.service_request.service_request_hash:
            raise ValueError("Stage-15 artifact result is not bound to its request")
        if (
            self.service_result.raw_projection_hash
            != self.service_request.lineage.raw_projection_hash
        ):
            raise ValueError("Stage-15 artifact raw projection lineage differs")
        if self.service_result.scenario_set_hash != self.service_request.lineage.scenario_set_hash:
            raise ValueError("Stage-15 artifact scenario lineage differs")
        if self.artifact_id != artifact_identity(self.service_request):
            raise ValueError("Stage-15 artifact identity is not deterministic")
        expected_hash = hash_without(self, "artifact_hash")
        if self.artifact_hash != _ZERO_HASH and expected_hash != self.artifact_hash:
            raise ValueError("Stage-15 artifact semantic hash mismatch")
        return self


def artifact_identity(request: RankServiceRequest) -> str:
    """Return a portable deterministic identity for one service request."""

    request_id = re.sub(r"[^A-Za-z0-9._-]+", "-", request.request_id).strip("-.")
    request_id = request_id[:96] or "rank-decision"
    return f"{request_id}-{request.service_request_hash[:24]}"


def seal_decision_artifact(
    request: RankServiceRequest,
    result: RankServiceResult | None = None,
) -> Stage15DecisionArtifact:
    """Evaluate and seal one immutable Stage-15 decision artifact."""

    checked_request = RankServiceRequest.model_validate(request.model_dump(mode="python"))
    evaluated = result or evaluate_rank_plans(checked_request)
    checked_result = RankServiceResult.model_validate(evaluated.model_dump(mode="python"))
    value = Stage15DecisionArtifact(
        artifact_id=artifact_identity(checked_request),
        issued_at=checked_request.forecast_origin,
        service_request=checked_request,
        service_result=checked_result,
        artifact_hash=_ZERO_HASH,
    )
    return Stage15DecisionArtifact.model_validate(
        value.model_copy(update={"artifact_hash": hash_without(value, "artifact_hash")}).model_dump(
            mode="python"
        )
    )


def verify_decision_artifact(value: Stage15DecisionArtifact) -> None:
    """Recompute the service result and every semantic relationship independently."""

    checked = Stage15DecisionArtifact.model_validate(value.model_dump(mode="python"))
    expected = evaluate_rank_plans(checked.service_request)
    if expected.model_dump(mode="json") != checked.service_result.model_dump(mode="json"):
        raise RankStrategyError(
            "RANK_ARTIFACT_DECISION_MISMATCH",
            "Stage-15 artifact result differs from independent service recomputation",
        )
    if hash_without(checked, "artifact_hash") != checked.artifact_hash:
        raise RankStrategyError(
            "RANK_ARTIFACT_SEMANTIC_HASH_MISMATCH",
            "Stage-15 artifact semantic hash does not match",
        )


def persist_decision_artifact(
    value: Stage15DecisionArtifact,
    *,
    artifact_root: Path,
) -> Path:
    """Persist through the accepted immutable content-addressed infrastructure."""

    checked = Stage15DecisionArtifact.model_validate(value.model_dump(mode="python"))
    verify_decision_artifact(checked)
    try:
        return persist_artifact(
            checked,
            artifact_root=artifact_root,
            category="rank-strategy",
            identity=checked.artifact_id,
        )
    except EvaluationError as exc:
        raise RankStrategyError(f"RANK_ARTIFACT_{exc.code}", exc.message) from exc


def load_decision_artifact(path: Path) -> Stage15DecisionArtifact:
    """Load detached-hash-protected bytes and independently recompute semantics."""

    try:
        value = load_verified_artifact(
            path,
            Stage15DecisionArtifact,
            hash_field="artifact_hash",
        )
    except EvaluationError as exc:
        raise RankStrategyError(f"RANK_ARTIFACT_{exc.code}", exc.message) from exc
    verify_decision_artifact(value)
    return value


__all__ = [
    "Stage15DecisionArtifact",
    "artifact_identity",
    "load_decision_artifact",
    "persist_decision_artifact",
    "seal_decision_artifact",
    "verify_decision_artifact",
]
