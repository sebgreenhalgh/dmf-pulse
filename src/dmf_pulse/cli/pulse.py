"""One-command private current recommendation CLI."""

from __future__ import annotations

import getpass
import hashlib
import importlib.metadata
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import SecretStr

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import (
    DIRECT_FPL_TOKEN_ENV,
    DirectFplClient,
    DirectFplCredential,
    DirectFplCredentialProvider,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.one_command import (
    OneCommandRequest,
    PrivateV1OneCommandService,
)

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class _PromptingCredentialProvider(DirectFplCredentialProvider):
    def get(self) -> DirectFplCredential:
        try:
            return super().get()
        except IngestionError as exc:
            if exc.code != "CREDENTIAL_MISSING" or not sys.stdin.isatty():
                raise
        token = getpass.getpass("Short-lived FPL bearer token: ")
        if not token:
            raise IngestionError("CREDENTIAL_MISSING", f"{DIRECT_FPL_TOKEN_ENV} is missing.")
        try:
            return DirectFplCredential(source="HIDDEN_PROMPT", bearer_token=SecretStr(token))
        except ValueError:
            raise IngestionError("CREDENTIAL_INVALID", "FPL bearer token is invalid.") from None


def _git_head(start: Path) -> str | None:
    try:
        for directory in (start, *start.parents):
            marker = directory / ".git"
            if marker.is_file():
                text = marker.read_text(encoding="utf-8").strip()
                if not text.startswith("gitdir: "):
                    continue
                git_dir = (directory / text.removeprefix("gitdir: ")).resolve()
            elif marker.is_dir():
                git_dir = marker
            else:
                continue
            head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
            if _SHA_PATTERN.fullmatch(head):
                return head
            if head.startswith("ref: "):
                ref_path = git_dir / head.removeprefix("ref: ")
                if ref_path.is_file():
                    value = ref_path.read_text(encoding="ascii").strip()
                    if _SHA_PATTERN.fullmatch(value):
                        return value
    except (OSError, UnicodeError):
        return None
    return None


def _installed_content_sha() -> str:
    """Fallback wheel-content identity when installed outside a Git checkout."""

    digest = hashlib.sha1(usedforsecurity=False)
    distribution = importlib.metadata.distribution("dmf-pulse")
    candidates = tuple(
        sorted(
            str(item)
            for item in distribution.files or ()
            if str(item).replace("\\", "/").startswith("dmf_pulse/")
            and not str(item).endswith((".pyc", "RECORD"))
        )
    )
    if not candidates:
        raise PrivateV1Error("CODE_IDENTITY_UNAVAILABLE", "installed code identity is unavailable")
    for relative in candidates:
        path = Path(str(distribution.locate_file(relative)))
        if not path.is_file():
            continue
        digest.update(relative.replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _code_sha() -> str:
    configured = os.environ.get("DMF_CODE_SHA", "").strip().casefold()
    if configured:
        if _SHA_PATTERN.fullmatch(configured) is None:
            raise PrivateV1Error("CODE_IDENTITY_INVALID", "DMF_CODE_SHA is invalid")
        return configured
    return _git_head(Path.cwd()) or _installed_content_sha()


def pulse_command(
    entry_id: Annotated[int, typer.Option("--entry-id", min=1, help="Private FPL entry ID.")],
) -> None:
    """Produce one current private FPL recommendation without retaining provider bodies."""

    try:
        if not os.environ.get("THE_ODDS_API_KEY", "").strip():
            raise PrivateV1Error("CREDENTIAL_UNAVAILABLE", "THE_ODDS_API_KEY is missing.")
        run_at = datetime.now(UTC)
        credential_provider = _PromptingCredentialProvider()
        service = PrivateV1OneCommandService(
            direct_client_factory=lambda attestation: DirectFplClient(
                attestation, credential_provider=credential_provider
            )
        )
        result = service.run(
            OneCommandRequest(entry_id=entry_id, code_sha=_code_sha(), run_at=run_at)
        )
        typer.echo(result.report)
    except PrivateV1Error as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(2) from exc


__all__ = ["pulse_command"]
