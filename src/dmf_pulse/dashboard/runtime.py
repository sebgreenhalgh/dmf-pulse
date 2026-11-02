"""Single-flight, disposable process execution and finite presentation lifetime."""

from __future__ import annotations

import multiprocessing
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from multiprocessing.connection import Connection
from secrets import token_hex
from threading import RLock
from time import monotonic
from typing import Literal, Protocol

from pydantic import computed_field

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.current_failures import (
    CURRENT_FAILURE_ACTIONS,
    CURRENT_FAILURE_CODES,
    EXPIRED_FAILURE_CODES,
)
from dmf_pulse.dashboard.authorization import AuthorizationError
from dmf_pulse.dashboard.current import (
    CurrentEligibility,
    CurrentLaunch,
    CurrentRefreshSession,
    CurrentWorkerResult,
    current_worker,
    validate_current_result,
)
from dmf_pulse.dashboard.views import DeskView, PlayerDetail, desk_view, player_detail
from dmf_pulse.operation.diagnostics import (
    MAX_EVENT_BYTES,
    STAGE_LABELS,
    STARTED_STAGES,
    DiagnosticEvent,
    DiagnosticLog,
    DiagnosticReport,
    Stage,
)
from dmf_pulse.private_v1.actionability import checked_report
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.one_command import OneCommandResult
from dmf_pulse.private_v1.presentation import PresentationModel

_CURRENT_PROGRESS = frozenset(
    {"DMF Pulse starting", "Recommendation ready", "Completed", *STAGE_LABELS.values()}
)


class JobState(PresentationModel):
    schema_version: Literal["desk-job-v1"] = "desk-job-v1"
    status: Literal["PENDING", "RUNNING", "COMPLETE", "BLOCKED", "CANCELLED", "EXPIRED"]
    job_id: str | None = None
    stages: tuple[str, ...] = ()
    error_code: str | None = None
    diagnostics: DiagnosticReport | None = None

    @computed_field
    def error_action(self) -> str | None:
        """Fixed operator guidance only; no provider or credential observation."""
        if self.error_code is None:
            return None
        from dmf_pulse.operation.failures import OPERATOR_FAILURE_ACTIONS

        return CURRENT_FAILURE_ACTIONS.get(self.error_code) or OPERATOR_FAILURE_ACTIONS.get(
            self.error_code
        )


class Worker(Protocol):
    def receive(self) -> tuple[str, object] | None: ...
    def alive(self) -> bool: ...
    def close(self) -> None: ...


class PipeProgress:
    """Only existing application stage messages cross this memory-only channel."""

    failure_reported = False

    def __init__(
        self,
        send: Callable[[tuple[str, object]], None],
        *,
        diagnostics: DiagnosticLog | None = None,
    ) -> None:
        self._send = send
        self.diagnostics = diagnostics

    def message(self, value: str) -> None:
        if self.diagnostics is not None and value not in _CURRENT_PROGRESS:
            return
        self._send(("progress", value[:200]))

    @contextmanager
    def stage(
        self,
        *,
        started: str | None,
        completed: str | None,
        failed: str,
        heartbeat: str | None = None,
        long_warning: str | None = None,
    ) -> Iterator[None]:
        del heartbeat, long_warning
        stage: Stage | None = STARTED_STAGES.get(started or "")
        if stage is None and failed == "Stage 8/9 fixture projection":
            stage = "STAGE8_EVENTS"
        elif stage is None and re.fullmatch(r"Stage 9 fixture [1-9][0-9]*/[1-9][0-9]*", failed):
            stage = "STAGE9_POINTS"
        if self.diagnostics is None:
            if started:
                self.message(started)
        elif stage is not None:
            self.diagnostics.enter(stage)
            self.message(STAGE_LABELS[stage])
        try:
            yield
        except Exception as error:
            if self.diagnostics is not None:
                self.diagnostics.failed(error)
            raise
        else:
            if self.diagnostics is None:
                if completed:
                    self.message(completed)
            elif stage is not None:
                self.diagnostics.stage = stage
                self.diagnostics.emit("STAGE_COMPLETED")

    def finish(self) -> None:
        self.message("Completed")

    def failure(self, stage: str, code: str) -> None:
        del stage
        self.failure_reported = True
        if self.diagnostics is not None and self.diagnostics.failure is None:
            active = sys.exception()
            self.diagnostics.failed(
                active
                if isinstance(active, Exception)
                else PrivateV1Error(code, "Closed failure boundary")
            )


def _demo_worker(pipe: Connection, horizon: Literal[1, 3]) -> None:
    try:
        from dmf_pulse.dashboard.synthetic import run_synthetic_recommendation

        result = run_synthetic_recommendation(horizon, PipeProgress(pipe.send))
        pipe.send(("result", result))
    except Exception:
        # Never serialize provider exceptions, tracebacks, headers, URLs or bodies.
        pipe.send(("error", "SYNTHETIC_RUN_BLOCKED"))
    finally:
        pipe.close()


class ProcessWorker:
    def __init__(
        self,
        horizon: Literal[1, 3],
        *,
        _target: Callable[..., None] = _demo_worker,
        _arguments: tuple[object, ...] = (),
    ) -> None:
        context = multiprocessing.get_context("spawn")
        self._reader, sender = context.Pipe(duplex=False)
        self._process = context.Process(
            target=_target, args=(sender, horizon, *_arguments), daemon=True
        )
        try:
            self._process.start()
        finally:
            sender.close()

    def receive(self) -> tuple[str, object] | None:
        if not self._reader.poll():
            return None
        value: object = self._reader.recv()
        if not isinstance(value, tuple) or len(value) != 2 or not isinstance(value[0], str):
            raise ValueError("invalid worker response")
        return value[0], value[1]

    def alive(self) -> bool:
        return self._process.is_alive()

    def close(self) -> None:
        self._reader.close()
        self._process.join(timeout=0.1)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=3)
        if self._process.is_alive():
            self._process.kill()
            self._process.join(timeout=3)
        if self._process.is_alive():
            raise RuntimeError("worker shutdown failed")
        self._process.close()


def _current_process(launch: CurrentLaunch) -> Worker:
    return ProcessWorker(launch.grant.request.horizon, _target=current_worker, _arguments=(launch,))


class DeskRuntime:
    """One operator/run; all derived presentation is discarded at the earliest limit."""

    def __init__(
        self,
        *,
        demo: bool = False,
        worker_factory: Callable[[Literal[1, 3]], Worker] = ProcessWorker,
        current_session: CurrentRefreshSession | None = None,
        current_worker_factory: Callable[[CurrentLaunch], Worker] = _current_process,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        elapsed_clock: Callable[[], float] = monotonic,
        lifetime_seconds: int = 900,
        run_timeout_seconds: int = 900,
        on_publication: Callable[[DeskView], None] | None = None,
    ) -> None:
        if not 1 <= lifetime_seconds <= 900 or not 1 <= run_timeout_seconds <= 900:
            raise ValueError("runtime bounds exceed private lifetime")
        self.demo = demo
        if demo and current_session is not None:
            raise ValueError("demo and current execution contexts cannot be combined")
        self._current = None if demo else current_session or CurrentRefreshSession()
        self._current_factory = current_worker_factory
        self._active_launch: CurrentLaunch | None = None
        self._current_result: CurrentWorkerResult | None = None
        self._factory = worker_factory
        self._clock = clock
        self._elapsed = elapsed_clock
        self._lifetime = lifetime_seconds
        self._timeout = run_timeout_seconds
        self._lock = RLock()
        self._worker: Worker | None = None
        self._result: OneCommandResult | None = None
        self._view: DeskView | None = None
        self._state = JobState(status="PENDING")
        self._started = self._elapsed()
        self._completed = self._started
        self._last_wall: datetime | None = None
        self._publication_floor: datetime | None = None
        self._closed = False
        self._on_publication = on_publication
        self._diagnostics = DiagnosticLog()
        self._diagnostic_started_at = datetime.now(UTC)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("invalid execution clock")
        value = value.astimezone(UTC)
        if self._last_wall is not None and value < self._last_wall:
            raise ValueError("execution clock reversed")
        self._last_wall = value
        return value

    def _discard(self, status: Literal["BLOCKED", "CANCELLED", "EXPIRED"], code: str) -> None:
        if status in {"BLOCKED", "EXPIRED"} and self._diagnostics.failure is None:
            self._diagnostics.failed(AuthorizationError(code))
        self._result = None
        self._view = None
        self._publication_floor = None
        self._active_launch = None
        self._current_result = None
        if self._current is not None:
            self._current.record_failure(
                AuthorizationError(code, "EXPIRED" if status == "EXPIRED" else "BLOCKED")
            )
        self._state = JobState(
            status=status,
            job_id=self._state.job_id,
            error_code=code,
            stages=self._state.stages,
            diagnostics=self.diagnostics(),
        )
        self._stop_worker()

    def _stop_worker(self) -> bool:
        if self._worker is not None:
            try:
                self._worker.close()
            except Exception as error:
                # Preserve the handle and permanently close this runtime. Never overlap
                # a replacement with a worker whose termination was not confirmed.
                self._closed = True
                self._diagnostics.failed(error)
                self._state = JobState(
                    status="BLOCKED",
                    error_code="WORKER_CLEANUP_FAILED",
                    job_id=self._state.job_id,
                    stages=self._state.stages,
                    diagnostics=self.diagnostics(),
                )
                if self._current is not None:
                    self._current.record_failure(AuthorizationError("WORKER_CLEANUP_FAILED"))
                return False
            self._worker = None
        return True

    def refresh(self, horizon: Literal[1, 3]) -> JobState:
        with self._lock:
            if self._closed:
                return JobState(status="BLOCKED", error_code="SESSION_CLOSED")
            self.tick()
            if self._worker is not None:
                return self._state
            self._discard("CANCELLED", "SUPERSEDED")
            if self._state.error_code == "WORKER_CLEANUP_FAILED":
                return self._state
            self._state = JobState(status="RUNNING", job_id=token_hex(16))
            self._diagnostics = DiagnosticLog()
            self._diagnostic_started_at = datetime.now(UTC)
            self._started = self._elapsed()
            try:
                if self.demo:
                    self._worker = self._factory(horizon)
                else:
                    if self._current is None:
                        raise AuthorizationError("OPERATOR_CONTROL_CONTEXT_REQUIRED")
                    launch = self._current.prepare(horizon)
                    self._active_launch = launch
                    self._worker = self._current_factory(launch)
            except AuthorizationError as error:
                self._discard("EXPIRED" if error.state == "EXPIRED" else "BLOCKED", error.code)
                if self._current is not None:
                    self._current.record_failure(error)
            except Exception as error:
                self._diagnostics.failed(error)
                self._discard("BLOCKED", "WORKER_START_FAILED")
            return self._state

    def tick(self) -> JobState:
        with self._lock:
            try:
                self._tick()
            except AuthorizationError as error:
                self._diagnostics.failed(error)
                self._discard("EXPIRED" if error.state == "EXPIRED" else "BLOCKED", error.code)
            except PrivateV1Error as error:
                self._diagnostics.failed(error)
                if error.code == "DECISION_DEADLINE_PASSED":
                    self._discard("EXPIRED", "DECISION_DEADLINE_PASSED")
                else:
                    self._discard("BLOCKED", "RUN_OR_PUBLICATION_INVALID")
            except Exception as error:
                self._diagnostics.failed(error)
                self._discard("BLOCKED", "RUN_OR_PUBLICATION_INVALID")
            return self._state

    def _tick(self) -> None:
        if self._closed:
            return
        if self._active_launch is not None:
            now = self._now()
            if self._current is None:
                raise AuthorizationError("OPERATOR_CONTROL_CONTEXT_REQUIRED")
            self._current.check_publication(self._active_launch.grant, now)
            if now >= self._active_launch.grant.expires_at:
                self._discard("EXPIRED", "AUTHORIZATION_EXPIRED")
                return
        if self._worker is not None:
            if self._elapsed() - self._started >= self._timeout:
                self._discard("BLOCKED", "RUN_TIMEOUT")
                return
            for _ in range(64):
                message = self._worker.receive()
                if message is None:
                    if not self._worker.alive():
                        self._discard("BLOCKED", "WORKER_STOPPED")
                    break
                kind, value = message
                if kind == "progress" and isinstance(value, str):
                    if not self.demo and value not in _CURRENT_PROGRESS:
                        continue
                    # The demonstration has no provider inputs; current progress is closed.
                    safe = re.sub(r"[^A-Za-z0-9 _.,:()/+\-]", "", value)[:200]
                    self._state = self._state.model_copy(
                        update={"stages": (*self._state.stages[-31:], safe)}
                    )
                elif kind == "diagnostic" and not self.demo and type(value) is str:
                    self._accept_diagnostic(value)
                elif kind == "result" and self.demo and isinstance(value, OneCommandResult):
                    self._accept(value)
                    break
                elif (
                    kind == "current_result"
                    and not self.demo
                    and isinstance(value, CurrentWorkerResult)
                ):
                    self._accept(value.result, envelope=value)
                    break
                elif kind == "error" and type(value) is str and value in CURRENT_FAILURE_CODES:
                    if (
                        not self.demo
                        and self._diagnostics.failure is not None
                        and self._diagnostics.failure.code != value
                    ):
                        self._discard("BLOCKED", "DIAGNOSTIC_PROTOCOL_INVALID")
                        return
                    self._diagnostics.worker_terminal_received = True
                    self._discard("EXPIRED" if value in EXPIRED_FAILURE_CODES else "BLOCKED", value)
                    if value == "SOURCE_NOT_AVAILABLE" and self._current is not None:
                        self._current.record_failure(
                            AuthorizationError(value, "SOURCE_NOT_AVAILABLE")
                        )
                    return
                else:
                    self._discard("BLOCKED", "RECOMMENDATION_BLOCKED")
                    return
        if self._result is not None:
            if not self.demo:
                if self._current_result is None or self._active_launch is None:
                    raise AuthorizationError("WORKER_RESULT_BINDING_INVALID")
                validate_current_result(self._current_result, self._active_launch)
            if self._elapsed() - self._completed >= self._lifetime:
                self._discard("EXPIRED", "PRESENTATION_LIFETIME_ENDED")
                return
            now = self._now()
            if self._view is not None and now >= self._view.expires_at:
                self._discard("EXPIRED", "PRESENTATION_LIFETIME_ENDED")
                return
            checked_report(self._result, clock=lambda: now)
            if self._publication_floor is not None and now < self._publication_floor:
                raise ValueError("publication clock reversed")
            self._publication_floor = now

    def _accept(
        self, value: OneCommandResult, *, envelope: CurrentWorkerResult | None = None
    ) -> None:
        now = self._now()
        checked_report(value, clock=lambda: now)
        if not self.demo:
            launch = self._active_launch
            if (
                launch is None
                or envelope is None
                or value.actionability.deadline_at != launch.grant.request.deadline_at
                or value.decision.information_cutoff != launch.grant.request.information_cutoff
                or value.presentation is None
                or len(value.presentation.gameweeks) != launch.grant.request.horizon
            ):
                raise ValueError("worker result differs from the authorized information set")
            validate_current_result(envelope, launch)
        if not self._stop_worker():
            return
        expires = min(value.actionability.deadline_at, now + timedelta(seconds=self._lifetime))
        if self._active_launch is not None:
            expires = min(expires, self._active_launch.grant.expires_at)
        self._view = desk_view(
            value,
            job_id=str(self._state.job_id),
            mode="SYNTHETIC_DEMONSTRATION"
            if self.demo
            else "SYNTHETIC_CURRENT_MODE"
            if self.synthetic_sources
            else "PRIVATE_TRANSIENT",
            generated_at=now,
            expires_at=expires,
        )
        self._diagnostics.worker_terminal_received = True
        if self._on_publication is not None:
            self._diagnostics.enter("PUBLICATION")
            try:
                self._on_publication(self._view)
            except Exception as error:
                self._diagnostics.failed(error)
                raise
        self._result = value
        self._current_result = envelope
        self._publication_floor = now
        self._completed = self._elapsed()
        self._state = self._state.model_copy(
            update={"status": "COMPLETE", "diagnostics": self.diagnostics()}
        )
        if self._current is not None:
            self._current.completed()

    def _accept_diagnostic(self, value: str) -> None:
        if len(value) > MAX_EVENT_BYTES or self._active_launch is None:
            raise AuthorizationError("DIAGNOSTIC_PROTOCOL_INVALID")
        try:
            event = DiagnosticEvent.model_validate_json(value)
            if not self._diagnostic_started_at <= event.at <= datetime.now(UTC):
                raise ValueError("diagnostic time is outside the observed worker lifetime")
            if event.request is not None:
                expected = {
                    (
                        scope.provider,
                        canonical_sha256([scope.provider, route.method, route.host, route.path]),
                    ): route.maximum_calls
                    for scope in self._active_launch.grant.request.source_scopes
                    for route in scope.routes
                }
                identity = event.request.provider, event.request.route_sha256
                if identity not in expected:
                    raise ValueError("diagnostic route differs from enrolled scope")
                if (
                    event.kind == "ADMITTED"
                    and sum(
                        row.identity.provider == event.request.provider
                        and row.identity.route_sha256 == event.request.route_sha256
                        for row in self._diagnostics.requests.values()
                    )
                    >= expected[identity]
                ):
                    raise ValueError("diagnostic admission exceeds enrolled route budget")
            self._diagnostics.accept(event)
        except (ValueError, TypeError):
            raise AuthorizationError("DIAGNOSTIC_PROTOCOL_INVALID") from None
        self._state = self._state.model_copy(update={"diagnostics": self._diagnostics.report()})

    def diagnostics(self) -> DiagnosticReport | None:
        """Read only; metadata cannot initiate or authorize a provider request."""
        with self._lock:
            return self._diagnostics.report() if self._diagnostics.events else None

    @property
    def synthetic_sources(self) -> bool:
        return self.demo or (self._current is not None and self._current.owned_sources)

    def eligibility(self) -> CurrentEligibility | None:
        with self._lock:
            self.tick()
            return None if self._current is None else self._current.eligibility()

    def view(self) -> DeskView | None:
        with self._lock:
            self.tick()
            if self._view is None:
                return None
            return self._view.model_copy(
                update={
                    "expires_in_seconds": max(
                        0.0,
                        min(
                            (self._view.expires_at - self._now()).total_seconds(),
                            self._lifetime - (self._elapsed() - self._completed),
                        ),
                    )
                }
            )

    def player(self, official_id: int) -> PlayerDetail:
        with self._lock:
            self.tick()
            if self._result is None:
                raise ValueError("no current recommendation")
            return player_detail(self._result, str(self._state.job_id), official_id)

    def cancel(self) -> JobState:
        with self._lock:
            self._discard("CANCELLED", "OPERATOR_CANCELLED")
            return self._state

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._discard("CANCELLED", "SESSION_ENDED")
