"""CLI failure boundaries never echo credentials or raw payload bodies."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app

pytestmark = pytest.mark.security

FAKE_DATABASE_URL = (
    "postgresql://" + "dmf_test:" + "SUPER" + "_SECRET_DO_NOT_LOG" + "@localhost/dmf"
)
RAW_MARKER = "RAW_BODY_" + "MUST_NOT_SURVIVE_FPL004"

runner = CliRunner()


def _json_output(result_output: str) -> dict[str, object]:
    value = json.loads(result_output)
    assert isinstance(value, dict)
    return value


def test_import_rejects_literal_database_url_without_echoing_it(repository_root: Path) -> None:
    fixture_root = repository_root / "fixtures/fpl/FPL-004/happy_path"
    result = runner.invoke(
        app,
        [
            "ingest",
            "fpl",
            "import",
            "--bootstrap",
            str(fixture_root / "bootstrap.json"),
            "--fixtures",
            str(fixture_root / "fixtures.json"),
            "--competition-key",
            "SYNTHETIC_PL",
            "--season-code",
            "2026/27",
            "--captured-at",
            "2026-08-21T17:00:00Z",
            "--information-cutoff",
            "2026-08-21T17:30:00Z",
            "--rights-profile",
            "synthetic_test_v1",
            "--database-url-ref",
            FAKE_DATABASE_URL,
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 3
    output = _json_output(result.stdout)
    assert output["status"] == "FAILED"
    assert output["error"]["code"] == "DATABASE_REFERENCE_INVALID"  # type: ignore[index]
    assert FAKE_DATABASE_URL not in result.output
    assert "SUPER_" + "SECRET_DO_NOT_LOG" not in result.output


def test_malformed_payload_failure_does_not_echo_raw_body(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text(f'{{"marker":"{RAW_MARKER}"', encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "ingest",
            "fpl",
            "validate",
            "--resource",
            "bootstrap",
            "--input",
            str(malformed),
            "--contract-version",
            "fpl-reference-v1",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 2
    output = _json_output(result.stdout)
    assert output["status"] == "FAILED"
    assert output["error"]["code"] == "MALFORMED_JSON"  # type: ignore[index]
    assert RAW_MARKER not in result.output


def test_snapshot_rejects_literal_database_url_without_echoing_it() -> None:
    result = runner.invoke(
        app,
        [
            "ingest",
            "fpl",
            "snapshot",
            "--resource",
            "all",
            "--competition-key",
            "PL",
            "--season-code",
            "2026/27",
            "--rights-profile",
            "fpl_official_private_manual_v1",
            "--database-url-ref",
            FAKE_DATABASE_URL,
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 3
    output = _json_output(result.stdout)
    assert output["status"] == "FAILED"
    error = output["error"]
    assert isinstance(error, dict)
    assert error["code"] == "DATABASE_REFERENCE_INVALID"
    assert FAKE_DATABASE_URL not in result.output
