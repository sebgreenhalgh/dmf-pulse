"""Typer rendering, exit-code, and golden-shape tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.assurance.review_pack import ReviewPackError, ReviewPackSummary
from dmf_pulse.cli.app import app
from dmf_pulse.cli.doctor import (
    ArtifactDiagnostic,
    ConfigDiagnostic,
    DoctorReport,
    NvidiaDiagnostic,
    PythonDiagnostic,
    SystemDiagnostic,
    ToolDiagnostic,
)

runner = CliRunner()


@pytest.mark.unit
def test_version_contract() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout == "dmf 0.1.0\n"


@pytest.mark.unit
def test_config_validate_and_show_json(repository_root: Path) -> None:
    config_root = str(repository_root / "config")
    valid = runner.invoke(
        app,
        ["config", "validate", "--environment", "TEST", "--config-root", config_root],
    )
    assert valid.exit_code == 0
    assert valid.stdout == "Configuration valid (environment=test).\n"

    shown = runner.invoke(
        app,
        ["config", "show", "--environment", "test", "--config-root", config_root, "--json"],
    )
    assert shown.exit_code == 0
    value = json.loads(shown.stdout)
    assert value["environment"] == "test"
    assert value["artifact_root"] == str(Path("artifacts/test"))
    assert value["database_dsn_ref"] is None
    assert list(value) == sorted(value)


@pytest.mark.unit
def test_config_error_is_machine_readable_with_stable_exit(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["config", "validate", "--environment", "unknown", "--config-root", str(tmp_path)],
    )
    assert result.exit_code == 10
    expected = (Path(__file__).parents[2] / "golden/config_error.json").read_text(encoding="utf-8")
    assert result.stderr == expected


@pytest.mark.unit
def test_evidence_missing_has_stable_machine_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["evidence", "validate", str(tmp_path / "missing.json")])
    assert result.exit_code == 20
    expected = (Path(__file__).parents[2] / "golden/evidence_error.json").read_text(
        encoding="utf-8"
    )
    assert result.stderr == expected


@pytest.mark.unit
def test_config_show_rejects_token_reference_without_disclosure(tmp_path: Path) -> None:
    raw_value = "eyJ" + "A" * 20 + "." + "B" * 12 + "." + "C" * 12
    base = tmp_path / "base"
    base.mkdir()
    (base / "application.yaml").write_text(
        "artifact_root: artifacts\ndatabase_dsn_ref: " + raw_value + "\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["config", "show", "--environment", "test", "--config-root", str(tmp_path), "--json"],
    )
    assert result.exit_code == 10
    assert raw_value not in result.stdout
    assert raw_value not in result.stderr
    assert json.loads(result.stderr)["error"]["code"] == "CONFIG_VALIDATION_FAILED"


@pytest.mark.unit
def test_evidence_success_and_config_human_output(tmp_path: Path, repository_root: Path) -> None:
    evidence = {
        "ticket_id": "FND-001",
        "status": "DRAFT",
        "created_at": "2026-07-22T00:00:00Z",
        "commands": [],
        "artifacts": [],
    }
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    validated = runner.invoke(app, ["evidence", "validate", str(path)])
    assert validated.exit_code == 0
    assert json.loads(validated.stdout) == {"kind": "ticket_evidence_manifest", "ok": True}

    shown = runner.invoke(
        app,
        [
            "config",
            "show",
            "--environment",
            "test",
            "--config-root",
            str(repository_root / "config"),
        ],
    )
    assert shown.exit_code == 0
    assert "environment: test" in shown.stdout


@pytest.mark.unit
def test_review_pack_command_success_and_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "review.zip"
    summary = ReviewPackSummary(
        path=output, file_count=20, sha256="a" * 64, payload_sha256="b" * 64
    )
    monkeypatch.setattr(
        "dmf_pulse.cli.review_pack_cmd.build_review_pack", lambda *args, **kwargs: summary
    )
    success = runner.invoke(
        app,
        ["review-pack", "build", "--ticket", "FND-001", "--output", str(output)],
    )
    assert success.exit_code == 0
    assert json.loads(success.stdout)["file_count"] == 20
    assert json.loads(success.stdout)["payload_sha256"] == "b" * 64

    def fail(*_args: object, **_kwargs: object) -> ReviewPackSummary:
        raise ReviewPackError("REVIEW_TEST_FAILURE", "simulated safe failure")

    monkeypatch.setattr("dmf_pulse.cli.review_pack_cmd.build_review_pack", fail)
    failure = runner.invoke(
        app,
        ["review-pack", "build", "--ticket", "FND-001", "--output", str(output)],
    )
    assert failure.exit_code == 30
    assert json.loads(failure.stderr)["error"]["code"] == "REVIEW_TEST_FAILURE"


@pytest.mark.golden
def test_doctor_json_matches_golden_contract(
    monkeypatch: pytest.MonkeyPatch, repository_root: Path
) -> None:
    from datetime import UTC, datetime

    report = DoctorReport(
        status="HEALTHY",
        package_version="0.1.0",
        python=PythonDiagnostic(version="3.13.9", required_minor="3.13", compatible=True),
        system=SystemDiagnostic(
            operating_system="TestOS",
            platform="test-platform",
            architecture="x86_64",
            python_implementation="CPython",
        ),
        utc_time=datetime(2026, 7, 22, 10, 30, tzinfo=UTC),
        config=ConfigDiagnostic(status="HEALTHY", environment="test", source="built_in"),
        artifact_root=ArtifactDiagnostic(
            status="HEALTHY",
            writable=True,
            cleaned_up=True,
            basis="nearest_existing_parent",
        ),
        tools={
            "git": ToolDiagnostic(status="AVAILABLE", available=True, version="git version 2.50.1"),
            "uv": ToolDiagnostic(status="UNAVAILABLE", available=False),
        },
        nvidia=NvidiaDiagnostic(status="UNAVAILABLE"),
    )
    monkeypatch.setattr("dmf_pulse.cli.app.build_doctor_report", lambda: report)
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    expected = (repository_root / "tests/golden/doctor.json").read_text(encoding="utf-8")
    assert result.stdout == expected


@pytest.mark.unit
def test_doctor_human_and_json_blocking_golden(
    monkeypatch: pytest.MonkeyPatch, repository_root: Path
) -> None:
    from datetime import UTC, datetime

    report = DoctorReport(
        status="BLOCKING",
        package_version="0.1.0",
        python=PythonDiagnostic(version="3.12.0", required_minor="3.13", compatible=False),
        system=SystemDiagnostic(
            operating_system="TestOS",
            platform="test-platform",
            architecture="x",
            python_implementation="CPython",
        ),
        utc_time=datetime(2026, 1, 1, tzinfo=UTC),
        config=ConfigDiagnostic(
            status="BLOCKING",
            environment="development",
            source="repository",
            error_code="CONFIG_VALIDATION_FAILED",
        ),
        artifact_root=ArtifactDiagnostic(
            status="NOT_CHECKED",
            writable=None,
            cleaned_up=True,
            basis="configuration_invalid",
        ),
        tools={},
        nvidia=NvidiaDiagnostic(status="UNAVAILABLE"),
    )
    monkeypatch.setattr("dmf_pulse.cli.app.build_doctor_report", lambda: report)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 40
    assert "BLOCKING" in result.stdout
    json_result = runner.invoke(app, ["doctor", "--json"])
    assert json_result.exit_code == 40
    expected = (repository_root / "tests/golden/doctor_blocking.json").read_text(encoding="utf-8")
    assert json_result.stdout == expected
