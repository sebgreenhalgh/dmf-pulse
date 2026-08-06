"""Acceptance-ledger success classification tests."""

from __future__ import annotations

import json
import runpy
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from dmf_pulse.assurance.review_pack import (
    DAT_MANDATORY_ACCEPTANCE_COMMANDS,
    FPL_MANDATORY_ACCEPTANCE_COMMANDS,
    FPL_REVIEW_WRITE_AHEAD_RESULT,
    FPL_TEARDOWN_FINAL_RESULT,
    FPL_TEARDOWN_WRITE_AHEAD_RESULT,
    NRM_MANDATORY_ACCEPTANCE_COMMANDS,
    ODD_MANDATORY_ACCEPTANCE_COMMANDS,
)


@pytest.mark.unit
def test_unmapped_success_uses_machine_valid_pass_prefix(repository_root: Path) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "run_acceptance.py"))
    command_type = namespace["AcceptanceCommand"]
    summarize = cast(Callable[[object, str, int], str], namespace["_summary"])
    command = command_type("rules contract command", ("dmf",), 1.0)

    assert summarize(command, "", 0) == "PASS: command completed"


@pytest.mark.unit
def test_fpl_snapshot_expected_rejection_reads_public_result_contract(
    repository_root: Path,
) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "run_acceptance.py"))
    command_type = namespace["AcceptanceCommand"]
    summarize = cast(Callable[[object, str, int], str], namespace["_summary"])
    command = command_type(
        "uv run dmf ingest fpl snapshot --resource all",
        ("dmf",),
        1.0,
        expected_exit=4,
    )
    output = json.dumps(
        {
            "canonical_effects": {
                "error_code": "RIGHTS_BLOCKED",
                "transport_call_count": 0,
            },
            "status": "RIGHTS_BLOCKED",
        }
    )

    assert summarize(command, output, 4) == (
        "PASS: expected exit 4; RIGHTS_BLOCKED with zero transport calls"
    )


@pytest.mark.unit
def test_fpl_teardown_has_one_exact_final_result(repository_root: Path) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "run_acceptance.py"))
    command_type = namespace["AcceptanceCommand"]
    summarize = cast(Callable[[object, str, int], str], namespace["_summary"])
    command = command_type(
        "docker compose -f compose.test.yaml down -v --remove-orphans",
        ("docker",),
        1.0,
    )
    assert summarize(command, "", 0) == FPL_TEARDOWN_FINAL_RESULT


@pytest.mark.unit
def test_fpl_write_ahead_is_pending_blocked_evidence_not_false_complete(
    repository_root: Path,
) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "generate_fpl004_evidence.py"))
    records: list[dict[str, object]] = []
    for index, command in enumerate(FPL_MANDATORY_ACCEPTANCE_COMMANDS, start=1):
        records.append(
            {
                "command": command,
                "duration_seconds": 0.1,
                "exit_code": 4 if index == 20 else 0,
                "result": (
                    "PASS: RIGHTS_BLOCKED with zero transport calls"
                    if index == 20
                    else "PASS: fixture"
                ),
            }
        )
    records[23].update(
        duration_seconds=None,
        result=FPL_REVIEW_WRITE_AHEAD_RESULT,
    )
    records[24].update(
        duration_seconds=None,
        result=FPL_TEARDOWN_WRITE_AHEAD_RESULT,
    )

    rows = namespace["_acceptance"](records)
    markdown = namespace["_acceptance_markdown"](rows, "BLOCKED")

    assert sum(row["status"] == "PASS" for row in rows) == 23
    assert rows[23]["status"] == rows[24]["status"] == "NOT_PASSED"
    assert "Status: **BLOCKED**" in markdown
    assert "23/25" in markdown


@pytest.mark.unit
def test_dat003_runner_has_exact_sequence_and_finally_teardown(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "run_acceptance.py"))
    globals_map = namespace["_main_dat"].__globals__
    globals_map["REPOSITORY_ROOT"] = tmp_path
    command_type = namespace["AcceptanceCommand"]
    record_type = namespace["CommandRecord"]
    commands = namespace["_dat_commands"]("uv", "docker")
    assert tuple(command.display for command in commands) == DAT_MANDATORY_ACCEPTANCE_COMMANDS
    assert commands[11].capture_path == tmp_path / "evidence/tickets/DAT-003/offline_upgrade.sql"

    calls: list[str] = []

    def fake_run(command: object) -> object:
        assert isinstance(command, command_type)
        calls.append(command.display)
        if command.display == DAT_MANDATORY_ACCEPTANCE_COMMANDS[0]:
            return record_type(command.display, 0.01, 1, "FAIL: injected")
        return record_type(command.display, 0.01, 0, "PASS: teardown")

    globals_map["run_command"] = fake_run
    monkeypatch.setattr(namespace["shutil"], "which", lambda name: name)
    main_dat = namespace["_main_dat"]
    assert main_dat() == 1
    assert calls == [DAT_MANDATORY_ACCEPTANCE_COMMANDS[0], DAT_MANDATORY_ACCEPTANCE_COMMANDS[22]]
    ledger = tmp_path / "evidence/tickets/DAT-003/commands.log"
    assert ledger.is_file()


@pytest.mark.unit
def test_dat003_runner_forces_the_disposable_database_target(
    repository_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "run_acceptance.py"))
    command_type = namespace["AcceptanceCommand"]
    captured: dict[str, object] = {}

    def fake_subprocess_run(*_args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("DMF_ENVIRONMENT", "PRODUCTION")
    monkeypatch.setenv("PGPASSWORD", "-".join(("do", "not", "use", "this")))
    monkeypatch.setenv("DMF_TEST_DATABASE_URL", "postgresql://" + "unsafe/production")
    monkeypatch.setenv("DMF_TEST_POSTGRES_PORT", "6432")
    monkeypatch.setattr(namespace["subprocess"], "run", fake_subprocess_run)

    record = namespace["run_command"](command_type("safe target", ("dmf",), 1.0))
    environment = cast(dict[str, str], captured["env"])
    assert record.exit_code == 0
    assert environment["DMF_ENVIRONMENT"] == "TEST"
    assert environment["PGPASSWORD"] == "changeme"
    assert environment["DMF_TEST_DATABASE_URL"] == (
        "postgresql+psycopg://dmf_test@127.0.0.1:55432/dmf_pulse_test"
    )
    assert "DMF_TEST_POSTGRES_PORT" not in environment


@pytest.mark.unit
def test_odd005_runner_scrubs_credentials_and_forces_offline(
    repository_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "run_acceptance.py"))
    command_type = namespace["AcceptanceCommand"]
    captured: dict[str, object] = {}

    def fake_subprocess_run(*_args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    for name in ("THE_ODDS_API_KEY", "ODDS_API_KEY", "DMF_ODDS_API_KEY"):
        monkeypatch.setenv(name, "constructed-test-only-value")
    monkeypatch.setattr(namespace["subprocess"], "run", fake_subprocess_run)

    namespace["run_command"](command_type("safe ODD target", ("dmf",), 1.0), force_offline=True)
    environment = cast(dict[str, str], captured["env"])
    assert environment["UV_OFFLINE"] == "1"
    assert not {
        "THE_ODDS_API_KEY",
        "ODDS_API_KEY",
        "DMF_ODDS_API_KEY",
    } & set(environment)


@pytest.mark.unit
def test_odd005_setup_failure_still_runs_literal_teardown(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "run_acceptance.py"))
    globals_map = namespace["_main_odd"].__globals__
    globals_map["REPOSITORY_ROOT"] = tmp_path
    command_type = namespace["AcceptanceCommand"]
    record_type = namespace["CommandRecord"]
    calls: list[tuple[str, bool]] = []

    def fail_setup() -> None:
        raise OSError("injected setup failure")

    def fake_run(command: object, *, force_offline: bool = False) -> object:
        assert isinstance(command, command_type)
        calls.append((command.display, force_offline))
        return record_type(command.display, 0.01, 0, "PASS: teardown")

    globals_map["_clean_odd_generated_outputs"] = fail_setup
    globals_map["run_command"] = fake_run
    monkeypatch.setattr(namespace["shutil"], "which", lambda name: name)

    assert namespace["_main_odd"]() == 1
    assert calls == [(ODD_MANDATORY_ACCEPTANCE_COMMANDS[27], True)]


@pytest.mark.unit
def test_nrm006_runner_has_exact_sequence_and_finally_teardown(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "run_acceptance.py"))
    commands = namespace["_nrm_commands"]("uv", "docker", "git")
    assert tuple(command.display for command in commands) == NRM_MANDATORY_ACCEPTANCE_COMMANDS
    assert commands[20].capture_path == (
        repository_root / "evidence/tickets/NRM-006/odds_replay.json"
    )

    globals_map = namespace["_main_nrm"].__globals__
    globals_map["REPOSITORY_ROOT"] = tmp_path
    command_type = namespace["AcceptanceCommand"]
    record_type = namespace["CommandRecord"]
    calls: list[tuple[str, bool]] = []

    def fail_setup() -> None:
        raise OSError("injected setup failure")

    def fake_run(command: object, *, force_offline: bool = False) -> object:
        assert isinstance(command, command_type)
        calls.append((command.display, force_offline))
        return record_type(command.display, 0.01, 0, "PASS: teardown")

    globals_map["_clean_nrm_generated_outputs"] = fail_setup
    globals_map["run_command"] = fake_run
    monkeypatch.setattr(namespace["shutil"], "which", lambda name: name)

    assert namespace["_main_nrm"]() == 1
    assert calls == [(NRM_MANDATORY_ACCEPTANCE_COMMANDS[31], True)]
