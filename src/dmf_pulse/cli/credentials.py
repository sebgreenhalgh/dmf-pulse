"""Explicit hidden-prompt setup and metadata-only credential status."""

from __future__ import annotations

import getpass
import json
import warnings
from datetime import datetime
from typing import Annotated

import typer
from pydantic import SecretStr

from dmf_pulse.cli.credential_errors import CredentialCommand, CredentialGroup
from dmf_pulse.credentials.service import CredentialError, CredentialService, Provider

credentials_app = typer.Typer(
    cls=CredentialGroup,
    help="Secure current-user credential setup. No provider requests.",
    no_args_is_help=True,
)


def _service() -> CredentialService:
    return CredentialService()


def _failure(error: CredentialError) -> None:
    typer.echo(
        json.dumps(
            {"status": "FAILED", "error": {"code": error.code, "message": error.message}},
            sort_keys=True,
        )
    )
    raise typer.Exit(4)


def _set(provider: Provider, replace: bool, expires_at: str | None) -> None:
    try:
        expiry = None
        if expires_at is not None:
            try:
                expiry = datetime.fromisoformat(expires_at)
            except ValueError:
                raise CredentialError("CREDENTIAL_EXPIRY_REQUIRED") from None
        # Prompt before the mutation lock; the service rechecks under the lock.
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                text = typer.prompt(
                    "Odds API key" if provider == "odds" else "Short-lived FPL bearer token",
                    hide_input=True,
                )
        except getpass.GetPassWarning:
            raise CredentialError("CREDENTIAL_SECURE_INPUT_REQUIRED") from None
        value = SecretStr(text)
        del text
        _service().set(provider, value, replace=replace, expires_at=expiry)
        del value
        typer.echo(json.dumps({"status": "CONFIGURED", "provider": provider}, sort_keys=True))
    except CredentialError as exc:
        _failure(exc)


@credentials_app.command("set-odds-key", cls=CredentialCommand)
def set_odds_key(
    replace: Annotated[
        bool, typer.Option("--replace", help="Explicitly rotate an existing key.")
    ] = False,
) -> None:
    """Register the existing account key once using a hidden prompt."""
    _set("odds", replace, None)


@credentials_app.command("set-fpl-token", cls=CredentialCommand)
def set_fpl_token(
    expires_at: Annotated[
        str, typer.Option("--expires-at", help="Explicit actual expiry with UTC/timezone offset.")
    ],
    replace: Annotated[
        bool, typer.Option("--replace", help="Explicitly replace the short-lived token.")
    ] = False,
) -> None:
    """Store a separate token with explicit expiry; no renewal or session extraction."""
    _set("fpl", replace, expires_at)


@credentials_app.command("status", cls=CredentialCommand)
def status() -> None:
    """Reveal configuration booleans only; no value, prefix, fingerprint or account."""
    try:
        service = _service()
        providers: tuple[Provider, ...] = ("odds", "fpl")
        result = {
            provider: {"configured": service.status(provider).configured} for provider in providers
        }
        typer.echo(json.dumps(result, sort_keys=True))
    except CredentialError as exc:
        _failure(exc)


def _delete(provider: Provider) -> None:
    try:
        deleted = _service().delete(provider)
        typer.echo(
            json.dumps(
                {"status": "DELETED" if deleted else "NOT_CONFIGURED", "provider": provider},
                sort_keys=True,
            )
        )
    except CredentialError as exc:
        _failure(exc)


@credentials_app.command("delete-odds-key", cls=CredentialCommand)
def delete_odds_key() -> None:
    """Delete only the current user's exact Pulse Odds credential target."""
    _delete("odds")


@credentials_app.command("delete-fpl-token", cls=CredentialCommand)
def delete_fpl_token() -> None:
    """Delete only the separate short-lived FPL credential."""
    _delete("fpl")
