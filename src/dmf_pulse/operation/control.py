"""Explicit canonical control setup and read-only recovery, with injected connections."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import field_validator, model_validator

from dmf_pulse.dashboard.authorization import Classification, LedgerAudit
from dmf_pulse.dashboard.postgres_authorization import (
    ConnectionFactory,
    DatabaseRef,
    PostgresUsageLedger,
)
from dmf_pulse.operation.models import Metadata, MetadataTime, OperationError, Ref, Sha


class _ControlRequest(Metadata):
    classification: Classification
    account_ref: Ref
    operator_ref: Ref
    database_ref: DatabaseRef
    control_metadata_retention_approved: Literal[True]
    control_permission_evidence_sha256: Sha

    @field_validator("control_metadata_retention_approved", mode="before")
    @classmethod
    def explicit_permission(cls, value: object) -> object:
        if value is not True:
            raise ValueError("control metadata permission requires explicit boolean true")
        return value

    @model_validator(mode="after")
    def exact_selector(self) -> Self:
        if (
            self.classification == "PRIVATE_CURRENT"
            and self.database_ref != "OPERATOR_CONTROL_DATABASE"
        ):
            raise ValueError("private control setup requires the operator database")
        return self


class ControlSetupRequest(_ControlRequest):
    schema_version: Literal["operator-control-setup-v1"] = "operator-control-setup-v1"


class ControlRecoveryRequest(_ControlRequest):
    schema_version: Literal["operator-control-recovery-v1"] = "operator-control-recovery-v1"
    ledger_id: Sha


class ControlReceipt(Metadata):
    schema_version: Literal["operator-control-receipt-v1"] = "operator-control-receipt-v1"
    action: Literal["INITIALIZE", "RECOVER"]
    classification: Classification
    database_ref: DatabaseRef
    request_sha256: Sha
    checked_at: datetime
    audit: LedgerAudit
    provider_authority: Literal["NOT_GRANTED"] = "NOT_GRANTED"


def init_control(
    request: ControlSetupRequest,
    factory: ConnectionFactory,
    *,
    now: datetime,
) -> ControlReceipt:
    """Explicit metadata admin action; initialization cannot select/reset a ledger ID."""
    # Revalidate rather than accepting a model_construct/model_copy bypass.
    request = ControlSetupRequest.model_validate(request)
    receipt_time = MetadataTime(checked_at=now)
    ledger = PostgresUsageLedger.initialize(
        factory,
        account_ref=request.account_ref,
        database_ref=request.database_ref,
    )
    return ControlReceipt(
        action="INITIALIZE",
        classification=request.classification,
        database_ref=request.database_ref,
        request_sha256=request.semantic_sha256,
        checked_at=receipt_time.checked_at,
        audit=ledger.audit(),
    )


def recover_control(
    request: ControlRecoveryRequest,
    factory: ConnectionFactory,
    *,
    now: datetime,
) -> ControlReceipt:
    """Authenticate the configured account/history only; never initialize or append."""
    request = ControlRecoveryRequest.model_validate(request)
    receipt_time = MetadataTime(checked_at=now)
    ledger = PostgresUsageLedger(
        factory,
        request.ledger_id,
        account_ref=request.account_ref,
        database_ref=request.database_ref,
    )
    audit = ledger.audit()
    if audit.ledger_id != request.ledger_id:
        raise OperationError("CONTROL_RECOVERY_IDENTITY_MISMATCH")
    return ControlReceipt(
        action="RECOVER",
        classification=request.classification,
        database_ref=request.database_ref,
        request_sha256=request.semantic_sha256,
        checked_at=receipt_time.checked_at,
        audit=audit,
    )
