"""Offline system boundary and doctor health tests."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.cli.doctor import build_doctor_report
from dmf_pulse.system.hardware import probe_artifact_writability
from dmf_pulse.system.process import ProcessResult, SubprocessProcessRunner


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now_utc(self) -> datetime:
        return self.value


class FakeRunner:
    def __init__(self, results: dict[str, ProcessResult]) -> None:
        self.results = results
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: Sequence[str], *, timeout_seconds: float) -> ProcessResult:
        assert 0 < timeout_seconds <= 5
        self.commands.append(tuple(command))
        return self.results.get(Path(command[0]).name, ProcessResult(return_code=1))


def _finder(available: set[str]):
    def find(name: str) -> str | None:
        return str(Path("tools") / name) if name in available else None

    return find


@pytest.mark.unit
def test_gpu_absence_and_missing_tools_are_healthy(tmp_path: Path) -> None:
    report = build_doctor_report(
        clock=FixedClock(datetime(2026, 7, 22, 10, 30, tzinfo=UTC)),
        process_runner=FakeRunner({}),
        executable_finder=_finder(set()),
        working_directory=tmp_path,
    )
    assert report.status == "HEALTHY"
    assert report.utc_time.isoformat() == "2026-07-22T10:30:00+00:00"
    assert report.nvidia.status == "UNAVAILABLE"
    assert report.nvidia.blocking is False
    assert report.tools["git"].status == "UNAVAILABLE"
    assert report.system.platform == sys.platform
    assert report.artifact_root.cleaned_up is True
    assert not list(tmp_path.glob(".dmf-pulse-probe-*"))


@pytest.mark.unit
def test_tool_versions_are_allowlisted_and_nvidia_timeout_is_nonblocking(tmp_path: Path) -> None:
    runner = FakeRunner(
        {
            "git": ProcessResult(return_code=0, stdout="git version 2.50.1 /Users/private-name"),
            "uv": ProcessResult(return_code=0, stdout="uv 0.11.2 /Users/private-name"),
            "nvidia-smi": ProcessResult(return_code=None, timed_out=True),
        }
    )
    report = build_doctor_report(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        process_runner=runner,
        executable_finder=_finder({"git", "uv", "nvidia-smi"}),
        working_directory=tmp_path,
    )
    rendered = report.model_dump_json()
    assert report.status == "HEALTHY"
    assert report.tools["git"].version == "git version 2.50.1"
    assert report.tools["uv"].version == "uv 0.11.2"
    assert report.nvidia.status == "TIMEOUT"
    assert "private-name" not in rendered
    assert all(len(command) >= 2 for command in runner.commands)


@pytest.mark.unit
def test_nvidia_count_ignores_device_names(tmp_path: Path) -> None:
    sensitive_device_text = "GPU name that must not be retained\nsecond device\n"
    runner = FakeRunner({"nvidia-smi": ProcessResult(return_code=0, stdout=sensitive_device_text)})
    report = build_doctor_report(
        process_runner=runner,
        executable_finder=_finder({"nvidia-smi"}),
        working_directory=tmp_path,
    )
    assert report.nvidia.device_count == 2
    assert sensitive_device_text.strip() not in report.model_dump_json()


@pytest.mark.unit
def test_invalid_repository_config_blocks_without_echoing_input(tmp_path: Path) -> None:
    base = tmp_path / "config" / "base"
    base.mkdir(parents=True)
    raw = "postgresql://service:" + "private-value" + "@host/db"
    (base / "application.yaml").write_text(
        "environment: development\nartifact_root: artifacts\ndatabase_dsn_ref: " + raw,
        encoding="utf-8",
    )
    report = build_doctor_report(
        process_runner=FakeRunner({}),
        executable_finder=_finder(set()),
        working_directory=tmp_path,
    )
    assert report.status == "BLOCKING"
    assert report.config.error_code == "CONFIG_VALIDATION_FAILED"
    assert raw not in report.model_dump_json()


@pytest.mark.unit
def test_existing_config_root_without_required_base_is_blocking(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    report = build_doctor_report(
        process_runner=FakeRunner({}),
        executable_finder=_finder(set()),
        working_directory=tmp_path,
    )
    assert report.status == "BLOCKING"
    assert report.config.error_code == "CONFIG_FILE_MISSING"
    assert report.artifact_root.status == "NOT_CHECKED"


@pytest.mark.unit
def test_naive_clock_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="naive"):
        build_doctor_report(
            clock=FixedClock(datetime(2026, 1, 1)),
            process_runner=FakeRunner({}),
            executable_finder=_finder(set()),
            working_directory=tmp_path,
        )


@pytest.mark.unit
def test_writability_probe_uses_parent_and_cleans_up(tmp_path: Path) -> None:
    target = Path("missing") / "artifact-root"
    result = probe_artifact_writability(target, working_directory=tmp_path)
    assert result.writable is True
    assert result.cleaned_up is True
    assert result.basis == "nearest_existing_parent"
    assert not (tmp_path / "missing").exists()
    assert not list(tmp_path.glob(".dmf-pulse-probe-*"))


@pytest.mark.unit
def test_subprocess_runner_bounds_output_and_times_out(tmp_path: Path) -> None:
    runner = SubprocessProcessRunner()
    output = runner.run(
        [sys.executable, "-c", "print('x' * 3000)"],
        timeout_seconds=5,
    )
    assert output.return_code == 0
    assert len(output.stdout) == 2048

    timeout = runner.run(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        timeout_seconds=0.01,
    )
    assert timeout.timed_out is True
    assert timeout.error_code == "TIMEOUT"


@pytest.mark.unit
def test_tool_and_nvidia_errors_are_nonblocking(tmp_path: Path) -> None:
    runner = FakeRunner(
        {
            "git": ProcessResult(return_code=None, timed_out=True),
            "uv": ProcessResult(return_code=1),
            "nvidia-smi": ProcessResult(return_code=1),
        }
    )
    report = build_doctor_report(
        process_runner=runner,
        executable_finder=_finder({"git", "uv", "nvidia-smi"}),
        working_directory=tmp_path,
    )
    assert report.status == "HEALTHY"
    assert report.tools["git"].status == "TIMEOUT"
    assert report.tools["uv"].status == "ERROR"
    assert report.nvidia.status == "ERROR"


@pytest.mark.unit
def test_unrecognized_tool_output_is_not_exposed(tmp_path: Path) -> None:
    runner = FakeRunner({"git": ProcessResult(return_code=0, stdout="private-name")})
    report = build_doctor_report(
        process_runner=runner,
        executable_finder=_finder({"git"}),
        working_directory=tmp_path,
    )
    assert report.tools["git"].version is None
    assert "private-name" not in report.model_dump_json()


@pytest.mark.unit
def test_probe_existing_directory_file_and_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = tmp_path / "artifacts"
    existing.mkdir()
    assert probe_artifact_writability(existing, working_directory=tmp_path).basis == "artifact_root"

    not_directory = tmp_path / "artifact-file"
    not_directory.write_text("x", encoding="utf-8")
    file_result = probe_artifact_writability(not_directory, working_directory=tmp_path)
    assert file_result.writable is False
    assert file_result.basis == "artifact_root_not_directory"

    def fail_mkstemp(*_args: object, **_kwargs: object) -> tuple[int, str]:
        raise OSError("simulated")

    monkeypatch.setattr(tempfile, "mkstemp", fail_mkstemp)
    failure = probe_artifact_writability(existing, working_directory=tmp_path)
    assert failure.error_code == "WRITE_PROBE_FAILED"
    assert failure.cleaned_up is True


@pytest.mark.unit
def test_process_runner_missing_and_os_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    runner = SubprocessProcessRunner()
    missing = runner.run(["definitely-not-a-real-dmf-command"], timeout_seconds=1)
    assert missing.error_code == "NOT_FOUND"

    def permission_error(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("simulated")

    monkeypatch.setattr(subprocess, "run", permission_error)
    denied = runner.run(["blocked"], timeout_seconds=1)
    assert denied.error_code == "OS_ERROR"
