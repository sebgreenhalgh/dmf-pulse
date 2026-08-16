"""Stable public OPT-010 CLI integrity-exit contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from dmf_pulse.cli.optimise import optimise_app
from dmf_pulse.fpl_points.artifacts import canonical_json_bytes
from tests.support.optimisation_factories import projection, request, synthetic_ruleset

runner = CliRunner()


def _stage9_artifact(path: Path) -> Path:
    stage9 = projection(synthetic_ruleset().ruleset_hash)
    path.write_bytes(canonical_json_bytes(stage9))
    path.with_suffix(".sha256").write_bytes(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n".encode("ascii")
    )
    return path


def test_one_gameweek_invalid_ruleset_has_stable_integrity_exit(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical_json_bytes(request()))
    stage9_path = _stage9_artifact(tmp_path / "stage9.json")
    rules_path = tmp_path / "invalid-ruleset.json"
    rules_path.write_bytes(b"{}\n")
    result = runner.invoke(
        optimise_app,
        [
            "one-gameweek",
            "--request",
            str(request_path),
            "--gameweek-artifact",
            str(stage9_path),
            "--ruleset",
            str(rules_path),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ],
    )
    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)
    assert json.loads(result.stdout) == {
        "error_code": "RULESET_ARTIFACT_INVALID",
        "error_message": "compiled ruleset is unavailable or invalid",
        "status": "BLOCKED",
    }


def test_validate_plan_missing_artifact_has_stable_integrity_exit(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical_json_bytes(request()))
    stage9_path = _stage9_artifact(tmp_path / "stage9.json")
    result = runner.invoke(
        optimise_app,
        [
            "validate-plan",
            "--request",
            str(request_path),
            "--gameweek-artifact",
            str(stage9_path),
            "--ruleset",
            "artifacts/rules/fpl-2026-27-0.1.0-prelaunch.1.schema-v1.1.json",
            "--artifact",
            str(tmp_path / "missing-result.json"),
        ],
    )
    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)
    assert json.loads(result.stdout) == {
        "error_code": "OPTIMISATION_ARTIFACT_INVALID",
        "error_message": "artifact or detached hash is unavailable",
        "legal": False,
    }
