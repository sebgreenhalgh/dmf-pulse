"""CLI error/status coverage for the OPT-011 public command boundary."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import typer
import typer.rich_utils
from typer.testing import CliRunner

from dmf_pulse.cli.optimise import (
    _exit_for,
    _exit_for_multi_gameweek,
    _integrity_failure,
    optimise_app,
)
from dmf_pulse.fpl_points.artifacts import canonical_json_bytes
from dmf_pulse.optimisation.errors import OptimisationError
from dmf_pulse.optimisation.models import OptimisationStatus
from dmf_pulse.optimisation.multi_gameweek_artifacts import (
    load_canonical_json,
    persist_result,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekOptimisationRequest,
    MultiGameweekResultStatus,
    seal_request,
)
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek

pytestmark = pytest.mark.unit
RUNNER = CliRunner()
FIXTURES = Path("fixtures/optimisation/multi_gameweek")


@pytest.mark.parametrize(
    ("status", "code"),
    (
        (OptimisationStatus.SUCCESS, 0),
        (OptimisationStatus.BLOCKED, 3),
        (OptimisationStatus.INFEASIBLE, 4),
        (OptimisationStatus.RESOURCE_LIMIT, 5),
    ),
)
def test_stage10_exit_status_mapping_is_total(status: OptimisationStatus, code: int) -> None:
    with pytest.raises(typer.Exit) as raised:
        _exit_for(status)
    assert raised.value.exit_code == code


@pytest.mark.parametrize(
    ("status", "code"),
    (
        (MultiGameweekResultStatus.SUCCESS, 0),
        (MultiGameweekResultStatus.RESOURCE_LIMIT, 5),
        (MultiGameweekResultStatus.INFEASIBLE, 4),
        (MultiGameweekResultStatus.BLOCKED, 3),
        (MultiGameweekResultStatus.ERROR, 6),
    ),
)
def test_stage11_exit_status_mapping_is_total(status: MultiGameweekResultStatus, code: int) -> None:
    with pytest.raises(typer.Exit) as raised:
        _exit_for_multi_gameweek(status)
    assert raised.value.exit_code == code


@pytest.mark.parametrize("validate", (False, True))
def test_integrity_failure_emits_machine_readable_fail_closed_payload(
    capsys: pytest.CaptureFixture[str], validate: bool
) -> None:
    with pytest.raises(typer.Exit) as raised:
        _integrity_failure(
            OptimisationError("SYNTHETIC_INTEGRITY_FAILURE", "synthetic failure"),
            validate=validate,
        )
    assert raised.value.exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] == "SYNTHETIC_INTEGRITY_FAILURE"
    assert payload["legal"] is False if validate else payload["status"] == "BLOCKED"


@pytest.mark.parametrize(
    ("command", "args"),
    (
        (
            "one-gameweek",
            [
                "--request",
                "unused",
                "--gameweek-artifact",
                "unused",
                "--ruleset",
                "unused",
                "--artifact-root",
                "unused",
            ],
        ),
        (
            "validate-plan",
            [
                "--request",
                "unused",
                "--gameweek-artifact",
                "unused",
                "--ruleset",
                "unused",
                "--artifact",
                "unused",
            ],
        ),
        (
            "multi-gameweek",
            [
                "--request",
                "unused",
                "--ruleset",
                "unused",
                "--artifact-root",
                "unused",
            ],
        ),
        (
            "advance-multi-gameweek",
            [
                "--request",
                "unused",
                "--result",
                "unused",
                "--artifact-root",
                "unused",
            ],
        ),
    ),
)
def test_all_optimise_commands_reject_non_json_output(
    command: str, args: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(typer.rich_utils, "MAX_WIDTH", 240)
    invoked = RUNNER.invoke(optimise_app, [command, *args, "--output", "yaml"])
    assert invoked.exit_code == 2
    plain = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", invoked.output)
    assert "--output must be json" in plain


def test_multi_gameweek_cli_blocks_missing_or_rules_mismatched_input(
    tmp_path: Path,
) -> None:
    missing = RUNNER.invoke(
        optimise_app,
        [
            "multi-gameweek",
            "--request",
            str(tmp_path / "missing.json"),
            "--ruleset",
            str(FIXTURES / "reference_ruleset_test_only.json"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ],
    )
    assert missing.exit_code == 2
    assert json.loads(missing.output)["status"] == "BLOCKED"

    request = load_canonical_json(FIXTURES / "request.json", MultiGameweekOptimisationRequest)
    altered = seal_request(
        request.model_copy(
            update={
                "rules": request.rules.model_copy(update={"capability": "DIFFERENT"}),
                "request_sha256": "0" * 64,
            }
        )
    )
    request_path = tmp_path / "altered.json"
    request_path.write_bytes(canonical_json_bytes(altered))
    mismatched = RUNNER.invoke(
        optimise_app,
        [
            "multi-gameweek",
            "--request",
            str(request_path),
            "--ruleset",
            str(FIXTURES / "reference_ruleset_test_only.json"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ],
    )
    assert mismatched.exit_code == 2
    assert json.loads(mismatched.output)["error_code"] == ("MULTI_GAMEWEEK_RULES_LINEAGE_MISMATCH")


def test_advance_cli_distinguishes_artifact_integrity_and_execution_errors(
    tmp_path: Path,
) -> None:
    request_path = FIXTURES / "request.json"
    request = load_canonical_json(request_path, MultiGameweekOptimisationRequest)
    result = optimise_multi_gameweek(request)
    result_path = persist_result(result, artifact_root=tmp_path / "source")

    missing = RUNNER.invoke(
        optimise_app,
        [
            "advance-multi-gameweek",
            "--request",
            str(request_path),
            "--result",
            str(tmp_path / "missing.json"),
            "--artifact-root",
            str(tmp_path / "output"),
        ],
    )
    assert missing.exit_code == 2
    assert json.loads(missing.output)["error_code"] == "MULTI_GAMEWEEK_ARTIFACT_INVALID"

    invalid_observation = RUNNER.invoke(
        optimise_app,
        [
            "advance-multi-gameweek",
            "--request",
            str(request_path),
            "--result",
            str(result_path),
            "--artifact-root",
            str(tmp_path / "output"),
            "--observed-node",
            "not-a-child",
        ],
    )
    assert invalid_observation.exit_code == 2
    assert json.loads(invalid_observation.output)["error_code"] == (
        "MULTI_GAMEWEEK_ADVANCE_INVALID"
    )
