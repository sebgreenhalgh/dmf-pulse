"""Bounded owner review packages; proposed metadata never becomes runtime authority."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.dashboard.authorization import QualifiedPlanQuota, SourceScope
from dmf_pulse.operation.models import Metadata, MetadataTime, OperationError, Ref, Sha


class PilotProposal(Metadata):
    schema_version: Literal["operator-pilot-proposal-v1"] = "operator-pilot-proposal-v1"
    authorization_id: Annotated[str, Field(pattern=r"^ACCEL00[45]-PILOT-[A-Za-z0-9_.:-]{1,80}$")]
    classification: Literal["PRIVATE_CURRENT"] = "PRIVATE_CURRENT"
    operator_ref: Ref | None = None
    entry_id: Annotated[int, Field(ge=1)] | None = None
    season_code: Literal["2026/27"] = "2026/27"
    qualified_deadline_at: datetime | None = None
    owner_approval_evidence_sha256: Sha | None = None
    account_entitlement_evidence_sha256: Sha | None = None
    project_rights_review_sha256: Sha | None = None
    implementation_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] | None = None
    wheel_sha256: Sha | None = None
    source_scopes: tuple[SourceScope, ...] = ()
    plan_quota: QualifiedPlanQuota | None = None
    ledger_id: Sha | None = None
    control_receipt_sha256: Sha | None = None
    control_metadata_retention_approved: bool = False

    @model_validator(mode="after")
    def exact_partial_scope(self) -> Self:
        if self.source_scopes and (
            len(self.source_scopes) != 3
            or {row.provider for row in self.source_scopes} != {"FPL", "ODDS", "OPENFOOTBALL"}
            or any(row.source_kind != "RIGHTS_QUALIFIED_PRIVATE" for row in self.source_scopes)
        ):
            raise ValueError("proposal needs all three exact private source scopes or none")
        if self.plan_quota is not None and self.source_scopes:
            odds = next(row for row in self.source_scopes if row.provider == "ODDS")
            if odds.account_ref != self.plan_quota.account_ref:
                raise ValueError("proposal account identity differs")
        return self


class OwnerPackage(Metadata):
    schema_version: Literal["operator-owner-package-v1"] = "operator-owner-package-v1"
    prepared_at: datetime
    proposal: PilotProposal
    state: Literal["INCOMPLETE", "READY_FOR_INDEPENDENT_OWNER_REVIEW"]
    blockers: tuple[Ref, ...]
    usage: Literal["ONE_SHOT"] = "ONE_SHOT"
    horizon: Literal[1] = 1
    mode: Literal["MARKET_PRIMARY"] = "MARKET_PRIMARY"
    sport: Literal["soccer_epl"] = "soccer_epl"
    regions: Literal["uk"] = "uk"
    markets: tuple[Literal["h2h", "totals"], Literal["h2h", "totals"]] = ("h2h", "totals")
    odds_gets: Literal[1] = 1
    reserved_odds_credits: Literal[2] = 2
    automatic_retries: Literal[0] = 0
    proposed_daily_requests: Literal[1] = 1
    proposed_monthly_requests: Literal[1] = 1
    proposed_daily_credits: Literal[2] = 2
    proposed_monthly_credits: Literal[2] = 2
    runtime_authority: Literal["NOT_GRANTED"] = "NOT_GRANTED"
    installation: Literal["REVIEWED_FIXED_RESOURCE_IN_NEW_WHEEL_REQUIRED"] = (
        "REVIEWED_FIXED_RESOURCE_IN_NEW_WHEEL_REQUIRED"
    )

    @model_validator(mode="after")
    def genuine_pending_state(self) -> Self:
        expected = _blockers(self.proposal, self.prepared_at)
        if self.blockers != expected or (self.state == "INCOMPLETE") != bool(expected):
            raise ValueError("package status differs from actual missing metadata")
        if self.markets != ("h2h", "totals"):
            raise ValueError("pilot markets are exact")
        return self


def _blockers(proposal: PilotProposal, now: datetime) -> tuple[str, ...]:
    required = {
        "operator_ref": "OPERATOR_IDENTITY_REQUIRED",
        "entry_id": "MANAGER_SCOPE_REQUIRED",
        "qualified_deadline_at": "QUALIFIED_DEADLINE_REQUIRED",
        "owner_approval_evidence_sha256": "OWNER_APPROVAL_REQUIRED",
        "account_entitlement_evidence_sha256": "ACCOUNT_ENTITLEMENT_REQUIRED",
        "project_rights_review_sha256": "PROJECT_RIGHTS_REVIEW_REQUIRED",
        "implementation_sha": "EXACT_IMPLEMENTATION_REQUIRED",
        "wheel_sha256": "EXACT_WHEEL_REQUIRED",
        "source_scopes": "EXACT_SOURCE_SCOPES_REQUIRED",
        "plan_quota": "QUALIFIED_PLAN_QUOTA_REQUIRED",
        "ledger_id": "CANONICAL_LEDGER_REQUIRED",
        "control_receipt_sha256": "CONTROL_RECEIPT_REQUIRED",
        "control_metadata_retention_approved": "CONTROL_RETENTION_PERMISSION_REQUIRED",
    }
    result = [reason for field, reason in required.items() if not getattr(proposal, field)]
    if proposal.qualified_deadline_at is not None and proposal.qualified_deadline_at <= now:
        result.append("QUALIFIED_DEADLINE_EXPIRED")
    if proposal.plan_quota is not None and (
        not proposal.plan_quota.observed_at <= now < proposal.plan_quota.resets_at
        or proposal.plan_quota.remaining_credits < 2
        or proposal.plan_quota.allocated_monthly_credits < 2
    ):
        result.append("QUALIFIED_PLAN_QUOTA_UNUSABLE")
    return tuple(result)


def prepare_pilot(proposal: PilotProposal, *, now: datetime) -> OwnerPackage:
    proposal = PilotProposal.model_validate(proposal)
    # Validate the clock before comparing any dates.
    now = MetadataTime(checked_at=now).checked_at
    blockers = _blockers(proposal, now)
    return OwnerPackage(
        prepared_at=now,
        proposal=proposal,
        blockers=blockers,
        state="INCOMPLETE" if blockers else "READY_FOR_INDEPENDENT_OWNER_REVIEW",
    )


def write_metadata(path: Path, value: Metadata) -> str:
    """Create one immutable authenticated metadata artifact, never overwrite."""
    envelope = {"payload": value.model_dump(mode="json"), "semantic_sha256": value.semantic_sha256}
    body = canonical_json_bytes(envelope) + b"\n"
    return _write_body(path, body)


def write_nonexecuting_input(path: Path, value: Metadata) -> str:
    """Create an editable evidence draft, with no approval or integrity claim."""
    return _write_body(path, canonical_json_bytes(value.model_dump(mode="json")) + b"\n")


def _write_body(path: Path, body: bytes) -> str:
    if len(body) > 131072 or path.is_symlink():
        raise OperationError("OPERATOR_ARTIFACT_INVALID")
    try:
        with path.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError):
        raise OperationError("OPERATOR_ARTIFACT_WRITE_FAILED") from None
    return hashlib.sha256(body).hexdigest()


def _read_metadata_scope[T: Metadata](
    path: Path, contract: type[T], *, sealed: bool = True
) -> T | None:
    """Discard invalid bytes and parser exception frames before a public error exists."""

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate metadata field")
            result[key] = value
        return result

    try:
        if path.is_symlink():
            raise ValueError("metadata symlink is unsupported")
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(os.open(path, flags), "rb") as stream:
            descriptor = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(descriptor.st_mode)
                or descriptor.st_size > 131072
                or path.is_symlink()
            ):
                raise ValueError("metadata requires a bounded regular file")
            body = stream.read(131073)
        if len(body) > 131072:
            raise ValueError("metadata file exceeds bound")
        value = json.loads(body, object_pairs_hook=unique)
        if not sealed:
            return contract.model_validate_json(json.dumps(value, allow_nan=False))
        if not isinstance(value, dict) or set(value) != {"payload", "semantic_sha256"}:
            raise ValueError("metadata envelope differs")
        result = contract.model_validate_json(json.dumps(value["payload"], allow_nan=False))
        if value["semantic_sha256"] != canonical_sha256(result.model_dump(mode="json")):
            raise ValueError("metadata hash differs")
        return result
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def read_metadata[T: Metadata](path: Path, contract: type[T]) -> T:
    """Authenticate bounded metadata; failed parser payloads cannot escape as context."""
    result = _read_metadata_scope(path, contract)
    if result is None:
        raise OperationError("OPERATOR_ARTIFACT_INVALID")
    return result


def read_nonexecuting_input[T: Metadata](path: Path, contract: type[T]) -> T:
    """Read an editable local evidence draft; integrity or approval is not inferred."""
    result = _read_metadata_scope(path, contract, sealed=False)
    if result is None:
        raise OperationError("OPERATOR_ARTIFACT_INVALID")
    return result
