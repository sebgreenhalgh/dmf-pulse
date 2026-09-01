"""Operator UX proofs for the top-level one-command surface."""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from dmf_pulse.cli import pulse as pulse_module
from dmf_pulse.cli.app import app
from dmf_pulse.private_v1.errors import PrivateV1Error

runner = CliRunner()


def test_pulse_help_exposes_only_the_entry_identifier() -> None:
    result = runner.invoke(app, ["pulse", "--help"])

    assert result.exit_code == 0
    assert "--entry-id" in result.stdout
    assert "token" not in result.stdout.casefold()
    assert "bootstrap" not in result.stdout.casefold()
    assert "fixtures" not in result.stdout.casefold()
    assert "score-prior" not in result.stdout.casefold()


def test_missing_odds_key_is_the_first_actionable_blocker(monkeypatch) -> None:
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    marker = "secret-that-must-not-appear"
    monkeypatch.setenv("DMF_FPL_BEARER_TOKEN", marker)

    result = runner.invoke(app, ["pulse", "--entry-id", "42"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "THE_ODDS_API_KEY is missing."
    assert marker not in result.output
    assert "Traceback" not in result.output


def test_successful_cli_prints_recommendation_and_passes_only_entry_id(monkeypatch) -> None:
    monkeypatch.setenv("THE_ODDS_API_KEY", "synthetic-odds-key")
    monkeypatch.setenv("DMF_FPL_BEARER_TOKEN", "synthetic-fpl-key")
    requests = []

    class Service:
        def __init__(self, **kwargs) -> None:
            assert set(kwargs) == {"direct_client_factory"}

        def run(self, request):
            requests.append(request)
            return SimpleNamespace(report="DMF PULSE - GW2\n\nRECOMMENDATION\nNO TRANSFER\n")

    monkeypatch.setattr(pulse_module, "PrivateV1OneCommandService", Service)
    result = runner.invoke(app, ["pulse", "--entry-id", "42"])

    assert result.exit_code == 0
    assert result.stdout.startswith("DMF PULSE - GW2\n\nRECOMMENDATION")
    assert requests[0].entry_id == 42
    assert len(requests[0].code_sha) == 40
    assert requests[0].operator_approved_at < requests[0].run_at
    assert (requests[0].run_at - requests[0].operator_approved_at).total_seconds() == 300


def test_expected_service_error_has_no_traceback(monkeypatch) -> None:
    monkeypatch.setenv("THE_ODDS_API_KEY", "synthetic-odds-key")

    class Service:
        def __init__(self, **kwargs) -> None:
            del kwargs

        def run(self, request):
            del request
            raise PrivateV1Error("FPL_AUTH_REQUIRED", "Set DMF_FPL_BEARER_TOKEN.")

    monkeypatch.setattr(pulse_module, "PrivateV1OneCommandService", Service)
    result = runner.invoke(app, ["pulse", "--entry-id", "42"])

    assert result.exit_code == 2
    assert result.stderr.strip() == "Set DMF_FPL_BEARER_TOKEN."
    assert "Traceback" not in result.output


def test_prompting_provider_uses_environment_without_disclosure() -> None:
    marker = "synthetic-fpl-secret"
    provider = pulse_module._PromptingCredentialProvider({"DMF_FPL_BEARER_TOKEN": marker})

    credential = provider.get()

    assert credential.source == "ENVIRONMENT"
    assert marker not in repr(credential)
