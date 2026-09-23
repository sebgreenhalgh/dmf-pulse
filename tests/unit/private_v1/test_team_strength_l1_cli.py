"""Safe finite operator argument errors and terminal-only private observation."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "l1_operator", Path(__file__).resolve().parents[3] / "scripts/run_team_strength_l1.py"
)
assert spec is not None and spec.loader is not None
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


def test_operator_has_no_output_or_scenario_override(capsys):
    with pytest.raises(SystemExit):
        script.parser().parse_args(
            ["observe", "--output", "private", "--entry-id", "secret-marker"]
        )
    text = capsys.readouterr().err
    assert "secret-marker" not in text and "Invalid L3 operator arguments" in text


def observe_args():
    return [
        "operator",
        "observe",
        "--public-readiness",
        "public.json",
        "--readiness-sha256",
        "0" * 64,
        "--entry-id",
        "42",
        "--code-sha",
        "a" * 40,
        "--approval-reference",
        "unapproved",
        "--execution-attestation",
        "unapproved",
        "--confirm-one-shot",
    ]


def test_nonterminal_blocks_without_opening_public_file_or_providers(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", observe_args())
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert script.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["reason"] == "TERMINAL_REQUIRED" and not result["private_attempt_consumed"]


def test_missing_public_evidence_safe_and_unconsumed(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", observe_args())
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert script.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "TEAM_STRENGTH_PUBLIC_PREFLIGHT_BLOCKED"
    assert (
        not result["private_attempt_consumed"]
        and result["fpl_requests"] == result["odds_requests"] == 0
    )
