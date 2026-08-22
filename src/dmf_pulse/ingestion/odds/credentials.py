"""Runtime-only, secret-safe credential resolution for The Odds API."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from dmf_pulse.ingestion.errors import IngestionError

ODDS_API_ENVIRONMENT_VARIABLE = "DMF_PULSE_ODDS_API_KEY"
SYSTEMD_CREDENTIAL_DIRECTORY_VARIABLE = "CREDENTIALS_DIRECTORY"
SYSTEMD_CREDENTIAL_FILE = "the_odds_api_key"
_MIN_CREDENTIAL_LENGTH = 16
_MAX_CREDENTIAL_LENGTH = 512
_ALLOWED_CREDENTIAL_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)


class CredentialProvider(Protocol):
    """Resolve a credential at the final pre-transport boundary."""

    def get_credential(self) -> str | None: ...


class UnavailableCredentialProvider:
    """Explicit safe refusal provider used by tests and controlled callers."""

    def __repr__(self) -> str:
        return "UnavailableCredentialProvider(<unconfigured>)"

    def get_credential(self) -> None:
        return None


class StaticCredentialProvider:
    """Explicit test-only/runtime injection without a revealing representation."""

    __slots__ = ("_credential",)

    def __init__(self, credential: str) -> None:
        self._credential = credential

    def __repr__(self) -> str:
        return "StaticCredentialProvider(<redacted>)"

    def get_credential(self) -> str:
        return self._credential


def validate_runtime_credential(value: str | None) -> str:
    """Return a usable credential or fail with one non-disclosing error."""

    if (
        not isinstance(value, str)
        or not (_MIN_CREDENTIAL_LENGTH <= len(value) <= _MAX_CREDENTIAL_LENGTH)
        or not value.isascii()
        or any(character not in _ALLOWED_CREDENTIAL_CHARACTERS for character in value)
    ):
        raise IngestionError("CREDENTIAL_UNAVAILABLE", "approved runtime credential is unavailable")
    return value


def _read_systemd_credential(path: Path) -> str:
    """Read one bounded regular credential file without following a symlink."""

    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError("credential path is not a regular file")
        with path.open("rb") as handle:
            value = handle.read(_MAX_CREDENTIAL_LENGTH + 3)
    except OSError:
        raise IngestionError(
            "CREDENTIAL_UNAVAILABLE", "approved runtime credential is unavailable"
        ) from None
    if len(value) > _MAX_CREDENTIAL_LENGTH + 2:
        raise IngestionError("CREDENTIAL_UNAVAILABLE", "approved runtime credential is unavailable")
    if value.endswith(b"\r\n"):
        value = value[:-2]
    elif value.endswith(b"\n"):
        value = value[:-1]
    try:
        decoded = value.decode("ascii")
    except UnicodeDecodeError:
        raise IngestionError(
            "CREDENTIAL_UNAVAILABLE", "approved runtime credential is unavailable"
        ) from None
    return validate_runtime_credential(decoded)


class RuntimeOddsCredentialProvider:
    """Resolve only a systemd-delivered runtime credential file.

    ``CREDENTIALS_DIRECTORY`` is a non-secret location identifier. Raw API-key
    values in the process environment are deliberately ignored. For injected
    test environments, retain only the directory identifier rather than the
    caller's potentially secret-bearing mapping.
    """

    __slots__ = ("_credential_directory_override", "_use_process_environment")

    def __init__(self, *, environment: Mapping[str, str] | None = None) -> None:
        self._use_process_environment = environment is None
        self._credential_directory_override = (
            None if environment is None else environment.get(SYSTEMD_CREDENTIAL_DIRECTORY_VARIABLE)
        )

    def __repr__(self) -> str:
        return "RuntimeOddsCredentialProvider(<runtime-secret>)"

    def _credential_directory(self) -> str | None:
        if self._use_process_environment:
            return os.environ.get(SYSTEMD_CREDENTIAL_DIRECTORY_VARIABLE)
        return self._credential_directory_override

    def get_credential(self) -> str | None:
        credential_directory = self._credential_directory()
        if credential_directory:
            return _read_systemd_credential(Path(credential_directory) / SYSTEMD_CREDENTIAL_FILE)
        return None


def credential_is_configured(provider: CredentialProvider) -> bool:
    """Return only whether one valid credential resolves, suppressing all detail."""

    try:
        value = provider.get_credential()
        validate_runtime_credential(value)
    except Exception:
        return False
    return True


def credential_configuration_hint(provider: CredentialProvider) -> bool | None:
    """Report known configuration presence without resolving secret material.

    ``None`` is deliberate for arbitrary providers: error handlers must not call
    an unknown secret-bearing boundary merely to choose error precedence.
    """

    if isinstance(provider, UnavailableCredentialProvider):
        return False
    if isinstance(provider, StaticCredentialProvider):
        return True
    if isinstance(provider, RuntimeOddsCredentialProvider):
        return bool(provider._credential_directory())
    return None
