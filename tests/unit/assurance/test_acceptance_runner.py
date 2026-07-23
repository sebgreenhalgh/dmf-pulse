"""Acceptance-ledger success classification tests."""

from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from dmf_pulse.assurance.review_pack import DAT_MANDATORY_ACCEPTANCE_COMMANDS


@pytest.mark.unit
def test_unmapped_success_uses_machine_valid_pass_prefix(repository_root: Path) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "run_acceptance.py"))
    command_type = namespace["AcceptanceCommand"]
    summarize = cast(Callable[[object, str, int], str], namespace["_summary"])
    command = command_type("rules contract command", ("dmf",), 1.0)

    assert summarize(command, "", 0) == "PASS: command completed"


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
