"""Reviewed refresh scope and durable, secret-free acquisition reservations.

No production approvals are enrolled. An operator JSON document is never an
approval registry. Owned-source injection remains explicitly synthetic.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_hex
from typing import Annotated, Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.authorization_errors import AuthorizationError as AuthorizationError
from dmf_pulse.authorization_errors import AuthorizationState

Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Ref = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")]
Provider = Literal["FPL", "ODDS", "OPENFOOTBALL"]
Classification = Literal["OWNED_SYNTHETIC", "PRIVATE_CURRENT"]
State = AuthorizationState


class _Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        revalidate_instances="always",
    )

    @model_validator(mode="after")
    def aware_times(self) -> Self:
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError("authorization times must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        del deep
        values = {name: getattr(self, name) for name in type(self).model_fields}
        if update:
            values.update(update)
        return type(self).model_validate(values)


class RouteBudget(_Contract):
    method: Literal["GET"] = "GET"
    host: str = Field(pattern=r"^[a-z0-9.-]+$", max_length=120)
    path: str = Field(pattern=r"^/[A-Za-z0-9_./-]+$", max_length=240)
    maximum_calls: int = Field(ge=1, le=32)


class SourceScope(_Contract):
    provider: Provider
    account_ref: Ref
    profile_id: Ref
    profile_sha256: Sha
    source_kind: Literal["REPOSITORY_OWNED_SYNTHETIC", "RIGHTS_QUALIFIED_PRIVATE"]
    routes: Annotated[tuple[RouteBudget, ...], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def exact_routes(self) -> Self:
        identities = [(row.method, row.host, row.path) for row in self.routes]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate source route")
        if self.provider == "ODDS" and (
            len(self.routes) != 1
            or self.routes[0]
            != RouteBudget(
                host="api.the-odds-api.com",
                path="/v4/sports/soccer_epl/odds",
                maximum_calls=1,
            )
        ):
            raise ValueError("Odds scope must be the single accepted EPL odds route")
        return self


class QualifiedPlanQuota(_Contract):
    account_ref: Ref
    plan_ref: Ref
    evidence_sha256: Sha
    terms_evidence_sha256: Sha
    monthly_plan_credits: int = Field(ge=2)
    allocated_monthly_credits: int = Field(ge=2)
    remaining_credits: int = Field(ge=0)
    observed_at: datetime
    period_started_at: datetime
    resets_at: datetime

    @model_validator(mode="after")
    def coherent_balance(self) -> Self:
        if not self.period_started_at <= self.observed_at < self.resets_at:
            raise ValueError("quota observation outside its qualified reset window")
        if (
            self.allocated_monthly_credits > self.monthly_plan_credits
            or self.remaining_credits > self.monthly_plan_credits
        ):
            raise ValueError("quota or allocation exceeds qualified account plan")
        return self


class OperatorRefreshApproval(_Contract):
    schema_version: Literal["operator-refresh-approval-v1"] = "operator-refresh-approval-v1"
    authorization_id: Ref
    classification: Classification
    approval_evidence_sha256: Sha
    implementation_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    review_sha256: Sha
    operator_ref: Ref
    purpose: Literal["PRIVATE_OPERATOR_FPL_RECOMMENDATIONS"]
    season_code: Annotated[str, Field(pattern=r"^20[0-9]{2}/[0-9]{2}$")]
    horizons: tuple[Literal[1, 3], ...]
    mode: Literal["MARKET_PRIMARY"] = "MARKET_PRIMARY"
    source_scopes: tuple[SourceScope, ...]
    plan_quota: QualifiedPlanQuota
    ledger_id: Sha
    ledger_backend: Literal["OWNED_JSON", "POSTGRES"] = "OWNED_JSON"
    status: Literal["APPROVED_REVIEWED", "REVOKED"]
    usage: Literal["ONE_SHOT", "MANUAL_RECURRING"]
    approved_at: datetime
    not_before: datetime
    expires_at: datetime
    quota_max_age_seconds: int = Field(ge=1, le=86400)
    max_acquisition_seconds: int = Field(ge=1, le=900)
    max_run_seconds: int = Field(ge=1, le=900)
    qualified_deadline_at: datetime | None = None
    daily_request_limit: int = Field(ge=1)
    daily_credit_limit: int = Field(ge=2)
    monthly_request_limit: int = Field(ge=1)
    monthly_credit_limit: int = Field(ge=2)
    safety_reserve_credits: int = Field(ge=0)
    control_metadata_retention_approved: Literal[True]

    @field_validator("control_metadata_retention_approved", mode="before")
    @classmethod
    def explicit_control_permission(cls, value: object) -> object:
        if value is not True:
            raise ValueError("control metadata permission must be explicit boolean true")
        return value

    @field_validator("horizons", mode="before")
    @classmethod
    def integer_horizons(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, (tuple, list)) and any(type(item) is not int for item in value):
            raise ValueError("horizons require exact integers")
        if info.mode == "json" and isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def complete_scope(self) -> Self:
        if not self.approved_at <= self.not_before < self.expires_at:
            raise ValueError("approval dates are incoherent")
        if not self.horizons or len(set(self.horizons)) != len(self.horizons):
            raise ValueError("explicit unique horizons are required")
        if {row.provider for row in self.source_scopes} != {"FPL", "ODDS", "OPENFOOTBALL"}:
            raise ValueError("exact FPL, Odds and OpenFootball scopes are required")
        if len(self.source_scopes) != 3:
            raise ValueError("duplicate provider scope")
        odds = next(row for row in self.source_scopes if row.provider == "ODDS")
        if odds.account_ref != self.plan_quota.account_ref:
            raise ValueError("quota account differs from Odds account")
        if self.monthly_credit_limit > self.plan_quota.allocated_monthly_credits:
            raise ValueError("owner budget exceeds account allocation")
        if self.daily_credit_limit > self.monthly_credit_limit:
            raise ValueError("daily budget exceeds monthly budget")
        if self.daily_request_limit > self.monthly_request_limit:
            raise ValueError("daily request cap exceeds monthly cap")
        synthetic = self.classification == "OWNED_SYNTHETIC"
        if any(
            (row.source_kind == "REPOSITORY_OWNED_SYNTHETIC") != synthetic
            for row in self.source_scopes
        ):
            raise ValueError("source classification differs from execution classification")
        return self


class RefreshRequest(_Contract):
    authorization_id: Ref
    implementation_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    review_sha256: Sha
    operator_ref: Ref
    purpose: Literal["PRIVATE_OPERATOR_FPL_RECOMMENDATIONS"]
    season_code: Annotated[str, Field(pattern=r"^20[0-9]{2}/[0-9]{2}$")]
    horizon: Literal[1, 3]
    mode: Literal["MARKET_PRIMARY"] = "MARKET_PRIMARY"
    source_scopes: tuple[SourceScope, ...]
    information_cutoff: datetime
    deadline_at: datetime

    @field_validator("horizon", mode="before")
    @classmethod
    def integer_horizon(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("horizon requires an exact integer")
        return value


class RefreshGrant(_Contract):
    schema_version: Literal["operator-refresh-grant-v1"] = "operator-refresh-grant-v1"
    reservation_id: Sha
    ledger_id: Sha
    ledger_backend: Literal["OWNED_JSON", "POSTGRES"] = "OWNED_JSON"
    approval_sha256: Sha
    classification: Classification
    request: RefreshRequest
    issued_at: datetime
    expires_at: datetime
    reserved_odds_requests: Literal[1] = 1
    reserved_odds_credits: Literal[2] = 2

    @property
    def semantic_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def production_approvals() -> tuple[OperatorRefreshApproval, ...]:
    """Load only trusted installed metadata on explicit invocation.

    This exact resource is excluded from the executable content fingerprint to
    avoid its own expected fingerprint being self-referential. Its byte digest
    and the complete wheel/Git identities are bound by detached release review.
    Installation is trusted as it is for executable code; no user path, runtime
    document, browser value or environment setting can enroll approval rows.
    """
    from dmf_pulse.operation.enrollment import installed_enrollment
    from dmf_pulse.operation.models import OperationError

    try:
        return installed_enrollment().approvals
    except OperationError:
        result = None
    if result is None:
        raise AuthorizationError("TRUSTED_APPROVAL_REGISTRY_INVALID")


def _now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise AuthorizationError("AUTHORIZATION_CLOCK_INVALID")
    return value.astimezone(UTC)


def _approved_expiry(
    approval: OperatorRefreshApproval, request: RefreshRequest, issued_at: datetime
) -> datetime:
    """One pure authority check shared by issuer, reservation and child worker."""
    source_expiry = approval.expires_at
    if approval.status != "APPROVED_REVIEWED":
        raise AuthorizationError("AUTHORIZATION_REVOKED")
    if approval.classification == "PRIVATE_CURRENT":
        from dmf_pulse.operation.enrollment import require_source_closure
        from dmf_pulse.operation.models import OperationError

        if approval not in production_approvals():
            raise AuthorizationError("PRODUCTION_APPROVAL_NOT_ENROLLED")
        try:
            source_expiry = require_source_closure(approval.source_scopes, now=issued_at)
        except OperationError as error:
            raise AuthorizationError(error.code, "RIGHTS_APPROVAL_REQUIRED") from None
    if not approval.not_before <= issued_at < approval.expires_at:
        raise AuthorizationError("AUTHORIZATION_EXPIRED", "EXPIRED")
    for name in (
        "authorization_id",
        "implementation_sha",
        "review_sha256",
        "operator_ref",
        "purpose",
        "season_code",
        "mode",
        "source_scopes",
    ):
        if getattr(request, name) != getattr(approval, name):
            raise AuthorizationError("AUTHORIZATION_SCOPE_MISMATCH")
    if request.horizon not in approval.horizons:
        raise AuthorizationError("AUTHORIZATION_HORIZON_NOT_APPROVED")
    if approval.classification == "PRIVATE_CURRENT" and (
        approval.qualified_deadline_at is None
        or request.deadline_at != approval.qualified_deadline_at
    ):
        raise AuthorizationError("AUTHORIZATION_DEADLINE_SCOPE_MISMATCH")
    if not issued_at <= request.information_cutoff < request.deadline_at:
        raise AuthorizationError("AUTHORIZATION_DEADLINE_INVALID", "EXPIRED")
    if request.information_cutoff > issued_at + timedelta(seconds=approval.max_acquisition_seconds):
        raise AuthorizationError("ACQUISITION_WINDOW_EXCEEDED")
    quota = approval.plan_quota
    if (
        not quota.period_started_at <= issued_at < quota.resets_at
        or not quota.observed_at
        <= issued_at
        <= quota.observed_at + timedelta(seconds=approval.quota_max_age_seconds)
    ):
        raise AuthorizationError("QUALIFIED_QUOTA_EVIDENCE_STALE")
    return min(
        source_expiry,
        approval.expires_at,
        request.deadline_at,
        issued_at + timedelta(seconds=approval.max_run_seconds),
    )


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate control record field")
        result[name] = value
    return result


def _read_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or path.stat().st_size > 16384:
        raise AuthorizationError("USAGE_LEDGER_INVALID")
    value = json.loads(path.read_bytes(), object_pairs_hook=_strict_object)
    if not isinstance(value, dict):
        raise AuthorizationError("USAGE_LEDGER_INVALID")
    return cast(dict[str, Any], value)


def _write_new(path: Path, value: dict[str, object]) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_json_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


class LedgerAudit(_Contract):
    """Authenticated control metadata only; no source facts or new execution grant."""

    ledger_id: Sha
    backend: Literal["OWNED_JSON", "POSTGRES"]
    event_count: int = Field(ge=0, le=100000)
    head_sha256: Sha
    reservation_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    check_count: int = Field(ge=0)
    attempt_count: int = Field(ge=0)
    last_event_at: datetime | None


class ReservationBudget(_Contract):
    """Qualified snapshot minus canonical reservations; not a live provider balance."""

    daily_requests_used: int = Field(ge=0)
    monthly_requests_used: int = Field(ge=0)
    daily_requests_available: int = Field(ge=1)
    monthly_requests_available: int = Field(ge=1)
    daily_credits_available: int = Field(ge=2)
    monthly_credits_available: int = Field(ge=2)
    qualified_credits_available: int = Field(ge=2)


class LedgerInspection(_Contract):
    audit: LedgerAudit
    budget: ReservationBudget


class AuthorizationPreview(_Contract):
    """A read-only observation; reserve/claim checks still run at actual Refresh."""

    schema_version: Literal["refresh-authorization-preview-v1"] = "refresh-authorization-preview-v1"
    approval_sha256: Sha
    request_sha256: Sha
    checked_at: datetime
    expires_at: datetime
    ledger: LedgerInspection


class UsageLedger:
    """Shared authorization policy over authenticated atomic storage hooks.

    Backends authenticate identity, sequence/hash chain and complete event rows
    before yielding a transaction. Append must be create-only/atomic, preserve
    the same transaction lock, and durably record the supplied event payload.
    A storage backend cannot expand approval scope or replace these policies.
    """

    def __init__(
        self,
        ledger_id: str,
        *,
        backend: Literal["OWNED_JSON", "POSTGRES"],
        transaction: Callable[[], AbstractContextManager[list[dict[str, Any]]]],
        append: Callable[[list[dict[str, Any]], dict[str, object]], None],
    ) -> None:
        if len(ledger_id) != 64 or any(ch not in "0123456789abcdef" for ch in ledger_id):
            raise AuthorizationError("USAGE_LEDGER_IDENTITY_INVALID")
        if backend not in {"OWNED_JSON", "POSTGRES"}:
            raise AuthorizationError("USAGE_LEDGER_BACKEND_INVALID")
        self.ledger_id = ledger_id
        self.backend_discriminator = backend
        self._transaction = transaction
        self._append = append

    @staticmethod
    def _clock(records: list[dict[str, Any]], now: datetime) -> None:
        if records and now < datetime.fromisoformat(str(records[-1]["at"])):
            raise AuthorizationError("AUTHORIZATION_CLOCK_REGRESSED")

    def _audit(self, records: list[dict[str, Any]]) -> LedgerAudit:
        counts = Counter(row.get("kind") for row in records)
        if set(counts) - {"RESERVATION", "CLAIM", "CHECK", "ATTEMPT"}:
            raise AuthorizationError("USAGE_LEDGER_INVALID")
        return LedgerAudit(
            ledger_id=self.ledger_id,
            backend=self.backend_discriminator,
            event_count=len(records),
            head_sha256=records[-1]["sha256"] if records else "0" * 64,
            reservation_count=counts["RESERVATION"],
            claim_count=counts["CLAIM"],
            check_count=counts["CHECK"],
            attempt_count=counts["ATTEMPT"],
            last_event_at=datetime.fromisoformat(str(records[-1]["at"])) if records else None,
        )

    def audit(self) -> LedgerAudit:
        """Authenticate an existing ledger; never initialize, append or reset it."""
        with self._transaction() as records:
            return self._audit(records)

    @staticmethod
    def _reservation_budget(
        records: list[dict[str, Any]], approval: OperatorRefreshApproval, issued_at: datetime
    ) -> ReservationBudget:
        reservations = [row for row in records if row.get("kind") == "RESERVATION"]
        authorization_hash = canonical_sha256(approval.authorization_id)
        same_approval = [
            row for row in reservations if row["authorization_sha256"] == authorization_hash
        ]
        if approval.usage == "ONE_SHOT" and same_approval:
            raise AuthorizationError("ONE_SHOT_CONSUMED")
        account_hash = canonical_sha256(approval.plan_quota.account_ref)
        account_rows = [row for row in reservations if row["account_sha256"] == account_hash]
        day = issued_at.date().isoformat()
        period = approval.plan_quota.period_started_at.isoformat()
        daily = sum(row["day"] == day for row in account_rows)
        monthly = sum(row["period"] == period for row in account_rows)
        if (
            daily + 1 > approval.daily_request_limit
            or 2 * (daily + 1) > approval.daily_credit_limit
        ):
            raise AuthorizationError("DAILY_BUDGET_EXHAUSTED")
        if (
            monthly + 1 > approval.monthly_request_limit
            or 2 * (monthly + 1) > approval.monthly_credit_limit
        ):
            raise AuthorizationError("MONTHLY_BUDGET_EXHAUSTED")
        since_quota = sum(
            datetime.fromisoformat(str(row["at"])) >= approval.plan_quota.observed_at
            for row in account_rows
        )
        qualified = (
            approval.plan_quota.remaining_credits
            - 2 * since_quota
            - approval.safety_reserve_credits
        )
        if qualified < 2:
            raise AuthorizationError("QUOTA_EXHAUSTED")
        return ReservationBudget(
            daily_requests_used=daily,
            monthly_requests_used=monthly,
            daily_requests_available=approval.daily_request_limit - daily,
            monthly_requests_available=approval.monthly_request_limit - monthly,
            daily_credits_available=approval.daily_credit_limit - 2 * daily,
            monthly_credits_available=approval.monthly_credit_limit - 2 * monthly,
            qualified_credits_available=qualified,
        )

    def preflight(
        self, approval: OperatorRefreshApproval, request: RefreshRequest, *, now: datetime
    ) -> LedgerInspection:
        """Reuse reservation policy under the same authenticated lock without spending."""
        now = _now(lambda: now)
        if (
            approval.classification == "PRIVATE_CURRENT"
            and self.backend_discriminator != "POSTGRES"
        ):
            raise AuthorizationError("PRODUCTION_CONTROL_STORE_NOT_ACCEPTED")
        _approved_expiry(approval, request, now)
        if (
            approval.ledger_id != self.ledger_id
            or approval.ledger_backend != self.backend_discriminator
        ):
            raise AuthorizationError("USAGE_LEDGER_REQUIRED")
        if approval.classification == "PRIVATE_CURRENT" and approval not in production_approvals():
            raise AuthorizationError("PRODUCTION_APPROVAL_NOT_ENROLLED", "RIGHTS_APPROVAL_REQUIRED")
        with self._transaction() as records:
            self._clock(records, now)
            budget = self._reservation_budget(records, approval, now)
            return LedgerInspection(audit=self._audit(records), budget=budget)

    def reserve(self, approval: OperatorRefreshApproval, grant: RefreshGrant) -> None:
        if (
            approval.classification == "PRIVATE_CURRENT"
            and self.backend_discriminator != "POSTGRES"
        ):
            raise AuthorizationError("PRODUCTION_CONTROL_STORE_NOT_ACCEPTED")
        expected_expiry = _approved_expiry(approval, grant.request, grant.issued_at)
        if (
            grant.approval_sha256 != canonical_sha256(approval.model_dump(mode="json"))
            or grant.classification != approval.classification
            or grant.ledger_id != approval.ledger_id
            or grant.ledger_id != self.ledger_id
            or approval.ledger_backend != self.backend_discriminator
            or grant.ledger_backend != self.backend_discriminator
            or grant.request.source_scopes != approval.source_scopes
            or grant.expires_at != expected_expiry
        ):
            raise AuthorizationError("REFRESH_GRANT_INVALID")
        if approval.classification == "PRIVATE_CURRENT" and approval not in production_approvals():
            raise AuthorizationError("PRODUCTION_APPROVAL_NOT_ENROLLED", "RIGHTS_APPROVAL_REQUIRED")
        with self._transaction() as records:
            self._clock(records, grant.issued_at)
            self._reservation_budget(records, approval, grant.issued_at)
            authorization_hash = canonical_sha256(approval.authorization_id)
            account_hash = canonical_sha256(approval.plan_quota.account_ref)
            day = grant.issued_at.date().isoformat()
            period = approval.plan_quota.period_started_at.isoformat()
            self._append(
                records,
                {
                    "kind": "RESERVATION",
                    "at": grant.issued_at.isoformat(),
                    "reservation_id": grant.reservation_id,
                    "grant_sha256": grant.semantic_sha256,
                    "approval_sha256": grant.approval_sha256,
                    "account_sha256": account_hash,
                    "authorization_sha256": authorization_hash,
                    "day": day,
                    "period": period,
                },
            )

    @staticmethod
    def _reservation(records: list[dict[str, Any]], grant: RefreshGrant) -> None:
        rows = [
            row
            for row in records
            if row.get("kind") == "RESERVATION"
            and row.get("reservation_id") == grant.reservation_id
        ]
        if len(rows) != 1 or rows[0]["grant_sha256"] != grant.semantic_sha256:
            raise AuthorizationError("REFRESH_GRANT_INVALID")

    def claim(self, grant: RefreshGrant, worker_id: str, *, now: datetime) -> None:
        self._valid_grant(grant, worker_id, now)
        with self._transaction() as records:
            self._clock(records, now)
            self._reservation(records, grant)
            if any(
                row.get("kind") == "CLAIM" and row.get("reservation_id") == grant.reservation_id
                for row in records
            ):
                raise AuthorizationError("REFRESH_GRANT_ALREADY_CLAIMED")
            self._append(
                records,
                {
                    "kind": "CLAIM",
                    "at": now.isoformat(),
                    "reservation_id": grant.reservation_id,
                    "worker_sha256": canonical_sha256(worker_id),
                },
            )

    def check(self, grant: RefreshGrant, worker_id: str, *, now: datetime) -> None:
        self._valid_grant(grant, worker_id, now)
        with self._transaction() as records:
            self._clock(records, now)
            self._claimed(records, grant, worker_id)
            self._append(
                records,
                {"kind": "CHECK", "at": now.isoformat(), "reservation_id": grant.reservation_id},
            )

    def _attempt_ready(self, grant: RefreshGrant, worker_id: str, now: datetime) -> None:
        self._valid_grant(grant, worker_id, now)
        if now > grant.request.information_cutoff:
            raise AuthorizationError("ACQUISITION_CUTOFF_PASSED", "EXPIRED")

    def check_transport_window(self, grant: RefreshGrant, worker_id: str, *, now: datetime) -> None:
        """Recheck the same grant/window after a blocking control observation/write.

        This pure check opens no control transaction and grants no route or
        claim. After preflight it precedes key lookup; after the exact durable
        attempt it precedes transport. Full claim/route/count checks and the
        atomic attempt remain required. A late refusal keeps any spent record;
        it does not refund or reset anything.
        """
        self._attempt_ready(grant, worker_id, now)

    def _available_attempt_route(
        self,
        records: list[dict[str, Any]],
        grant: RefreshGrant,
        worker_id: str,
        *,
        provider: Provider,
        method: str,
        host: str,
        path: str,
    ) -> str:
        self._claimed(records, grant, worker_id)
        source = next(
            (row for row in grant.request.source_scopes if row.provider == provider), None
        )
        route = (
            next(
                (
                    row
                    for row in source.routes
                    if (row.method, row.host, row.path) == (method, host, path)
                ),
                None,
            )
            if source
            else None
        )
        if route is None:
            raise AuthorizationError("SOURCE_ROUTE_NOT_AUTHORIZED")
        route_hash = canonical_sha256([provider, method, host, path])
        attempts = sum(
            row.get("kind") == "ATTEMPT"
            and row.get("reservation_id") == grant.reservation_id
            and row.get("route_sha256") == route_hash
            for row in records
        )
        if attempts >= route.maximum_calls:
            raise AuthorizationError("SOURCE_REQUEST_BUDGET_EXHAUSTED")
        return route_hash

    def preflight_attempt(
        self,
        grant: RefreshGrant,
        worker_id: str,
        *,
        provider: Provider,
        method: str,
        host: str,
        path: str,
        now: datetime,
    ) -> None:
        """Check the exact pending route before credentials, without consuming it.

        This is no grant or reservation. The eventual transport must still call
        attempt(), which repeats this same policy under its authenticated lock
        and appends exactly once. No usage can be refunded by this observation.
        """
        self._attempt_ready(grant, worker_id, now)
        with self._transaction() as records:
            self._clock(records, now)
            self._available_attempt_route(
                records,
                grant,
                worker_id,
                provider=provider,
                method=method,
                host=host,
                path=path,
            )

    def attempt(
        self,
        grant: RefreshGrant,
        worker_id: str,
        *,
        provider: Provider,
        method: str,
        host: str,
        path: str,
        now: datetime,
    ) -> None:
        self._attempt_ready(grant, worker_id, now)
        with self._transaction() as records:
            self._clock(records, now)
            route_hash = self._available_attempt_route(
                records,
                grant,
                worker_id,
                provider=provider,
                method=method,
                host=host,
                path=path,
            )
            self._append(
                records,
                {
                    "kind": "ATTEMPT",
                    "at": now.isoformat(),
                    "reservation_id": grant.reservation_id,
                    "route_sha256": route_hash,
                },
            )

    def _valid_grant(self, grant: RefreshGrant, worker_id: str, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise AuthorizationError("AUTHORIZATION_CLOCK_INVALID")
        if (
            grant.ledger_id != self.ledger_id
            or grant.ledger_backend != self.backend_discriminator
            or len(worker_id) != 64
            or any(ch not in "0123456789abcdef" for ch in worker_id)
        ):
            raise AuthorizationError("REFRESH_GRANT_INVALID")
        if grant.classification == "PRIVATE_CURRENT" and self.backend_discriminator != "POSTGRES":
            raise AuthorizationError("PRODUCTION_CONTROL_STORE_NOT_ACCEPTED")
        if grant.classification == "PRIVATE_CURRENT":
            # Child workers prove code enrollment independently of a parent's
            # launch document or the ability to construct a library object.
            enrolled = [
                row
                for row in production_approvals()
                if canonical_sha256(row.model_dump(mode="json")) == grant.approval_sha256
            ]
            if (
                len(enrolled) != 1
                or enrolled[0].status != "APPROVED_REVIEWED"
                or enrolled[0].ledger_id != self.ledger_id
                or enrolled[0].ledger_backend != self.backend_discriminator
                or not enrolled[0].not_before <= now < enrolled[0].expires_at
            ):
                raise AuthorizationError("REFRESH_GRANT_INVALID")
            if grant.expires_at != _approved_expiry(enrolled[0], grant.request, grant.issued_at):
                raise AuthorizationError("REFRESH_GRANT_INVALID")
            from dmf_pulse.operation.enrollment import require_source_closure
            from dmf_pulse.operation.models import OperationError

            try:
                require_source_closure(enrolled[0].source_scopes, now=now)
            except OperationError as error:
                raise AuthorizationError(error.code, "RIGHTS_APPROVAL_REQUIRED") from None
        if not grant.issued_at <= now < grant.expires_at or now >= grant.request.deadline_at:
            raise AuthorizationError("REFRESH_GRANT_EXPIRED", "EXPIRED")

    def _claimed(self, records: list[dict[str, Any]], grant: RefreshGrant, worker_id: str) -> None:
        self._reservation(records, grant)
        rows = [
            row
            for row in records
            if row.get("kind") == "CLAIM" and row.get("reservation_id") == grant.reservation_id
        ]
        if len(rows) != 1 or rows[0]["worker_sha256"] != canonical_sha256(worker_id):
            raise AuthorizationError("REFRESH_GRANT_NOT_CLAIMED")


class DurableUsageLedger(UsageLedger):
    """Append-only local control records, bound to one enrolled ledger identity.

    Every attempted refresh is reserved permanently, even before transport. A
    crash leaves an exclusive lock or incomplete record and therefore blocks.
    Operator/OS tampering with this trusted local control directory is outside
    the browser threat boundary; hash chains are integrity evidence, not a
    defence against a privileged operator replacing a complete disk history.
    """

    def __init__(self, path: Path, ledger_id: str) -> None:
        self.path = path.absolute()
        super().__init__(
            ledger_id,
            backend="OWNED_JSON",
            transaction=self._file_transaction,
            append=self._file_append,
        )

    @classmethod
    def create(cls, path: Path) -> DurableUsageLedger:
        """Explicit setup; never implicitly recreate a missing history."""
        identity = token_hex(32)
        try:
            path.mkdir(parents=False, exist_ok=False)
            _write_new(
                path / "identity.json",
                {"schema_version": "refresh-usage-v1", "ledger_id": identity},
            )
        except OSError:
            raise AuthorizationError("USAGE_LEDGER_INITIALIZATION_FAILED") from None
        return cls(path, identity)

    @contextmanager
    def _file_transaction(self) -> Iterator[list[dict[str, Any]]]:
        lock = self.path / "lock"
        acquired = False
        try:
            if self.path.is_symlink() or not self.path.is_dir():
                raise AuthorizationError("USAGE_LEDGER_INVALID")
            lock.mkdir()
            acquired = True
            identity = _read_object(self.path / "identity.json")
            if identity != {"schema_version": "refresh-usage-v1", "ledger_id": self.ledger_id}:
                raise AuthorizationError("USAGE_LEDGER_IDENTITY_MISMATCH")
            entries = sorted(self.path.iterdir(), key=lambda path: path.name)
            if len(entries) > 100002:
                raise AuthorizationError("USAGE_LEDGER_CAPACITY_REACHED")
            records: list[dict[str, Any]] = []
            previous = "0" * 64
            for entry in entries:
                if entry.name in {"identity.json", "lock"}:
                    continue
                if entry.name != f"{len(records):010d}.json":
                    raise AuthorizationError("USAGE_LEDGER_INVALID")
                record = _read_object(entry)
                digest = record.pop("sha256", None)
                if (
                    record.get("sequence") != len(records)
                    or record.get("previous_sha256") != previous
                    or record.get("ledger_id") != self.ledger_id
                    or canonical_sha256(record) != digest
                ):
                    raise AuthorizationError("USAGE_LEDGER_INVALID")
                record["sha256"] = digest
                records.append(record)
                previous = cast(str, digest)
            yield records
        except AuthorizationError:
            raise
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            raise AuthorizationError("USAGE_LEDGER_UNAVAILABLE") from None
        finally:
            if acquired:
                lock.rmdir()

    def _file_append(self, records: list[dict[str, Any]], payload: dict[str, object]) -> None:
        record = {
            **payload,
            "ledger_id": self.ledger_id,
            "sequence": len(records),
            "previous_sha256": records[-1]["sha256"] if records else "0" * 64,
        }
        _write_new(
            self.path / f"{len(records):010d}.json", {**record, "sha256": canonical_sha256(record)}
        )


class RefreshAuthorizer:
    """Resolve trusted code enrollment, then reserve before worker creation."""

    def __init__(
        self,
        ledger: UsageLedger | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._clock = clock
        self._approvals: tuple[OperatorRefreshApproval, ...] | None = None

    @classmethod
    def for_owned_sources(
        cls,
        approval: OperatorRefreshApproval,
        ledger: UsageLedger,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> RefreshAuthorizer:
        if approval.classification != "OWNED_SYNTHETIC":
            raise AuthorizationError("OWNED_SOURCE_INJECTION_REQUIRED")
        value = cls(ledger, clock=clock)
        value._approvals = (approval,)
        return value

    def _approved(
        self, request: RefreshRequest
    ) -> tuple[OperatorRefreshApproval, datetime, datetime, UsageLedger]:
        registry = self._approvals if self._approvals is not None else production_approvals()
        approvals = [row for row in registry if row.authorization_id == request.authorization_id]
        if len(approvals) != 1:
            raise AuthorizationError(
                "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED", "RIGHTS_APPROVAL_REQUIRED"
            )
        approval = approvals[0]
        now = _now(self._clock)
        expires_at = _approved_expiry(approval, request, now)
        if (
            self._ledger is None
            or approval.ledger_id != self._ledger.ledger_id
            or approval.ledger_backend != self._ledger.backend_discriminator
        ):
            raise AuthorizationError("USAGE_LEDGER_REQUIRED")
        return approval, now, expires_at, self._ledger

    def preflight(self, request: RefreshRequest) -> AuthorizationPreview:
        approval, now, expires_at, ledger = self._approved(request)
        return AuthorizationPreview(
            approval_sha256=canonical_sha256(approval.model_dump(mode="json")),
            request_sha256=canonical_sha256(request.model_dump(mode="json")),
            checked_at=now,
            expires_at=expires_at,
            ledger=ledger.preflight(approval, request, now=now),
        )

    def authorize(self, request: RefreshRequest) -> RefreshGrant:
        approval, now, expires_at, ledger = self._approved(request)
        grant = RefreshGrant(
            reservation_id=token_hex(32),
            ledger_id=ledger.ledger_id,
            ledger_backend=ledger.backend_discriminator,
            approval_sha256=canonical_sha256(approval.model_dump(mode="json")),
            classification=approval.classification,
            request=request,
            issued_at=now,
            expires_at=expires_at,
        )
        ledger.reserve(approval, grant)
        return grant
