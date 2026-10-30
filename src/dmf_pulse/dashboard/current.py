"""Rights-gated current-mode execution; no provider credentials cross the process boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from multiprocessing.connection import Connection
from pathlib import Path
from secrets import token_hex
from typing import Literal

from sqlalchemy import Connection as SqlConnection

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.authorization_errors import AuthorizationState, safe_authorization_fields
from dmf_pulse.current_failures import CREDENTIAL_FAILURE_CODES, safe_current_failure_code
from dmf_pulse.dashboard.authorization import (
    AuthorizationError,
    AuthorizationPreview,
    DurableUsageLedger,
    OperatorRefreshApproval,
    QualifiedPlanQuota,
    RefreshAuthorizer,
    RefreshGrant,
    RefreshRequest,
    RouteBudget,
    SourceScope,
    UsageLedger,
    production_approvals,
)
from dmf_pulse.dashboard.current_sources import CurrentSourceFactories, Provider
from dmf_pulse.dashboard.synthetic import DEMO_TIME, demo_inputs
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.ingestion.odds.models import QualifiedOperatorQuota, QuotaSource, QuotaState
from dmf_pulse.private_v1.actionability import checked_report
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import PrivateV1Decision
from dmf_pulse.private_v1.one_command import (
    OneCommandRequest,
    OneCommandResult,
    PrivateV1OneCommandService,
)
from dmf_pulse.private_v1.presentation import PresentationModel
from dmf_pulse.private_v1.progress import ProgressSink

ExecutionState = Literal[
    "ENGINEERING_READY",
    "RIGHTS_APPROVAL_REQUIRED",
    "SOURCE_NOT_AVAILABLE",
    "REAL_RUN_AUTHORIZED",
    "REAL_RUN_COMPLETED",
    "BLOCKED",
    "EXPIRED",
]


class CurrentEligibility(PresentationModel):
    schema_version: Literal["desk-current-eligibility-v1"] = "desk-current-eligibility-v1"
    engineering_status: Literal["ENGINEERING_READY"] = "ENGINEERING_READY"
    execution_mode: Literal["PRIVATE_CURRENT"] = "PRIVATE_CURRENT"
    source_classification: Literal["OWNED_SYNTHETIC", "PRIVATE_CURRENT", "UNQUALIFIED"]
    state: ExecutionState
    market_mode: Literal["MARKET_PRIMARY"] = "MARKET_PRIMARY"
    error_code: str | None = None
    deadline_at: datetime | None = None
    qualified_quota_snapshot_remaining: int | None = None
    retention: Literal["TRANSIENT_INPUTS_CONTROL_METADATA_ONLY"] = (
        "TRANSIENT_INPUTS_CONTROL_METADATA_ONLY"
    )


def implementation_fingerprint() -> str:
    """160-bit SHA-256 package-content pin, independent of caller/env Git assertions."""
    root = Path(str(files("dmf_pulse")))
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if (
            path.relative_to(root).as_posix()
            == "dashboard/resources/production_refresh_enrollments.json"
        ):
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:40]


def resolved_profiles(
    scopes: tuple[SourceScope, ...] | None = None,
) -> dict[Provider, RightsProfile]:
    from dmf_pulse.ingestion.odds.config import load_rights_profiles as odds_profiles
    from dmf_pulse.ingestion.openfootball.config import load_rights_profiles as score_profiles
    from dmf_pulse.ingestion.rights import load_rights_profiles as fpl_profiles

    registries = {"FPL": fpl_profiles(), "ODDS": odds_profiles(), "OPENFOOTBALL": score_profiles()}
    identities: dict[Provider, str] = (
        {
            "FPL": "fpl_official_private_operator_initiated_read_v1",
            "ODDS": "the_odds_api_private_analytics_v1",
            "OPENFOOTBALL": "openfootball_football_json_score_prior_v1",
        }
        if scopes is None
        else {row.provider: row.profile_id for row in scopes}
    )
    try:
        if scopes is not None and any(
            row.source_kind == "RIGHTS_QUALIFIED_PRIVATE" for row in scopes
        ):
            from dmf_pulse.operation.enrollment import installed_enrollment

            for qualification in installed_enrollment().qualifications:
                registries[qualification.scope.provider][
                    qualification.profile.rights_profile_id
                ] = qualification.profile
        return {
            provider: registries[provider][identity] for provider, identity in identities.items()
        }
    except KeyError:
        raise AuthorizationError("SOURCE_PROFILE_NOT_AVAILABLE", "SOURCE_NOT_AVAILABLE") from None


DatabaseReference = Literal["OPERATOR_CONTROL_DATABASE", "SYNTHETIC_TEST_DATABASE"]


@contextmanager
def _control_connection(database_ref: DatabaseReference) -> Iterator[SqlConnection]:
    # Resolution happens only inside an explicitly authorized transaction. The
    # identifier crosses the process boundary; the connection string never does.
    from dmf_pulse.database.engine import create_database_engine, resolve_test_database_url
    from dmf_pulse.database.models import DatabaseSettings

    if database_ref == "SYNTHETIC_TEST_DATABASE":
        url = resolve_test_database_url(environment="TEST")
    elif database_ref == "OPERATOR_CONTROL_DATABASE":
        url = os.environ.get("DMF_CONTROL_DATABASE_URL", "")
    else:
        raise AuthorizationError("CONTROL_DATABASE_REFERENCE_INVALID")
    engine = create_database_engine(url, DatabaseSettings(url_secret_ref=database_ref))
    try:
        with engine.connect() as connection:
            yield connection
    finally:
        engine.dispose()


def _postgres_ledger(
    ledger_id: str, account_ref: str, database_ref: DatabaseReference
) -> UsageLedger:
    from dmf_pulse.dashboard.postgres_authorization import PostgresUsageLedger

    return PostgresUsageLedger(
        lambda: _control_connection(database_ref),
        ledger_id,
        account_ref=account_ref,
        database_ref=database_ref,
    )


def profile_fingerprint(profile: RightsProfile) -> str:
    value = profile.model_dump(mode="json", exclude={"capabilities"})
    value["capabilities"] = {key.value: item.value for key, item in profile.capabilities.items()}
    return canonical_sha256(value)


@dataclass(frozen=True, slots=True, repr=False)
class CurrentLaunch:
    grant: RefreshGrant
    ledger_path: Path | None
    entry_id: int
    quota: QuotaState | QualifiedOperatorQuota
    worker_id: str = field(repr=False)
    control_account_ref: str
    database_ref: DatabaseReference = "OPERATOR_CONTROL_DATABASE"


@dataclass(frozen=True, slots=True)
class CurrentWorkerResult:
    """Bind the transient presentation and accepted result to one claimed grant."""

    result: OneCommandResult
    grant_sha256: str
    presentation_sha256: str
    authentication_sha256: str


def _result_authentication(
    launch: CurrentLaunch, result: OneCommandResult, presentation_sha256: str
) -> str:
    # The ephemeral worker claim is already shared only by parent and child.
    # Authenticate presentation custody; this never creates source/provider rights.
    payload = canonical_sha256(
        [
            "current-worker-result-v1",
            launch.grant.semantic_sha256,
            result.decision.semantic_sha256,
            presentation_sha256,
            result.actionability.model_dump(mode="json"),
        ]
    ).encode("ascii")
    return hmac.new(bytes.fromhex(launch.worker_id), payload, hashlib.sha256).hexdigest()


def validate_current_result(envelope: CurrentWorkerResult, launch: CurrentLaunch) -> None:
    result = envelope.result
    presentation = result.presentation
    grant = launch.grant
    if (
        envelope.grant_sha256 != grant.semantic_sha256
        or presentation is None
        or not hmac.compare_digest(
            envelope.authentication_sha256,
            _result_authentication(launch, result, envelope.presentation_sha256),
        )
        or envelope.presentation_sha256 != canonical_sha256(presentation.model_dump(mode="json"))
        or result.decision.lineage.code_sha != grant.request.implementation_sha
        or result.decision.information_cutoff != grant.request.information_cutoff
        or result.actionability.deadline_at != grant.request.deadline_at
        or presentation.deadline_at != grant.request.deadline_at
        or presentation.source_captured_at != grant.request.information_cutoff
    ):
        raise AuthorizationError("WORKER_RESULT_BINDING_INVALID")
    decision = result.decision
    actual_gameweeks = {row.gameweek: row.result_sha256 for row in presentation.gameweeks}
    if isinstance(decision, PrivateV1Decision):
        expected_gameweeks = {decision.target_gameweek: decision.lineage.stage9_result_sha256}
        expected_fixtures = set(decision.lineage.stage8_result_sha256_by_fixture)
    else:
        expected_gameweeks = decision.lineage.gameweek_projection_sha256_by_gameweek
        expected_fixture_hashes = decision.lineage.fixture_projection_sha256_by_gameweek
        expected_fixtures = {fixture for row in expected_fixture_hashes.values() for fixture in row}
        actual_fixture_hashes = {
            gameweek: {
                row.fixture_id: row.result_sha256
                for row in presentation.fixtures
                if row.gameweek == gameweek
            }
            for gameweek in actual_gameweeks
        }
        if actual_fixture_hashes != expected_fixture_hashes:
            raise AuthorizationError("WORKER_RESULT_BINDING_INVALID")
    if (
        len(presentation.gameweeks) != grant.request.horizon
        or actual_gameweeks != expected_gameweeks
        or len(actual_gameweeks) != len(presentation.gameweeks)
        or {row.fixture_id for row in presentation.fixtures} != expected_fixtures
        or len(expected_fixtures) != len(presentation.fixtures)
        or any(row.gameweek not in expected_gameweeks for row in presentation.fixtures)
    ):
        raise AuthorizationError("WORKER_RESULT_BINDING_INVALID")


@dataclass(frozen=True, slots=True)
class _GuardFailure:
    code: str
    state: AuthorizationState


class CurrentAcquisitionGuard:
    def __init__(self, launch: CurrentLaunch, clock: Callable[[], datetime]) -> None:
        self._launch, self._clock = launch, clock
        if launch.grant.ledger_backend == "OWNED_JSON":
            if launch.grant.classification != "OWNED_SYNTHETIC" or launch.ledger_path is None:
                raise AuthorizationError("PRODUCTION_CONTROL_STORE_NOT_ACCEPTED")
            self._ledger: UsageLedger = DurableUsageLedger(
                launch.ledger_path, launch.grant.ledger_id
            )
        else:
            if (
                launch.database_ref == "SYNTHETIC_TEST_DATABASE"
                and launch.grant.classification != "OWNED_SYNTHETIC"
            ):
                raise AuthorizationError("CONTROL_DATABASE_REFERENCE_INVALID")
            self._ledger = _postgres_ledger(
                launch.grant.ledger_id, launch.control_account_ref, launch.database_ref
            )
        self._closed = False
        self.failure: _GuardFailure | None = None
        self._ledger.claim(launch.grant, launch.worker_id, now=clock())

    def check(self) -> None:
        try:
            self._ledger.check(self._launch.grant, self._launch.worker_id, now=self._clock())
        except AuthorizationError as error:
            if self.failure is None:
                self.failure = _GuardFailure(*safe_authorization_fields(error))
            raise

    def credential_failed(self, code: object) -> None:
        """Keep only a known fixed credential reason across the accepted Odds client."""
        safe = (
            code
            if type(code) is str and code in CREDENTIAL_FAILURE_CODES
            else "CREDENTIAL_UNAVAILABLE"
        )
        if self.failure is None:
            self.failure = _GuardFailure(safe, "BLOCKED")

    def before_transport(self) -> None:
        """Recheck the same grant window after a potentially blocking ledger write."""
        try:
            if self._closed:
                raise AuthorizationError("ACQUISITION_CLOSED")
            self._ledger.check_transport_window(
                self._launch.grant, self._launch.worker_id, now=self._clock()
            )
        except AuthorizationError as error:
            if self.failure is None:
                self.failure = _GuardFailure(*safe_authorization_fields(error))
            raise

    def before_send(self, provider: Provider, method: str, host: str, path: str) -> None:
        try:
            if self._closed:
                raise AuthorizationError("ACQUISITION_CLOSED")
            self._ledger.attempt(
                self._launch.grant,
                self._launch.worker_id,
                provider=provider,
                method=method,
                host=host,
                path=path,
                now=self._clock(),
            )
        except AuthorizationError as error:
            if self.failure is None:
                self.failure = _GuardFailure(*safe_authorization_fields(error))
            raise

    def preflight_send(self, provider: Provider, method: str, host: str, path: str) -> None:
        try:
            if self._closed:
                raise AuthorizationError("ACQUISITION_CLOSED")
            self._ledger.preflight_attempt(
                self._launch.grant,
                self._launch.worker_id,
                provider=provider,
                method=method,
                host=host,
                path=path,
                now=self._clock(),
            )
            # The read-only transaction can wait too. Do not resolve a key if
            # that wait crossed the same grant/cutoff boundary.
            self.before_transport()
        except AuthorizationError as error:
            if self.failure is None:
                self.failure = _GuardFailure(*safe_authorization_fields(error))
            raise

    def finish_acquisition(self) -> None:
        self._closed = True


def _current_service_scope(
    service: PrivateV1OneCommandService, request: OneCommandRequest, guard: CurrentAcquisitionGuard
) -> OneCommandResult | _GuardFailure:
    """Preserve a safe boundary refusal across accepted clients' generic wrappers.

    Only the first bounded guard sidecar crosses this scope. Raw source/client
    exceptions and credential-bearing frames are discarded before public raise.
    No parser, model, retry policy or scoring implementation is changed.
    """
    try:
        result = service.run(request)
    except Exception:
        if guard.failure is None:
            raise
        return guard.failure
    return guard.failure if guard.failure is not None else result


def _launch_is_bound(launch: CurrentLaunch) -> None:
    grant = launch.grant
    if grant.request.implementation_sha != implementation_fingerprint():
        raise AuthorizationError("IMPLEMENTATION_IDENTITY_CHANGED")
    _scope_is_bound(launch.entry_id, grant.request.source_scopes)


def _scope_is_bound(entry_id: int, source_scopes: tuple[SourceScope, ...]) -> None:
    if type(entry_id) is not int or entry_id < 1:
        raise AuthorizationError("MANAGER_SCOPE_INVALID")
    scopes = {row.provider: row for row in source_scopes}
    if set(scopes) != {"FPL", "ODDS", "OPENFOOTBALL"}:
        raise AuthorizationError("SOURCE_SCOPE_INVALID")
    required = f"/api/my-team/{entry_id}/"
    if not any(route.path == required for route in scopes["FPL"].routes):
        raise AuthorizationError("MANAGER_SCOPE_INVALID")
    for provider, profile in resolved_profiles(source_scopes).items():
        scope = scopes[provider]
        if (
            scope.profile_id != profile.rights_profile_id
            or scope.profile_sha256 != profile_fingerprint(profile)
        ):
            raise AuthorizationError("SOURCE_PROFILE_CHANGED")


def run_current_recommendation(
    launch: CurrentLaunch,
    progress: ProgressSink,
    *,
    clock: Callable[[], datetime] | None = None,
) -> OneCommandResult:
    """The same worker path selects owned transports or eligible real clients."""
    owned = launch.grant.classification == "OWNED_SYNTHETIC"
    active_clock = clock or ((lambda: DEMO_TIME) if owned else lambda: datetime.now(UTC))
    _launch_is_bound(launch)
    guard = CurrentAcquisitionGuard(launch, active_clock)
    profiles = resolved_profiles(launch.grant.request.source_scopes)
    sources = CurrentSourceFactories(
        guard=guard,
        owned=owned,
        fpl_profile=profiles["FPL"],
        odds_profile=profiles["ODDS"],
        quota=launch.quota,
        clock=active_clock,
    )
    try:
        result = _current_service_scope(
            PrivateV1OneCommandService(
                direct_client_factory=sources.direct,
                odds_service_factory=sources.odds,
                score_service_factory=sources.score,
                _provider_request_guard=guard.check,
                progress=progress,
                collect_presentation=True,
                clock=active_clock,
            ),
            OneCommandRequest(
                entry_id=launch.entry_id,
                code_sha=launch.grant.request.implementation_sha,
                run_at=launch.grant.request.information_cutoff,
                operator_approved_at=launch.grant.issued_at,
                run_id="ACCEL003_CURRENT_MODE",
                horizon_gameweeks=launch.grant.request.horizon,
                scenario_count=32
                if owned and launch.grant.request.horizon == 1
                else 8
                if owned
                else 256,
                root_seed=42 if launch.grant.request.horizon == 1 else 43,
            ),
            guard,
        )
        if isinstance(result, _GuardFailure):
            raise AuthorizationError(result.code, result.state) from None
        guard.check()
        if result.actionability.deadline_at != launch.grant.request.deadline_at:
            raise AuthorizationError("OFFICIAL_DEADLINE_SCOPE_MISMATCH")
        checked_report(result, clock=active_clock)
        return result
    finally:
        guard.finish_acquisition()


def current_worker(pipe: Connection, horizon: Literal[1, 3], launch: CurrentLaunch) -> None:
    from dmf_pulse.dashboard.runtime import PipeProgress

    try:
        if horizon != launch.grant.request.horizon:
            raise AuthorizationError("AUTHORIZATION_HORIZON_NOT_APPROVED")
        result = run_current_recommendation(launch, PipeProgress(pipe.send))
        if result.presentation is None:
            raise AuthorizationError("WORKER_RESULT_BINDING_INVALID")
        envelope = CurrentWorkerResult(
            result=result,
            grant_sha256=launch.grant.semantic_sha256,
            presentation_sha256=canonical_sha256(result.presentation.model_dump(mode="json")),
            authentication_sha256=_result_authentication(
                launch, result, canonical_sha256(result.presentation.model_dump(mode="json"))
            ),
        )
        validate_current_result(envelope, launch)
        pipe.send(("current_result", envelope))
    except (AuthorizationError, IngestionError, PrivateV1Error) as error:
        pipe.send(("error", safe_current_failure_code(error.code)))
    except Exception:
        pipe.send(("error", "CURRENT_SOURCE_OR_RUN_BLOCKED"))
    finally:
        pipe.close()


class CurrentRefreshSession:
    """One server-side operator scope; browser input cannot enroll approvals."""

    def __init__(
        self,
        *,
        entry_id: int | None = None,
        approval: OperatorRefreshApproval | None = None,
        ledger: UsageLedger | None = None,
        deadline_at: datetime | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        credentials_available: Callable[[], bool] | None = None,
        database_ref: DatabaseReference = "OPERATOR_CONTROL_DATABASE",
    ) -> None:
        self._entry_id, self._approval, self._ledger = entry_id, approval, ledger
        self._deadline = deadline_at
        self._clock, self._credentials_available = clock, credentials_available
        self._database_ref = database_ref
        self._authorizer = RefreshAuthorizer(ledger, clock=clock)
        self._state: ExecutionState = "RIGHTS_APPROVAL_REQUIRED"
        self._error: str | None = "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED"
        self._owned_sources = False

    @property
    def owned_sources(self) -> bool:
        return self._owned_sources

    def _request(self, horizon: Literal[1, 3]) -> RefreshRequest:
        approval = self._approval
        if approval is None:
            raise AuthorizationError(
                "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED", "RIGHTS_APPROVAL_REQUIRED"
            )
        if self._ledger is None or self._entry_id is None or self._deadline is None:
            raise AuthorizationError("OPERATOR_CONTROL_CONTEXT_REQUIRED")
        _scope_is_bound(self._entry_id, approval.source_scopes)
        now = self._clock()
        cutoff = (
            now if self.owned_sources else now + timedelta(seconds=approval.max_acquisition_seconds)
        )
        # The exact official deadline must come from the separately qualified
        # pilot scope, not a browser timestamp or a stale previous-GW squad.
        deadline = self._deadline
        return RefreshRequest(
            authorization_id=approval.authorization_id,
            implementation_sha=implementation_fingerprint(),
            review_sha256=approval.review_sha256,
            operator_ref=approval.operator_ref,
            purpose="PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
            season_code="2026/27",
            horizon=horizon,
            source_scopes=approval.source_scopes,
            information_cutoff=cutoff,
            deadline_at=deadline,
        )

    def preflight(self, horizon: Literal[1, 3]) -> AuthorizationPreview:
        """Use the same complete policy without reserving, credentials or workers."""
        return self._authorizer.preflight(self._request(horizon))

    def prepare(self, horizon: Literal[1, 3]) -> CurrentLaunch:
        request = self._request(horizon)
        grant = self._authorizer.authorize(request)
        approval = self._approval
        if approval is None or self._entry_id is None:
            raise AuthorizationError("OPERATOR_CONTROL_CONTEXT_REQUIRED")
        launch = CurrentLaunch(
            grant=grant,
            ledger_path=self._ledger.path if isinstance(self._ledger, DurableUsageLedger) else None,
            entry_id=self._entry_id,
            worker_id=token_hex(32),
            control_account_ref=approval.plan_quota.account_ref,
            database_ref=self._database_ref,
            quota=QuotaState(
                remaining=approval.plan_quota.remaining_credits,
                used=0,
                last_cost=0,
                observed_at=approval.plan_quota.observed_at,
                source=QuotaSource.SYNTHETIC_FIXTURE,
            )
            if self.owned_sources
            else QualifiedOperatorQuota(
                remaining=approval.plan_quota.remaining_credits,
                observed_at=approval.plan_quota.observed_at,
                evidence_sha256=approval.plan_quota.evidence_sha256,
            ),
        )
        _launch_is_bound(launch)
        # Ordinary execution defers lookup to the claimed authorized worker.
        # The explicit callback is an owned-test preflight injection only.
        if self._credentials_available is not None and not self._credentials_available():
            raise AuthorizationError("CREDENTIAL_UNAVAILABLE")
        self._state = "ENGINEERING_READY" if self.owned_sources else "REAL_RUN_AUTHORIZED"
        self._error = None
        return launch

    def eligibility(self) -> CurrentEligibility:
        return CurrentEligibility(
            source_classification="OWNED_SYNTHETIC"
            if self.owned_sources
            else "UNQUALIFIED"
            if self._approval is None
            else "PRIVATE_CURRENT",
            state=self._state,
            error_code=self._error,
            deadline_at=self._deadline,
            qualified_quota_snapshot_remaining=None
            if self._approval is None
            else self._approval.plan_quota.remaining_credits,
        )

    def record_failure(self, error: AuthorizationError) -> None:
        self._state, self._error = error.state, error.code

    def completed(self) -> None:
        self._state = "ENGINEERING_READY" if self.owned_sources else "REAL_RUN_COMPLETED"

    def check_publication(self, grant: RefreshGrant, now: datetime) -> None:
        if grant.classification == "OWNED_SYNTHETIC":
            if not self.owned_sources:
                raise AuthorizationError("SOURCE_CLASSIFICATION_MISMATCH")
            return
        rows = [
            row
            for row in production_approvals()
            if canonical_sha256(row.model_dump(mode="json")) == grant.approval_sha256
        ]
        if len(rows) != 1 or rows[0].status != "APPROVED_REVIEWED":
            raise AuthorizationError("AUTHORIZATION_REVOKED")
        if not rows[0].not_before <= now < rows[0].expires_at:
            raise AuthorizationError("AUTHORIZATION_EXPIRED", "EXPIRED")
        if grant.request.implementation_sha != implementation_fingerprint():
            raise AuthorizationError("IMPLEMENTATION_IDENTITY_CHANGED")

    @classmethod
    def enrolled(
        cls,
        *,
        authorization_id: str,
        entry_id: int,
        deadline_at: datetime,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> CurrentRefreshSession:
        rows = [row for row in production_approvals() if row.authorization_id == authorization_id]
        if len(rows) != 1:
            raise AuthorizationError(
                "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED", "RIGHTS_APPROVAL_REQUIRED"
            )
        approval = rows[0]
        if approval.qualified_deadline_at is None or deadline_at != approval.qualified_deadline_at:
            raise AuthorizationError("AUTHORIZATION_DEADLINE_SCOPE_MISMATCH")
        if approval.ledger_backend != "POSTGRES":
            raise AuthorizationError("PRODUCTION_CONTROL_STORE_NOT_ACCEPTED")
        value = cls(
            entry_id=entry_id,
            approval=approval,
            ledger=_postgres_ledger(
                approval.ledger_id, approval.plan_quota.account_ref, "OPERATOR_CONTROL_DATABASE"
            ),
            clock=clock,
            deadline_at=deadline_at,
        )
        return value

    @classmethod
    def owned(cls, ledger_path: Path) -> CurrentRefreshSession:
        ledger = DurableUsageLedger.create(ledger_path)
        inputs = demo_inputs()
        bootstrap = json.loads(inputs["fpl-0.json"])
        target = [row for row in bootstrap["events"] if row["is_next"]]
        if len(target) != 1:
            raise ValueError("owned official deadline unresolved")
        deadline = datetime.fromisoformat(target[0]["deadline_time"])
        from dmf_pulse.ingestion.openfootball.config import OpenFootballProviderConfig

        config = OpenFootballProviderConfig.model_validate_json(inputs["score-config.json"])
        profile = resolved_profiles()
        paths: dict[Provider, tuple[str, tuple[str, ...]]] = {
            "FPL": (
                "fantasy.premierleague.com",
                (
                    "/api/bootstrap-static/",
                    "/api/fixtures/",
                    "/api/entry/42/",
                    "/api/entry/42/history/",
                    "/api/entry/42/transfers/",
                    "/api/entry/42/event/1/picks/",
                    "/api/my-team/42/",
                    "/api/event/1/live/",
                ),
            ),
            "ODDS": ("api.the-odds-api.com", ("/v4/sports/soccer_epl/odds",)),
            "OPENFOOTBALL": (
                "raw.githubusercontent.com",
                (
                    config.raw_path("LICENSE.md"),
                    *(config.raw_path(row.path) for row in config.seasons),
                ),
            ),
        }
        scopes = tuple(
            SourceScope(
                provider=provider,
                account_ref=f"owned-{provider.lower()}",
                profile_id=profile[provider].rights_profile_id,
                profile_sha256=profile_fingerprint(profile[provider]),
                source_kind="REPOSITORY_OWNED_SYNTHETIC",
                routes=tuple(RouteBudget(host=host, path=path, maximum_calls=1) for path in routes),
            )
            for provider, (host, routes) in paths.items()
        )
        approval = OperatorRefreshApproval(
            authorization_id="ACCEL003-OWNED-CURRENT",
            classification="OWNED_SYNTHETIC",
            approval_evidence_sha256=canonical_sha256("OWNED_SYNTHETIC_ENGINEERING_ONLY"),
            implementation_sha=implementation_fingerprint(),
            review_sha256=canonical_sha256("OWNED_TEST_SCOPE"),
            operator_ref="owned-test-operator",
            purpose="PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
            season_code="2026/27",
            horizons=(1, 3),
            source_scopes=scopes,
            plan_quota=QualifiedPlanQuota(
                account_ref="owned-odds",
                plan_ref="owned-synthetic-plan",
                evidence_sha256="a" * 64,
                terms_evidence_sha256="b" * 64,
                monthly_plan_credits=100,
                allocated_monthly_credits=100,
                remaining_credits=100,
                observed_at=DEMO_TIME,
                period_started_at=DEMO_TIME - timedelta(hours=1),
                resets_at=DEMO_TIME + timedelta(days=1),
            ),
            ledger_id=ledger.ledger_id,
            status="APPROVED_REVIEWED",
            usage="MANUAL_RECURRING",
            approved_at=DEMO_TIME - timedelta(minutes=1),
            not_before=DEMO_TIME - timedelta(minutes=1),
            expires_at=DEMO_TIME + timedelta(hours=1),
            quota_max_age_seconds=3600,
            max_acquisition_seconds=300,
            max_run_seconds=900,
            daily_request_limit=20,
            daily_credit_limit=40,
            monthly_request_limit=50,
            monthly_credit_limit=100,
            safety_reserve_credits=0,
            control_metadata_retention_approved=True,
        )
        value = cls(
            entry_id=42,
            approval=approval,
            ledger=ledger,
            clock=lambda: DEMO_TIME,
            credentials_available=lambda: True,
        )
        value._owned_sources = True
        value._deadline = deadline
        value._authorizer = RefreshAuthorizer.for_owned_sources(
            approval, ledger, clock=lambda: DEMO_TIME
        )
        value._state, value._error = "ENGINEERING_READY", None
        return value
