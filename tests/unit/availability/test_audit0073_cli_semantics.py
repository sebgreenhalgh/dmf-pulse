from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from dmf_pulse.cli.app import app
from dmf_pulse.cli.availability_cmd import predict_command

SEED = "MIN-007-COHERENCE-V1"


def _args(external_id: int, *, as_of: str = "2026-08-14T17:30:00Z", seed: str = SEED) -> list[str]:
    return [
        "availability",
        "predict",
        "--fixture-external-provider",
        "synthetic_availability",
        "--fixture-external-id",
        str(external_id),
        "--season-code",
        "2026/27",
        "--team-side",
        "HOME",
        "--as-of",
        as_of,
        "--model-key",
        "min007-baseline-v1",
        "--seed",
        seed,
        "--output",
        "json",
    ]


def test_all_plan_projected_scenarios_are_json_and_frozen(
    repository_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DMF_ENVIRONMENT", "REPLAY")
    plan = json.loads(
        (repository_root / "fixtures/availability/MIN-007/external_mapping_plan.json").read_text()
    )
    expected = json.loads(
        (repository_root / "fixtures/availability/MIN-007G/prediction_registry.json").read_text()
    )
    runner = CliRunner()
    for fixture in plan["target_fixtures"]:
        external_id = int(fixture["external_id"])
        result = runner.invoke(app, _args(external_id))
        if external_id == 709:
            assert result.exit_code == 42
            blocked = json.loads(result.stdout)
            assert blocked["status"] == "BLOCKED"
            assert blocked["error_code"] == "INSUFFICIENT_ELIGIBLE_SQUAD"
            continue
        assert result.exit_code == 0, result.stderr
        value = json.loads(result.stdout)
        scenario = fixture["scenario"]
        frozen = expected[scenario]
        assert value["status"] == "PROJECTED"
        assert value["as_of"] == "2026-08-14T17:30:00Z"
        assert value["fixture_id"] == frozen["fixture_id"]
        assert value["team_id"] == frozen["team_id"]
        assert value["projection"]["result_sha256"] == frozen["team_result_sha256"]


@pytest.mark.parametrize(
    "as_of",
    ("1900-01-01T00:00:00Z", "2099-01-01T00:00:00Z", "2026-08-15T15:00:00Z"),
)
def test_invalid_as_of_is_typed_stderr_only(monkeypatch: pytest.MonkeyPatch, as_of: str) -> None:
    monkeypatch.setenv("DMF_ENVIRONMENT", "TEST")
    result = CliRunner().invoke(app, _args(701, as_of=as_of))
    assert result.exit_code == 3
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "USAGE_INVALID"


def test_wrong_seed_is_rejected_before_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMF_ENVIRONMENT", "TEST")
    result = CliRunner().invoke(app, _args(701, seed="WRONG-SEED"))
    assert result.exit_code == 3
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "USAGE_INVALID"


def test_python_non_string_seed_is_rejected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DMF_ENVIRONMENT", "TEST")
    with pytest.raises(typer.Exit) as caught:
        predict_command(
            "synthetic_availability",
            701,
            "2026/27",
            "HOME",
            "2026-08-14T17:30:00Z",
            "min007-baseline-v1",
            7,  # type: ignore[arg-type]
            "json",
        )
    assert caught.value.exit_code == 3
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "USAGE_INVALID"


@pytest.mark.parametrize(
    "overrides",
    (
        {"fixture_external_provider": "other"},
        {"fixture_external_id": 999},
        {"season_code": "2025/26"},
        {"team_side": "AWAY"},
    ),
)
def test_invalid_mapping_inputs_have_no_stdout(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, object]
) -> None:
    monkeypatch.setenv("DMF_ENVIRONMENT", "TEST")
    args = _args(701)
    for key, value in overrides.items():
        option = "--" + key.replace("_", "-")
        index = args.index(option)
        args[index + 1] = str(value)
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 3
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "USAGE_INVALID"
