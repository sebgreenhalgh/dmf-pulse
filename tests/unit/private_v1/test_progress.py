"""Human progress is truthful, transient, ordered, and disclosure-safe."""

from __future__ import annotations

import time

from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.progress import HumanCliProgress, NullProgress


def test_monotonic_progress_has_nonnegative_durations_and_no_fake_percentage() -> None:
    output: list[str] = []
    progress = HumanCliProgress(write=output.append)

    progress.message("DMF Pulse starting")
    with progress.stage(
        started="Acquiring current FPL state...",
        completed="FPL state ready",
        failed="current FPL state",
    ):
        pass
    progress.finish()

    assert [line.split("] ", 1)[1].split(" (", 1)[0] for line in output] == [
        "DMF Pulse starting",
        "Acquiring current FPL state...",
        "FPL state ready",
        "Total runtime: 0.0s",
    ]
    durations = [
        float(line.rsplit("(", 1)[1].removesuffix("s)")) for line in output if line.endswith("s)")
    ]
    assert durations and all(value >= 0 for value in durations)
    assert not any("%" in line for line in output)


def test_long_stage_emits_heartbeat_and_one_non_cancelling_warning() -> None:
    output: list[str] = []
    progress = HumanCliProgress(
        write=output.append,
        heartbeat_interval_seconds=0.01,
        long_stage_warning_seconds=0.02,
    )

    with progress.stage(
        started="Exact optimisation starting",
        completed="Exact optimisation complete",
        failed="exact optimisation",
        heartbeat="Exact optimisation still running",
        long_warning=(
            "WARNING: exact optimisation has exceeded the expected private-V1 runtime; "
            "computation is still active."
        ),
    ):
        time.sleep(0.045)

    assert sum("Exact optimisation still running" in line for line in output) >= 2
    assert sum("WARNING: exact optimisation" in line for line in output) == 1
    assert output[-1].split("] ", 1)[1].startswith("Exact optimisation complete (")
    assert not any("%" in line for line in output)


def test_stage_failure_emits_only_typed_public_code() -> None:
    output: list[str] = []
    marker = "raw-provider-body-and-private-id"
    progress = HumanCliProgress(write=output.append)

    try:
        with progress.stage(
            started="Building Stage-7 minutes...",
            completed="Stage-7 minutes ready",
            failed="Stage-7 minutes",
        ):
            raise PrivateV1Error("SAFE_TYPED_CODE", marker)
    except PrivateV1Error:
        pass

    assert any("FAILED: Stage-7 minutes" in line for line in output)
    assert any(line.endswith("SAFE_TYPED_CODE") for line in output)
    assert marker not in "\n".join(output)


def test_null_progress_is_fully_silent() -> None:
    progress = NullProgress()

    progress.message("secret")
    with progress.stage(started="start", completed="done", failed="stage"):
        pass
    progress.finish()


def test_keyboard_interrupt_stops_heartbeat_without_false_failure() -> None:
    output: list[str] = []
    progress = HumanCliProgress(write=output.append, heartbeat_interval_seconds=0.01)

    try:
        with progress.stage(
            started="Exact optimisation starting",
            completed="Exact optimisation complete",
            failed="exact optimisation",
            heartbeat="Exact optimisation still running",
        ):
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        pass
    count_after_interrupt = len(output)
    time.sleep(0.025)

    assert len(output) == count_after_interrupt
    assert not any("FAILED" in line for line in output)
