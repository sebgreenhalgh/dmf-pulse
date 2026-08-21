"""LIVE-ODDS-001 runtime credential isolation contract."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds.credentials import (
    ODDS_API_ENVIRONMENT_VARIABLE,
    SYSTEMD_CREDENTIAL_DIRECTORY_VARIABLE,
    RuntimeOddsCredentialProvider,
    StaticCredentialProvider,
    UnavailableCredentialProvider,
    credential_configuration_hint,
    credential_is_configured,
    validate_runtime_credential,
)

pytestmark = pytest.mark.unit

SENTINEL = "runtime-secret-sentinel-913579"


def test_runtime_provider_is_lazy_and_uses_only_the_injected_environment() -> None:
    environment: dict[str, str] = {}
    provider = RuntimeOddsCredentialProvider(environment=environment)

    assert credential_configuration_hint(provider) is False
    environment[ODDS_API_ENVIRONMENT_VARIABLE] = SENTINEL

    assert credential_configuration_hint(provider) is True
    assert provider.get_credential() == SENTINEL
    assert SENTINEL not in repr(provider)


def test_systemd_credential_precedes_process_fallback_and_trims_one_newline(
    tmp_path: Path,
) -> None:
    credential_file = tmp_path / "the_odds_api_key"
    credential_file.write_bytes(f"{SENTINEL}\r\n".encode("ascii"))
    provider = RuntimeOddsCredentialProvider(
        environment={
            SYSTEMD_CREDENTIAL_DIRECTORY_VARIABLE: os.fspath(tmp_path),
            ODDS_API_ENVIRONMENT_VARIABLE: "different-valid-secret-24680",
        }
    )

    assert provider.get_credential() == SENTINEL


@pytest.mark.parametrize(
    "value",
    (
        None,
        "short",
        "contains whitespace 913579",
        "contains.dot.913579",
        "non-ascii-é-913579",
        "x" * 513,
    ),
)
def test_invalid_runtime_credentials_fail_with_one_non_disclosing_error(
    value: str | None,
) -> None:
    with pytest.raises(IngestionError) as raised:
        validate_runtime_credential(value)

    assert raised.value.code == "CREDENTIAL_UNAVAILABLE"
    assert value is None or value not in str(raised.value)


def test_systemd_credential_must_be_a_bounded_regular_file(tmp_path: Path) -> None:
    provider = RuntimeOddsCredentialProvider(
        environment={SYSTEMD_CREDENTIAL_DIRECTORY_VARIABLE: os.fspath(tmp_path / "missing")}
    )

    with pytest.raises(IngestionError) as raised:
        provider.get_credential()

    assert raised.value.code == "CREDENTIAL_UNAVAILABLE"
    assert os.fspath(tmp_path) not in str(raised.value)


def test_known_configuration_hints_never_resolve_secret_material() -> None:
    class ExplodingProvider:
        def get_credential(self) -> str:
            raise AssertionError("must not be called")

    assert credential_configuration_hint(UnavailableCredentialProvider()) is False
    assert credential_configuration_hint(StaticCredentialProvider(SENTINEL)) is True
    assert credential_configuration_hint(ExplodingProvider()) is None


def test_credential_probe_returns_only_a_boolean() -> None:
    assert credential_is_configured(StaticCredentialProvider(SENTINEL)) is True
    assert credential_is_configured(StaticCredentialProvider("invalid")) is False
    assert credential_is_configured(UnavailableCredentialProvider()) is False
    assert SENTINEL not in repr(StaticCredentialProvider(SENTINEL))
