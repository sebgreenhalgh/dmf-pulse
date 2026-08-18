"""Secret-safe runtime credential oracles for GW1 live odds input."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.client import OddsClient, build_request
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.credentials import (
    ODDS_API_ENVIRONMENT_VARIABLE,
    SYSTEMD_CREDENTIAL_DIRECTORY_VARIABLE,
    SYSTEMD_CREDENTIAL_FILE,
    RuntimeOddsCredentialProvider,
    credential_is_configured,
)

pytestmark = pytest.mark.unit


def _credential(character: str = "A") -> str:
    return character * 32


def _render_exception(error: BaseException) -> str:
    return "\n".join((repr(error), str(error), json.dumps(getattr(error, "__dict__", {}))))


def test_absent_blank_and_malformed_runtime_credentials_fail_closed() -> None:
    invalid_environments = (
        {},
        {ODDS_API_ENVIRONMENT_VARIABLE: ""},
        {ODDS_API_ENVIRONMENT_VARIABLE: " " * 32},
        {ODDS_API_ENVIRONMENT_VARIABLE: "too-short"},
        {ODDS_API_ENVIRONMENT_VARIABLE: "A" * 31 + "&"},
        {ODDS_API_ENVIRONMENT_VARIABLE: "é" * 32},
    )

    for environment in invalid_environments:
        provider = RuntimeOddsCredentialProvider(environment=environment)
        assert credential_is_configured(provider) is False
        profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
        client = OddsClient(
            profile,
            credential_provider=provider,
            transport_factory=lambda: (_ for _ in ()).throw(
                AssertionError("transport must not be constructed")
            ),
            clock=lambda: datetime(2026, 8, 18, 12, tzinfo=UTC),
        )
        with pytest.raises(IngestionError) as raised:
            client.fetch()
        assert raised.value.code == "CREDENTIAL_UNAVAILABLE"
        assert raised.value.details == {"transport_call_count": 0}
        assert client.transport_call_count == 0


def test_valid_process_runtime_injection_is_lazy_and_secret_free() -> None:
    secret = _credential()
    environment = {ODDS_API_ENVIRONMENT_VARIABLE: secret}
    provider = RuntimeOddsCredentialProvider(environment=environment)

    assert credential_is_configured(provider) is True
    assert provider.get_credential() == secret
    assert secret not in repr(provider)
    assert environment == {ODDS_API_ENVIRONMENT_VARIABLE: secret}


def test_systemd_credential_precedes_environment_and_allows_one_final_newline(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "credentials"
    directory.mkdir()
    systemd_secret = _credential("B")
    (directory / SYSTEMD_CREDENTIAL_FILE).write_text(systemd_secret + "\n", encoding="ascii")
    provider = RuntimeOddsCredentialProvider(
        environment={
            SYSTEMD_CREDENTIAL_DIRECTORY_VARIABLE: str(directory),
            ODDS_API_ENVIRONMENT_VARIABLE: _credential("C"),
        }
    )

    assert provider.get_credential() == systemd_secret
    assert credential_is_configured(provider) is True


def test_missing_or_symlinked_systemd_credential_does_not_fall_back(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "credentials"
    directory.mkdir()
    provider = RuntimeOddsCredentialProvider(
        environment={
            SYSTEMD_CREDENTIAL_DIRECTORY_VARIABLE: str(directory),
            ODDS_API_ENVIRONMENT_VARIABLE: _credential(),
        }
    )
    assert credential_is_configured(provider) is False

    target = tmp_path / "target"
    target.write_text(_credential(), encoding="ascii")
    try:
        (directory / SYSTEMD_CREDENTIAL_FILE).symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this host")
    assert credential_is_configured(provider) is False


def test_secret_is_absent_from_error_request_repr_url_and_fingerprint() -> None:
    first = _credential("D")
    second = _credential("E")
    first_request = build_request(first)
    second_request = build_request(second)

    assert first not in repr(first_request)
    assert first not in first_request.sanitized_target
    assert "apiKey" not in first_request.sanitized_target
    assert first_request.request_fingerprint == second_request.request_fingerprint
    assert first not in first_request.request_fingerprint

    with pytest.raises(IngestionError) as raised:
        build_request(first + "&")
    assert first not in _render_exception(raised.value)
    assert raised.value.as_error_object()["error"] == {
        "code": "CREDENTIAL_UNAVAILABLE",
        "message": "approved runtime credential is unavailable",
        "retryable": False,
    }
