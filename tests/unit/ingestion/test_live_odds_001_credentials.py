"""LIVE-ODDS-001 runtime credential isolation contract."""

from __future__ import annotations

import inspect
import os
import stat
from pathlib import Path
from types import SimpleNamespace

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


def test_cred02_cred03_raw_environment_secret_is_not_a_production_source() -> None:
    provider = RuntimeOddsCredentialProvider(environment={ODDS_API_ENVIRONMENT_VARIABLE: SENTINEL})

    assert credential_configuration_hint(provider) is False
    assert provider.get_credential() is None
    assert credential_is_configured(provider) is False
    assert SENTINEL not in repr(provider)


def test_cred01_systemd_credential_ignores_raw_environment_value_and_trims_newline(
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


@pytest.mark.parametrize(
    "content",
    (
        b"short",
        b"x" * 515,
        b"non-ascii-\xff-credential",
        b"contains whitespace 913579",
    ),
    ids=("short", "oversized", "non-ascii", "whitespace"),
)
def test_cred05_systemd_credential_file_content_remains_bounded(
    tmp_path: Path,
    content: bytes,
) -> None:
    (tmp_path / "the_odds_api_key").write_bytes(content)
    provider = RuntimeOddsCredentialProvider(
        environment={SYSTEMD_CREDENTIAL_DIRECTORY_VARIABLE: os.fspath(tmp_path)}
    )

    with pytest.raises(IngestionError) as raised:
        provider.get_credential()

    assert raised.value.code == "CREDENTIAL_UNAVAILABLE"
    assert content.decode("ascii", errors="ignore") not in str(raised.value)


def test_cred05_systemd_credential_symlink_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = tmp_path / "the_odds_api_key"
    link.write_text(SENTINEL, encoding="ascii")
    original_lstat = Path.lstat
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda candidate: (
            SimpleNamespace(st_mode=stat.S_IFLNK)
            if candidate == link
            else original_lstat(candidate)
        ),
    )
    provider = RuntimeOddsCredentialProvider(
        environment={SYSTEMD_CREDENTIAL_DIRECTORY_VARIABLE: os.fspath(tmp_path)}
    )

    with pytest.raises(IngestionError) as raised:
        provider.get_credential()

    assert raised.value.code == "CREDENTIAL_UNAVAILABLE"


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


def test_cred06_through_cred08_only_file_or_explicit_test_injection_is_supported() -> None:
    assert StaticCredentialProvider(SENTINEL).get_credential() == SENTINEL
    source = inspect.getsource(RuntimeOddsCredentialProvider.get_credential)
    assert ODDS_API_ENVIRONMENT_VARIABLE not in source
    assert "DMF_PULSE_ODDS_API_KEY" not in source
    assert ".env" not in source
    assert "argv" not in source
