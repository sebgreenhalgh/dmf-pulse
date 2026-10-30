"""Current-user vault operations with isolated secret-bearing exception frames."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import SecretStr

Provider = Literal["odds", "fpl"]

_MESSAGES = {
    "CREDENTIAL_NOT_CONFIGURED": "Credential is not configured. Run the secure credentials setup command.",
    "CREDENTIAL_ALREADY_CONFIGURED": "Credential already exists. Use --replace to rotate it explicitly.",
    "CREDENTIAL_BACKEND_UNAVAILABLE": "Windows Credential Manager is unavailable in this user session. Use the reviewed Windows installation and the intended Windows user.",
    "CREDENTIAL_BACKEND_UNSUPPORTED": "Persistent credentials require Windows Credential Manager. Use the explicit session-only mechanism on this platform.",
    "CREDENTIAL_CORRUPT": "The stored credential is invalid. Replace it explicitly using secure setup.",
    "CREDENTIAL_EXPIRED": "The FPL bearer token has expired. Supply a fresh token through secure setup.",
    "CREDENTIAL_INVALID": "Credential input is invalid; no credential was stored.",
    "CREDENTIAL_EXPIRY_REQUIRED": "FPL storage requires an explicit future timezone-aware --expires-at value.",
    "CREDENTIAL_TOO_LARGE": "The token exceeds the Windows vault limit. Use the approved session-only or hidden-prompt mechanism; it was not truncated.",
    "CREDENTIAL_LOCK_TIMEOUT": "Another credential mutation is in progress. Retry the explicit setup operation later.",
    "CREDENTIAL_SECURE_INPUT_REQUIRED": "Secure terminal input is unavailable. Run this setup command in an interactive PowerShell terminal.",
}


class CredentialError(RuntimeError):
    """Only fixed public codes/messages, never backend exception text or values."""

    def __init__(self, code: str) -> None:
        self.code = code if code in _MESSAGES else "CREDENTIAL_BACKEND_UNAVAILABLE"
        self.message = _MESSAGES[self.code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True, repr=False)
class VaultRecord:
    blob: bytes
    username: str
    comment: str


class VaultBackend(Protocol):
    def read(self, provider: Provider) -> VaultRecord | None: ...

    def write(self, provider: Provider, value: str, comment: str) -> None: ...

    def delete(self, provider: Provider) -> bool: ...

    def mutation_lock(self) -> AbstractContextManager[None]: ...


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    configured: bool
    state: Literal["CONFIGURED", "MISSING", "EXPIRED", "UNAVAILABLE", "CORRUPT"]


@dataclass(frozen=True, slots=True, repr=False)
class ResolvedCredential:
    value: SecretStr
    expires_at: datetime | None


@dataclass(frozen=True, slots=True, repr=False)
class _Outcome:
    code: str | None = None
    resolved: ResolvedCredential | None = None
    status: CredentialStatus | None = None
    deleted: bool | None = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CredentialError("CREDENTIAL_EXPIRY_REQUIRED")
    return value.astimezone(UTC)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate metadata")
        result[key] = value
    return result


def _metadata(record: VaultRecord, provider: Provider, now: datetime) -> datetime | None:
    if record.username != f"dmf-pulse.{provider}.v1" or len(record.comment) > 256:
        raise CredentialError("CREDENTIAL_CORRUPT")
    try:
        data = json.loads(record.comment, object_pairs_hook=_unique)
        if (
            not isinstance(data, dict)
            or set(data) != {"schema_version", "provider", "expires_at"}
            or data["schema_version"] != "credential-metadata-v1"
            or data["provider"] != provider
        ):
            raise ValueError("invalid metadata")
        expiry = data["expires_at"]
        if provider == "odds":
            if expiry is not None:
                raise ValueError("unexpected expiry")
            return None
        if not isinstance(expiry, str):
            raise ValueError("missing expiry")
        expires_at = datetime.fromisoformat(expiry)
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError("naive expiry")
    except (TypeError, ValueError, KeyError):
        raise CredentialError("CREDENTIAL_CORRUPT") from None
    expires_at = expires_at.astimezone(UTC)
    if expires_at <= now:
        raise CredentialError("CREDENTIAL_EXPIRED")
    return expires_at


def _validate(value: str, provider: Provider) -> None:
    if provider == "odds":
        from dmf_pulse.ingestion.odds.credentials import validate_runtime_credential

        try:
            validate_runtime_credential(value)
        except Exception:
            raise CredentialError("CREDENTIAL_INVALID") from None
    elif (
        not value
        or len(value) > 16_384
        or not value.isascii()
        or any(ord(char) <= 32 or ord(char) > 126 for char in value)
    ):
        raise CredentialError("CREDENTIAL_INVALID")
    if len(value.encode("utf-16-le")) > 2560:
        raise CredentialError("CREDENTIAL_TOO_LARGE")


def _read_scope(
    backend: VaultBackend, provider: Provider, now: datetime, *, decode: bool
) -> _Outcome:
    """Return fixed failure state so native records/exception graphs cannot escape."""
    try:
        record = backend.read(provider)
        if record is None:
            return _Outcome(
                status=CredentialStatus(False, "MISSING"), code="CREDENTIAL_NOT_CONFIGURED"
            )
        expires_at = _metadata(record, provider, now)
        lower, upper = (32, 1024) if provider == "odds" else (2, 2560)
        if (
            not isinstance(record.blob, bytes)
            or not lower <= len(record.blob) <= upper
            or len(record.blob) % 2
        ):
            return _Outcome(code="CREDENTIAL_CORRUPT")
        if not decode:
            # CredRead copies the blob internally; status does not decode it.
            return _Outcome(status=CredentialStatus(True, "CONFIGURED"))
        value = record.blob.decode("utf-16-le", errors="strict")
        _validate(value, provider)
        return _Outcome(resolved=ResolvedCredential(SecretStr(value), expires_at))
    except CredentialError as exc:
        code = (
            "CREDENTIAL_CORRUPT"
            if exc.code in {"CREDENTIAL_INVALID", "CREDENTIAL_TOO_LARGE"}
            else exc.code
        )
    except (UnicodeError, ValueError, TypeError, AttributeError):
        code = "CREDENTIAL_CORRUPT"
    except Exception:
        code = "CREDENTIAL_BACKEND_UNAVAILABLE"
    return _Outcome(code=code)


def _write_scope(
    backend: VaultBackend,
    provider: Provider,
    value: str,
    expires_at: datetime | None,
    now: datetime,
    replace: bool,
) -> _Outcome:
    try:
        _validate(value, provider)
        if provider == "fpl":
            if expires_at is None or _utc(expires_at) <= now:
                return _Outcome(code="CREDENTIAL_EXPIRY_REQUIRED")
            expires_at = _utc(expires_at)
        elif expires_at is not None:
            return _Outcome(code="CREDENTIAL_INVALID")
        comment = json.dumps(
            {
                "schema_version": "credential-metadata-v1",
                "provider": provider,
                "expires_at": None if expires_at is None else expires_at.isoformat(),
            },
            separators=(",", ":"),
        )
        with backend.mutation_lock():
            if backend.read(provider) is not None and not replace:
                return _Outcome(code="CREDENTIAL_ALREADY_CONFIGURED")
            backend.write(provider, value, comment)
        return _Outcome()
    except CredentialError as exc:
        code = exc.code
    except Exception:
        code = "CREDENTIAL_BACKEND_UNAVAILABLE"
    return _Outcome(code=code)


def _delete_scope(backend: VaultBackend, provider: Provider) -> _Outcome:
    try:
        with backend.mutation_lock():
            return _Outcome(deleted=backend.delete(provider))
    except CredentialError as exc:
        code = exc.code
    except Exception:
        code = "CREDENTIAL_BACKEND_UNAVAILABLE"
    return _Outcome(code=code)


class CredentialService:
    """Backend is lazy, current-user scoped, and never holds a cached key."""

    def __init__(
        self,
        backend_factory: Callable[[], VaultBackend] | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._factory = backend_factory or _windows_backend
        self._clock = clock

    def __repr__(self) -> str:
        return "CredentialService(<current-user-store>)"

    def resolve(self, provider: Provider) -> ResolvedCredential:
        outcome = self._read(provider, decode=True)
        del self
        if outcome.code is not None:
            raise CredentialError(outcome.code) from None
        if outcome.resolved is None:
            raise CredentialError("CREDENTIAL_BACKEND_UNAVAILABLE")
        return outcome.resolved

    def _read(self, provider: Provider, *, decode: bool) -> _Outcome:
        try:
            return _read_scope(self._factory(), provider, _utc(self._clock()), decode=decode)
        except CredentialError as exc:
            code = exc.code
        except Exception:
            code = "CREDENTIAL_BACKEND_UNAVAILABLE"
        return _Outcome(code=code)

    def status(self, provider: Provider) -> CredentialStatus:
        outcome = self._read(provider, decode=False)
        del self
        if outcome.status is not None:
            return outcome.status
        if outcome.code == "CREDENTIAL_EXPIRED":
            return CredentialStatus(False, "EXPIRED")
        if outcome.code == "CREDENTIAL_CORRUPT":
            return CredentialStatus(False, "CORRUPT")
        raise CredentialError(outcome.code or "CREDENTIAL_BACKEND_UNAVAILABLE")

    def set(
        self,
        provider: Provider,
        secret: SecretStr,
        *,
        replace: bool = False,
        expires_at: datetime | None = None,
    ) -> None:
        outcome = self._set(provider, secret, replace=replace, expires_at=expires_at)
        del self, secret
        if outcome.code is not None:
            raise CredentialError(outcome.code) from None

    def _set(
        self, provider: Provider, secret: SecretStr, *, replace: bool, expires_at: datetime | None
    ) -> _Outcome:
        try:
            return _write_scope(
                self._factory(),
                provider,
                secret.get_secret_value(),
                expires_at,
                _utc(self._clock()),
                replace,
            )
        except CredentialError as exc:
            code = exc.code
        except Exception:
            code = "CREDENTIAL_BACKEND_UNAVAILABLE"
        return _Outcome(code=code)

    def delete(self, provider: Provider) -> bool:
        outcome = self._delete(provider)
        del self
        if outcome.code is not None:
            raise CredentialError(outcome.code) from None
        return bool(outcome.deleted)

    def _delete(self, provider: Provider) -> _Outcome:
        try:
            return _delete_scope(self._factory(), provider)
        except CredentialError as exc:
            code = exc.code
        except Exception:
            code = "CREDENTIAL_BACKEND_UNAVAILABLE"
        return _Outcome(code=code)


def _windows_backend() -> VaultBackend:
    from dmf_pulse.credentials.windows import WindowsCredentialBackend

    return WindowsCredentialBackend()
