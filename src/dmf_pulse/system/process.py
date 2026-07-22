"""Bounded subprocess execution used only by explicit diagnostics."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

MAX_CAPTURE_CHARS = 2048


def _bounded_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    return text[:MAX_CAPTURE_CHARS]


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Sanitized bounded result from a process attempt."""

    return_code: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error_code: str | None = None


class ProcessRunner(Protocol):
    """Execute an argument vector with a mandatory timeout."""

    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        """Run ``command`` without a shell."""


class SubprocessProcessRunner:
    """Standard-library process runner with capture limits and safe error codes."""

    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        """Run ``command`` only when explicitly invoked at runtime."""

        try:
            completed = subprocess.run(
                list(command),
                check=False,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return ProcessResult(
                return_code=None,
                stdout=_bounded_text(exc.stdout),
                stderr=_bounded_text(exc.stderr),
                timed_out=True,
                error_code="TIMEOUT",
            )
        except FileNotFoundError:
            return ProcessResult(return_code=None, error_code="NOT_FOUND")
        except OSError:
            return ProcessResult(return_code=None, error_code="OS_ERROR")
        return ProcessResult(
            return_code=completed.returncode,
            stdout=_bounded_text(completed.stdout),
            stderr=_bounded_text(completed.stderr),
        )
