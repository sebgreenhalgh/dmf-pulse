"""Hash-only prospective receipt for later Stage-12 evaluation without FPL content."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.evaluation.models import DatasetMode, ObservationRole, require_utc


class ProspectiveDecisionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    schema_version: Literal["gw1-prospective-receipt-v1"] = "gw1-prospective-receipt-v1"
    contract: Literal["EVAL012_GW1_PROSPECTIVE_METADATA"] = "EVAL012_GW1_PROSPECTIVE_METADATA"
    dataset_mode: Literal[DatasetMode.LIVE_OBSERVED] = DatasetMode.LIVE_OBSERVED
    observation_role: Literal[ObservationRole.METADATA] = ObservationRole.METADATA
    rights_classification: Literal["PERMITTED_HASH_ONLY_METADATA"] = "PERMITTED_HASH_ONLY_METADATA"
    gameweek: Literal[1] = 1
    recorded_at: datetime
    information_cutoff: datetime
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    ruleset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manager_capability_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    session1_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    availability_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gameweek_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    detailed_fpl_content_persisted: Literal[False] = False
    raw_provider_content_persisted: Literal[False] = False
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        recorded = require_utc(self.recorded_at, field_name="recorded_at")
        cutoff = require_utc(self.information_cutoff, field_name="information_cutoff")
        if cutoff > recorded or self.receipt_sha256 != _receipt_sha256(self):
            raise ValueError("prospective receipt time or identity is inconsistent")
        return self


def _receipt_sha256(value: ProspectiveDecisionReceipt) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"receipt_sha256"}))


def build_prospective_receipt(
    *,
    recorded_at: datetime,
    information_cutoff: datetime,
    code_commit: str,
    ruleset_hash: str,
    manager_capability_hash: str,
    session1_semantic_sha256: str,
    market_semantic_sha256: str,
    availability_semantic_sha256: str,
    event_semantic_sha256: str,
    projection_config_sha256: str,
    projection_semantic_sha256: str,
    gameweek_result_sha256: str,
    scenario_set_sha256: str,
    decision_sha256: str,
) -> ProspectiveDecisionReceipt:
    require_utc(recorded_at, field_name="recorded_at")
    require_utc(information_cutoff, field_name="information_cutoff")
    values = dict(
        recorded_at=recorded_at.astimezone(UTC),
        information_cutoff=information_cutoff.astimezone(UTC),
        code_commit=code_commit,
        ruleset_hash=ruleset_hash,
        manager_capability_hash=manager_capability_hash,
        session1_semantic_sha256=session1_semantic_sha256,
        market_semantic_sha256=market_semantic_sha256,
        availability_semantic_sha256=availability_semantic_sha256,
        event_semantic_sha256=event_semantic_sha256,
        projection_config_sha256=projection_config_sha256,
        projection_semantic_sha256=projection_semantic_sha256,
        gameweek_result_sha256=gameweek_result_sha256,
        scenario_set_sha256=scenario_set_sha256,
        decision_sha256=decision_sha256,
    )
    provisional = ProspectiveDecisionReceipt.model_construct(
        **values,  # type: ignore[arg-type]
        receipt_sha256="0" * 64,
    )
    return ProspectiveDecisionReceipt.model_validate(
        {**values, "receipt_sha256": _receipt_sha256(provisional)}
    )


def persist_prospective_receipt(
    receipt: ProspectiveDecisionReceipt, *, artifact_root: Path
) -> Path:
    """Persist only hash metadata at a content-addressed, no-overwrite path."""

    validated = ProspectiveDecisionReceipt.model_validate_json(receipt.model_dump_json())
    root = artifact_root.resolve()
    destination = (root / "gw1" / validated.receipt_sha256 / "receipt.json").resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ValueError("prospective receipt path escapes its artifact root") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            validated.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    if destination.exists():
        if destination.read_bytes() != payload:
            raise FileExistsError("prospective receipt path already contains different bytes")
        return destination
    with destination.open("xb") as handle:
        handle.write(payload)
    return destination


__all__ = [
    "ProspectiveDecisionReceipt",
    "build_prospective_receipt",
    "persist_prospective_receipt",
]
