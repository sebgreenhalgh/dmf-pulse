from __future__ import annotations

import runpy
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script_name", "helper_name"),
    [
        ("verify_wheel.py", "_environment_dmf"),
        ("verify_nrm006_wheel.py", "_dmf"),
    ],
)
def test_clean_wheel_uses_fail_closed_isolated_console_entry_point(
    repository_root: Path,
    script_name: str,
    helper_name: str,
) -> None:
    namespace: dict[str, Any] = runpy.run_path(str(repository_root / "scripts" / script_name))
    helper = namespace[helper_name]
    python = Path("C:/trusted/python.exe")

    command = helper(python)

    assert command[:3] == (str(python), "-I", "-c")
    assert len(command) == 4
    runner = command[3]
    assert "m.distribution('dmf-pulse').entry_points" in runner
    assert "e.group=='console_scripts'" in runner
    assert "e.name=='dmf'" in runner
    assert "ep.value=='dmf_pulse.cli.app:main'" in runner
    assert "sys.exit(ep.load()())" in runner
    assert "sys.exit(125)" in runner
    assert "assert" not in runner
    assert all("dmf.exe" not in argument.casefold() for argument in command)


def test_nrm_clean_wheel_seeds_schedule_before_market_cutoff(repository_root: Path) -> None:
    namespace: dict[str, Any] = runpy.run_path(
        str(repository_root / "scripts/verify_nrm006_wheel.py")
    )
    dmf = ("trusted-python", "-I", "-c", "trusted-runner")

    command = namespace["_fpl_seed_command"](dmf)

    assert command[:4] == dmf
    assert command[4:7] == ("ingest", "fpl", "import")
    assert command[command.index("--rights-profile") + 1] == "synthetic_test_v1"
    captured_at = datetime.fromisoformat(command[command.index("--captured-at") + 1])
    information_cutoff = datetime.fromisoformat(command[command.index("--information-cutoff") + 1])
    market_as_of = datetime.fromisoformat(namespace["MARKET_AS_OF"])
    assert captured_at < market_as_of
    assert information_cutoff == market_as_of
