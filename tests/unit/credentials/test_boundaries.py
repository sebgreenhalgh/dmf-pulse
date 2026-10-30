"""Security regressions at the hidden-input and credential-bearing FPL boundary."""

from __future__ import annotations

import getpass
import traceback
import warnings
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr, ValidationError
from typer.testing import CliRunner

from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.cli import credentials as credential_cli
from dmf_pulse.cli.app import app
from dmf_pulse.credentials import windows
from dmf_pulse.credentials.service import CredentialError
from dmf_pulse.dashboard.current_sources import GuardedFplTransport
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredential,
    DirectFplCredentialProvider,
    DirectFplResource,
    DirectFplRunAttestation,
    DirectHttpResponse,
)
from tests.unit.credentials.test_service import KEY, NOW


@pytest.mark.parametrize("command", ["set-odds-key", "status", "delete-odds-key"])
@pytest.mark.parametrize("argument", [KEY, "--" + KEY])
def test_accidental_secret_argument_is_never_echoed(command, argument, monkeypatch):
    monkeypatch.setattr(credential_cli, "_service", lambda: pytest.fail("vault accessed"))
    result = CliRunner().invoke(app, ["credentials", command, argument])
    assert result.exit_code != 0 and KEY not in result.output


def test_unknown_command_is_sanitized(monkeypatch):
    monkeypatch.setattr(credential_cli, "_service", lambda: pytest.fail("vault accessed"))
    result = CliRunner().invoke(app, ["credentials", KEY])
    assert result.exit_code != 0 and KEY not in result.output


def test_getpass_echo_fallback_is_refused_before_input_or_store(monkeypatch):
    monkeypatch.setattr(credential_cli, "_service", lambda: pytest.fail("vault accessed"))

    def insecure(*args, **kwargs):
        warnings.warn("hidden input unavailable", getpass.GetPassWarning, stacklevel=1)
        pytest.fail("echo fallback continued")

    monkeypatch.setattr(credential_cli.typer, "prompt", insecure)
    result = CliRunner().invoke(app, ["credentials", "set-odds-key"])
    assert result.exit_code == 4
    assert "CREDENTIAL_SECURE_INPUT_REQUIRED" in result.output


class CredentialProvider(DirectFplCredentialProvider):
    def get(self):
        return DirectFplCredential(
            source="OS_VAULT", bearer_token=SecretStr(KEY), expires_at=NOW + timedelta(seconds=1)
        )


def client(transport, **kwargs):
    return DirectFplClient(
        DirectFplRunAttestation(attested_at=NOW),
        transport=transport,
        credential_provider=CredentialProvider(),
        sleeper=lambda _: None,
        clock=lambda: NOW,
        **kwargs,
    )


@pytest.mark.parametrize("typed", [False, True])
def test_transport_exception_message_code_and_context_are_detached(typed):
    def send(request):
        assert KEY in request.headers["X-API-Authorization"]
        try:
            raise ValueError(KEY)
        except ValueError as exc:
            if typed:
                raise IngestionError(KEY, KEY, details={"payload": KEY}) from exc
            raise RuntimeError(KEY) from exc

    value = client(SimpleNamespace(send=send))
    with pytest.raises(IngestionError) as error:
        value.fetch(DirectFplResource.MY_TEAM, entry_id=42)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert KEY not in str(error.value.as_error_object())
    assert KEY not in "".join(traceback.format_exception(error.value))
    frame = error.value.__traceback__
    while frame:
        if frame.tb_frame.f_code.co_name == "fetch":
            assert "self" not in frame.tb_frame.f_locals
        frame = frame.tb_next


@pytest.mark.parametrize(
    "code",
    ["AUTHORIZATION_REVOKED", "SOURCE_REQUEST_BUDGET_EXHAUSTED", "REFRESH_GRANT_EXPIRED", KEY],
)
def test_transport_authorization_failure_retains_only_known_reason_and_state(code):
    def send(request):
        raise AuthorizationError(code)

    value = client(SimpleNamespace(send=send))
    with pytest.raises(AuthorizationError) as error:
        value.fetch(DirectFplResource.MY_TEAM, entry_id=42)
    assert error.value.code == ("AUTHORIZATION_UNAVAILABLE" if code == KEY else code)
    assert error.value.state == ("EXPIRED" if code == "REFRESH_GRANT_EXPIRED" else "BLOCKED")
    assert error.value.__context__ is None and error.value.__cause__ is None


@pytest.mark.parametrize("retryable", [False, True])
def test_source_unavailable_preserves_accepted_boolean_retryability(retryable):
    def send(request):
        raise IngestionError("SOURCE_UNAVAILABLE", KEY, retryable=retryable)

    with pytest.raises(IngestionError) as error:
        client(SimpleNamespace(send=send)).fetch(DirectFplResource.MY_TEAM, entry_id=42)
    assert error.value.retryable is retryable and KEY not in str(error.value)


def test_expiry_during_retry_wait_prevents_second_transport():
    now = [NOW]
    sent = []

    def send(request):
        sent.append(True)
        return DirectHttpResponse(503, "application/json", b"owned")

    value = client(SimpleNamespace(send=send))
    value._clock = lambda: now[0]
    value._sleeper = lambda _: now.__setitem__(0, NOW + timedelta(seconds=1))
    with pytest.raises(IngestionError) as error:
        value.fetch(DirectFplResource.MY_TEAM, entry_id=42)
    assert error.value.code == "CREDENTIAL_EXPIRED" and sent == [True]


def test_exhausted_request_budget_refuses_before_credential_lookup():
    value = client(SimpleNamespace(send=lambda _: pytest.fail("transport reached")))
    value._request_count = value._maximum_requests
    value._credential_provider = SimpleNamespace(get=lambda: pytest.fail("credential reached"))
    with pytest.raises(IngestionError, match="budget exhausted"):
        value.fetch(DirectFplResource.MY_TEAM, entry_id=42)


def test_vault_token_cannot_omit_actual_expiry():
    with pytest.raises(ValidationError):
        DirectFplCredential(source="OS_VAULT", bearer_token=SecretStr(KEY))


def test_expiry_during_control_transaction_refuses_before_delegate_without_relookup():
    now = [NOW]
    sent = []
    lookups = []

    class Provider(CredentialProvider):
        def get(self):
            lookups.append(True)
            return super().get()

        def check_expiry(self):
            if now[0] >= NOW + timedelta(seconds=1):
                raise IngestionError("CREDENTIAL_EXPIRED", "fixed expired message")

    provider = Provider()
    guard = SimpleNamespace(
        before_send=lambda *args: now.__setitem__(0, NOW + timedelta(seconds=1)),
        before_transport=lambda: None,
    )
    transport = GuardedFplTransport(
        guard,
        SimpleNamespace(send=lambda request: sent.append(True)),
        check_expiry=provider.check_expiry,
    )
    value = client(transport)
    value._credential_provider = provider
    value._clock = lambda: now[0]
    with pytest.raises(IngestionError) as error:
        value.fetch(DirectFplResource.MY_TEAM, entry_id=42)
    assert error.value.code == "CREDENTIAL_EXPIRED" and not sent and lookups == [True]


def test_native_facade_uses_exact_targets_generic_user_scope_and_utf16(monkeypatch):
    calls = []
    native = SimpleNamespace(
        CredWrite=lambda row: calls.append(row),
        CredRead=lambda **kwargs: {
            "CredentialBlob": KEY.encode("utf-16-le"),
            "UserName": "dmf-pulse.odds.v1",
            "Comment": "owned",
        },
        CredDelete=lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(windows, "_native", lambda: native)
    backend = windows.WindowsCredentialBackend(namespace="dmf-pulse/owned-test")
    backend.write("odds", KEY, "owned")
    assert calls[0]["CredentialBlob"] == KEY
    assert calls[0]["Persist"] == 2 and calls[0]["Type"] == 1
    assert calls[0]["TargetName"] == "dmf-pulse/owned-test/odds"
    assert backend.read("odds").blob.decode("utf-16-le") == KEY
    assert backend.delete("odds")


@pytest.mark.parametrize("missing", [False, True])
def test_native_not_found_is_distinct_from_backend_failure(monkeypatch, missing):
    def fail(**kwargs):
        error = OSError("owned-backend-error")
        error.winerror = 1168 if missing else 5
        raise error

    monkeypatch.setattr(windows, "_native", lambda: SimpleNamespace(CredRead=fail, CredDelete=fail))
    backend = windows.WindowsCredentialBackend(namespace="dmf-pulse/owned-test")
    if missing:
        assert backend.read("odds") is None
        assert backend.delete("odds") is False
    else:
        with pytest.raises(OSError):
            backend.read("odds")
        with pytest.raises(OSError):
            backend.delete("odds")


def test_native_malformed_blob_is_corrupt(monkeypatch):
    monkeypatch.setattr(windows, "_native", lambda: SimpleNamespace(CredRead=lambda **kw: {}))
    with pytest.raises(CredentialError) as error:
        windows.WindowsCredentialBackend().read("odds")
    assert error.value.code == "CREDENTIAL_CORRUPT"
