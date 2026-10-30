"""Installed command entry API: metadata only, with no payload or path echo."""

import json

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli import recovery
from dmf_pulse.player_lab.recovery import RecoveryError

pytestmark = pytest.mark.contract


def test_inventory_then_unknown_artifact_verification_stays_offline(tmp_path):
    runner = CliRunner()
    result = runner.invoke(recovery.recovery_app, ["inventory"])
    assert result.exit_code == 0, result.output
    catalogue = json.loads(result.output)
    assert catalogue["families"][0]["sample_count"] == 10
    assert catalogue["families"][0]["forecast_rows"] == 30
    assert not catalogue["scoring_performed"]
    artifact = tmp_path / "owned.json"
    artifact.write_text('{"execution_status":"REAL_PRIVATE_TRANSIENT_RECOMMENDATION"}')
    result = runner.invoke(recovery.recovery_app, ["verify", "--artifact", str(artifact)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["classification"] == "UNVERIFIED_CUSTODY"
    assert not json.loads(result.output)["scoring_authorized"]
    assert str(artifact) not in result.output
    assert "REAL_PRIVATE_TRANSIENT" not in result.output
    assert sorted(path.name for path in tmp_path.iterdir() if path.is_file()) == ["owned.json"]


def test_safe_missing_input_and_catalogue_failure_errors(tmp_path, monkeypatch):
    runner = CliRunner()
    result = runner.invoke(
        recovery.recovery_app, ["verify", "--artifact", str(tmp_path / "absent")]
    )
    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["code"] == "RECOVERY_ARTIFACT_UNSAFE_OR_UNREADABLE"
    assert str(tmp_path) not in result.output

    def failed():
        raise RecoveryError("RECOVERY_CATALOGUE_UNAVAILABLE")

    monkeypatch.setattr(recovery, "recovery_catalogue", failed)
    result = runner.invoke(recovery.recovery_app, ["inventory"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["code"] == "RECOVERY_CATALOGUE_UNAVAILABLE"
