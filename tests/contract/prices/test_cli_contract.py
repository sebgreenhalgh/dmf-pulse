from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app

pytestmark = pytest.mark.contract


def test_prices_help_exposes_complete_nonplaceholder_vertical_slice() -> None:
    result = CliRunner().invoke(app, ["prices", "--help"])
    assert result.exit_code == 0
    for command in (
        "build-update-cycles",
        "build-features",
        "train-baseline",
        "predict-next",
        "simulate-path",
        "selling-value",
        "price-scenarios",
        "act-or-wait",
        "evaluate",
        "validate",
    ):
        assert command in result.stdout


def test_validate_cli_is_machine_readable_and_fail_closed() -> None:
    result = CliRunner().invoke(app, ["prices", "validate"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ENGINEERING_READY"
    assert payload["production_actionable"] is False
    assert payload["challenger_status"] == "DEPENDENCY_NOT_APPROVED"


def test_malformed_cli_payload_is_a_typed_failure(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not-json", encoding="utf-8")
    result = CliRunner().invoke(app, ["prices", "simulate-path", "--input", str(path)])
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "PRICE_INPUT_INVALID"
    assert payload["error"]["blocking"] is True
