"""Reviewed refresh scope and durable, secret-free acquisition reservations.

No production approvals are enrolled. An operator JSON document is never an
approval registry. Owned-source injection remains explicitly synthetic.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_hex
from typing import Annotated, Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256

Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Ref = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")]
Provider = Literal["FPL", "ODDS", "OPENFOOTBALL"]
Classification = Literal["OWNED_SYNTHETIC", "PRIVATE_CURRENT"]
State = Literal["RIGHTS_APPROVAL_REQUIRED", "BLOCKED", "EXPIRED"]


class AuthorizationError(ValueError):
    """A bounded code safe for the dashboard; no source or approval payload."""

    def __init__(self, code: str, state: State = "BLOCKED") -> None:
        super().__init__(code)
        self.code = code
        self.state = state


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
    status: Literal["APPROVED_REVIEWED", "REVOKED"]
    usage: Literal["ONE_SHOT", "MANUAL_RECURRING"]
    approved_at: datetime
    not_before: datetime
    expires_at: datetime
    quota_max_age_seconds: int = Field(ge=1, le=86400)
    max_acquisition_seconds: int = Field(ge=1, le=900)
    max_run_seconds: int = Field(ge=1, le=900)
    daily_request_limit: int = Field(ge=1)
    daily_credit_limit: int = Field(ge=2)
    monthly_request_limit: int = Field(ge=1)
    monthly_credit_limit: int = Field(ge=2)
    safety_reserve_credits: int = Field(ge=0)
    control_metadata_retention_approved: Literal[True]

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


class RefreshGrant(_Contract):
    schema_version: Literal["operator-refresh-grant-v1"] = "operator-refresh-grant-v1"
    reservation_id: Sha
    ledger_id: Sha
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


# Enrollment requires a separate reviewed implementation and owner approval.
# Runtime documents, environment variables and browser requests cannot add rows.
PRODUCTION_APPROVALS: tuple[OperatorRefreshApproval, ...] = ()


def _now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise AuthorizationError("AUTHORIZATION_CLOCK_INVALID")
    return value.astimezone(UTC)


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


class DurableUsageLedger:
    """Append-only local control records, bound to one enrolled ledger identity.

    Every attempted refresh is reserved permanently, even before transport. A
    crash leaves an exclusive lock or incomplete record and therefore blocks.
    Operator/OS tampering with this trusted local control directory is outside
    the browser threat boundary; hash chains are integrity evidence, not a
    defence against a privileged operator replacing a complete disk history.
    """

    def __init__(self, path: Path, ledger_id: str) -> None:
        self.path = path.absolute()
        self.ledger_id = ledger_id

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
    def _transaction(self) -> Iterator[list[dict[str, Any]]]:
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
        except (OSError, ValueError, TypeError, KeyError):
            raise AuthorizationError("USAGE_LEDGER_UNAVAILABLE") from None
        finally:
            if acquired:
                lock.rmdir()

    def _append(self, records: list[dict[str, Any]], payload: dict[str, object]) -> None:
        record = {
            **payload,
            "ledger_id": self.ledger_id,
            "sequence": len(records),
            "previous_sha256": records[-1]["sha256"] if records else "0" * 64,
        }
        _write_new(
            self.path / f"{len(records):010d}.json", {**record, "sha256": canonical_sha256(record)}
        )

    @staticmethod
    def _clock(records: list[dict[str, Any]], now: datetime) -> None:
        if records and now < datetime.fromisoformat(str(records[-1]["at"])):
            raise AuthorizationError("AUTHORIZATION_CLOCK_REGRESSED")

    def reserve(self, approval: OperatorRefreshApproval, grant: RefreshGrant) -> None:
        with self._transaction() as records:
            self._clock(records, grant.issued_at)
            reservations = [row for row in records if row.get("kind") == "RESERVATION"]
            authorization_hash = canonical_sha256(approval.authorization_id)
            same_approval = [
                row for row in reservations if row["authorization_sha256"] == authorization_hash
            ]
            if approval.usage == "ONE_SHOT" and same_approval:
                raise AuthorizationError("ONE_SHOT_CONSUMED")
            account_hash = canonical_sha256(approval.plan_quota.account_ref)
            account_rows = [row for row in reservations if row["account_sha256"] == account_hash]
            day = grant.issued_at.date().isoformat()
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
            if (
                approval.plan_quota.remaining_credits
                - 2 * since_quota
                - approval.safety_reserve_credits
                < 2
            ):
                raise AuthorizationError("QUOTA_EXHAUSTED")
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
        self._valid_grant(grant, worker_id, now)
        if now > grant.request.information_cutoff:
            raise AuthorizationError("ACQUISITION_CUTOFF_PASSED", "EXPIRED")
        with self._transaction() as records:
            self._clock(records, now)
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
            or len(worker_id) != 64
            or any(ch not in "0123456789abcdef" for ch in worker_id)
        ):
            raise AuthorizationError("REFRESH_GRANT_INVALID")
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


class RefreshAuthorizer:
    """Resolve trusted code enrollment, then reserve before worker creation."""

    def __init__(
        self,
        ledger: DurableUsageLedger | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._clock = clock
        self._approvals = PRODUCTION_APPROVALS

    @classmethod
    def for_owned_sources(
        cls,
        approval: OperatorRefreshApproval,
        ledger: DurableUsageLedger,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> RefreshAuthorizer:
        if approval.classification != "OWNED_SYNTHETIC":
            raise AuthorizationError("OWNED_SOURCE_INJECTION_REQUIRED")
        value = cls(ledger, clock=clock)
        value._approvals = (approval,)
        return value

    def authorize(self, request: RefreshRequest) -> RefreshGrant:
        approvals = [
            row for row in self._approvals if row.authorization_id == request.authorization_id
        ]
        if len(approvals) != 1:
            raise AuthorizationError(
                "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED", "RIGHTS_APPROVAL_REQUIRED"
            )
        approval = approvals[0]
        now = _now(self._clock)
        if approval.status != "APPROVED_REVIEWED":
            raise AuthorizationError("AUTHORIZATION_REVOKED")
        if not approval.not_before <= now < approval.expires_at:
            raise AuthorizationError("AUTHORIZATION_EXPIRED", "EXPIRED")
        for name in (
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
        if not now <= request.information_cutoff < request.deadline_at:
            raise AuthorizationError("AUTHORIZATION_DEADLINE_INVALID", "EXPIRED")
        if request.information_cutoff > now + timedelta(seconds=approval.max_acquisition_seconds):
            raise AuthorizationError("ACQUISITION_WINDOW_EXCEEDED")
        quota = approval.plan_quota
        if (
            not quota.period_started_at <= now < quota.resets_at
            or not quota.observed_at
            <= now
            <= quota.observed_at + timedelta(seconds=approval.quota_max_age_seconds)
        ):
            raise AuthorizationError("QUALIFIED_QUOTA_EVIDENCE_STALE")
        if self._ledger is None or approval.ledger_id != self._ledger.ledger_id:
            raise AuthorizationError("USAGE_LEDGER_REQUIRED")
        grant = RefreshGrant(
            reservation_id=token_hex(32),
            ledger_id=self._ledger.ledger_id,
            approval_sha256=canonical_sha256(approval.model_dump(mode="json")),
            classification=approval.classification,
            request=request,
            issued_at=now,
            expires_at=min(
                approval.expires_at,
                request.deadline_at,
                now + timedelta(seconds=approval.max_run_seconds),
            ),
        )
        self._ledger.reserve(approval, grant)
        return grant
