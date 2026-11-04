"""One explicit launch, one bounded acquisition, one private local dashboard."""

from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from dmf_pulse.credentials.service import CredentialError, CredentialService
from dmf_pulse.dashboard.authorization import AuthorizationError
from dmf_pulse.dashboard.current import (
    CurrentEligibility,
    CurrentRefreshSession,
    CurrentWorkerResult,
)
from dmf_pulse.dashboard.runtime import DeskRuntime, JobState
from dmf_pulse.dashboard.views import DeskView, PlayerDetail
from dmf_pulse.operation.analysis_optimizer import AnalysisOptimizerEvidence
from dmf_pulse.operation.analysis_store import AnalysisStorageError
from dmf_pulse.operation.journal import OperationJournal
from dmf_pulse.operation.models import ChargedQuotaStatus, OperationError
from dmf_pulse.operation.quota import (
    QUOTA_HOST,
    QUOTA_PATH,
    QuotaClient,
    QuotaLookupError,
    QuotaSourceQualification,
)
from dmf_pulse.operation.standing import (
    QuotaProof,
    StandingPolicy,
    execution_key,
    require_history_policy,
    require_policy,
)
from dmf_pulse.private_v1.one_command import OneCommandResult

PORT = 8765

if TYPE_CHECKING:
    from dmf_pulse.operation.analysis_store import AnalysisStore


def retained_receipt_view(view: DeskView) -> DeskView:
    marker = "PRIVATE_DERIVED_RECEIPT_RETAINED_SOURCE_BODIES_TRANSIENT"
    return view.model_copy(
        update={
            "restrictions": (
                *(
                    item
                    for item in view.restrictions
                    if item not in {"TRANSIENT_SESSION_NO_RETENTION", marker}
                ),
                marker,
            )
        }
    )


def ensure_fpl_credential(
    policy: StandingPolicy,
    *,
    service: CredentialService | None = None,
    prompt: Callable[..., datetime] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> datetime:
    """Metadata-only reuse; only a newly supplied token is decoded by the prompt."""
    from dmf_pulse.cli.credentials import prompt_fpl_jwt

    credentials = service or CredentialService()
    status = credentials.status("fpl")
    minimum = policy.limits.credential_minimum_remaining_seconds
    if (
        status.configured
        and status.expires_at is not None
        and status.registered_at is not None
        and status.expires_at >= clock() + timedelta(seconds=minimum)
        and status.expires_at
        <= clock() + timedelta(seconds=policy.limits.credential_maximum_remaining_seconds)
    ):
        return status.expires_at
    return (prompt or prompt_fpl_jwt)(
        minimum_remaining_seconds=minimum,
        maximum_remaining_seconds=policy.limits.credential_maximum_remaining_seconds,
        service=credentials,
    )


class PreparationGuard:
    """Separate single-call quota or official-discovery admission, no paid route."""

    def __init__(
        self,
        policy: StandingPolicy,
        *,
        provider: Literal["ODDS", "FPL"],
        clock: Callable[[], datetime],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.policy, self.provider, self.clock = policy, provider, clock
        self.cancelled = cancelled
        self.path = QUOTA_PATH if provider == "ODDS" else "/api/bootstrap-static/"
        self.host = QUOTA_HOST if provider == "ODDS" else "fantasy.premierleague.com"
        self.started_at = clock()
        self.attempted = False

    def admission(self) -> None:
        if self.cancelled():
            raise OperationError("OPERATOR_RUN_CANCELLED")
        current = require_policy()
        now = self.clock()
        if current != self.policy or not self.started_at <= now < self.started_at + timedelta(
            seconds=self.policy.limits.max_acquisition_seconds
        ):
            raise OperationError("PREPARATION_AUTHORITY_CHANGED_OR_EXPIRED")

    def quota_admission(
        self, qualification: QuotaSourceQualification, *, checked_at: datetime
    ) -> None:
        self.admission()
        if (
            qualification != self.policy.quota_qualification
            or not qualification.qualified_at <= checked_at
        ):
            raise OperationError("QUOTA_SOURCE_NOT_ENROLLED")

    def preflight_send(self, provider: Literal["ODDS"], method: str, host: str, path: str) -> None:
        self.admission()
        if (provider, method, host, path) != (
            self.provider,
            "GET",
            self.host,
            self.path,
        ) or self.attempted:
            raise OperationError("PREPARATION_ROUTE_OR_BUDGET_DENIED")

    def before_send(self, provider: Literal["ODDS"], method: str, host: str, path: str) -> None:
        self.preflight_send(provider, method, host, path)
        self.attempted = True

    def before_transport(self) -> None:
        self.admission()

    def discovery_before_send(self) -> None:
        self.admission()
        if self.attempted:
            raise OperationError("DISCOVERY_REQUEST_ALREADY_ATTEMPTED")
        self.attempted = True


class SingleAcquisitionRuntime(DeskRuntime):
    """Browser actions never initiate another provider acquisition in this launch."""

    def __init__(
        self,
        *,
        current_session: CurrentRefreshSession,
        on_publication: Callable[[DeskView], None],
        on_failure: Callable[[str], None],
        quota_status: Callable[[], ChargedQuotaStatus | None] | None = None,
        on_derived: Callable[[DeskView, OneCommandResult, AnalysisOptimizerEvidence | None], None]
        | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        from dmf_pulse.operation.standing_worker import StandingWorker

        self._publishing_result: OneCommandResult | None = None
        self._publishing_optimizer: AnalysisOptimizerEvidence | None = None

        def publish(view: DeskView) -> None:
            if on_derived is not None:
                if self._publishing_result is None:
                    raise AuthorizationError("WORKER_RESULT_BINDING_INVALID")
                on_derived(view, self._publishing_result, self._publishing_optimizer)
            else:
                on_publication(view)

        super().__init__(
            current_session=current_session,
            on_publication=publish,
            current_worker_factory=StandingWorker,
            clock=clock,
        )
        self._launch_started = False
        self._on_failure = on_failure
        self._failure_recorded = False
        self._quota_status = quota_status
        self._observed_quota: ChargedQuotaStatus | None = None

    def _accept(
        self, value: OneCommandResult, *, envelope: CurrentWorkerResult | None = None
    ) -> None:
        from dmf_pulse.operation.standing_pipeline import validate_standing_source_proof

        if self._active_launch is None:
            raise AuthorizationError("WORKER_RESULT_BINDING_INVALID")
        validate_standing_source_proof(tuple(self._diagnostics.events), value, self._active_launch)
        self._publishing_result = value
        self._publishing_optimizer = None if envelope is None else envelope.optimizer_evidence
        try:
            super()._accept(value, envelope=envelope)
        finally:
            self._publishing_result = None
            self._publishing_optimizer = None

    def tick(self) -> JobState:
        state = super().tick()
        if (
            self._launch_started
            and state.status in {"BLOCKED", "EXPIRED", "CANCELLED"}
            and not self._failure_recorded
        ):
            self._failure_recorded = True
            self._on_failure(state.error_code or "OPERATOR_RUN_CANCELLED")
        return state

    def refresh(self, horizon: Literal[1, 3]) -> JobState:
        with self._lock:
            if self._launch_started:
                return self.tick()
            self._launch_started = True
            if horizon != 1:
                return JobState(status="BLOCKED", error_code="AUTHORIZATION_HORIZON_NOT_APPROVED")
            return super().refresh(horizon)

    def view(self) -> DeskView | None:
        view = super().view()
        return None if view is None else retained_receipt_view(view)

    def eligibility(self) -> CurrentEligibility | None:
        value = super().eligibility()
        if self._observed_quota is None and self._quota_status is not None:
            self._observed_quota = self._quota_status()
        return (
            None
            if value is None
            else value.model_copy(
                update={
                    "retention": "TRANSIENT_INPUTS_PRIVATE_DERIVED_RECEIPT_RETAINED",
                    "actual_market_quota": self._observed_quota,
                }
            )
        )


class RetainedRuntime(DeskRuntime):
    """A stored derived view is explicitly historical, never a fresh grant/result."""

    def __init__(self, view: DeskView) -> None:
        super().__init__()
        self._saved = view
        self._display_until = datetime.now(UTC) + timedelta(seconds=900)
        self._state = JobState(status="COMPLETE", job_id=view.job_id)

    def tick(self) -> JobState:
        if datetime.now(UTC) >= self._display_until:
            self._state = JobState(status="EXPIRED", error_code="PRESENTATION_LIFETIME_ENDED")
        return self._state

    def refresh(self, horizon: Literal[1, 3]) -> JobState:
        del horizon
        return self.tick()

    def eligibility(self) -> CurrentEligibility:
        return CurrentEligibility(
            source_classification="PRIVATE_CURRENT",
            state="REAL_RUN_COMPLETED",
            error_code="GAMEWEEK_ACQUISITION_ALREADY_RECORDED",
            deadline_at=self._saved.deadline_at,
        )

    def view(self) -> DeskView | None:
        if self.tick().status != "COMPLETE":
            return None
        return self._saved.model_copy(
            update={
                "dataset_mode": "PRIVATE_RETAINED_AS_OF",
                "expires_at": self._display_until,
                "expires_in_seconds": max(
                    0.0, (self._display_until - datetime.now(UTC)).total_seconds()
                ),
                "restrictions": (
                    *(
                        item
                        for item in self._saved.restrictions
                        if item != "TRANSIENT_SESSION_NO_RETENTION"
                    ),
                    "RETAINED_AS_OF_NOT_CURRENT_NO_NEW_ACQUISITION",
                ),
            }
        )

    def player(self, official_id: int) -> PlayerDetail:
        del official_id
        raise ValueError("retained player means are available in the saved table")

    def cancel(self) -> JobState:
        self._state = JobState(status="CANCELLED")
        return self._state


class BlockedRuntime(DeskRuntime):
    """A preflight failure remains visible locally without source side effects."""

    def __init__(self, code: str) -> None:
        super().__init__()
        from dmf_pulse.operation.failures import operator_action

        self._blocked = JobState(status="BLOCKED", error_code=code, stages=(operator_action(code),))

    def tick(self) -> JobState:
        return self._blocked

    def refresh(self, horizon: Literal[1, 3]) -> JobState:
        del horizon
        return self._blocked

    def eligibility(self) -> CurrentEligibility:
        return CurrentEligibility(
            source_classification="UNQUALIFIED",
            state="BLOCKED",
            error_code=self._blocked.error_code,
        )


def prepare_runtime(
    policy: StandingPolicy,
    *,
    progress: Callable[[str], None],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ensure_credentials: bool = True,
    analysis_store: AnalysisStore | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> DeskRuntime:
    from dmf_pulse.operation.discovery import discover_event

    journal = OperationJournal.production(policy)
    journal.recover()
    progress("Original PostgreSQL ledger recovered; history retained.")
    if ensure_credentials:
        ensure_fpl_credential(policy, clock=clock)
    launch = journal.begin_launch(now=clock())
    key: str | None = None
    try:
        progress("Checking account quota with the separate zero-credit sports request.")
        quota_guard = PreparationGuard(policy, provider="ODDS", clock=clock, cancelled=cancelled)
        observed = QuotaClient(guard=quota_guard, clock=clock).fetch(
            policy.quota_qualification, admission=quota_guard.quota_admission
        )
        quota = QuotaProof(
            source="ZERO_CREDIT_PROVIDER_RESPONSE_HEADERS",
            remaining_credits=observed.remaining_credits,
            used_credits=observed.used_credits,
            last_request_cost=0,
            request_started_at=observed.request_started_at,
            received_at=observed.received_at,
            qualification_sha256=observed.qualification_sha256,
            observation_sha256=observed.semantic_sha256,
        )
        journal.record_quota(quota, now=clock(), observation=observed)
        journal.qualify_quota(quota, now=clock())
        progress("Quota verified against actual headers and canonical consumption.")
        discovery_guard = PreparationGuard(policy, provider="FPL", clock=clock, cancelled=cancelled)
        fpl = next(q for q in policy.qualifications if q.scope.provider == "FPL")
        event = discover_event(
            profile=fpl.profile,
            admission=discovery_guard.admission,
            before_send=discovery_guard.discovery_before_send,
            clock=clock,
        )
        journal.record_discovery(event, now=clock())
        if cancelled():
            raise OperationError("OPERATOR_RUN_CANCELLED")
        key = execution_key(policy, event.target_gameweek)
        if journal.contains_event(key):
            saved = journal.saved_view(key)
            if saved is None:
                raise OperationError("GAMEWEEK_ALREADY_ATTEMPTED_NO_COMPLETED_PUBLICATION")
            progress("Showing retained as-of recommendations; no new paid acquisition.")
            return RetainedRuntime(saved)
        journal.enroll(event, quota, now=clock())
        progress(
            f"GW{event.target_gameweek} admitted from official FPL data. Reserving two credits; zero retries."
        )
        session = CurrentRefreshSession.enrolled(
            authorization_id=f"OPR001-{key}",
            entry_id=policy.entry_id,
            deadline_at=event.deadline_at,
            clock=clock,
        )
        session.preflight(1)

        def publish(view: DeskView) -> None:
            journal.publish(
                key, retained_receipt_view(view), now=clock(), diagnostics=runtime.diagnostics()
            )
            receipt = view.market_quota_receipt
            progress(
                f"Real recommendations recorded. Odds reserved 2; actual cost {receipt.last_request_cost if receipt else 'unknown'}; remaining {receipt.remaining_credits if receipt else 'unknown'}."
            )

        def publish_analysis(
            view: DeskView, result: OneCommandResult, optimizer: AnalysisOptimizerEvidence | None
        ) -> None:
            from dmf_pulse.operation.analysis_models import AnalysisSnapshot
            from dmf_pulse.operation.maintenance import verify_active_release

            if analysis_store is None or result.presentation is None or optimizer is None:
                raise OperationError("REAL_PRIVATE_PUBLICATION_REQUIRED")
            retained = retained_receipt_view(view)
            snapshot = AnalysisSnapshot(
                run_id=view.job_id,
                provenance_class="NORMAL_STANDING",
                permission_origin=policy.permission_provenance,
                implementation_sha=policy.implementation_sha,
                policy_sha256=policy.semantic_sha256,
                wheel_sha256=verify_active_release(policy).wheel_sha256,
                recorded_at=clock(),
                view=retained,
                presentation=result.presentation,
                diagnostics=runtime.diagnostics(),
                optimizer_evidence=optimizer,
            )
            digest = analysis_store.stage(snapshot)
            canonical = journal.publish(
                key,
                retained,
                now=clock(),
                diagnostics=runtime.diagnostics(),
                analysis_sha256=digest,
            )
            analysis_store.confirm(snapshot.run_id, digest, canonical, at=clock())
            progress(
                "Recommendations durably published to the canonical ledger and analysis warehouse."
            )

        runtime = SingleAcquisitionRuntime(
            current_session=session,
            on_publication=publish,
            on_failure=lambda code: journal.fail(
                key, code, now=clock(), diagnostics=runtime.diagnostics()
            ),
            quota_status=lambda: journal.charged_quota_status(key),
            on_derived=publish_analysis if analysis_store is not None else None,
            clock=clock,
        )
        runtime.refresh(1)
        return runtime
    except (OperationError, AuthorizationError) as error:
        journal.fail(
            key,
            error.code,
            now=clock(),
            quota_evidence=error.evidence if isinstance(error, QuotaLookupError) else None,
        )
        raise
    finally:
        journal.close_launch(launch, now=clock())


def _open_when_ready(*, port: int, timeout: float = 10.0) -> None:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                webbrowser.open(f"http://127.0.0.1:{port}")
                return
        except OSError:
            time.sleep(0.05)


def run_start(*, progress: Callable[[str], None]) -> None:
    """Actual installed command; no provider action is triggered by HTTP/reload."""
    import uvicorn

    from dmf_pulse.dashboard.app import create_app
    from dmf_pulse.operation.analysis_paths import warehouse_path
    from dmf_pulse.operation.desk_instance import (
        register_instance,
        remove_instance,
        verified_existing_instance,
    )
    from dmf_pulse.operation.local_control import recover_local_control

    policy = require_history_policy()
    instance_path = warehouse_path().parent / "desk-instance.json"
    # Reserve the fixed loopback listener before credential entry or source I/O.
    # A repeated invocation opens the existing authenticated application only.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", PORT))
        listener.listen(8)
    except OSError:
        listener.close()
        if verified_existing_instance(instance_path, policy, PORT):
            webbrowser.open(f"http://127.0.0.1:{PORT}")
            progress("Opened the existing verified Seb's Desk; no refresh was started.")
            return
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED") from None
    runtime: DeskRuntime | None = None
    instance = None
    try:
        # Native process/listener ownership proof currently supports Windows.
        # Other platforms can start normally, but cannot reuse an unverified listener.
        if sys.platform == "win32":
            instance = register_instance(instance_path, policy, PORT)
        try:
            recover_local_control(policy)
            from dmf_pulse.operation.analysis_store import AnalysisStore
            from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime

            store = AnalysisStore(warehouse_path())
            store.initialize()
            journal = OperationJournal.production(policy)
            journal.recover()
            runtime = PersistentDeskRuntime.production(policy, journal, store)
        except (OperationError, AuthorizationError, CredentialError) as error:
            from dmf_pulse.operation.failures import operator_action

            progress(f"{error.code}: {operator_action(error.code)}")
            runtime = BlockedRuntime(error.code)
        except (OSError, ValueError, AnalysisStorageError):
            progress(
                "ANALYSIS_STORAGE_UNAVAILABLE_OR_INVALID: saved data was preserved; no refresh was admitted."
            )
            runtime = BlockedRuntime("ANALYSIS_STORAGE_UNAVAILABLE_OR_INVALID")
        application = create_app(
            runtime=runtime,
            pairing_code="unused-standing-local-session",
            port=PORT,
            trusted_local_navigation=True,
        )
        server = uvicorn.Server(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=PORT,
                access_log=False,
                log_config=None,
                log_level="critical",
                proxy_headers=False,
                server_header=False,
                limit_concurrency=8,
                timeout_keep_alive=5,
                timeout_graceful_shutdown=10,
            )
        )
        threading.Thread(target=_open_when_ready, kwargs={"port": PORT}, daemon=True).start()
        progress(f"Seb's Desk: http://127.0.0.1:{PORT} — forecasts remain unvalidated.")
        server.run(sockets=[listener])
    finally:
        try:
            if runtime is not None:
                runtime.close()
        finally:
            listener.close()
            if instance is not None and (runtime is None or runtime.cleanup_complete()):
                remove_instance(instance_path, instance)
