"""Offline L1 authority, consumption, retry and safe-output boundaries."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from dmf_pulse.football_events.team_strength_adapter import _source_assessment
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import DirectFplCredentialProvider, DirectHttpResponse
from dmf_pulse.ingestion.odds.client import OddsClient, OddsHttpResponse
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.credentials import (
    EnvironmentOddsCredentialProvider,
    StaticCredentialProvider,
)
from dmf_pulse.ingestion.openfootball.team_strength_current import CurrentTeamStrengthReadiness
from dmf_pulse.ingestion.openfootball.team_strength_data import seal
from dmf_pulse.private_v1 import team_strength_live as live
from dmf_pulse.private_v1 import team_strength_live_authority as authority
from dmf_pulse.private_v1.team_strength_live_network import OneShotNetworkGate, fpl_endpoint
from tests.unit.private_v1.team_strength_shadow_support import STAMP, synthetic_strength

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def archived_l1_authority(monkeypatch):
    """Historical synthetic L1 behaviour only; the actual approval is consumed."""
    monkeypatch.setattr(authority, "CONSUMED_APPROVALS", frozenset())


@pytest.fixture(scope="module")
def readiness():
    dataset, artifact = synthetic_strength(mode="LIVE_OBSERVED")
    return seal(
        CurrentTeamStrengthReadiness,
        artifact=artifact,
        fixture_registry=dataset.fixture_registry,
        sources=dataset.sources,
        source_assessment=_source_assessment(dataset),
    )


def request(ready, **changes):
    return replace(
        live.L1OperatorRequest(
            42, "a" * 40, authority.APPROVAL, authority.ATTESTATION, ready.semantic_sha256
        ),
        **changes,
    )


def service(**kwargs):
    marker = "synthetic-test-only-value"
    return live.TeamStrengthL1ObservationService(
        clock=lambda: STAMP + timedelta(minutes=1),
        fpl_credentials=DirectFplCredentialProvider({"DMF_FPL_BEARER_TOKEN": marker}),
        odds_credentials=EnvironmentOddsCredentialProvider(
            environment={"THE_ODDS_API_KEY": marker}
        ),
        **kwargs,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"entry_id": True},
        {"entry_id": 0},
        {"code_sha": "HEAD"},
        {"approval": "DMF-R9C-A2-PRIVATE-RIGHTS-2026-09-17"},
        {"attestation": "wrong"},
        {"readiness_sha256": "0" * 64},
    ],
)
def test_invalid_authority_or_input_never_reaches_provider(readiness, changes):
    result = service().run(request(readiness, **changes), readiness)
    assert result["private_attempt_consumed"] is False
    assert result["fpl_requests"] == result["odds_requests"] == 0
    assert "42" not in json.dumps(result)


def test_exact_purposes_and_old_a2_runtime_rejected():
    authority.validate_l1_authority(
        approval=authority.APPROVAL, attestation=authority.ATTESTATION, checked_at=STAMP
    )
    from dmf_pulse.private_v1.live_shadow_observation import (
        A2FailureReason,
        R9CA2LiveShadowObservationService,
    )
    from tests.unit.private_v1.test_a2_preparation import A2_CUTOFF, _request

    result = R9CA2LiveShadowObservationService(clock=lambda: A2_CUTOFF).run(_request())
    assert result.reason_code == A2FailureReason.PROVIDER_AUTHORITY_INVALID
    assert result.fpl_request_attempt_count == result.odds_acquisition_attempt_count == 0


@pytest.mark.parametrize("profile_kind", ["FPL", "ODDS"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("human_approval_id", "old"),
        ("approved_purpose", "broader purpose"),
        ("geography_scope", "other"),
        ("retention_seconds", 10),
    ],
)
def test_authority_drift_fails(profile_kind, field, value, monkeypatch):
    loader = "load_fpl_rights" if profile_kind == "FPL" else "load_odds_rights"
    profile_id = authority.FPL_PROFILE if profile_kind == "FPL" else authority.ODDS_PROFILE
    profiles = getattr(authority, loader)()
    profiles = {**profiles, profile_id: profiles[profile_id].model_copy(update={field: value})}
    monkeypatch.setattr(authority, loader, lambda: profiles)
    with pytest.raises(ValueError, match="exact"):
        authority.validate_l1_authority(
            approval=authority.APPROVAL, attestation=authority.ATTESTATION, checked_at=STAMP
        )


@pytest.mark.parametrize("checked_at", [STAMP.replace(tzinfo=None), STAMP - timedelta(days=30)])
def test_authority_clock_invalid(checked_at):
    with pytest.raises(ValueError):
        authority.validate_l1_authority(
            approval=authority.APPROVAL, attestation=authority.ATTESTATION, checked_at=checked_at
        )


@pytest.mark.parametrize("response", ["exception", "http", "malformed"])
def test_first_fpl_transport_attempt_consumes_even_failure_no_retry(readiness, response):
    class Broken:
        calls = 0

        def send(self, request):
            self.calls += 1
            if response == "exception":
                raise IngestionError("SOURCE_UNAVAILABLE", "secret body forbidden", retryable=True)
            return DirectHttpResponse(
                503 if response == "http" else 200, "application/json", b"secret body forbidden"
            )

    transport = Broken()
    active = service(fpl_transport=transport)
    result = active.run(request(readiness), readiness)
    assert result["private_attempt_consumed"] is True
    assert result["fpl_requests"] == transport.calls == 1
    assert result["odds_requests"] == 0
    assert result["retry_performed"] is False
    assert result["stage"] == "PREPARE_PRIVATE_FROZEN_CONTEXT"
    assert "secret body" not in json.dumps(result)
    assert active.run(request(readiness), readiness)["reason"] == "ALREADY_INVOKED"
    assert transport.calls == 1
    with pytest.raises(ValueError):
        active.guard_network_event()


def test_missing_credential_before_transport_does_not_consume(readiness):
    active = live.TeamStrengthL1ObservationService(
        clock=lambda: STAMP + timedelta(minutes=1), fpl_credentials=DirectFplCredentialProvider({})
    )
    result = active.run(request(readiness), readiness)
    assert result["reason"] == "CREDENTIAL_UNAVAILABLE"
    assert not result["private_attempt_consumed"]


def test_post_cutoff_artifact_and_unexpected_onecommand_return_fail_closed(readiness, monkeypatch):
    from tests.unit.ingestion.openfootball.test_team_strength_current import reseal

    artifact = reseal(
        readiness.artifact,
        fitted_at=STAMP + timedelta(hours=1),
        usable_at=STAMP + timedelta(hours=1),
    )
    future = reseal(readiness, artifact=artifact)
    result = service().run(request(future), future)
    assert result["reason"] == "PUBLIC_READINESS_INVALID" and not result["private_attempt_consumed"]

    class UnexpectedReturn:
        def __init__(self, **kwargs):
            self.options = kwargs

        def run(self, request):
            return object()

    monkeypatch.setattr(live, "PrivateV1OneCommandService", UnexpectedReturn)
    result = service().run(request(readiness), readiness)
    assert result["reason"] == "FROZEN_CONTEXT_FAILED" and not result["private_attempt_consumed"]


def test_audit_hook_allows_only_declared_open_window():
    active = service()
    active._gate = OneShotNetworkGate(STAMP, STAMP + timedelta(minutes=5), lambda: STAMP)
    active.guard_network_event()
    assert not active._gate.consumed
    active._gate.closed = True
    with pytest.raises(ValueError, match="network"):
        active.guard_network_event()
    assert active._gate.denied == 1


@pytest.mark.parametrize("kind", ["fpl", "odds", "league", "accounting"])
def test_repeated_acquisition_or_unreconciled_context_is_rejected(readiness, monkeypatch, kind):
    from dmf_pulse.ingestion.fpl.direct import DirectFplRunAttestation
    from dmf_pulse.private_v1.progress import NullProgress

    # This adversarial test simulates an erroneous caller, not a computational
    # success. The separate principal E2E uses the real one-command and maths.
    class ErroneousCaller:
        def __init__(self, **kwargs):
            self.options = kwargs

        def run(self, request):
            options = self.options
            if kind == "fpl":
                for _ in range(2):
                    options["direct_client_factory"](DirectFplRunAttestation(attested_at=STAMP))
            elif kind == "odds":
                client = options["odds_service_factory"](options["clock"])
                for _ in range(2):
                    client.acquire(information_cutoff=STAMP, commence_to=STAMP + timedelta(days=1))
            elif kind == "league":
                client = options["score_service_factory"](options["clock"])
                for _ in range(2):
                    client.build(None)
            else:
                options["_prepared_rolling_runner"](None, progress=NullProgress())

    monkeypatch.setattr(live.CurrentOddsTransientService, "acquire", lambda *args, **kwargs: None)
    monkeypatch.setattr(live.CurrentScorePriorService, "build", lambda *args, **kwargs: None)
    monkeypatch.setattr(live, "PrivateV1OneCommandService", ErroneousCaller)
    result = service().run(request(readiness), readiness)
    assert result["reason"] == "FROZEN_CONTEXT_FAILED" and not result["private_attempt_consumed"]


def test_stale_public_source_never_consumes(readiness):
    active = live.TeamStrengthL1ObservationService(clock=lambda: STAMP + timedelta(hours=73))
    result = active.run(request(readiness), readiness)
    assert result["reason"] == "SOURCE_STALE"
    assert result["status"] == "TEAM_STRENGTH_PUBLIC_PREFLIGHT_BLOCKED"
    assert not result["private_attempt_consumed"]


def test_closed_transport_and_window():
    now = [STAMP]
    gate = OneShotNetworkGate(STAMP, STAMP + timedelta(minutes=5), lambda: now[0])
    gate.attempt("OPENFOOTBALL")
    assert not gate.consumed
    gate.attempt("FPL", "BOOTSTRAP")
    gate.attempt("ODDS")
    assert gate.consumed
    with pytest.raises(ValueError, match="consumed"):
        gate.attempt("ODDS")
    now[0] += timedelta(minutes=6)
    with pytest.raises(ValueError, match="window"):
        gate.preparation_guard()
    gate.closed = True
    gate.preparation_guard()  # deterministic work may continue after cutoff
    before = gate.counters()
    for provider in ("FPL", "ODDS", "OPENFOOTBALL"):
        with pytest.raises(ValueError, match="closed"):
            gate.attempt(provider)
    assert gate.counters()[:-1] == before[:-1]
    assert gate.denied == 4


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/api/bootstrap-static/", "BOOTSTRAP"),
        ("/api/fixtures/", "FIXTURES"),
        ("/api/event/5/live/", "EVENT_LIVE"),
        ("/api/entry/42/", "ENTRY"),
        ("/api/entry/42/history/", "HISTORY"),
        ("/api/entry/42/event/5/picks/", "PICKS"),
        ("/api/entry/42/transfers/", "TRANSFERS"),
        ("/api/my-team/42/", "MY_TEAM"),
    ],
)
def test_endpoint_classes_do_not_emit_identifiers(path, expected):
    assert fpl_endpoint(path) == expected


def test_endpoint_unknown_and_non_json_objects_rejected():
    with pytest.raises(ValueError):
        fpl_endpoint("/api/other/secret")
    for value in (object(), {42: "private"}, Decimal("NaN"), b"private"):
        with pytest.raises(ValueError):
            live.json_safe(value)
    assert live.json_safe({"safe": (Decimal("1.2"), True, None)}) == {"safe": ["1.2", True, None]}


@pytest.mark.parametrize("kind", ["exception", "http"])
@pytest.mark.parametrize("override,expected_calls", [(1, 1), (None, 2)])
def test_odds_local_one_attempt_does_not_change_normal_retry(kind, override, expected_calls):
    class Broken:
        transport_id = "injected"
        calls = 0

        def send(self, request, credential):
            self.calls += 1
            if kind == "exception":
                raise IngestionError("SOURCE_UNAVAILABLE", "private error", retryable=True)
            return OddsHttpResponse(
                429,
                "application/json",
                {
                    "retry-after": "0",
                    "x-requests-remaining": "100",
                    "x-requests-used": "2",
                    "x-requests-last": "2",
                },
                b'{"message":"synthetic provider unavailable"}',
            )

    transport = Broken()
    client = OddsClient(
        load_rights_profiles()[authority.ODDS_PROFILE],
        maximum_attempts=override,
        credential_provider=StaticCredentialProvider("synthetic-test-only-value"),
        transport_factory=lambda: transport,
        clock=lambda: STAMP,
        sleeper=lambda _: None,
    )
    with pytest.raises(IngestionError):
        client.fetch()
    assert transport.calls == expected_calls


@pytest.mark.parametrize("value", [True, 0, 2, -1])
def test_retry_override_can_only_narrow(value):
    with pytest.raises(ValueError):
        OddsClient(load_rights_profiles()[authority.ODDS_PROFILE], maximum_attempts=value)


def test_private_write_guard_catches_any_destination(tmp_path):
    import os

    from tests.unit.private_v1.l1_test_support import deny_writes

    with deny_writes():
        for writer in (
            lambda: (tmp_path / "a").write_text("private"),
            lambda: open(tmp_path / "b", "wb"),  # noqa: SIM115 - guard must raise before open
            lambda: os.open(tmp_path / "c", os.O_CREAT | os.O_WRONLY),
        ):
            with pytest.raises(AssertionError, match="filesystem write"):
                writer()
        with open(__file__, "rb") as source:
            assert source.read(1)
    assert not any((tmp_path / name).exists() for name in ("a", "b", "c"))
