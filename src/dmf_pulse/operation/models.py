"""Strict metadata-only operator readiness, without inferred approvals."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256

Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Ref = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")]
Stage = Literal[
    "ENGINEERING_READY",
    "CREDENTIALS_CONFIGURED",
    "ACCOUNT_ENTITLEMENT_VERIFIED",
    "PROJECT_RIGHTS_APPROVED",
    "CONTROL_LEDGER_READY",
    "LIVE_PILOT_AUTHORIZED",
    "LIVE_PILOT_EXECUTED",
    "PRODUCTION_ACTIVE",
]
STAGES: tuple[Stage, ...] = (
    "ENGINEERING_READY",
    "CREDENTIALS_CONFIGURED",
    "ACCOUNT_ENTITLEMENT_VERIFIED",
    "PROJECT_RIGHTS_APPROVED",
    "CONTROL_LEDGER_READY",
    "LIVE_PILOT_AUTHORIZED",
    "LIVE_PILOT_EXECUTED",
    "PRODUCTION_ACTIVE",
)


class OperationError(ValueError):
    """A bounded code; never expose source bodies, paths, secrets or driver errors."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Metadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        revalidate_instances="always",
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def utc_times(self) -> Self:
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError("operator timestamps require a UTC offset")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self

    @property
    def semantic_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class StageCheck(Metadata):
    stage: Stage
    state: Literal["NOT_CHECKED", "VERIFIED", "BLOCKED", "EXPIRED"] = "NOT_CHECKED"
    reason_code: Ref = "EXPLICIT_CHECK_REQUIRED"
    evidence_sha256: tuple[Sha, ...] = ()
    checked_at: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def meaningful_state(self) -> Self:
        if (self.state == "NOT_CHECKED") != (self.checked_at is None):
            raise ValueError("checked stages need an actual observation time")
        if self.state == "VERIFIED" and not self.evidence_sha256:
            raise ValueError("verified stages require authenticated metadata evidence")
        if self.valid_until is not None:
            if self.checked_at is None:
                raise ValueError("stage validity needs an actual observation")
            if self.state == "VERIFIED" and self.valid_until <= self.checked_at:
                raise ValueError("stage validity window is empty")
            if self.state == "EXPIRED" and self.valid_until > self.checked_at:
                raise ValueError("stage expiry is in the future")
        return self


class OperatorReadiness(Metadata):
    schema_version: Literal["operator-readiness-v1"] = "operator-readiness-v1"
    observed_at: datetime
    checks: tuple[StageCheck, ...]

    @model_validator(mode="after")
    def exact_stages(self) -> Self:
        if tuple(row.stage for row in self.checks) != STAGES:
            raise ValueError("readiness needs all eight stages in their canonical order")
        if any(
            row.checked_at is not None and row.checked_at > self.observed_at for row in self.checks
        ):
            raise ValueError("readiness contains a future observation")
        if self.checks[-1].state == "VERIFIED":
            raise ValueError("production activation is outside this programme")
        if any(
            row.state == "VERIFIED"
            and row.valid_until is not None
            and row.valid_until <= self.observed_at
            for row in self.checks
        ):
            raise ValueError("readiness cannot retain an expired verified stage")
        return self


class CredentialObservation(Metadata):
    """Explicit local presence metadata; this cannot establish entitlement or rights."""

    provider: Literal["odds", "fpl"]
    configured: bool
    state: Literal["CONFIGURED", "MISSING", "EXPIRED", "UNAVAILABLE", "CORRUPT"]

    @model_validator(mode="after")
    def coherent_presence(self) -> Self:
        if self.configured != (self.state == "CONFIGURED"):
            raise ValueError("credential presence metadata differs")
        return self


def readiness(
    *,
    now: datetime,
    checks: tuple[StageCheck, ...] = (),
    credentials: tuple[CredentialObservation, ...] | None = None,
) -> OperatorReadiness:
    """Pure composition. The caller must explicitly obtain any credential observation."""
    if len({row.stage for row in checks}) != len(checks):
        raise OperationError("DUPLICATE_READINESS_STAGE")
    rows = {row.stage: row for row in checks}
    if credentials is not None:
        if len(credentials) != 2 or {row.provider for row in credentials} != {"odds", "fpl"}:
            raise OperationError("EXACT_CREDENTIAL_METADATA_REQUIRED")
        if "CREDENTIALS_CONFIGURED" in rows:
            raise OperationError("DUPLICATE_READINESS_STAGE")
        configured = all(row.configured for row in credentials)
        rows["CREDENTIALS_CONFIGURED"] = StageCheck(
            stage="CREDENTIALS_CONFIGURED",
            state="VERIFIED" if configured else "BLOCKED",
            reason_code="LOCAL_CREDENTIAL_PRESENCE_ONLY"
            if configured
            else "CREDENTIAL_UNAVAILABLE",
            checked_at=now,
            evidence_sha256=(
                canonical_sha256([row.model_dump(mode="json") for row in credentials]),
            ),
        )
    return OperatorReadiness(
        observed_at=now, checks=tuple(rows.get(stage, StageCheck(stage=stage)) for stage in STAGES)
    )
