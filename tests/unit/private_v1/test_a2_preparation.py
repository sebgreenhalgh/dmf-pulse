"""A2 acquire-once preparation and fail-closed operator boundaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dmf_pulse.fpl_points.current_player_posterior import ALLOWED_PROFILE_FIELDS
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectFplResource,
    DirectFplRunAttestation,
    DirectHttpResponse,
)
from dmf_pulse.ingestion.models import RightsProfileStatus
from dmf_pulse.ingestion.odds.config import load_rights_profiles as load_odds_rights
from dmf_pulse.ingestion.openfootball.config import (
    APPROVED_PROFILE_ID,
)
from dmf_pulse.ingestion.openfootball.config import (
    load_rights_profiles as load_score_rights,
)
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorService,
)
from dmf_pulse.private_v1 import live_shadow_observation as a2
from dmf_pulse.private_v1.live_shadow_observation import (
    A2_APPROVAL_REFERENCE,
    A2_EXECUTION_ATTESTATION,
    A2FailureReason,
    A2OperatorRequest,
    LiveA2BlockedResult,
    LiveFourWorldShadowDecisionObservation,
    R9CA2LiveShadowObservationService,
    _compile_shadow,
)
from tests.unit.ingestion.openfootball.conftest import FakeTransport as ScoreTransport
from tests.unit.ingestion.openfootball.conftest import synthetic_snapshot
from tests.unit.private_v1.a2_test_support import build_a2_comparison_inputs
from tests.unit.private_v1.test_one_command import (
    RUN_AT,
    _DirectTransport,
    _odds_input,
    _OddsService,
    _provider_sources,
)

pytestmark = pytest.mark.unit
A2_CUTOFF = datetime(2026, 9, 17, 15, tzinfo=UTC)


def _request(**updates) -> A2OperatorRequest:
    values = {
        "entry_id": 42,
        "code_sha": "a" * 40,
        "operator_approved_at": A2_CUTOFF - timedelta(minutes=1),
        "acquisition_cutoff": A2_CUTOFF,
        "provider_approval_reference": A2_APPROVAL_REFERENCE,
        "execution_attestation": A2_EXECUTION_ATTESTATION,
        "scenario_count": 2,
        **updates,
    }
    return A2OperatorRequest(**values)


def test_wrong_authority_blocks_before_any_factory_or_provider_call() -> None:
    calls: list[str] = []

    def forbidden(*args, **kwargs):
        calls.append("called")
        raise AssertionError("provider factory must not be called")

    service = R9CA2LiveShadowObservationService(
        direct_client_factory=forbidden,
        odds_service_factory=forbidden,
        score_service_factory=forbidden,
        clock=lambda: A2_CUTOFF,
    )

    result = service.run(_request(provider_approval_reference="wrong-reference"))

    assert isinstance(result, LiveA2BlockedResult)
    assert result.reason_code == A2FailureReason.PROVIDER_AUTHORITY_INVALID
    assert result.fpl_request_attempt_count == 0
    assert result.odds_acquisition_attempt_count == 0
    assert result.retry_performed is False
    assert calls == []


@pytest.mark.parametrize(
    "updates",
    (
        {"entry_id": True},
        {"entry_id": 0},
        {"code_sha": "not-a-sha"},
        {"acquisition_cutoff": A2_CUTOFF + timedelta(minutes=5, seconds=1)},
        {"scenario_count": 0},
    ),
)
def test_invalid_runtime_input_blocks_before_authority_or_provider(updates) -> None:
    result = R9CA2LiveShadowObservationService().run(_request(**updates))

    assert isinstance(result, LiveA2BlockedResult)
    assert result.reason_code == A2FailureReason.RUNTIME_INPUT_INVALID
    assert result.fpl_request_attempt_count == 0
    assert result.odds_acquisition_attempt_count == 0


def test_same_prepared_snapshot_builds_history_and_shadow_without_network(
    repository_root, tmp_path, monkeypatch
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("history and shadow assembly must not access the network")

    import socket

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(a2, "DirectFplClient", forbidden)
    monkeypatch.setattr(a2, "CurrentOddsTransientService", forbidden)
    monkeypatch.setattr(a2, "CurrentScorePriorService", forbidden)
    prepared, expected_history, expected_shadow = build_a2_comparison_inputs(
        repository_root,
        tmp_path,
    )

    history, shadow = _compile_shadow(prepared)

    assert history == expected_history
    assert shadow == expected_shadow
    assert history.information_cutoff == prepared.information_cutoff
    assert history.coverage.observed_gameweeks == tuple(
        range(1, prepared.rolling_execution.horizon_gameweeks[0])
    )
    assert shadow.new_network_requests == 0
    assert shadow.persistence_performed is False
    assert shadow.model_training_performed is False
    assert all(world.posterior.shrinkage_strength_calibrated is False for world in shadow.worlds)
    for world in shadow.worlds:
        for stale, updated in zip(world.stale_profiles, world.profiles, strict=True):
            unchanged = set(type(stale).model_fields) - set(ALLOWED_PROFILE_FIELDS)
            assert all(getattr(stale, field) == getattr(updated, field) for field in unchanged)
            assert updated.goal_share == stale.goal_share
            assert updated.penalty_taker_share == stale.penalty_taker_share
            assert updated.own_goal_share == stale.own_goal_share


def test_blocked_payload_has_closed_safe_schema() -> None:
    result = R9CA2LiveShadowObservationService(clock=lambda: A2_CUTOFF).run(
        _request(provider_approval_reference="wrong-reference")
    )
    assert isinstance(result, LiveA2BlockedResult)
    payload = result.public_dict()

    assert set(payload) == {
        "schema_version",
        "status",
        "reason_code",
        "failure_stage",
        "fpl_request_attempt_count",
        "fpl_endpoint_classes",
        "odds_acquisition_attempt_count",
        "retry_performed",
        "persistence_performed",
        "model_training_performed",
        "production_activation",
    }


@pytest.mark.parametrize(
    "update",
    (
        {"status": RightsProfileStatus.WITHDRAWN},
        {"terms_version": "checked-2026-07-25"},
        {"checked_at": datetime(2026, 7, 25, tzinfo=UTC)},
        {"approved_at": datetime(2026, 7, 25, tzinfo=UTC)},
        {"geography_scope": "different geography"},
    ),
    ids=("withdrawn", "stale-terms", "stale-review", "stale-approval", "wrong-scope"),
)
def test_odds_authority_metadata_blocks_before_any_provider(monkeypatch, update) -> None:
    profile = load_odds_rights()["the_odds_api_private_analytics_v1"]
    monkeypatch.setattr(
        "dmf_pulse.private_v1.live_shadow_observation.load_odds_rights",
        lambda: {profile.rights_profile_id: profile.model_copy(update=update)},
    )
    calls: list[str] = []

    def forbidden(*args, **kwargs):
        calls.append("provider")
        raise AssertionError("invalid Odds authority must block before provider construction")

    result = R9CA2LiveShadowObservationService(
        direct_client_factory=forbidden,
        odds_service_factory=forbidden,
        score_service_factory=forbidden,
        clock=lambda: A2_CUTOFF,
    ).run(_request())

    assert isinstance(result, LiveA2BlockedResult)
    assert result.reason_code == A2FailureReason.PROVIDER_AUTHORITY_INVALID
    assert result.fpl_request_attempt_count == 0
    assert result.odds_acquisition_attempt_count == 0
    assert calls == []


@pytest.mark.parametrize(
    "update",
    (
        {"status": RightsProfileStatus.WITHDRAWN},
        {"terms_source": "different terms source"},
        {"unresolved_rights": ("synthetic unresolved right",)},
        {"termination_deletion_required": True},
        {"approved_purpose": "different purpose"},
    ),
    ids=("withdrawn", "terms-source", "unresolved-rights", "deletion-flag", "purpose"),
)
def test_fpl_authority_metadata_blocks_before_any_provider(monkeypatch, update) -> None:
    profile = a2.load_fpl_rights()[a2.FPL_PROFILE_ID]
    monkeypatch.setattr(
        a2,
        "load_fpl_rights",
        lambda: {profile.rights_profile_id: profile.model_copy(update=update)},
    )
    calls: list[str] = []

    def forbidden(*args, **kwargs):
        calls.append("provider")
        raise AssertionError("invalid FPL authority must block before provider construction")

    result = R9CA2LiveShadowObservationService(
        direct_client_factory=forbidden,
        odds_service_factory=forbidden,
        score_service_factory=forbidden,
        clock=lambda: A2_CUTOFF,
    ).run(_request())

    assert isinstance(result, LiveA2BlockedResult)
    assert result.reason_code == A2FailureReason.PROVIDER_AUTHORITY_INVALID
    assert result.fpl_request_attempt_count == 0
    assert result.odds_acquisition_attempt_count == 0
    assert calls == []


def test_pre_approval_clock_blocks_before_provider_construction() -> None:
    calls: list[str] = []

    def forbidden(*args, **kwargs):
        calls.append("provider")
        raise AssertionError("A2 access must not start before operator approval")

    request = _request(operator_approved_at=A2_CUTOFF - timedelta(seconds=30))
    result = R9CA2LiveShadowObservationService(
        direct_client_factory=forbidden,
        odds_service_factory=forbidden,
        score_service_factory=forbidden,
        clock=lambda: A2_CUTOFF - timedelta(seconds=31),
    ).run(request)

    assert isinstance(result, LiveA2BlockedResult)
    assert result.reason_code == A2FailureReason.FROZEN_CONTEXT_PREPARATION_FAILED
    assert result.fpl_request_attempt_count == 0
    assert result.odds_acquisition_attempt_count == 0
    assert calls == []


def test_expired_window_blocks_before_provider_construction() -> None:
    calls: list[str] = []

    def forbidden(*args, **kwargs):
        calls.append("provider")
        raise AssertionError("expired A2 window must block before provider construction")

    result = R9CA2LiveShadowObservationService(
        direct_client_factory=forbidden,
        odds_service_factory=forbidden,
        score_service_factory=forbidden,
        clock=lambda: A2_CUTOFF + timedelta(seconds=1),
    ).run(_request())

    assert isinstance(result, LiveA2BlockedResult)
    assert result.reason_code == A2FailureReason.FROZEN_CONTEXT_PREPARATION_FAILED
    assert result.fpl_request_attempt_count == 0
    assert calls == []


def test_cutoff_crossing_after_bootstrap_prevents_later_provider_requests(
    repository_root: Path,
) -> None:
    direct_bodies, _ = _provider_sources(repository_root)
    direct_transport = _DirectTransport(direct_bodies)
    clock_calls = 0
    odds_calls = 0

    def crossing_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return A2_CUTOFF if clock_calls <= 4 else A2_CUTOFF + timedelta(seconds=1)

    def direct_factory(attestation: DirectFplRunAttestation, before_request) -> DirectFplClient:
        return DirectFplClient(
            attestation,
            transport=direct_transport,
            credential_provider=DirectFplCredentialProvider({}),
            sleeper=lambda _: None,
            pace_seconds=0,
            before_request=before_request,
        )

    def forbidden_odds(*args, **kwargs):
        nonlocal odds_calls
        odds_calls += 1
        raise AssertionError("Odds must not be constructed after FPL crosses the cutoff")

    result = R9CA2LiveShadowObservationService(
        direct_client_factory=direct_factory,
        odds_service_factory=forbidden_odds,
        score_service_factory=forbidden_odds,
        clock=crossing_clock,
    ).run(_request())

    assert isinstance(result, LiveA2BlockedResult)
    assert result.reason_code == A2FailureReason.FROZEN_CONTEXT_PREPARATION_FAILED
    assert len(direct_transport.requests) == 1
    assert result.fpl_request_attempt_count == 1
    assert odds_calls == 0


def test_cutoff_guard_runs_again_before_a_direct_fpl_retry() -> None:
    class RetryTransport:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request):
            del request
            self.calls += 1
            return DirectHttpResponse(503, "application/json", b"synthetic unavailable")

    guard_calls = 0

    def guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls > 2:
            raise IngestionError("POST_CUTOFF", "synthetic cutoff crossed")

    transport = RetryTransport()
    client = DirectFplClient(
        DirectFplRunAttestation(attested_at=A2_CUTOFF),
        transport=transport,
        credential_provider=DirectFplCredentialProvider({}),
        sleeper=lambda _: None,
        pace_seconds=0,
        before_request=guard,
    )

    with pytest.raises(IngestionError) as caught:
        client.fetch(DirectFplResource.BOOTSTRAP)

    assert caught.value.code == "POST_CUTOFF"
    assert guard_calls == 3
    assert transport.calls == 1
    assert client.request_count == 1


def test_score_prior_guard_blocks_later_resource_after_processing_crosses_cutoff() -> None:
    score_config, score_bodies = synthetic_snapshot()
    transport = ScoreTransport(score_bodies)
    guard_calls = 0

    def guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls > 1:
            raise IngestionError("POST_CUTOFF", "synthetic cutoff crossed during processing")

    service = CurrentScorePriorService(
        provider_config=score_config,
        rights_profiles=load_score_rights(),
        transport=transport,
        clock=lambda: A2_CUTOFF - timedelta(seconds=1),
        before_request=guard,
        provider_config_identity="a" * 64,
        rights_config_identity="b" * 64,
    )

    with pytest.raises(IngestionError) as caught:
        service.build(
            CurrentScorePriorBuildRequest(
                information_cutoff=A2_CUTOFF,
                rights_profile_id=APPROVED_PROFILE_ID,
            )
        )

    assert caught.value.code == "POST_CUTOFF"
    assert caught.value.details["transport_call_count"] == 1
    assert guard_calls == 2
    assert len(transport.requests) == 1


def test_one_shot_prepares_once_then_runs_four_worlds_without_more_provider_calls(
    repository_root: Path,
    monkeypatch,
) -> None:
    direct_bodies, _ = _provider_sources(repository_root)
    direct_transport = _DirectTransport(direct_bodies)
    marker = "synthetic-token"
    odds_service = _OddsService(
        _odds_input(
            repository_root,
            horizon_market_coverage=True,
        )
    )
    score_config, score_bodies = synthetic_snapshot()
    direct_factory_calls = 0
    odds_factory_calls = 0
    score_factory_calls = 0
    synthetic_checked_at = RUN_AT - timedelta(days=1)
    synthetic_approved_at = RUN_AT - timedelta(minutes=2)
    odds_profile = load_odds_rights()["the_odds_api_private_analytics_v1"].model_copy(
        update={
            "checked_at": synthetic_checked_at,
            "approved_at": synthetic_approved_at,
        }
    )
    monkeypatch.setattr(a2, "_ODDS_CHECKED_AT", synthetic_checked_at)
    monkeypatch.setattr(a2, "_ODDS_APPROVED_AT", synthetic_approved_at)
    monkeypatch.setattr(
        a2,
        "load_odds_rights",
        lambda: {odds_profile.rights_profile_id: odds_profile},
    )

    def direct_factory(attestation: DirectFplRunAttestation, before_request) -> DirectFplClient:
        nonlocal direct_factory_calls
        direct_factory_calls += 1
        return DirectFplClient(
            attestation,
            transport=direct_transport,
            credential_provider=DirectFplCredentialProvider({"DMF_FPL_BEARER_TOKEN": marker}),
            sleeper=lambda _: None,
            pace_seconds=0,
            before_request=before_request,
        )

    def odds_factory(clock):
        nonlocal odds_factory_calls
        del clock
        odds_factory_calls += 1
        return odds_service

    def score_factory(clock, before_request):
        nonlocal score_factory_calls
        score_factory_calls += 1
        return CurrentScorePriorService(
            provider_config=score_config,
            rights_profiles=load_score_rights(),
            transport=ScoreTransport(score_bodies),
            clock=clock,
            before_request=before_request,
            provider_config_identity="a" * 64,
            rights_config_identity="b" * 64,
        )

    service = R9CA2LiveShadowObservationService(
        direct_client_factory=direct_factory,
        odds_service_factory=odds_factory,
        score_service_factory=score_factory,
        clock=lambda: RUN_AT,
    )
    result = service.run(
        A2OperatorRequest(
            entry_id=42,
            code_sha="a" * 40,
            operator_approved_at=RUN_AT - timedelta(minutes=1),
            acquisition_cutoff=RUN_AT,
            provider_approval_reference=A2_APPROVAL_REFERENCE,
            execution_attestation=A2_EXECUTION_ATTESTATION,
            scenario_count=2,
            root_seed=43,
        )
    )

    assert isinstance(result, LiveFourWorldShadowDecisionObservation)
    assert direct_factory_calls == 1
    assert odds_factory_calls == 1
    assert score_factory_calls == 1
    assert len(odds_service.requests) == 1
    assert result.fpl_request_count == len(direct_transport.requests) == 8
    assert result.odds_request_count == 1
    assert result.new_network_requests_during_world_comparison == 0
    assert len(result.results) == 4
    summary = service.take_safe_summary(result)
    assert isinstance(summary, dict)
    assert summary["persistence_performed"] is False
    second = service.take_safe_summary(result)
    assert isinstance(second, LiveA2BlockedResult)
    assert second.reason_code == A2FailureReason.SAFE_SUMMARY_FAILED
