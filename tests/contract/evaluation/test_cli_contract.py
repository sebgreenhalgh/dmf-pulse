from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.app import app

pytestmark = pytest.mark.contract
runner = CliRunner()

_DIAG_OUTPUT_LIMIT = 4096


def _bounded_diagnostic(text: str, *, limit: int = _DIAG_OUTPUT_LIMIT) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    suffix = b"\n...[truncated to 4 KiB]\n"
    return encoded[: limit - len(suffix)].decode("utf-8", errors="ignore") + suffix.decode()


def _append_ci_diag_02_observation(
    *,
    command_index: int,
    command: list[str],
    result: Any,
    tmp_path: Path,
) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path is None:
        return

    invoked_arguments = [*command, "--output", "yaml"]
    normalized_arguments = [
        argument.replace(str(tmp_path), "<TMP_PATH>") for argument in invoked_arguments
    ]
    output = result.output.replace(str(tmp_path), "<TMP_PATH>")
    stdout = result.stdout.replace(str(tmp_path), "<TMP_PATH>")
    try:
        stderr = result.stderr.replace(str(tmp_path), "<TMP_PATH>")
    except ValueError:
        stderr = None
    exception = result.exception
    unexpected = result.exit_code != 2 or "--output must be json" not in result.output
    exception_traceback = None
    if unexpected and result.exc_info is not None:
        exception_traceback = "".join(traceback.format_exception(*result.exc_info)).replace(
            str(tmp_path), "<TMP_PATH>"
        )

    lines = [
        "## CI-DIAG-02 evaluation CLI observation",
        "",
        f"### command {command_index} — {command[1]}",
        f"- arguments: `{json.dumps(normalized_arguments, ensure_ascii=True)}`",
        f"- exit_code: `{result.exit_code}`",
        f"- expected_message_present: `{str('--output must be json' in result.output).lower()}`",
        f"- output_contains_ansi_escape: `{str(chr(27) in output).lower()}`",
        f"- cwd: `{Path.cwd()}`",
        f"- CI: `{os.environ.get('CI', '<UNSET>')}`",
        f"- GITHUB_ACTIONS: `{os.environ.get('GITHUB_ACTIONS', '<UNSET>')}`",
        f"- RUNNER_OS: `{os.environ.get('RUNNER_OS', '<UNSET>')}`",
        f"- RUNNER_ARCH: `{os.environ.get('RUNNER_ARCH', '<UNSET>')}`",
        f"- DMF_ENVIRONMENT: `{os.environ.get('DMF_ENVIRONMENT', '<UNSET>')}`",
        f"- Python: `{sys.version.split()[0]}`",
        f"- exception_type: `{type(exception).__name__ if exception is not None else 'None'}`",
        f"- exception_repr: `{repr(exception) if exception is not None else 'None'}`",
        f"- stderr_available: `{str(stderr is not None).lower()}`",
        f"- stderr_same_as_output: `{str(stderr == output).lower()}`",
        "",
        "#### output",
        "",
        "```text",
        output,
        "```",
        "",
        "#### output repr",
        "",
        "```text",
        repr(output),
        "```",
    ]
    if stdout != output:
        lines.extend(("", "#### stdout", "", "```text", stdout, "```"))
    if stderr is not None and stderr != output:
        lines.extend(("", "#### stderr", "", "```text", stderr, "```"))
    if exception_traceback is not None:
        lines.extend(
            ("", "#### unexpected exc_info traceback", "", "```text", exception_traceback, "```")
        )
    record = _bounded_diagnostic("\n".join(lines) + "\n\n")
    with Path(summary_path).open("a", encoding="utf-8", newline="\n") as summary:
        summary.write(record)


def _run(command: list[str]) -> tuple[int, object]:
    result = runner.invoke(app, command)
    payload = json.loads(result.stdout)
    return result.exit_code, payload


def test_all_evaluation_cli_commands_share_application_path(tmp_path: Path) -> None:
    code, folds = _run(
        [
            "evaluate",
            "build-folds",
            "--input",
            "fixtures/historical/synthetic_five_gw/folds_input.json",
        ]
    )
    assert code == 0 and isinstance(folds, list) and len(folds) == 5
    code, benchmarks = _run(
        [
            "evaluate",
            "benchmark",
            "--input",
            "fixtures/historical/benchmark_player_histories/benchmark_input.json",
        ]
    )
    assert code == 0 and isinstance(benchmarks, list) and len(benchmarks) == 11
    code, metrics = _run(
        [
            "evaluate",
            "projections",
            "--input",
            "fixtures/historical/synthetic_five_gw/projections_input.json",
        ]
    )
    assert code == 0 and metrics["count"] == 4
    code, policy = _run(
        [
            "evaluate",
            "policy",
            "--input",
            "fixtures/historical/synthetic_five_gw/policy_input.json",
            "--artifact-root",
            str(tmp_path),
        ]
    )
    assert code == 0 and len(policy["steps"]) == 5
    code, report = _run(
        [
            "evaluate",
            "report",
            "--input",
            "fixtures/historical/synthetic_five_gw/report_input.json",
            "--artifact-root",
            str(tmp_path),
        ]
    )
    assert code == 0 and report["forecast_rows"] == 1


def test_leakage_cli_pass_and_block_exit_codes() -> None:
    code, clean = _run(
        [
            "evaluate",
            "leakage",
            "--input",
            "fixtures/historical/synthetic_five_gw/leakage_clean_input.json",
        ]
    )
    assert code == 0 and clean["status"] == "PASS"
    code, blocked = _run(
        [
            "evaluate",
            "leakage",
            "--input",
            "fixtures/historical/future_leakage_canary/leakage_input.json",
        ]
    )
    assert code == 3 and blocked["status"] == "BLOCKED"


def test_cli_invalid_input_returns_typed_failure(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    code, payload = _run(["evaluate", "build-folds", "--input", str(invalid)])
    assert code == 2
    assert payload["error"]["blocking"] is True


def test_cli_rejects_non_json_output_for_every_public_command(tmp_path: Path) -> None:
    commands = (
        [
            "evaluate",
            "build-folds",
            "--input",
            "fixtures/historical/synthetic_five_gw/folds_input.json",
        ],
        [
            "evaluate",
            "benchmark",
            "--input",
            "fixtures/historical/benchmark_player_histories/benchmark_input.json",
        ],
        [
            "evaluate",
            "projections",
            "--input",
            "fixtures/historical/synthetic_five_gw/projections_input.json",
        ],
        [
            "evaluate",
            "policy",
            "--input",
            "fixtures/historical/synthetic_five_gw/policy_input.json",
            "--artifact-root",
            str(tmp_path),
        ],
        [
            "evaluate",
            "leakage",
            "--input",
            "fixtures/historical/synthetic_five_gw/leakage_clean_input.json",
        ],
        [
            "evaluate",
            "report",
            "--input",
            "fixtures/historical/synthetic_five_gw/report_input.json",
            "--artifact-root",
            str(tmp_path),
        ],
    )
    for command in commands:
        result = runner.invoke(app, [*command, "--output", "yaml"])
        _append_ci_diag_02_observation(
            command_index=commands.index(command) + 1,
            command=command,
            result=result,
            tmp_path=tmp_path,
        )
        assert result.exit_code == 2
        assert "--output must be json" in result.output


def test_cli_maps_validation_and_evaluation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from dmf_pulse.evaluation.errors import EvaluationError
    from dmf_pulse.evaluation.service import EvaluationService

    def validation_failure(self: EvaluationService, payload: dict[str, object]) -> object:
        from dmf_pulse.evaluation.models import FeatureRecord

        return FeatureRecord.model_validate({})

    monkeypatch.setattr(EvaluationService, "build_folds", validation_failure)
    code, payload = _run(
        [
            "evaluate",
            "build-folds",
            "--input",
            "fixtures/historical/synthetic_five_gw/folds_input.json",
        ]
    )
    assert code == 2
    assert payload["error"]["code"] == "EVALUATION_INPUT_INVALID"
    assert "input_value" not in payload["error"]["message"]

    def evaluation_failure(self: EvaluationService, payload: dict[str, object]) -> object:
        raise EvaluationError("LEAKAGE_BLOCKED", "blocked")

    monkeypatch.setattr(EvaluationService, "build_folds", evaluation_failure)
    code, payload = _run(
        [
            "evaluate",
            "build-folds",
            "--input",
            "fixtures/historical/synthetic_five_gw/folds_input.json",
        ]
    )
    assert code == 2
    assert payload["error"]["code"] == "LEAKAGE_BLOCKED"


def test_every_cli_command_maps_malformed_json_to_typed_failure(tmp_path: Path) -> None:
    invalid = tmp_path / "malformed.json"
    invalid.write_text("{", encoding="utf-8")
    commands = (
        ["evaluate", "build-folds", "--input", str(invalid)],
        ["evaluate", "benchmark", "--input", str(invalid)],
        ["evaluate", "projections", "--input", str(invalid)],
        ["evaluate", "policy", "--input", str(invalid), "--artifact-root", str(tmp_path)],
        ["evaluate", "leakage", "--input", str(invalid)],
        ["evaluate", "report", "--input", str(invalid), "--artifact-root", str(tmp_path)],
    )
    for command in commands:
        code, payload = _run(command)
        assert code == 2
        assert payload["error"]["code"] == "EVALUATION_INPUT_INVALID"
        assert payload["error"]["blocking"] is True
