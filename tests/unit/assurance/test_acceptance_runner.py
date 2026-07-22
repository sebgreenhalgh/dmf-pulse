"""Acceptance-ledger success classification tests."""

from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest


@pytest.mark.unit
def test_unmapped_success_uses_machine_valid_pass_prefix(repository_root: Path) -> None:
    namespace = runpy.run_path(str(repository_root / "scripts" / "run_acceptance.py"))
    command_type = namespace["AcceptanceCommand"]
    summarize = cast(Callable[[object, str, int], str], namespace["_summary"])
    command = command_type("rules contract command", ("dmf",), 1.0)

    assert summarize(command, "", 0) == "PASS: command completed"
