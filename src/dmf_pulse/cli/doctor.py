"""Offline, privacy-minimizing system diagnostics."""

from __future__ import annotations

import platform
import re
import shutil
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from dmf_pulse import __version__
from dmf_pulse.config import ConfigError, EnvironmentName, load_config
from dmf_pulse.config.loader import default_config
from dmf_pulse.system import (
    Clock,
    ProcessRunner,
    SubprocessProcessRunner,
    SystemClock,
    probe_artifact_writability,
)

VERSION_PATTERNS = {
    "git": re.compile(r"^git version ([0-9A-Za-z.+_-]+)"),
    "uv": re.compile(r"^uv ([0-9A-Za-z.+_-]+)"),
}
ExecutableFinder = Callable[[str], str | None]


class StrictReportModel(BaseModel):
    """Base model for stable machine-readable doctor contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PythonDiagnostic(StrictReportModel):
    version: str
    required_minor: str
    compatible: bool


class SystemDiagnostic(StrictReportModel):
    operating_system: str
    platform: str
    architecture: str
    python_implementation: str


class ConfigDiagnostic(StrictReportModel):
    status: Literal["HEALTHY", "BLOCKING"]
    environment: str
    source: Literal["repository", "built_in"]
    error_code: str | None = None


class ArtifactDiagnostic(StrictReportModel):
    status: Literal["HEALTHY", "BLOCKING", "NOT_CHECKED"]
    writable: bool | None
    cleaned_up: bool
    basis: str
    error_code: str | None = None


class ToolDiagnostic(StrictReportModel):
    status: Literal["AVAILABLE", "UNAVAILABLE", "ERROR", "TIMEOUT"]
    available: bool
    version: str | None = None


class NvidiaDiagnostic(StrictReportModel):
    status: Literal["AVAILABLE", "UNAVAILABLE", "ERROR", "TIMEOUT"]
    blocking: Literal[False] = False
    device_count: int | None = None


class DoctorReport(StrictReportModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["HEALTHY", "BLOCKING"]
    package_version: str
    python: PythonDiagnostic
    system: SystemDiagnostic
    utc_time: datetime
    config: ConfigDiagnostic
    artifact_root: ArtifactDiagnostic
    tools: dict[str, ToolDiagnostic]
    nvidia: NvidiaDiagnostic


def _safe_version_line(name: str, output: str) -> str | None:
    first_line = output.splitlines()[0].strip() if output.splitlines() else ""
    if not first_line:
        return None
    pattern = VERSION_PATTERNS.get(name)
    match = pattern.match(first_line) if pattern is not None else None
    if match is None:
        return None
    return f"{name} {match.group(1)}" if name == "uv" else f"git version {match.group(1)}"


def _probe_tool(
    name: str,
    *,
    runner: ProcessRunner,
    finder: ExecutableFinder,
) -> ToolDiagnostic:
    executable = finder(name)
    if executable is None:
        return ToolDiagnostic(status="UNAVAILABLE", available=False)
    result = runner.run([executable, "--version"], timeout_seconds=2.0)
    if result.timed_out:
        return ToolDiagnostic(status="TIMEOUT", available=True)
    if result.return_code != 0:
        return ToolDiagnostic(status="ERROR", available=True)
    return ToolDiagnostic(
        status="AVAILABLE",
        available=True,
        version=_safe_version_line(name, result.stdout),
    )


def _probe_nvidia(*, runner: ProcessRunner, finder: ExecutableFinder) -> NvidiaDiagnostic:
    executable = finder("nvidia-smi")
    if executable is None:
        return NvidiaDiagnostic(status="UNAVAILABLE")
    result = runner.run(
        [executable, "--query-gpu=name", "--format=csv,noheader"],
        timeout_seconds=2.0,
    )
    if result.timed_out:
        return NvidiaDiagnostic(status="TIMEOUT")
    if result.return_code != 0:
        return NvidiaDiagnostic(status="ERROR")
    device_count = len([line for line in result.stdout.splitlines() if line.strip()])
    return NvidiaDiagnostic(status="AVAILABLE", device_count=device_count)


def _validated_utc(clock: Clock) -> datetime:
    value = clock.now_utc()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock returned a naive datetime")
    return value.astimezone(UTC)


def build_doctor_report(
    *,
    clock: Clock | None = None,
    process_runner: ProcessRunner | None = None,
    executable_finder: ExecutableFinder = shutil.which,
    working_directory: Path | None = None,
) -> DoctorReport:
    """Build an offline diagnostic report through injectable runtime boundaries."""

    selected_clock = clock or SystemClock()
    selected_runner = process_runner or SubprocessProcessRunner()
    cwd = working_directory or Path.cwd()
    config_root = cwd / "config"
    config_source: Literal["repository", "built_in"]
    try:
        if config_root.exists():
            config = load_config(
                environment=EnvironmentName.DEVELOPMENT,
                config_root=config_root,
            )
            config_source = "repository"
        else:
            config = default_config()
            config_source = "built_in"
        config_diagnostic = ConfigDiagnostic(
            status="HEALTHY",
            environment=config.environment.value,
            source=config_source,
        )
    except ConfigError as exc:
        config = None
        config_diagnostic = ConfigDiagnostic(
            status="BLOCKING",
            environment=EnvironmentName.DEVELOPMENT.value,
            source="repository",
            error_code=exc.code,
        )

    if config is None:
        artifact_diagnostic = ArtifactDiagnostic(
            status="NOT_CHECKED",
            writable=None,
            cleaned_up=True,
            basis="configuration_invalid",
        )
    else:
        probe = probe_artifact_writability(config.artifact_root, working_directory=cwd)
        artifact_diagnostic = ArtifactDiagnostic(
            status="HEALTHY" if probe.writable and probe.cleaned_up else "BLOCKING",
            writable=probe.writable,
            cleaned_up=probe.cleaned_up,
            basis=probe.basis,
            error_code=probe.error_code,
        )

    python_compatible = sys.version_info[:2] == (3, 13)
    overall_healthy = (
        python_compatible
        and config_diagnostic.status == "HEALTHY"
        and artifact_diagnostic.status == "HEALTHY"
    )
    return DoctorReport(
        status="HEALTHY" if overall_healthy else "BLOCKING",
        package_version=__version__,
        python=PythonDiagnostic(
            version=platform.python_version(),
            required_minor="3.13",
            compatible=python_compatible,
        ),
        system=SystemDiagnostic(
            operating_system=platform.system() or "Unknown",
            platform=sys.platform,
            architecture=platform.machine() or "unknown",
            python_implementation=platform.python_implementation(),
        ),
        utc_time=_validated_utc(selected_clock),
        config=config_diagnostic,
        artifact_root=artifact_diagnostic,
        tools={
            "git": _probe_tool("git", runner=selected_runner, finder=executable_finder),
            "uv": _probe_tool("uv", runner=selected_runner, finder=executable_finder),
        },
        nvidia=_probe_nvidia(runner=selected_runner, finder=executable_finder),
    )
