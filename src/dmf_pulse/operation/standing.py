"""Installed standing authority and pure derivation of bounded event grants.

The public wheel carries no standing authority. Only its fixed, reviewed private
installation resource can activate this path. Runtime documents are observations,
not policy, and are recovered from the canonical append-only control journal.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard.authorization import OperatorRefreshApproval, QualifiedPlanQuota
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability, RightsProfileStatus
from dmf_pulse.operation.models import Metadata, MetadataTime, OperationError, Ref, Sha

if TYPE_CHECKING:
    from dmf_pulse.operation.discovery import EventDiscovery
    from dmf_pulse.operation.enrollment import InstalledEnrollment, SourceQualification
    from dmf_pulse.operation.quota import QuotaSourceQualification


class OperatingLimits(Metadata):
    """Owner-reviewed security/operating values, never inferred provider limits."""

    fpl_discovery_requests: Literal[1]
    fpl_snapshot_requests: Literal[19]
    fpl_total_requests: Literal[20]
    openfootball_requests: Literal[4]
    quota_requests_per_launch: Literal[1]
    charged_requests_per_event: Literal[1]
    reserved_credits_per_event: Literal[2]
    automatic_retries: Literal[0]
    daily_requests: Literal[1]
    daily_credits: Literal[2]
    monthly_requests: Annotated[int, Field(ge=1, le=8)]
    monthly_credits: Annotated[int, Field(ge=2, le=16)]
    safety_reserve_credits: Annotated[int, Field(ge=10)]
    quota_max_age_seconds: Annotated[int, Field(ge=1, le=300)]
    max_acquisition_seconds: Annotated[int, Field(ge=1, le=300)]
    max_run_seconds: Annotated[int, Field(ge=1, le=900)]
    credential_minimum_remaining_seconds: Annotated[int, Field(ge=1200)]
    credential_maximum_remaining_seconds: Annotated[int, Field(ge=1200, le=86400)]

    @field_validator("*", mode="before")
    @classmethod
    def exact_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("operating limits require exact integers")
        return value

    @model_validator(mode="after")
    def coherent_limits(self) -> Self:
        if (
            self.monthly_requests * 2 > self.monthly_credits
            or self.max_acquisition_seconds > self.max_run_seconds
            or self.credential_minimum_remaining_seconds > self.credential_maximum_remaining_seconds
            or self.credential_minimum_remaining_seconds < self.max_run_seconds + 300
        ):
            raise ValueError("standing operating limits disagree")
        return self


class QuotaProof(Metadata):
    """Strict retained header facts; this type alone never authorizes acquisition."""

    source: Literal["ZERO_CREDIT_PROVIDER_RESPONSE_HEADERS"]
    remaining_credits: Annotated[int, Field(ge=0)]
    used_credits: Annotated[int, Field(ge=0)]
    last_request_cost: Literal[0]
    request_started_at: datetime
    received_at: datetime
    qualification_sha256: Sha
    observation_sha256: Sha

    @model_validator(mode="after")
    def coherent_observation(self) -> Self:
        if (
            not self.request_started_at
            <= self.received_at
            <= self.request_started_at + timedelta(seconds=60)
        ):
            raise ValueError("quota observation timing differs")
        return self


class VerifiedPeriod(Metadata):
    started_at: datetime
    resets_at: datetime
    basis: Literal["OWNER_QUALIFIED_UTC_CALENDAR_ANCHOR_AND_FRESH_PROVIDER_COUNTERS"]
    quota_sha256: Sha
    expected_used_credits: Annotated[int, Field(ge=0)]


class StandingPolicy(Metadata):
    schema_version: Literal["standing-private-operation-v1"]
    policy_id: Ref
    owner_ref: Ref
    entry_id: Annotated[int, Field(ge=1)]
    season_code: Literal["2026/27"]
    purpose: Literal["PRIVATE_OPERATOR_FPL_RECOMMENDATIONS"]
    permitted_countries: tuple[Literal["IT", "GB"], Literal["IT", "GB"]]
    operator_country: Literal["IT", "GB"]
    permission_provenance: Literal["OWNER_ATTESTED_NOT_ISSUER_AUTHENTICATED"]
    supplier_permission_withdrawn: Literal[False]
    owner_acceptance_sha256: Sha
    owner_decision_ref: Ref
    independent_review_sha256: Sha
    accepted_at: datetime
    valid_until: datetime
    implementation_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    protected_numerical_sha256: Sha
    dependency_lock_sha256: Sha
    dependency_project_sha256: Sha
    dependency_tree_sha256: Sha
    python_platform_sha256: Sha
    execution_entrypoint: Literal["REVIEWED_STDLIB_BOOTSTRAP_ONLY"]
    ledger_id: Sha
    odds_account_ref: Ref
    plan_ref: Ref
    plan_credit_allowance: Annotated[int, Field(ge=1)]
    account_exclusive_to_dmf: Literal[True]
    account_review_sha256: Sha
    quota_terms_sha256: Sha
    calendar_anchor_at: datetime
    calendar_anchor_resets_at: datetime
    calendar_anchor_used_credits: Annotated[int, Field(ge=0)]
    calendar_anchor_evidence_sha256: Sha
    control_metadata_retention_approved: Literal[True]
    private_derived_forecast_retention_approved: Literal[True]
    raw_source_retention: Literal["DENIED_TRANSIENT_ONLY"]
    limits: OperatingLimits
    qualifications: tuple[SourceQualification, ...]
    quota_qualification: QuotaSourceQualification

    @model_validator(mode="after")
    def complete_policy(self) -> Self:
        if (
            self.accepted_at >= self.valid_until
            or set(self.permitted_countries) != {"IT", "GB"}
            or self.operator_country not in self.permitted_countries
            or self.calendar_anchor_at.day != 1
            or self.calendar_anchor_at.time() != datetime.min.time()
            or next_month(self.calendar_anchor_at) != self.calendar_anchor_resets_at
            or self.calendar_anchor_used_credits > self.plan_credit_allowance
            or self.limits.monthly_credits > self.plan_credit_allowance
            or len(self.qualifications) != 3
            or {q.scope.provider for q in self.qualifications} != {"FPL", "ODDS", "OPENFOOTBALL"}
            or any(
                q.qualified_at > self.accepted_at
                or q.valid_until < self.valid_until
                or q.operator_country != self.operator_country
                for q in self.qualifications
            )
        ):
            raise ValueError("standing authority closure differs")
        odds = next(q for q in self.qualifications if q.scope.provider == "ODDS")
        if (
            odds.scope.account_ref != self.odds_account_ref
            or odds.account_review_sha256 != self.account_review_sha256
        ):
            raise ValueError("standing quota account differs")
        quota = self.quota_qualification
        if (
            quota.account_ref != self.odds_account_ref
            or quota.operator_country != self.operator_country
            or quota.account_review_sha256 != self.account_review_sha256
            or quota.qualified_at > self.accepted_at
            or (quota.valid_until is not None and quota.valid_until < self.valid_until)
        ):
            raise ValueError("separate quota source does not close to standing authority")
        required = (
            RightsCapability.AUTOMATED_ACCESS,
            RightsCapability.TRANSIENT_PROCESSING,
            RightsCapability.PRIVATE_INTERNAL_USE,
            RightsCapability.DERIVED_STORAGE,
        )
        if any(
            q.profile.status is not RightsProfileStatus.HUMAN_APPROVED
            or q.profile.approved_purpose != self.purpose
            or q.profile.unresolved_rights
            or not q.profile.approved_at <= q.profile.checked_at <= q.qualified_at
            or any(
                q.profile.capabilities[capability] is not CapabilityValue.ALLOW
                for capability in required
            )
            for q in self.qualifications
        ):
            raise ValueError("source permission does not allow retained private derived forecasts")
        fpl = next(q for q in self.qualifications if q.scope.provider == "FPL")
        manager_paths = {
            route.path for route in fpl.scope.routes if route.path.startswith("/api/my-team/")
        }
        if manager_paths != {f"/api/my-team/{self.entry_id}/"}:
            raise ValueError("standing manager differs from original permission scope")
        score = next(q for q in self.qualifications if q.scope.provider == "OPENFOOTBALL")
        if (
            sum(route.maximum_calls for route in score.scope.routes)
            != self.limits.openfootball_requests
        ):
            raise ValueError("standing OpenFootball request ceiling differs")
        return self


def next_month(value: datetime) -> datetime:
    value = MetadataTime(checked_at=value).checked_at
    return datetime(value.year + (value.month == 12), value.month % 12 + 1, 1, tzinfo=UTC)


def validate_policy(value: object) -> StandingPolicy:
    # Late imports avoid a cycle with the existing installed enrollment boundary.
    from dmf_pulse.operation.enrollment import SourceQualification
    from dmf_pulse.operation.quota import QuotaSourceQualification

    StandingPolicy.model_rebuild(
        _types_namespace={
            "SourceQualification": SourceQualification,
            "QuotaSourceQualification": QuotaSourceQualification,
        }
    )
    return StandingPolicy.model_validate_json(json.dumps(value, allow_nan=False))


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate standing resource field")
        result[key] = value
    return result


def installed_standing_policy(
    *, required: bool = True, history_only: bool = False
) -> StandingPolicy | None:
    """Read only the fixed installed resource, never a caller path/environment."""
    try:
        body = (
            files("dmf_pulse.dashboard.resources")
            .joinpath("production_refresh_enrollments.json")
            .read_bytes()
        )
        if len(body) > 262144:
            raise ValueError("standing resource exceeds bound")
        value = json.loads(body, object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise ValueError("standing resource differs")
        if value.get("schema_version") != "trusted-refresh-enrollments-v3":
            if not required:
                return None
            raise OperationError("STANDING_OWNER_ACCEPTANCE_REQUIRED")
        if (
            set(value)
            != {
                "schema_version",
                "approvals",
                "qualifications",
                "release_permits",
                "default_authorization_id",
                "standing_policy",
            }
            or any(value[name] != [] for name in ("approvals", "qualifications", "release_permits"))
            or value["default_authorization_id"] is not None
        ):
            raise OperationError("STANDING_RESOURCE_HAS_ADDITIONAL_AUTHORITY")
        policy = validate_policy(value["standing_policy"])
        from dmf_pulse.dashboard.current import implementation_fingerprint

        now = datetime.now(UTC)
        if policy.implementation_sha != implementation_fingerprint():
            raise OperationError("STANDING_RELEASE_IDENTITY_CHANGED")
        if now < policy.accepted_at or (not history_only and now >= policy.valid_until):
            raise OperationError("STANDING_PERMISSION_REVIEW_EXPIRED")
        from dmf_pulse.operation.maintenance import verify_active_release

        verify_active_release(policy)
        return policy
    except OperationError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise OperationError("STANDING_POLICY_INVALID") from None


def require_policy() -> StandingPolicy:
    result = installed_standing_policy()
    if result is None:
        raise OperationError("STANDING_OWNER_ACCEPTANCE_REQUIRED")
    return result


def require_history_policy() -> StandingPolicy:
    """Authenticate retained-data access, without granting time-expired acquisition.

    Signature, installed bytes, original trust and withdrawal checks still run.
    Every provider/enrollment path continues to use strict require_policy().
    """
    result = installed_standing_policy(history_only=True)
    if result is None:
        raise OperationError("STANDING_OWNER_ACCEPTANCE_REQUIRED")
    return result


def verify_period(
    policy: StandingPolicy,
    quota: QuotaProof,
    *,
    now: datetime,
    settled_credits: int,
    unresolved_paid_attempts: int,
) -> VerifiedPeriod:
    """Reconcile calendar evidence and exclusive-account actual usage, never guess."""
    now = MetadataTime(checked_at=now).checked_at
    if (
        not quota.received_at
        <= now
        <= quota.received_at + timedelta(seconds=policy.limits.quota_max_age_seconds)
        or quota.qualification_sha256 != policy.quota_qualification.semantic_sha256
        or quota.remaining_credits + quota.used_credits != policy.plan_credit_allowance
        or unresolved_paid_attempts
        or settled_credits < 0
        or now < policy.calendar_anchor_at
    ):
        raise OperationError("QUOTA_EVIDENCE_OR_LEDGER_CONTRADICTION")
    started = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if quota.request_started_at < started:
        raise OperationError("QUOTA_CHECK_CROSSED_MONTHLY_RESET")
    expected = settled_credits + (
        policy.calendar_anchor_used_credits if started == policy.calendar_anchor_at else 0
    )
    if quota.used_credits != expected:
        raise OperationError("EXCLUSIVE_ACCOUNT_USAGE_CONTRADICTION")
    if quota.remaining_credits < policy.limits.safety_reserve_credits + 2:
        raise OperationError("QUOTA_BELOW_SAFETY_RESERVE")
    return VerifiedPeriod(
        started_at=started,
        resets_at=next_month(started),
        basis="OWNER_QUALIFIED_UTC_CALENDAR_ANCHOR_AND_FRESH_PROVIDER_COUNTERS",
        quota_sha256=quota.semantic_sha256,
        expected_used_credits=expected,
    )


def execution_key(policy: StandingPolicy, gameweek: int) -> str:
    if type(gameweek) is not int or not 1 <= gameweek <= 38:
        raise OperationError("OFFICIAL_EVENT_INVALID")
    # Deliberately independent of release/policy IDs and horizon: upgrades and
    # repeated launches cannot manufacture a second paid acquisition.
    return canonical_sha256(
        [policy.odds_account_ref, policy.owner_ref, policy.entry_id, policy.season_code, gameweek]
    )


def derive_enrollment(
    policy: StandingPolicy,
    event: EventDiscovery,
    quota: QuotaProof,
    period: VerifiedPeriod,
    *,
    created_at: datetime,
) -> InstalledEnrollment:
    from dmf_pulse.operation.discovery import fpl_routes
    from dmf_pulse.operation.enrollment import InstalledEnrollment, SourceQualification

    created_at = MetadataTime(checked_at=created_at).checked_at
    if (
        not policy.accepted_at <= created_at < policy.valid_until
        or policy.valid_until <= created_at + timedelta(seconds=policy.limits.max_run_seconds)
        or not event.received_at <= created_at <= event.received_at + timedelta(seconds=60)
        or not quota.received_at
        <= created_at
        <= quota.received_at + timedelta(seconds=policy.limits.quota_max_age_seconds)
        or event.deadline_at <= created_at + timedelta(seconds=policy.limits.max_run_seconds)
        or period.resets_at <= created_at + timedelta(seconds=policy.limits.max_run_seconds)
        or period.quota_sha256 != quota.semantic_sha256
        or not period.started_at <= created_at < period.resets_at
    ):
        raise OperationError("STANDING_EVENT_OR_QUOTA_STALE")
    key = execution_key(policy, event.target_gameweek)
    expires = min(
        created_at + timedelta(seconds=policy.limits.max_run_seconds),
        event.deadline_at,
        period.resets_at,
        policy.valid_until,
    )
    qualifications = tuple(
        SourceQualification.model_validate(
            q.model_copy(
                update={
                    "qualification_id": f"OPR001-{key[:32]}-{q.scope.provider}",
                    "scope": q.scope.model_copy(
                        update={"routes": fpl_routes(policy.entry_id, event)}
                    )
                    if q.scope.provider == "FPL"
                    else q.scope,
                    "qualified_at": created_at,
                    "valid_until": expires,
                }
            )
        )
        for q in policy.qualifications
    )
    approval = OperatorRefreshApproval(
        authorization_id=f"OPR001-{key}",
        classification="PRIVATE_CURRENT",
        approval_evidence_sha256=policy.owner_acceptance_sha256,
        implementation_sha=policy.implementation_sha,
        review_sha256=policy.independent_review_sha256,
        operator_ref=policy.owner_ref,
        purpose=policy.purpose,
        season_code=policy.season_code,
        horizons=(1,),
        source_scopes=tuple(q.scope for q in qualifications),
        plan_quota=QualifiedPlanQuota(
            account_ref=policy.odds_account_ref,
            plan_ref=policy.plan_ref,
            evidence_sha256=quota.observation_sha256,
            terms_evidence_sha256=policy.quota_terms_sha256,
            monthly_plan_credits=policy.plan_credit_allowance,
            allocated_monthly_credits=policy.limits.monthly_credits,
            remaining_credits=quota.remaining_credits,
            observed_at=quota.received_at,
            period_started_at=period.started_at,
            resets_at=period.resets_at,
        ),
        ledger_id=policy.ledger_id,
        ledger_backend="POSTGRES",
        status="APPROVED_REVIEWED",
        usage="ONE_SHOT",
        approved_at=policy.accepted_at,
        not_before=created_at,
        expires_at=expires,
        quota_max_age_seconds=policy.limits.quota_max_age_seconds,
        max_acquisition_seconds=policy.limits.max_acquisition_seconds,
        max_run_seconds=policy.limits.max_run_seconds,
        qualified_deadline_at=event.deadline_at,
        daily_request_limit=policy.limits.daily_requests,
        daily_credit_limit=policy.limits.daily_credits,
        monthly_request_limit=policy.limits.monthly_requests,
        monthly_credit_limit=policy.limits.monthly_credits,
        safety_reserve_credits=policy.limits.safety_reserve_credits,
        control_metadata_retention_approved=True,
    )
    return InstalledEnrollment(approvals=(approval,), qualifications=qualifications)


def runtime_enrollment(base: InstalledEnrollment) -> InstalledEnrollment:
    """Fixed standing authority plus canonical derived rows, shared by child/parent."""
    policy = installed_standing_policy(required=False)
    if policy is None:
        return base
    from dmf_pulse.operation.journal import OperationJournal

    active = OperationJournal.production(policy).active_enrollment(policy, now=datetime.now(UTC))
    if active is not None:
        return active
    # Pre-discovery only the one fixed official bootstrap route is qualified.
    # No charged approval exists until official event and fresh quota admission.
    fpl = next(q for q in policy.qualifications if q.scope.provider == "FPL")
    routes = tuple(route for route in fpl.scope.routes if route.path == "/api/bootstrap-static/")
    if len(routes) != 1:
        raise OperationError("STANDING_BOOTSTRAP_SCOPE_INVALID")
    return base.model_copy(
        update={
            "approvals": (),
            "qualifications": (
                fpl.model_copy(update={"scope": fpl.scope.model_copy(update={"routes": routes})}),
            ),
        }
    )
