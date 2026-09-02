"""Run-local, disclosure-safe progress for the interactive private command."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from threading import Event, Lock, Thread
from time import monotonic
from typing import Protocol


class ProgressSink(Protocol):
    """Small observer boundary; numerical services remain silent unless explicitly observed."""

    failure_reported: bool

    def message(self, value: str) -> None: ...

    def stage(
        self,
        *,
        started: str | None,
        completed: str | None,
        failed: str,
        heartbeat: str | None = None,
        long_warning: str | None = None,
    ) -> AbstractContextManager[None]: ...

    def finish(self) -> None: ...

    def failure(self, stage: str, code: str) -> None: ...


class NullProgress:
    """No-op observer used by services and `--no-progress`."""

    failure_reported = False

    def message(self, value: str) -> None:
        del value

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
        del started, completed, failed, heartbeat, long_warning
        yield

    def finish(self) -> None:
        return

    def failure(self, stage: str, code: str) -> None:
        del stage, code


def _public_error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code else "INTERNAL_ERROR"


class HumanCliProgress:
    """Monotonic STDERR-oriented renderer with truthful periodic heartbeats."""

    def __init__(
        self,
        *,
        write: Callable[[str], None],
        clock: Callable[[], float] = monotonic,
        heartbeat_interval_seconds: float = 30.0,
        long_stage_warning_seconds: float = 300.0,
    ) -> None:
        if heartbeat_interval_seconds <= 0 or long_stage_warning_seconds <= 0:
            raise ValueError("progress timing intervals must be positive")
        self._write = write
        self._clock = clock
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._long_stage_warning_seconds = long_stage_warning_seconds
        self._started_at = clock()
        self._lock = Lock()
        self._finished = False
        self.failure_reported = False

    def _elapsed(self, since: float | None = None) -> float:
        start = self._started_at if since is None else since
        return max(0.0, self._clock() - start)

    @staticmethod
    def _clock_text(seconds: float) -> str:
        total = max(0, int(seconds))
        minutes, remainder = divmod(total, 60)
        return f"{minutes:02d}:{remainder:02d}"

    @staticmethod
    def _heartbeat_elapsed(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s elapsed"
        minutes, remainder = divmod(int(seconds), 60)
        return f"{minutes}m{remainder:02d}s elapsed"

    def message(self, value: str) -> None:
        with self._lock:
            self._write(f"[{self._clock_text(self._elapsed())}] {value}")

    def failure(self, stage: str, code: str) -> None:
        self.failure_reported = True
        self.message(f"FAILED: {stage}")
        self.message(code)

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
        if started is not None:
            self.message(started)
        stage_started = self._clock()
        stopped = Event()
        heartbeat_thread: Thread | None = None
        if heartbeat is not None:

            def emit_heartbeats() -> None:
                warning_emitted = False
                while not stopped.wait(self._heartbeat_interval_seconds):
                    elapsed = self._elapsed(stage_started)
                    self.message(f"{heartbeat} ({self._heartbeat_elapsed(elapsed)})")
                    if (
                        long_warning is not None
                        and not warning_emitted
                        and elapsed >= self._long_stage_warning_seconds
                    ):
                        self.message(long_warning)
                        warning_emitted = True

            heartbeat_thread = Thread(target=emit_heartbeats, daemon=True)
            heartbeat_thread.start()
        try:
            yield
        except BaseException as exc:
            stopped.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join()
            if isinstance(exc, Exception) and not self.failure_reported:
                self.failure(failed, _public_error_code(exc))
            raise
        else:
            stopped.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join()
            if completed is not None:
                self.message(f"{completed} ({self._elapsed(stage_started):.1f}s)")

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.message(f"Total runtime: {self._elapsed():.1f}s")


__all__ = ["HumanCliProgress", "NullProgress", "ProgressSink"]
