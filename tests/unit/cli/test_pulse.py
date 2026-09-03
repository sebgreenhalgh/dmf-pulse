"""Operator UX proofs for the top-level one-command surface."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner

from dmf_pulse.cli import pulse as pulse_module
from dmf_pulse.cli.app import app
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.private_v1.errors import PrivateV1Error

runner = CliRunner()


def test_pulse_help_exposes_entry_identifier_and_progress_suppression_only() -> None:
    result = runner.invoke(app, ["pulse", "--help"])

    assert result.exit_code == 0
    root_command = get_command(app)
    assert isinstance(root_command, TyperGroup)
    pulse_options = {
        option
        for parameter in root_command.commands["pulse"].params
        for option in getattr(parameter, "opts", ())
    }
    assert pulse_options == {"--entry-id", "--horizon-gameweeks", "--no-progress"}
    assert "--horizon-gameweeks" in result.stdout
    assert "Optimisation horizon" in result.stdout
    assert "token" not in result.stdout.casefold()
    assert "bootstrap" not in result.stdout.casefold()
    assert "fixtures" not in result.stdout.casefold()
    assert "score-prior" not in result.stdout.casefold()


def test_missing_odds_key_is_the_first_actionable_blocker(monkeypatch) -> None:
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    marker = "secret-that-must-not-appear"
    monkeypatch.setenv("DMF_FPL_BEARER_TOKEN", marker)

    result = runner.invoke(app, ["pulse", "--entry-id", "42", "--no-progress"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "THE_ODDS_API_KEY is missing."
    assert marker not in result.output
    assert "Traceback" not in result.output


def test_successful_cli_prints_recommendation_and_passes_only_entry_id(monkeypatch) -> None:
    monkeypatch.setenv("THE_ODDS_API_KEY", "synthetic-odds-key")
    monkeypatch.setenv("DMF_FPL_BEARER_TOKEN", "synthetic-fpl-key")
    requests = []
    approved_at = datetime(2026, 9, 2, 0, 0, 38, 492580, tzinfo=UTC)

    class FixedDatetime:
        @classmethod
        def now(cls, tz):
            assert tz is UTC
            return approved_at

    class Service:
        def __init__(self, **kwargs) -> None:
            assert set(kwargs) == {"direct_client_factory", "progress"}
            self.progress = kwargs["progress"]

        def run(self, request):
            requests.append(request)
            self.progress.message("DMF Pulse starting")
            with self.progress.stage(
                started="Acquiring current FPL state...",
                completed="FPL state ready",
                failed="current FPL state",
            ):
                pass
            self.progress.finish()
            return SimpleNamespace(report="DMF PULSE - GW2\n\nRECOMMENDATION\nNO TRANSFER\n")

    monkeypatch.setattr(pulse_module, "PrivateV1OneCommandService", Service)
    monkeypatch.setattr(pulse_module, "datetime", FixedDatetime)
    result = runner.invoke(app, ["pulse", "--entry-id", "42"])

    assert result.exit_code == 0
    assert result.stdout.startswith("DMF PULSE - GW2\n\nRECOMMENDATION")
    assert "DMF Pulse starting" in result.stderr
    assert "Acquiring current FPL state..." in result.stderr
    assert "FPL state ready" in result.stderr
    assert "Total runtime:" in result.stderr
    assert requests[0].entry_id == 42
    assert len(requests[0].code_sha) == 40
    assert requests[0].operator_approved_at == approved_at
    assert requests[0].run_at == datetime(2026, 9, 2, 0, 5, 38, tzinfo=UTC)
    assert requests[0].run_at.microsecond == 0
    assert requests[0].horizon_gameweeks == 1


def test_horizon_option_is_explicit_and_rejects_every_value_except_one_or_three(
    monkeypatch,
) -> None:
    monkeypatch.setenv("THE_ODDS_API_KEY", "synthetic-odds-key")
    captured = []

    class Service:
        def __init__(self, **kwargs) -> None:
            del kwargs

        def run(self, request):
            captured.append(request)
            return SimpleNamespace(report="ROLLING REPORT")

    monkeypatch.setattr(pulse_module, "PrivateV1OneCommandService", Service)

    rolling = runner.invoke(
        app,
        ["pulse", "--entry-id", "42", "--horizon-gameweeks", "3", "--no-progress"],
    )
    invalid = runner.invoke(
        app,
        ["pulse", "--entry-id", "42", "--horizon-gameweeks", "2", "--no-progress"],
    )

    assert rolling.exit_code == 0
    assert captured[0].horizon_gameweeks == 3
    assert invalid.exit_code == 2
    assert invalid.stderr.strip() == "--horizon-gameweeks must be exactly 1 or 3."


def test_no_progress_suppresses_observability_and_preserves_report(monkeypatch) -> None:
    monkeypatch.setenv("THE_ODDS_API_KEY", "synthetic-odds-key")
    marker = "private-runtime-identifier-that-must-not-appear"

    class Service:
        def __init__(self, **kwargs) -> None:
            self.progress = kwargs["progress"]

        def run(self, request):
            del request
            self.progress.message(f"forbidden {marker}")
            return SimpleNamespace(report="UNCHANGED FINAL REPORT")

    monkeypatch.setattr(pulse_module, "PrivateV1OneCommandService", Service)
    result = runner.invoke(app, ["pulse", "--entry-id", "42", "--no-progress"])

    assert result.exit_code == 0
    assert result.stdout == "UNCHANGED FINAL REPORT\n"
    assert result.stderr == ""
    assert marker not in result.output


def test_expected_service_error_has_no_traceback(monkeypatch) -> None:
    monkeypatch.setenv("THE_ODDS_API_KEY", "synthetic-odds-key")

    class Service:
        def __init__(self, **kwargs) -> None:
            del kwargs

        def run(self, request):
            del request
            raise PrivateV1Error("FPL_AUTH_REQUIRED", "Set DMF_FPL_BEARER_TOKEN.")

    monkeypatch.setattr(pulse_module, "PrivateV1OneCommandService", Service)
    result = runner.invoke(app, ["pulse", "--entry-id", "42", "--no-progress"])

    assert result.exit_code == 2
    assert result.stderr.strip() == "Set DMF_FPL_BEARER_TOKEN."
    assert "Traceback" not in result.output


def test_prompting_provider_uses_environment_without_disclosure() -> None:
    marker = "synthetic-fpl-secret"
    provider = pulse_module._PromptingCredentialProvider({"DMF_FPL_BEARER_TOKEN": marker})

    credential = provider.get()

    assert credential.source == "ENVIRONMENT"
    assert marker not in repr(credential)


def test_prompting_provider_is_interactive_only_and_validates_hidden_input(
    monkeypatch,
) -> None:
    provider = pulse_module._PromptingCredentialProvider({})
    monkeypatch.setattr(pulse_module.sys.stdin, "isatty", lambda: False)
    with pytest.raises(IngestionError) as non_interactive:
        provider.get()
    assert getattr(non_interactive.value, "code", None) == "CREDENTIAL_MISSING"

    monkeypatch.setattr(pulse_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(pulse_module.getpass, "getpass", lambda _prompt: "")
    with pytest.raises(IngestionError) as empty:
        provider.get()
    assert getattr(empty.value, "code", None) == "CREDENTIAL_MISSING"

    monkeypatch.setattr(pulse_module.getpass, "getpass", lambda _prompt: " hidden-token ")
    with pytest.raises(IngestionError) as invalid:
        provider.get()
    assert getattr(invalid.value, "code", None) == "CREDENTIAL_INVALID"

    monkeypatch.setattr(pulse_module.getpass, "getpass", lambda _prompt: "hidden-token")
    assert provider.get().source == "HIDDEN_PROMPT"


def test_code_identity_override_is_strict_and_git_head_supports_checkout_forms(
    monkeypatch, tmp_path
) -> None:
    configured_sha = "a" * 40
    monkeypatch.setenv("DMF_CODE_SHA", configured_sha.upper())
    assert pulse_module._code_sha() == configured_sha
    monkeypatch.setenv("DMF_CODE_SHA", "not-a-sha")
    with pytest.raises(PrivateV1Error) as invalid:
        pulse_module._code_sha()
    assert invalid.value.code == "CODE_IDENTITY_INVALID"

    detached = tmp_path / "detached"
    (detached / ".git").mkdir(parents=True)
    (detached / ".git" / "HEAD").write_text(configured_sha, encoding="ascii")
    assert pulse_module._git_head(detached) == configured_sha

    symbolic = tmp_path / "symbolic"
    ref = symbolic / ".git" / "refs" / "heads" / "test"
    ref.parent.mkdir(parents=True)
    (symbolic / ".git" / "HEAD").write_text("ref: refs/heads/test", encoding="ascii")
    ref.write_text(configured_sha, encoding="ascii")
    assert pulse_module._git_head(symbolic) == configured_sha

    worktree = tmp_path / "worktree"
    git_dir = tmp_path / "worktree-metadata"
    worktree.mkdir()
    git_dir.mkdir()
    (worktree / ".git").write_text("gitdir: ../worktree-metadata", encoding="utf-8")
    (git_dir / "HEAD").write_text(configured_sha, encoding="ascii")
    assert pulse_module._git_head(worktree) == configured_sha

    (worktree / ".git").write_text("malformed", encoding="utf-8")
    assert pulse_module._git_head(worktree) is None

    unreadable = tmp_path / "missing-head"
    (unreadable / ".git").mkdir(parents=True)
    assert pulse_module._git_head(unreadable) is None


def test_installed_content_identity_fails_closed_without_package_files(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        pulse_module.importlib.metadata,
        "distribution",
        lambda _name: SimpleNamespace(files=()),
    )
    with pytest.raises(PrivateV1Error) as absent:
        pulse_module._installed_content_sha()
    assert absent.value.code == "CODE_IDENTITY_UNAVAILABLE"

    class MissingFileDistribution:
        files = (Path("dmf_pulse/missing.py"),)

        @staticmethod
        def locate_file(_relative):
            return tmp_path / "does-not-exist.py"

    monkeypatch.setattr(
        pulse_module.importlib.metadata,
        "distribution",
        lambda _name: MissingFileDistribution(),
    )
    assert pulse_module._installed_content_sha() == "da39a3ee5e6b4b0d3255bfef95601890afd80709"


def test_cli_does_not_duplicate_a_failure_already_reported_by_the_service(
    monkeypatch,
) -> None:
    monkeypatch.setenv("THE_ODDS_API_KEY", "synthetic-odds-key")

    class Service:
        def __init__(self, **kwargs) -> None:
            self.progress = kwargs["progress"]

        def run(self, request):
            del request
            self.progress.failure("service stage", "FPL_AUTH_REQUIRED")
            raise PrivateV1Error("FPL_AUTH_REQUIRED", "Authentication failed.")

    monkeypatch.setattr(pulse_module, "PrivateV1OneCommandService", Service)
    result = runner.invoke(app, ["pulse", "--entry-id", "42"])

    assert result.exit_code == 2
    assert result.stderr.count("FAILED: service stage") == 1
    assert "FAILED: command preflight" not in result.stderr
