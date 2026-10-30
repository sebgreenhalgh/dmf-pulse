"""Pinned WinCred facade and a nonsensitive current-user mutation lock."""

from __future__ import annotations

import importlib
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, cast

from dmf_pulse.credentials.service import CredentialError, Provider, VaultRecord


class _WinCred(Protocol):
    def CredRead(self, TargetName: str, Type: int, Flags: int = 0) -> dict[str, object]: ...

    def CredWrite(self, Credential: dict[str, object], Flags: int = 0) -> None: ...

    def CredDelete(self, TargetName: str, Type: int, Flags: int = 0) -> None: ...


class _ByteLock(Protocol):
    LK_NBLCK: int
    LK_UNLCK: int

    def locking(self, descriptor: int, mode: int, nbytes: int) -> None: ...


class _WindowsOpenFlags(Protocol):
    O_BINARY: int
    O_NOINHERIT: int


def _native() -> _WinCred:
    if os.name != "nt":
        raise CredentialError("CREDENTIAL_BACKEND_UNSUPPORTED")
    # Never discover arbitrary keyring plugins or plaintext fallbacks.
    core = importlib.import_module("win32ctypes.core")
    if getattr(core, "_backend", None) != "ctypes":
        raise CredentialError("CREDENTIAL_BACKEND_UNAVAILABLE")
    return cast(_WinCred, importlib.import_module("win32ctypes.pywin32.win32cred"))


class WindowsCredentialBackend:
    """Only this application's two exact targets; no credential enumeration."""

    def __init__(self, *, namespace: str = "dmf-pulse/credentials/v1") -> None:
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,160}", namespace) or ".." in namespace:
            raise ValueError("invalid credential namespace")
        self._namespace = namespace

    def __repr__(self) -> str:
        return "WindowsCredentialBackend(<current-user>)"

    def _target(self, provider: Provider) -> str:
        if provider not in {"odds", "fpl"}:
            raise CredentialError("CREDENTIAL_INVALID")
        return f"{self._namespace}/{provider}"

    def read(self, provider: Provider) -> VaultRecord | None:
        try:
            data = _native().CredRead(TargetName=self._target(provider), Type=1)
        except Exception as exc:
            if getattr(exc, "winerror", None) == 1168:
                return None
            raise
        blob, username, comment = (
            data.get("CredentialBlob"),
            data.get("UserName"),
            data.get("Comment"),
        )
        if (
            not isinstance(blob, bytes)
            or not isinstance(username, str)
            or not isinstance(comment, str)
        ):
            raise CredentialError("CREDENTIAL_CORRUPT")
        return VaultRecord(blob, username, comment)

    def write(self, provider: Provider, value: str, comment: str) -> None:
        _native().CredWrite(
            {
                "Type": 1,
                "TargetName": self._target(provider),
                # v0.2.3 converts a Python str to a UTF-16LE Windows blob.
                "CredentialBlob": value,
                "Persist": 2,
                "UserName": f"dmf-pulse.{provider}.v1",
                "Comment": comment,
            }
        )

    def delete(self, provider: Provider) -> bool:
        try:
            _native().CredDelete(TargetName=self._target(provider), Type=1)
        except Exception as exc:
            if getattr(exc, "winerror", None) == 1168:
                return False
            raise
        return True

    @contextmanager
    def mutation_lock(self) -> Iterator[None]:
        """Coordinate Pulse mutations; lock byte contains no secret material.

        The directory inherits the current user profile's Windows ACL. Python
        permission bits are not claimed to establish a Windows security boundary.
        Keep the lock file after release to avoid path/inode replacement races.
        """
        if os.name != "nt":
            raise CredentialError("CREDENTIAL_BACKEND_UNSUPPORTED")
        # Structural typing keeps Linux checks independent of Windows-only
        # stubs. Import and flag resolution remain lazy and have no fallback.
        byte_lock = cast(_ByteLock, importlib.import_module("msvcrt"))
        native_flags = cast(_WindowsOpenFlags, os)

        location = os.environ.get("LOCALAPPDATA")
        if not location or not Path(location).is_absolute():
            raise CredentialError("CREDENTIAL_BACKEND_UNAVAILABLE")
        directory = Path(location) / "dmf-pulse" / "control"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "credential-mutations.lock"
        flags = os.O_CREAT | os.O_RDWR | native_flags.O_BINARY | native_flags.O_NOINHERIT
        descriptor = os.open(path, flags, 0o600)
        locked = False
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            until = time.monotonic() + 5.0
            while not locked:
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    byte_lock.locking(descriptor, byte_lock.LK_NBLCK, 1)
                    locked = True
                except OSError:
                    if time.monotonic() >= until:
                        raise CredentialError("CREDENTIAL_LOCK_TIMEOUT") from None
                    time.sleep(0.05)
            yield
        finally:
            try:
                if locked:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    byte_lock.locking(descriptor, byte_lock.LK_UNLCK, 1)
            finally:
                os.close(descriptor)
