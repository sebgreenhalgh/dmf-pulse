"""Fresh replacement never reads legacy native or ambient FPL credentials."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from dmf_pulse.cli import credentials as cli
from dmf_pulse.credentials import windows
from dmf_pulse.credentials.providers import AutomaticFplCredentialProvider
from dmf_pulse.credentials.service import CredentialError, CredentialService, VaultRecord
from tests.unit.credentials.test_service import KEY, NOW, MemoryVault


@pytest.mark.parametrize("replace", [False, True])
def test_fresh_setup_is_blind_including_first_registration(replace):
    class NoRead(MemoryVault):
        def read(self, provider):
            pytest.fail("a replacement must not read any old blob")

    backend = NoRead()
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    service.set(
        "fpl",
        SecretStr(KEY),
        replace=replace,
        expires_at=NOW + timedelta(minutes=5),
        fresh_issuance_attested=True,
    )
    assert backend.events == [("lock", None), ("write", "fpl")]
    metadata = json.loads(backend.rows["fpl"].comment)
    assert metadata["schema_version"] == "credential-metadata-v2"
    assert metadata["fresh_issuance_attested"] is True
    assert metadata["registered_at"] == NOW.isoformat()


def test_missing_fresh_attestation_never_reads_or_writes():
    backend = MemoryVault()
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    with pytest.raises(CredentialError) as error:
        service.set("fpl", SecretStr(KEY), expires_at=NOW + timedelta(minutes=5))
    assert error.value.code == "CREDENTIAL_FRESH_ISSUANCE_REQUIRED"
    assert backend.events == []


def test_expiry_while_waiting_for_lock_refuses_before_storage():
    clock = [NOW]

    class DelayedLock(MemoryVault):
        @contextmanager
        def mutation_lock(self):
            clock[0] = NOW + timedelta(seconds=2)
            yield

    backend = DelayedLock()
    service = CredentialService(lambda: backend, clock=lambda: clock[0])
    with pytest.raises(CredentialError) as error:
        service.set(
            "fpl",
            SecretStr(KEY),
            expires_at=NOW + timedelta(seconds=1),
            fresh_issuance_attested=True,
        )
    assert error.value.code == "CREDENTIAL_EXPIRY_REQUIRED"
    assert backend.events == [] and backend.rows == {}


def test_registration_time_is_observed_inside_lock():
    clock = [NOW]

    class DelayedLock(MemoryVault):
        @contextmanager
        def mutation_lock(self):
            clock[0] = NOW + timedelta(seconds=2)
            yield

    backend = DelayedLock()
    service = CredentialService(lambda: backend, clock=lambda: clock[0])
    service.set(
        "fpl", SecretStr(KEY), expires_at=NOW + timedelta(minutes=5), fresh_issuance_attested=True
    )
    assert json.loads(backend.rows["fpl"].comment)["registered_at"] == clock[0].isoformat()


def test_expiry_during_native_write_does_not_report_success_or_retain_token():
    clock = [NOW]

    class DelayedWrite(MemoryVault):
        def write(self, *args):
            super().write(*args)
            clock[0] = NOW + timedelta(minutes=5)

    backend = DelayedWrite()
    service = CredentialService(lambda: backend, clock=lambda: clock[0])
    with pytest.raises(CredentialError) as error:
        service.set(
            "fpl",
            SecretStr(KEY),
            expires_at=NOW + timedelta(minutes=5),
            fresh_issuance_attested=True,
        )
    assert error.value.code == "CREDENTIAL_EXPIRED" and backend.rows == {}
    assert all(event[0] != "read" for event in backend.events)


def test_native_targets_preserve_odds_and_exclude_legacy_fpl(monkeypatch):
    calls = []

    def read(**kwargs):
        target = kwargs["TargetName"]
        assert target != "dmf-pulse/credentials/v1/fpl"
        calls.append(("read", target))
        error = OSError("owned missing")
        error.winerror = 1168
        raise error

    monkeypatch.setattr(windows, "_native", lambda: SimpleNamespace(CredRead=read))
    backend = windows.WindowsCredentialBackend()
    assert backend._target("odds") == "dmf-pulse/credentials/v1/odds"
    assert backend._target("fpl") == "dmf-pulse/credentials/v2/fpl"
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    assert service.status("fpl").state == "MISSING"
    assert calls == [("read", "dmf-pulse/credentials/v2/fpl")]


def test_vault_pinned_provider_never_reads_environment_selection_or_old_token():
    class ForbiddenEnvironment(dict):
        def get(self, *args):
            pytest.fail("private pilot consulted ambient credential environment")

    backend = MemoryVault()
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    service.set(
        "fpl",
        SecretStr(KEY),
        expires_at=NOW + timedelta(minutes=5),
        fresh_issuance_attested=True,
    )
    provider = AutomaticFplCredentialProvider(
        service_factory=lambda: service,
        platform="nt",
        environment=ForbiddenEnvironment(),
        vault_only=True,
        clock=lambda: NOW,
    )
    credential = provider.get()
    assert credential.source == "OS_VAULT"
    assert credential.credential_generation == "FPL_FRESH_V2"
    assert credential.registered_at == NOW


def test_fresh_expiry_status_retains_metadata_without_decoding(monkeypatch):
    backend = MemoryVault()
    expiry = NOW + timedelta(minutes=5)
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    service.set("fpl", SecretStr(KEY), expires_at=expiry, fresh_issuance_attested=True)
    monkeypatch.setattr(
        "dmf_pulse.credentials.service._validate", lambda *_: pytest.fail("decoded")
    )
    later = CredentialService(lambda: backend, clock=lambda: expiry)
    status = later.status("fpl")
    assert status.state == "EXPIRED" and not status.configured
    assert status.expires_at == expiry and status.registered_at == NOW


def test_legacy_metadata_in_fresh_slot_is_rejected_before_value_validation(monkeypatch):
    backend = MemoryVault()
    backend.rows["fpl"] = VaultRecord(
        b"owned-not-decoded",
        "dmf-pulse.fpl.v1",
        '{"schema_version":"credential-metadata-v1","provider":"fpl","expires_at":null}',
    )
    monkeypatch.setattr(
        "dmf_pulse.credentials.service._validate", lambda *_: pytest.fail("decoded")
    )
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    with pytest.raises(CredentialError) as error:
        service.resolve("fpl")
    assert error.value.code == "CREDENTIAL_CORRUPT"


def test_cli_requires_fresh_attestation_before_prompt_or_vault(monkeypatch):
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **kw: pytest.fail("prompt reached"))
    monkeypatch.setattr(cli, "_service", lambda: pytest.fail("vault reached"))
    result = CliRunner().invoke(
        cli.credentials_app, ["set-fpl-token", "--expires-at", "2030-01-01T00:00:00Z"]
    )
    assert result.exit_code == 4
    assert "CREDENTIAL_FRESH_ISSUANCE_REQUIRED" in result.output


def test_fresh_cli_setup_and_expiry_report_do_not_expose_value(monkeypatch):
    backend = MemoryVault()
    service = CredentialService(lambda: backend, clock=lambda: NOW)
    monkeypatch.setattr(cli, "_service", lambda: service)
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **kw: KEY)
    runner = CliRunner()
    result = runner.invoke(
        cli.credentials_app,
        [
            "set-fpl-token",
            "--fresh-issued",
            "--replace",
            "--expires-at",
            (NOW + timedelta(minutes=5)).isoformat(),
        ],
    )
    assert result.exit_code == 0 and KEY not in result.output
    assert all(event[0] != "read" for event in backend.events)
    status = runner.invoke(cli.credentials_app, ["fpl-status"])
    report = json.loads(status.stdout)
    assert report["generation"] == "FPL_FRESH_V2"
    assert report["expires_at"] == (NOW + timedelta(minutes=5)).isoformat()
    assert report["provider_authentication_verified"] is False
    assert KEY not in status.output


@pytest.mark.parametrize("command", ["set-odds-key", "set-fpl-token"])
def test_cli_failed_setup_unwinds_secret_frames_before_public_exit(monkeypatch, command):
    class RejectedStore:
        def set(self, *args, **kwargs):
            raise CredentialError("CREDENTIAL_BACKEND_UNAVAILABLE")

    monkeypatch.setattr(cli, "_service", RejectedStore)
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **kw: KEY)
    args = [command]
    if command == "set-fpl-token":
        args += ["--fresh-issued", "--expires-at", "2030-01-01T00:00:00Z"]
    result = CliRunner().invoke(cli.credentials_app, args)
    assert result.exit_code == 4 and KEY not in result.output
    seen = set()

    def inspect(error):
        if error is None or id(error) in seen:
            return
        seen.add(id(error))
        tb = error.__traceback__
        while tb:
            if "dmf_pulse" in tb.tb_frame.f_code.co_filename:
                for value in tb.tb_frame.f_locals.values():
                    assert not (isinstance(value, str) and KEY in value)
                    assert not (isinstance(value, SecretStr) and value.get_secret_value() == KEY)
            tb = tb.tb_next
        inspect(error.__context__)
        inspect(error.__cause__)

    inspect(result.exception)
