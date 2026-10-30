"""Live route preflight blocks before either automatic credential interface."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.credentials.providers import (
    AutomaticFplCredentialProvider,
    AutomaticOddsCredentialProvider,
)
from dmf_pulse.dashboard.authorization import UsageLedger
from dmf_pulse.dashboard.current import (
    CurrentAcquisitionGuard,
    CurrentRefreshSession,
    _current_service_scope,
    resolved_profiles,
)
from dmf_pulse.dashboard.current_sources import (
    CurrentSourceFactories,
    GuardedFplTransport,
    GuardedOddsTransport,
    GuardedScoreTransport,
)
from dmf_pulse.dashboard.synthetic import DEMO_TIME
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplCredential,
    DirectFplResource,
    DirectFplRunAttestation,
    DirectHttpResponse,
    DirectUrllibTransport,
)


@pytest.fixture(autouse=True)
def owned_supplier_closure(monkeypatch):
    """These credential/ledger tests own their native-send replacement.

    Missing real supplier permission is tested without this seam in
    test_supplier_enrollment; no source eligibility is inferred here.
    """
    from dmf_pulse.operation import enrollment

    monkeypatch.setattr(enrollment, "require_fpl_route", lambda *args, **kwargs: None)


def sources(tmp_path):
    launch = CurrentRefreshSession.owned(tmp_path / "usage").prepare(1)
    time = [DEMO_TIME]
    guard = CurrentAcquisitionGuard(launch, lambda: time[0])
    profiles = resolved_profiles(launch.grant.request.source_scopes)
    factory = CurrentSourceFactories(
        guard=guard,
        owned=False,
        fpl_profile=profiles["FPL"],
        odds_profile=profiles["ODDS"],
        quota=launch.quota,
        clock=lambda: time[0],
    )
    return launch, time, guard, factory


@pytest.mark.parametrize("provider", ["FPL", "ODDS"])
@pytest.mark.parametrize("denial", ["spent", "cutoff"])
def test_denied_exact_route_never_resolves_either_automatic_provider(
    tmp_path, monkeypatch, provider, denial
):
    launch, time, guard, factory = sources(tmp_path)
    monkeypatch.setattr(
        AutomaticFplCredentialProvider, "get", lambda *_: pytest.fail("FPL credential resolved")
    )
    monkeypatch.setattr(
        AutomaticOddsCredentialProvider,
        "get_credential",
        lambda *_: pytest.fail("Odds credential resolved"),
    )
    source = next(row for row in launch.grant.request.source_scopes if row.provider == provider)
    route = next(
        row for row in source.routes if provider == "ODDS" or row.path.startswith("/api/my-team/")
    )
    if denial == "spent":
        for _ in range(route.maximum_calls):
            guard.before_send(provider, route.method, route.host, route.path)
    else:
        time[0] = launch.grant.request.information_cutoff + timedelta(microseconds=1)
    expected = (
        "SOURCE_REQUEST_BUDGET_EXHAUSTED" if denial == "spent" else "ACQUISITION_CUTOFF_PASSED"
    )
    with pytest.raises((AuthorizationError, IngestionError)):
        if provider == "FPL":
            factory.direct(DirectFplRunAttestation(attested_at=DEMO_TIME)).fetch(
                DirectFplResource.MY_TEAM, entry_id=launch.entry_id
            )
        else:
            factory.odds(lambda: time[0]).acquire(
                information_cutoff=launch.grant.request.information_cutoff,
                commence_to=launch.grant.request.information_cutoff + timedelta(days=1),
            )
    assert guard.failure is not None and guard.failure.code == expected


def test_fpl_success_preflights_without_spending_then_records_one_attempt(tmp_path, monkeypatch):
    launch, _, guard, factory = sources(tmp_path)
    seen = []

    def credential(self):
        records = list(guard._ledger.path.glob("[0-9]*.json"))
        assert not any(b'"kind":"ATTEMPT"' in p.read_bytes().replace(b" ", b"") for p in records)
        seen.append("lookup")
        return DirectFplCredential(
            source="OS_VAULT",
            bearer_token=SecretStr("owned_synthetic_fpl_token"),
            expires_at=DEMO_TIME + timedelta(hours=1),
        )

    def send(self, request):
        seen.append("send")
        return DirectHttpResponse(200, "application/json", b"{}")

    monkeypatch.setattr(AutomaticFplCredentialProvider, "get", credential)
    monkeypatch.setattr(DirectUrllibTransport, "send", send)
    value = factory.direct(DirectFplRunAttestation(attested_at=DEMO_TIME)).fetch(
        DirectFplResource.MY_TEAM, entry_id=launch.entry_id
    )
    assert value == b"{}" and seen == ["lookup", "send"]
    records = list(guard._ledger.path.glob("[0-9]*.json"))
    assert sum(b'"kind":"ATTEMPT"' in p.read_bytes().replace(b" ", b"") for p in records) == 1


@pytest.mark.parametrize(
    "code", ["CREDENTIAL_CORRUPT", "CREDENTIAL_BACKEND_UNAVAILABLE", "CREDENTIAL_NOT_CONFIGURED"]
)
def test_actual_odds_credential_refusal_keeps_safe_reason_across_client_wrapper(
    tmp_path, monkeypatch, code
):
    launch, time, guard, factory = sources(tmp_path)

    def deny(self):
        raise IngestionError(code, "owned-private-message-must-be-discarded")

    monkeypatch.setattr(AutomaticOddsCredentialProvider, "get_credential", deny)

    class Controller:
        def run(self, request):
            return factory.odds(lambda: time[0]).acquire(
                information_cutoff=launch.grant.request.information_cutoff,
                commence_to=launch.grant.request.information_cutoff + timedelta(days=1),
            )

    value = _current_service_scope(Controller(), object(), guard)
    assert value.code == code and value.state == "BLOCKED"
    assert "owned-private-message" not in repr(value)


@pytest.mark.parametrize("provider", ["FPL", "ODDS"])
def test_preflight_lock_wait_crossing_cutoff_refuses_before_key_lookup(
    tmp_path, monkeypatch, provider
):
    launch, time, guard, factory = sources(tmp_path)
    original = UsageLedger.preflight_attempt

    def waited(self, *args, **kwargs):
        original(self, *args, **kwargs)
        time[0] = launch.grant.request.information_cutoff + timedelta(microseconds=1)

    monkeypatch.setattr(UsageLedger, "preflight_attempt", waited)
    monkeypatch.setattr(
        AutomaticFplCredentialProvider, "get", lambda *_: pytest.fail("FPL key reached")
    )
    monkeypatch.setattr(
        AutomaticOddsCredentialProvider,
        "get_credential",
        lambda *_: pytest.fail("Odds key reached"),
    )
    with pytest.raises((AuthorizationError, IngestionError)):
        if provider == "FPL":
            factory.direct(DirectFplRunAttestation(attested_at=DEMO_TIME)).fetch(
                DirectFplResource.MY_TEAM, entry_id=launch.entry_id
            )
        else:
            factory.odds(lambda: time[0]).acquire(
                information_cutoff=launch.grant.request.information_cutoff,
                commence_to=launch.grant.request.information_cutoff + timedelta(days=1),
            )
    assert guard.failure.code == "ACQUISITION_CUTOFF_PASSED"


@pytest.mark.parametrize(
    "provider,wrapper",
    [
        ("FPL", GuardedFplTransport),
        ("ODDS", GuardedOddsTransport),
        ("OPENFOOTBALL", GuardedScoreTransport),
    ],
)
def test_attempt_lock_wait_crossing_cutoff_keeps_spend_and_refuses_every_delegate(
    tmp_path, monkeypatch, provider, wrapper
):
    launch, time, guard, _ = sources(tmp_path)
    source = next(row for row in launch.grant.request.source_scopes if row.provider == provider)
    route = source.routes[0]
    original = UsageLedger.attempt

    def waited(self, *args, **kwargs):
        original(self, *args, **kwargs)
        time[0] = launch.grant.request.information_cutoff + timedelta(microseconds=1)

    monkeypatch.setattr(UsageLedger, "attempt", waited)
    delegate = SimpleNamespace(send=lambda *args: pytest.fail("late provider delegate reached"))
    request = SimpleNamespace(method=route.method, host=route.host, path=route.path)
    transport = wrapper(guard, delegate)
    with pytest.raises(AuthorizationError, match="ACQUISITION_CUTOFF_PASSED"):
        transport.send(request, "placeholder") if provider == "ODDS" else transport.send(request)
    rows = list(guard._ledger.path.glob("[0-9]*.json"))
    assert sum(b'"kind":"ATTEMPT"' in p.read_bytes().replace(b" ", b"") for p in rows) == 1
