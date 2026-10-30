from __future__ import annotations

import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from dmf_pulse.cli import credentials as cli
from dmf_pulse.credentials.providers import (
    AutomaticFplCredentialProvider,
    AutomaticOddsCredentialProvider,
)
from dmf_pulse.credentials.service import CredentialError, CredentialService, VaultRecord

NOW = datetime(2026, 10, 30, 1, tzinfo=UTC)
KEY = "owned_synthetic_credential"


class MemoryVault:
    def __init__(self):
        self.rows = {}
        self.events = []
        self.lock = threading.RLock()

    def __repr__(self):
        return "MemoryVault(<owned-test>)"

    def read(self, provider):
        self.events.append(("read", provider))
        return self.rows.get(provider)

    def write(self, provider, value, comment):
        self.events.append(("write", provider))
        self.rows[provider] = VaultRecord(
            value.encode("utf-16-le"), f"dmf-pulse.{provider}.v1", comment
        )

    def delete(self, provider):
        self.events.append(("delete", provider))
        return self.rows.pop(provider, None) is not None

    @contextmanager
    def mutation_lock(self):
        with self.lock:
            self.events.append(("lock", None))
            yield


@pytest.fixture
def setup_service():
    backend = MemoryVault()
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    return backend, service


def test_setup_persists_to_new_provider_rotation_and_delete(setup_service):
    backend, first = setup_service
    assert not backend.events
    first.set("odds", SecretStr(KEY))
    second = CredentialService(lambda: backend, clock=lambda: NOW)
    assert second.resolve("odds").value.get_secret_value() == KEY
    with pytest.raises(CredentialError, match="already exists"):
        second.set("odds", SecretStr(KEY + "_replacement"))
    second.set("odds", SecretStr(KEY + "_replacement"), replace=True)
    assert first.resolve("odds").value.get_secret_value() == KEY + "_replacement"
    assert second.delete("odds") is True
    assert second.delete("odds") is False
    assert not first.status("odds").configured
    with pytest.raises(CredentialError) as error:
        first.resolve("odds")
    assert error.value.code == "CREDENTIAL_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "value", ["", "short", " " + KEY, KEY + "\n", "a" * 513, "é" * 25, KEY + "/"]
)
def test_invalid_input_never_writes(setup_service, value):
    backend, service = setup_service
    with pytest.raises(CredentialError) as error:
        service.set("odds", SecretStr(value))
    assert error.value.code == "CREDENTIAL_INVALID"
    assert not any(event[0] == "write" for event in backend.events)


@pytest.mark.parametrize(
    "mutation",
    [
        "odd",
        "short",
        "oversize",
        "wrong_user",
        "bad_comment",
        "wrong_provider",
        "duplicate",
        "invalid_value",
    ],
)
def test_corrupt_store_fails_closed(setup_service, mutation):
    backend, service = setup_service
    service.set("odds", SecretStr(KEY))
    record = backend.rows["odds"]
    blob, username, comment = record.blob, record.username, record.comment
    if mutation == "odd":
        blob = b"a"
    if mutation == "short":
        blob = b"aa"
    if mutation == "oversize":
        blob = b"aa" * 513
    if mutation == "wrong_user":
        username = "another-app"
    if mutation == "bad_comment":
        comment = "not-json"
    if mutation == "wrong_provider":
        comment = comment.replace('"odds"', '"fpl"')
    if mutation == "duplicate":
        comment = '{"provider":"odds",' + comment[1:]
    if mutation == "invalid_value":
        blob = (KEY + " ").encode("utf-16-le")
    backend.rows["odds"] = VaultRecord(blob, username, comment)
    with pytest.raises(CredentialError):
        service.resolve("odds")


def test_status_copies_record_without_decoding_key(setup_service, monkeypatch):
    backend, service = setup_service
    service.set("odds", SecretStr(KEY))
    monkeypatch.setattr(
        "dmf_pulse.credentials.service._validate", lambda *_: pytest.fail("value decoded")
    )
    assert service.status("odds").configured
    assert backend.events[-1] == ("read", "odds")


@pytest.mark.parametrize(
    "expiry", [None, NOW, NOW - timedelta(seconds=1), NOW.replace(tzinfo=None)]
)
def test_fpl_requires_explicit_future_aware_expiry(setup_service, expiry):
    backend, service = setup_service
    with pytest.raises(CredentialError) as error:
        service.set("fpl", SecretStr(KEY), expires_at=expiry)
    assert error.value.code == "CREDENTIAL_EXPIRY_REQUIRED"
    assert "fpl" not in backend.rows


def test_fpl_separate_expiry_and_size_limit(setup_service):
    backend, service = setup_service
    expiry = NOW + timedelta(minutes=5)
    service.set("odds", SecretStr(KEY))
    service.set("fpl", SecretStr(KEY), expires_at=expiry)
    later = CredentialService(lambda: backend, clock=lambda: expiry)
    assert later.status("fpl").state == "EXPIRED"
    with pytest.raises(CredentialError) as error:
        later.resolve("fpl")
    assert error.value.code == "CREDENTIAL_EXPIRED"
    assert later.resolve("odds").value.get_secret_value() == KEY
    with pytest.raises(CredentialError) as error:
        service.set("fpl", SecretStr("t" * 1281), replace=True, expires_at=expiry)
    assert error.value.code == "CREDENTIAL_TOO_LARGE"


def test_concurrent_create_only_has_one_winner(setup_service):
    backend, service = setup_service

    def install(index):
        try:
            service.set("odds", SecretStr(KEY + str(index)))
            return "CREATED"
        except CredentialError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(install, range(16)))
    assert results.count("CREATED") == 1
    assert results.count("CREDENTIAL_ALREADY_CONFIGURED") == 15
    assert sum(event[0] == "write" for event in backend.events) == 1


def test_wrong_user_store_cannot_resolve_other_user(setup_service):
    _, service = setup_service
    service.set("odds", SecretStr(KEY))
    other = CredentialService(MemoryVault, clock=lambda: NOW)
    with pytest.raises(CredentialError) as error:
        other.resolve("odds")
    assert error.value.code == "CREDENTIAL_NOT_CONFIGURED"


@pytest.mark.parametrize("operation", ["resolve", "status", "set", "delete"])
def test_backend_exception_graph_never_escapes(operation):
    class Broken(MemoryVault):
        def read(self, _):
            try:
                raise ValueError(KEY)
            except ValueError as exc:
                raise RuntimeError(KEY) from exc

    backend = Broken()
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    with pytest.raises(CredentialError) as error:
        if operation == "set":
            service.set("odds", SecretStr(KEY))
        elif operation == "delete":
            backend.delete = backend.read
            service.delete("odds")
        else:
            getattr(service, operation)("odds")
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert KEY not in "".join(traceback.format_exception(error.value))
    assert KEY not in repr(error.value.args)


def test_auto_constructor_does_not_access_store_or_environment():
    class Forbidden(dict):
        def get(self, *_):
            pytest.fail("environment read before authorized lookup")

    provider = AutomaticOddsCredentialProvider(
        service_factory=lambda: pytest.fail("vault reached"), platform="nt", environment=Forbidden()
    )
    assert KEY not in repr(provider)


def test_windows_vault_is_normal_env_requires_explicit_selection(setup_service):
    _, service = setup_service
    service.set("odds", SecretStr(KEY))
    provider = AutomaticOddsCredentialProvider(
        service_factory=lambda: service,
        platform="nt",
        environment={"THE_ODDS_API_KEY": KEY + "_environment"},
    )
    assert provider.get_credential() == KEY
    explicit = AutomaticOddsCredentialProvider(
        service_factory=lambda: pytest.fail("vault reached"),
        platform="nt",
        environment={"DMF_ODDS_CREDENTIAL_SOURCE": "environment", "THE_ODDS_API_KEY": KEY},
    )
    assert explicit.get_credential() == KEY
    missing = AutomaticOddsCredentialProvider(
        service_factory=lambda: CredentialService(MemoryVault, clock=lambda: NOW),
        platform="nt",
        environment={"THE_ODDS_API_KEY": KEY},
    )
    with pytest.raises(Exception) as error:
        missing.get_credential()
    assert error.value.code == "CREDENTIAL_NOT_CONFIGURED"


def test_cli_hidden_setup_status_rotation_and_delete(setup_service, monkeypatch):
    _, service = setup_service
    monkeypatch.setattr(cli, "_service", lambda: service)
    runner = CliRunner()
    result = runner.invoke(cli.credentials_app, ["set-odds-key"], input=KEY + "\n")
    assert result.exit_code == 0 and KEY not in result.output
    assert json.loads(runner.invoke(cli.credentials_app, ["status"]).stdout) == {
        "odds": {"configured": True},
        "fpl": {"configured": False},
    }
    result = runner.invoke(cli.credentials_app, ["set-odds-key", "--replace"], input=KEY + "\n")
    assert result.exit_code == 0 and KEY not in result.output
    assert runner.invoke(cli.credentials_app, ["delete-odds-key"]).exit_code == 0
    assert not service.status("odds").configured


def test_auto_fpl_expiry_is_separate(setup_service):
    _, service = setup_service
    expiry = NOW + timedelta(seconds=1)
    service.set("fpl", SecretStr(KEY), expires_at=expiry)
    provider = AutomaticFplCredentialProvider(
        service_factory=lambda: service, platform="nt", environment={}, clock=lambda: expiry
    )
    credential = provider.get()
    assert credential.expires_at == expiry and credential.source == "OS_VAULT"
    with pytest.raises(Exception) as error:
        provider.check_expiry()
    assert error.value.code == "CREDENTIAL_EXPIRED"
