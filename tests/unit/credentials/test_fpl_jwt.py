"""Only owned in-memory JWTs and vault doubles; no current-user credentials."""

from __future__ import annotations

import base64
import getpass
import json
import traceback
import warnings
from contextlib import contextmanager
from datetime import UTC, timedelta

import pytest
from pydantic import SecretStr

from dmf_pulse.cli import credentials as cli
from dmf_pulse.credentials.jwt import fpl_jwt_expiry
from dmf_pulse.credentials.service import CredentialError, CredentialService
from tests.unit.credentials.test_service import NOW, MemoryVault

MINIMUM = 1200
MAXIMUM = 86400


def segment(value):
    body = value if isinstance(value, bytes) else json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(body).decode().rstrip("=")


def token(*, expiry=None, header=None, claims=None, signature=b"owned test signature"):
    payload = {"exp": int((NOW + timedelta(hours=1)).timestamp()) if expiry is None else expiry}
    if claims:
        payload.update(claims)
    return ".".join((segment(header or {"alg": "HS256"}), segment(payload), segment(signature)))


def parse(value, **kwargs):
    return fpl_jwt_expiry(
        SecretStr(value),
        now=NOW,
        minimum_remaining_seconds=MINIMUM,
        maximum_remaining_seconds=MAXIMUM,
        **kwargs,
    )


def test_expiry_is_exact_utc_and_signature_is_not_verified():
    expiry = NOW + timedelta(hours=1)
    first = token(signature=b"owned first signature")
    second = token(signature=b"different owned signature")
    assert first != second and parse(first) == parse(second) == expiry
    assert parse(first).tzinfo == UTC


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b"[]",
        b'"owned"',
        b'{"exp":true}',
        b'{"exp":null}',
        b'{"exp":"123"}',
        b'{"exp":1.5}',
        b'{"exp":NaN}',
        b'{"exp":Infinity}',
        b'{"exp":1,"exp":2}',
        b'{"exp":1,"\\u0065xp":2}',
        b'{"exp":1,"nested":{"x":1,"x":2}}',
        b"\xff",
        b'{"exp":',
        b"\xff\xfe{\x00}\x00",
    ],
)
def test_bad_claims_never_escape_decoder_errors(payload):
    value = ".".join((segment({"alg": "HS256"}), segment(payload), segment(b"owned")))
    with pytest.raises(CredentialError) as error:
        parse(value)
    assert error.value.code == "CREDENTIAL_JWT_INVALID"
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert value not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize(
    "header",
    [
        b"{}",
        b"[]",
        b'{"alg":null}',
        b'{"alg":"none"}',
        b'{"alg":"HS256","alg":"HS256"}',
        b"not JSON",
    ],
)
def test_invalid_compact_header(header):
    value = ".".join(
        (segment(header), segment({"exp": int(NOW.timestamp()) + 3600}), segment(b"owned"))
    )
    with pytest.raises(CredentialError) as error:
        parse(value)
    assert error.value.code == "CREDENTIAL_JWT_INVALID"


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "empty", "padding", "alphabet", "padbits"]
)
def test_compact_segments_are_canonical_urlsafe_without_padding(mutation):
    parts = token().split(".")
    if mutation == "missing":
        parts.pop()
    elif mutation == "extra":
        parts.append("owned")
    elif mutation == "empty":
        parts[2] = ""
    elif mutation == "padding":
        parts[0] += "="
    elif mutation == "alphabet":
        parts[2] = "/+"
    else:
        parts[2] = "Zh"  # Decodes but has nonzero unused bits; canonical form is Zg.
    with pytest.raises(CredentialError):
        parse(".".join(parts))


@pytest.mark.parametrize(
    ("seconds", "code"),
    [
        (-1, "CREDENTIAL_EXPIRED"),
        (0, "CREDENTIAL_EXPIRED"),
        (1199, "CREDENTIAL_LIFETIME_INSUFFICIENT"),
        (86401, "CREDENTIAL_LIFETIME_EXCESSIVE"),
    ],
)
def test_actual_expiry_and_accepted_lifetime_bounds(seconds, code):
    with pytest.raises(CredentialError) as error:
        parse(token(expiry=int(NOW.timestamp()) + seconds))
    assert error.value.code == code


@pytest.mark.parametrize("seconds", [1200, 86400])
def test_lifetime_boundaries_are_inclusive(seconds):
    assert parse(token(expiry=int(NOW.timestamp()) + seconds)) == NOW + timedelta(seconds=seconds)


@pytest.mark.parametrize("claim", ["iat", "nbf"])
def test_future_or_noninteger_optional_time_claims_refuse(claim):
    for value in (True, "owned", int(NOW.timestamp()) + 1):
        with pytest.raises(CredentialError):
            parse(token(claims={claim: value}))


@pytest.mark.parametrize("expiry", [10**50, -(10**50)])
def test_unrepresentable_expiry_refuses_without_overflow_graph(expiry):
    with pytest.raises(CredentialError) as error:
        parse(token(expiry=expiry))
    assert error.value.code == "CREDENTIAL_JWT_INVALID"


@pytest.mark.parametrize(
    ("minimum", "maximum"), [(True, 86400), (0, 86400), (-1, 86400), (1200, 1199), (1200, True)]
)
def test_invalid_policy_never_opens_the_store(minimum, maximum):
    service = CredentialService(lambda: pytest.fail("vault accessed"), clock=lambda: NOW)
    with pytest.raises(CredentialError) as error:
        service.set_fpl_jwt(
            SecretStr(token()), minimum_remaining_seconds=minimum, maximum_remaining_seconds=maximum
        )
    assert error.value.code == "CREDENTIAL_POLICY_INVALID"


def test_blind_write_uses_actual_expiry_and_existing_fresh_v2_metadata():
    class NoRead(MemoryVault):
        def read(self, provider):
            pytest.fail("JWT registration read an old credential")

    backend = NoRead()
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    actual = token()
    expires = service.set_fpl_jwt(
        SecretStr(actual), minimum_remaining_seconds=MINIMUM, maximum_remaining_seconds=MAXIMUM
    )
    assert expires == NOW + timedelta(hours=1)
    assert backend.events == [("lock", None), ("write", "fpl")]
    record = backend.rows["fpl"]
    assert record.username == "dmf-pulse.fpl.v2"
    metadata = json.loads(record.comment)
    assert metadata == {
        "schema_version": "credential-metadata-v2",
        "provider": "fpl",
        "expires_at": expires.isoformat(),
        "registered_at": NOW.isoformat(),
        "fresh_issuance_attested": True,
    }
    assert "alg" not in metadata and "exp" not in metadata
    assert record.blob.decode("utf-16-le") == actual


@pytest.mark.parametrize("during_write", [False, True])
def test_minimum_lifetime_is_rechecked_inside_lock_and_after_write(during_write):
    clock = [NOW]

    class Delayed(MemoryVault):
        @contextmanager
        def mutation_lock(self):
            if not during_write:
                clock[0] += timedelta(seconds=2)
            yield

        def write(self, *args):
            super().write(*args)
            if during_write:
                clock[0] += timedelta(seconds=2)

    backend = Delayed()
    service = CredentialService(lambda: backend, clock=lambda: clock[0])
    with pytest.raises(CredentialError) as error:
        service.set_fpl_jwt(
            SecretStr(token(expiry=int(NOW.timestamp()) + 1201)),
            minimum_remaining_seconds=MINIMUM,
            maximum_remaining_seconds=MAXIMUM,
        )
    assert error.value.code == "CREDENTIAL_LIFETIME_INSUFFICIENT" and backend.rows == {}
    assert all(event[0] != "read" for event in backend.events)


def test_public_failure_drops_secret_exception_context_and_locals():
    actual = token()

    class Broken(MemoryVault):
        def write(self, *args):
            raise RuntimeError(actual)

    service = CredentialService(Broken, clock=lambda: NOW)
    with pytest.raises(CredentialError) as error:
        service.set_fpl_jwt(
            SecretStr(actual), minimum_remaining_seconds=MINIMUM, maximum_remaining_seconds=MAXIMUM
        )
    assert error.value.code == "CREDENTIAL_BACKEND_UNAVAILABLE"
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert actual not in "".join(traceback.format_exception(error.value))
    frame = error.value.__traceback__
    while frame:
        if frame.tb_frame.f_code.co_name in {"set_fpl_jwt", "fpl_jwt_expiry"}:
            assert "secret" not in frame.tb_frame.f_locals and "self" not in frame.tb_frame.f_locals
        frame = frame.tb_next


def test_hidden_prompt_is_one_paste_and_returns_only_expiry(monkeypatch, capsys):
    backend = MemoryVault()
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    actual = token()
    calls = []

    def prompt(*args, **kwargs):
        calls.append(kwargs)
        return actual

    monkeypatch.setattr(cli.typer, "prompt", prompt)
    assert cli.prompt_fpl_jwt(
        minimum_remaining_seconds=MINIMUM, maximum_remaining_seconds=MAXIMUM, service=service
    ) == NOW + timedelta(hours=1)
    assert calls == [{"hide_input": True}]
    assert actual not in capsys.readouterr().out
    assert all(event[0] != "read" for event in backend.events)


def test_hidden_prompt_refuses_echo_fallback_without_store(monkeypatch):
    def insecure(*args, **kwargs):
        warnings.warn("owned insecure terminal", getpass.GetPassWarning, stacklevel=1)
        pytest.fail("echo fallback continued")

    monkeypatch.setattr(cli.typer, "prompt", insecure)
    monkeypatch.setattr(cli, "_service", lambda: pytest.fail("store reached"))
    with pytest.raises(CredentialError) as error:
        cli.prompt_fpl_jwt(minimum_remaining_seconds=MINIMUM, maximum_remaining_seconds=MAXIMUM)
    assert error.value.code == "CREDENTIAL_SECURE_INPUT_REQUIRED"


def test_hidden_prompt_rejects_policy_before_asking_for_input(monkeypatch):
    monkeypatch.setattr(cli.typer, "prompt", lambda *args, **kwargs: pytest.fail("prompted"))
    with pytest.raises(CredentialError) as error:
        cli.prompt_fpl_jwt(minimum_remaining_seconds=0, maximum_remaining_seconds=MAXIMUM)
    assert error.value.code == "CREDENTIAL_POLICY_INVALID"


def test_configured_fresh_status_does_not_decode_the_stored_jwt(monkeypatch):
    backend = MemoryVault()
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    expiry = service.set_fpl_jwt(
        SecretStr(token()), minimum_remaining_seconds=MINIMUM, maximum_remaining_seconds=MAXIMUM
    )
    monkeypatch.setattr(
        "dmf_pulse.credentials.jwt._expiry_scope", lambda *args: pytest.fail("stored JWT decoded")
    )
    metadata = service.status("fpl")
    assert metadata.configured and metadata.expires_at == expiry
    assert backend.events[-1] == ("read", "fpl")


def test_vault_size_limit_precedes_backend_access_without_truncation():
    service = CredentialService(lambda: pytest.fail("backend accessed"), clock=lambda: NOW)
    value = token(claims={"owned_test_padding": "x" * 1280})
    with pytest.raises(CredentialError) as error:
        service.set_fpl_jwt(
            SecretStr(value), minimum_remaining_seconds=MINIMUM, maximum_remaining_seconds=MAXIMUM
        )
    assert error.value.code == "CREDENTIAL_TOO_LARGE"


def test_maximum_lifetime_is_rechecked_under_the_lock():
    clock = [NOW]

    class ClockChanged(MemoryVault):
        @contextmanager
        def mutation_lock(self):
            clock[0] -= timedelta(seconds=1)
            yield

    backend = ClockChanged()
    service = CredentialService(lambda: backend, clock=lambda: clock[0])
    with pytest.raises(CredentialError) as error:
        service.set_fpl_jwt(
            SecretStr(token(expiry=int(NOW.timestamp()) + MAXIMUM)),
            minimum_remaining_seconds=MINIMUM,
            maximum_remaining_seconds=MAXIMUM,
        )
    assert error.value.code == "CREDENTIAL_LIFETIME_EXCESSIVE" and backend.rows == {}
