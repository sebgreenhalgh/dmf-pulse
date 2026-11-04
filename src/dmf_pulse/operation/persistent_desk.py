"""Persistent historical browser facade with explicit, single-job acquisition."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from secrets import token_hex, token_urlsafe
from threading import Event, Thread
from time import monotonic
from typing import TYPE_CHECKING, Any, Literal

from pydantic import SecretStr

from dmf_pulse.credentials.service import CredentialError, CredentialService
from dmf_pulse.dashboard.authorization import AuthorizationError
from dmf_pulse.dashboard.current import CurrentEligibility
from dmf_pulse.dashboard.runtime import DeskRuntime, JobState
from dmf_pulse.dashboard.views import DeskView, PlayerDetail
from dmf_pulse.operation.analysis_store import AnalysisStore
from dmf_pulse.operation.diagnostics import DiagnosticReport
from dmf_pulse.operation.models import ChargedQuotaStatus, OperationError

if TYPE_CHECKING:
    from dmf_pulse.operation.analysis_models import AnalysisSnapshot
    from dmf_pulse.operation.journal import OperationJournal
    from dmf_pulse.operation.standing import StandingPolicy


class PersistentDeskRuntime(DeskRuntime):
    """History is independent of active eligibility, token expiry and job failures."""

    persistent = True

    def __init__(
        self,
        store: AnalysisStore,
        *,
        local_check: Callable[[], None],
        register: Callable[[SecretStr], datetime],
        prepare: Callable[[Callable[[str], None], Event], DeskRuntime],
        provenance: Literal["NORMAL_STANDING", "OWNED_SYNTHETIC"] = "NORMAL_STANDING",
    ) -> None:
        super().__init__()
        self.store = store
        self._provenance = provenance
        self._local_check, self._register, self._prepare = local_check, register, prepare
        self._saved = store.snapshot()
        self._active: DeskRuntime | None = None
        self._thread: Thread | None = None
        self._cancel_event = Event()
        self._challenge: str | None = None
        self._challenge_at = 0.0
        self._attempt_id: str | None = None
        self._failure_saved = False
        self._terminal_diagnostics: DiagnosticReport | None = None
        self._terminal_quota: ChargedQuotaStatus | None = None
        self._state = JobState(
            status="COMPLETE" if self._saved else "PENDING",
            job_id=None if self._saved is None else self._saved.run_id,
        )
        self._eligibility = CurrentEligibility(
            source_classification="OWNED_SYNTHETIC"
            if provenance == "OWNED_SYNTHETIC"
            else "PRIVATE_CURRENT",
            state="ENGINEERING_READY",
            retention="TRANSIENT_INPUTS_PRIVATE_DERIVED_RECEIPT_RETAINED",
        )

    @classmethod
    def production(
        cls, policy: StandingPolicy, journal: OperationJournal, store: AnalysisStore
    ) -> PersistentDeskRuntime:
        from dmf_pulse.operation.standing import require_policy
        from dmf_pulse.operation.start import prepare_runtime

        for publication in journal.analysis_publications():
            digest = publication["value"].get("analysis_sha256")
            if digest is not None:
                staged = store.snapshot(
                    publication["value"]["view"]["job_id"], include_pending=True
                )
                if (
                    staged is None
                    or staged.view.model_dump(mode="json") != publication["value"]["view"]
                ):
                    raise OperationError("REAL_PRIVATE_PUBLICATION_REQUIRED")
                store.confirm(
                    publication["value"]["view"]["job_id"],
                    digest,
                    publication["sha256"],
                    at=publication["at"],
                )

        def check() -> None:
            if require_policy() != policy:
                raise OperationError("STANDING_RELEASE_IDENTITY_CHANGED")
            journal.local_refresh_check(now=datetime.now(UTC))
            saved = store.snapshot()
            # A retained diagnostic cannot be mistaken for a new normal grant.
            if saved is not None and datetime.now(UTC) < saved.view.deadline_at:
                from dmf_pulse.operation.standing import execution_key

                if journal.contains_event(execution_key(policy, saved.view.gameweeks[0])):
                    raise OperationError("GAMEWEEK_ACQUISITION_ALREADY_RECORDED")

        def register(secret: SecretStr) -> datetime:
            return CredentialService().set_fpl_jwt(
                secret,
                minimum_remaining_seconds=policy.limits.credential_minimum_remaining_seconds,
                maximum_remaining_seconds=policy.limits.credential_maximum_remaining_seconds,
            )

        instance = cls(
            store,
            local_check=check,
            register=register,
            prepare=lambda progress, cancelled: prepare_runtime(
                policy,
                progress=progress,
                ensure_credentials=False,
                analysis_store=store,
                cancelled=cancelled.is_set,
            ),
        )
        try:
            check()
        except (OperationError, AuthorizationError) as error:
            instance._eligibility = instance._eligibility.model_copy(
                update={"state": "BLOCKED", "error_code": error.code}
            )
        return instance

    def refresh(self, horizon: Literal[1, 3]) -> JobState:
        with self._lock:
            if self._closed:
                return JobState(
                    status="BLOCKED",
                    error_code="WORKER_CLEANUP_FAILED"
                    if self._state.error_code == "WORKER_CLEANUP_FAILED"
                    else "SESSION_CLOSED",
                )
            if self._thread is not None and self._thread.is_alive():
                return (
                    self._state
                    if self._state.status == "RUNNING"
                    else JobState(status="BLOCKED", error_code="REFRESH_CLEANUP_IN_PROGRESS")
                )
            if self._state.status == "RUNNING":
                return self._state
            if horizon != 1:
                return JobState(status="BLOCKED", error_code="AUTHORIZATION_HORIZON_NOT_APPROVED")
            try:
                self._local_check()
            except (OperationError, AuthorizationError) as error:
                self._challenge = None
                self._eligibility = self._eligibility.model_copy(
                    update={"state": "BLOCKED", "error_code": error.code}
                )
                self._state = JobState(status="BLOCKED", error_code=error.code)
                self.store.failure(
                    token_hex(32), error.code, at=datetime.now(UTC), provenance=self._provenance
                )
                return self._state
            self._challenge, self._challenge_at = token_urlsafe(32), monotonic()
            self._state = JobState(
                status="PENDING",
                stages=("Enter a freshly issued FPL JWT in the secure local prompt.",),
            )
            self._eligibility = self._eligibility.model_copy(
                update={"state": "ENGINEERING_READY", "error_code": None}
            )
            return self._state

    def credential_challenge(self) -> str | None:
        with self._lock:
            return self._challenge if monotonic() - self._challenge_at < 120 else None

    def submit_fpl(self, secret: SecretStr, challenge: str) -> JobState:
        import hmac

        with self._lock:
            expected = self.credential_challenge()
            if self._closed or expected is None or not hmac.compare_digest(expected, challenge):
                del secret
                return JobState(
                    status="BLOCKED", error_code="CREDENTIAL_PROMPT_EXPIRED_OR_CONSUMED"
                )
            self._challenge = None
            try:
                self._local_check()
                self._register(secret)
            except (OperationError, AuthorizationError, CredentialError) as error:
                self._state = JobState(status="BLOCKED", error_code=error.code)
                self.store.failure(
                    token_hex(32), error.code, at=datetime.now(UTC), provenance=self._provenance
                )
                return self._state
            finally:
                del secret
            self._cancel_event = Event()
            self._attempt_id, self._failure_saved = token_hex(32), False
            self._terminal_diagnostics = None
            self._terminal_quota = None
            self._state = JobState(
                status="RUNNING",
                job_id=self._attempt_id,
                stages=("Credential registered; checking current policy and quota.",),
            )
            self._thread = Thread(
                target=self._prepare_job, name="dmf-explicit-refresh", daemon=True
            )
            self._thread.start()
            return self._state

    def _progress(self, text: str) -> None:
        # Callers emit application-owned messages, never provider exceptions.
        with self._lock:
            self._state = self._state.model_copy(
                update={"stages": (*self._state.stages[-31:], text)}
            )

    def _prepare_job(self) -> None:
        try:
            active = self._prepare(self._progress, self._cancel_event)
            with self._lock:
                if self._cancel_event.is_set() or self._closed:
                    self._active = active
                    self._close_active()
                else:
                    self._active = active
        except (OperationError, AuthorizationError, CredentialError) as error:
            with self._lock:
                self._state = JobState(
                    status="BLOCKED", job_id=self._attempt_id, error_code=error.code
                )
        except Exception:
            with self._lock:
                self._state = JobState(
                    status="BLOCKED",
                    job_id=self._attempt_id,
                    error_code="RUN_OR_PUBLICATION_INVALID",
                )

    def tick(self) -> JobState:
        with self._lock:
            if self._closed:
                return self._state
            if self._active is not None:
                self._state = self._active.tick()
                if self._state.status in {"COMPLETE", "BLOCKED", "EXPIRED", "CANCELLED"}:
                    self._capture_terminal()
                if self._state.status == "COMPLETE":
                    self._saved = self.store.snapshot()
                    self._eligibility = self._eligibility.model_copy(
                        update={"error_code": "GAMEWEEK_ACQUISITION_ALREADY_RECORDED"}
                    )
                    self._close_active()
                    self._attempt_id = None
                elif self._state.status in {"BLOCKED", "EXPIRED", "CANCELLED"}:
                    self._close_active()
            self._record_terminal_failure()
            return self._state

    def _capture_terminal(self) -> None:
        if self._active is not None:
            observed = self._active.eligibility()
            if observed is not None:
                self._eligibility = observed
                self._terminal_quota = observed.actual_market_quota
            self._terminal_diagnostics = self._active.diagnostics()

    def _record_terminal_failure(self) -> None:
        if (
            self._attempt_id is not None
            and not self._failure_saved
            and self._state.status in {"BLOCKED", "EXPIRED", "CANCELLED"}
        ):
            self.store.failure(
                self._attempt_id,
                self._state.error_code or "OPERATOR_RUN_CANCELLED",
                at=datetime.now(UTC),
                diagnostics=self._terminal_diagnostics,
                quota=self._terminal_quota,
                provenance=self._provenance,
            )
            self._failure_saved = True

    @property
    def synthetic_sources(self) -> bool:
        return self._provenance == "OWNED_SYNTHETIC"

    def _close_active(self) -> None:
        if self._active is not None:
            try:
                self._active.close()
                if not self._active.cleanup_complete():
                    raise OperationError("WORKER_CLEANUP_FAILED")
            except Exception:
                self._closed = True
                self._state = JobState(status="BLOCKED", error_code="WORKER_CLEANUP_FAILED")
                self._record_terminal_failure()
                raise OperationError("WORKER_CLEANUP_FAILED") from None
            self._active = None

    def view(self) -> DeskView | None:
        with self._lock:
            if self._saved is None:
                return None
            # The original timestamps remain unchanged in SQLite. No invented
            # future expiry makes a historical recommendation actionable.
            return self._saved.view.model_copy(
                update={
                    "dataset_mode": "PRIVATE_RETAINED_AS_OF"
                    if self._saved.provenance_class != "OWNED_SYNTHETIC"
                    else self._saved.view.dataset_mode,
                    "restrictions": (
                        *self._saved.view.restrictions,
                        "HISTORICAL_AS_OF_NOT_CURRENT",
                    ),
                }
            )

    def select_run(self, run_id: str) -> DeskView | None:
        with self._lock:
            saved = self.store.snapshot(run_id)
            if saved is not None:
                self._saved = saved
            return self.view() if saved is not None else None

    def history(self) -> list[dict[str, Any]]:
        return self.store.history()

    def compare_runs(self, first: str, second: str) -> dict[str, Any] | None:
        """Observed differences only; no optimizer rerun or causal explanation."""
        left, right = self.store.snapshot(first), self.store.snapshot(second)
        if left is None or right is None or first == second:
            return None
        old = {p.catalogue.official_id: p for p in left.view.players}
        new = {p.catalogue.official_id: p for p in right.view.players}
        rows = []
        for identity in sorted(old.keys() | new.keys()):
            a, b = old.get(identity), new.get(identity)
            before = None if a is None else a.expected_points
            after = None if b is None else b.expected_points
            rows.append(
                {
                    "official_id": identity,
                    "old_name": None if a is None else a.catalogue.name,
                    "new_name": None if b is None else b.catalogue.name,
                    "old_expected_points": before,
                    "new_expected_points": after,
                    "expected_points_delta": None
                    if before is None or after is None
                    else after - before,
                }
            )

        def summary(value: AnalysisSnapshot) -> dict[str, Any]:
            return {
                "run_id": value.run_id,
                "gameweeks": value.view.gameweeks,
                "generated_at": value.view.generated_at.isoformat(),
                "information_cutoff": value.view.information_cutoff.isoformat(),
                "provenance_class": value.provenance_class,
                "validation": value.validation,
                "implementation_sha": value.implementation_sha,
                "wheel_sha256": value.wheel_sha256,
                "team": value.view.team.model_dump(mode="json"),
            }

        return {
            "schema_version": "historical-comparison-v1",
            "first": summary(left),
            "second": summary(right),
            "players": rows,
            "attribution": "OBSERVED_DIFFERENCES_ONLY_NO_CAUSAL_OR_VALIDATION_CLAIM",
        }

    def analysis_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": "persistent-desk-v1",
                "historical": True,
                "selected_run": None if self._saved is None else self._saved.run_id,
                "provenance_class": None if self._saved is None else self._saved.provenance_class,
                "validation": "UNVALIDATED",
                "quota_is_last_observed_not_current": True,
                "captaincy_explanation": "UNAVAILABLE_IN_RETAINED_ENGINE_OUTPUT",
                "fixture_details_available": self._saved is not None
                and self._saved.presentation is not None,
                "optimizer_evidence_available": self._saved is not None
                and self._saved.optimizer_evidence is not None,
                "last_failure": self.store.query(
                    "SELECT f.attempt_id,f.recorded_at,f.error_code,e.derived_json FROM failed_attempts f LEFT JOIN failure_evidence e USING(attempt_id) ORDER BY f.recorded_at DESC LIMIT 1"
                ),
            }

    def optimizer_evidence(self) -> dict[str, Any]:
        with self._lock:
            saved = self._saved
        return {
            "run_id": None if saved is None else saved.run_id,
            "optimizer_evidence": None
            if saved is None or saved.optimizer_evidence is None
            else saved.optimizer_evidence.model_dump(mode="json"),
            "captain_only_explanation": "UNAVAILABLE_IN_RETAINED_ENGINE_OUTPUT",
        }

    def eligibility(self) -> CurrentEligibility:
        return self._eligibility

    def player(self, official_id: int) -> PlayerDetail:
        from dmf_pulse.operation.analysis_player import saved_player

        with self._lock:
            if self._saved is None:
                raise ValueError("HISTORICAL_RUN_UNAVAILABLE")
            return saved_player(self._saved, official_id)

    def player_pair(self, first: int, second: int) -> tuple[PlayerDetail, PlayerDetail]:
        from dmf_pulse.operation.analysis_player import saved_player

        with self._lock:
            saved = self._saved
        if saved is None:
            raise ValueError("HISTORICAL_RUN_UNAVAILABLE")
        return saved_player(saved, first), saved_player(saved, second)

    def cancel(self) -> JobState:
        with self._lock:
            self._challenge = None
            self._cancel_event.set()
            if self._active is not None:
                self._capture_terminal()
                self._active.cancel()
                self._active.tick()
                self._close_active()
            self._state = JobState(
                status="CANCELLED", job_id=self._attempt_id, error_code="OPERATOR_RUN_CANCELLED"
            )
            self._record_terminal_failure()
            return self._state

    def close(self) -> None:
        self.cancel()
        with self._lock:
            self._closed = True
            thread = self._thread
        if thread is not None:
            thread.join(timeout=320)
            if thread.is_alive():
                raise OperationError("WORKER_CLEANUP_FAILED")

    def cleanup_complete(self) -> bool:
        with self._lock:
            return (
                self._closed
                and self._active is None
                and (self._thread is None or not self._thread.is_alive())
            )
