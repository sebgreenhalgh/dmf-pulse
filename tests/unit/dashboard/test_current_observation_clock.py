"""Actual owned model/worker results use observed times below a future cutoff."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard import current as current_module
from dmf_pulse.dashboard.authorization import AuthorizationError, RefreshAuthorizer
from dmf_pulse.dashboard.current import (
    CurrentRefreshSession,
    current_worker,
    validate_current_result,
)
from dmf_pulse.dashboard.current_sources import CurrentSourceFactories
from dmf_pulse.dashboard.synthetic import DEMO_TIME
from dmf_pulse.private_v1 import one_command as command_module
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.one_command import PrivateV1OneCommandService

pytestmark = pytest.mark.unit


class AdvancingClock:
    def __init__(self):
        self.value = DEMO_TIME

    def __call__(self):
        self.value += timedelta(microseconds=1)
        return self.value


class FutureCutoffOwnedSession(CurrentRefreshSession):
    def _request(self, horizon):
        # Exercise the actual production window calculation while keeping the
        # grant, ledger, provider bodies and transports explicitly owned.
        self._owned_sources = False
        try:
            return super()._request(horizon)
        finally:
            self._owned_sources = True


class Pipe:
    def __init__(self):
        self.messages = []
        self.closed = False

    def send(self, value):
        self.messages.append(value)

    def close(self):
        self.closed = True


def owned_session(path, clock, *, one_shot=False, wrong_deadline=False):
    session = FutureCutoffOwnedSession.owned(path)
    if one_shot:
        session._approval = session._approval.model_copy(update={"usage": "ONE_SHOT"})
    if wrong_deadline:
        session._deadline -= timedelta(days=1)
    session._clock = clock
    session._authorizer = RefreshAuthorizer.for_owned_sources(
        session._approval, session._ledger, clock=clock
    )
    return session


@pytest.fixture(scope="module", params=[1, 3])
def advancing_worker(request, tmp_path_factory):
    horizon = request.param
    clock = AdvancingClock()
    session = owned_session(tmp_path_factory.mktemp(f"advancing-worker-{horizon}") / "usage", clock)
    launch = session.prepare(horizon)
    original = current_module.run_current_recommendation
    pipe = Pipe()
    with pytest.MonkeyPatch.context() as monkeypatch:
        # Keep the actual current_worker, guarded transports, OneCommand models,
        # keyed result envelope and parent validator. Inject only its clock.
        monkeypatch.setattr(
            current_module,
            "run_current_recommendation",
            lambda value, progress: original(value, progress, clock=clock),
        )
        current_worker(pipe, horizon, launch)
    assert pipe.closed
    errors = [value for kind, value in pipe.messages if kind == "error"]
    assert not errors, errors
    results = [value for kind, value in pipe.messages if kind == "current_result"]
    assert len(results) == 1
    return launch, results[0], session, horizon


def reseal(envelope, launch, result):
    digest = canonical_sha256(result.presentation.model_dump(mode="json"))
    return replace(
        envelope,
        result=result,
        presentation_sha256=digest,
        authentication_sha256=current_module._result_authentication(launch, result, digest),
    )


@pytest.mark.parametrize("budget", [1, 300, 900])
def test_actual_request_shortens_only_future_bound_to_provider_precision(tmp_path, budget):
    clock = AdvancingClock()
    clock.value = DEMO_TIME + timedelta(microseconds=987654)
    session = owned_session(tmp_path / "usage", clock)
    session._approval = session._approval.model_copy(update={"max_acquisition_seconds": budget})
    request = session._request(1)
    observed = clock.value
    full_budget = observed + timedelta(seconds=budget)
    assert observed.microsecond != 0
    assert observed < request.information_cutoff <= full_budget
    assert full_budget - request.information_cutoff < timedelta(seconds=1)
    assert request.information_cutoff.microsecond == 0
    assert session.owned_sources and request.source_scopes == session._approval.source_scopes


def test_advancing_real_worker_model_path_accepts_observations_before_future_cutoff(
    advancing_worker,
):
    launch, envelope, session, horizon = advancing_worker
    result = envelope.result
    presentation = result.presentation
    validate_current_result(envelope, launch)
    assert launch.grant.issued_at < presentation.source_captured_at
    assert presentation.source_captured_at < launch.grant.request.information_cutoff
    fpl, markets, prior = presentation.source_vintages
    assert (
        presentation.source_captured_at
        <= fpl.received_at
        < fpl.usable_at
        < markets.received_at
        <= markets.usable_at
        < prior.received_at
        < prior.usable_at
        < result.actionability.checked_at
        < launch.grant.expires_at
    )
    assert (fpl.requests, markets.requests, prior.requests) == (result.fpl_request_count, 1, 4)
    assert len(presentation.gameweeks) == horizon
    assert presentation.market_quota_receipt.received_at == markets.received_at
    assert session._ledger.audit().attempt_count == result.fpl_request_count + 1 + 4
    assert result.persistence_performed is False


@pytest.mark.parametrize(
    "attack",
    [
        "capture_pregrant",
        "capture_future_cutoff",
        "capture_naive",
        "fpl_received_pre_capture",
        "fpl_usable_pre_received",
        "market_pre_fpl",
        "market_usable_pre_received",
        "prior_pre_market",
        "prior_usable_pre_received",
        "prior_post_cutoff",
        "source_naive",
        "missing",
        "duplicate",
        "reordered",
        "wrong_mode",
        "fpl_count",
        "market_count",
        "prior_count",
        "boolean_count",
        "actionability_before_sources",
        "actionability_at_expiry",
        "publication_before_check",
    ],
)
def test_even_reauthenticated_owned_result_rejects_incoherent_source_chronology(
    advancing_worker,
    attack,
):
    launch, envelope, _, _ = advancing_worker
    result = envelope.result
    presentation = result.presentation
    fpl, markets, prior = presentation.source_vintages
    rows = (fpl, markets, prior)
    updates = {}
    if attack == "capture_pregrant":
        updates["source_captured_at"] = launch.grant.issued_at - timedelta(microseconds=1)
    elif attack == "capture_future_cutoff":
        updates["source_captured_at"] = launch.grant.request.information_cutoff
    elif attack == "capture_naive":
        updates["source_captured_at"] = presentation.source_captured_at.replace(tzinfo=None)
    elif attack == "fpl_received_pre_capture":
        rows = (
            fpl.model_copy(
                update={"received_at": presentation.source_captured_at - timedelta(microseconds=1)}
            ),
            markets,
            prior,
        )
    elif attack == "fpl_usable_pre_received":
        rows = (
            fpl.model_copy(update={"usable_at": fpl.received_at - timedelta(microseconds=1)}),
            markets,
            prior,
        )
    elif attack == "market_pre_fpl":
        rows = (
            fpl,
            markets.model_copy(update={"received_at": fpl.usable_at - timedelta(microseconds=1)}),
            prior,
        )
    elif attack == "market_usable_pre_received":
        rows = (
            fpl,
            markets.model_copy(
                update={"usable_at": markets.received_at - timedelta(microseconds=1)}
            ),
            prior,
        )
    elif attack == "prior_pre_market":
        rows = (
            fpl,
            markets,
            prior.model_copy(update={"received_at": markets.usable_at - timedelta(microseconds=1)}),
        )
    elif attack == "prior_usable_pre_received":
        rows = (
            fpl,
            markets,
            prior.model_copy(update={"usable_at": prior.received_at - timedelta(microseconds=1)}),
        )
    elif attack == "prior_post_cutoff":
        rows = (
            fpl,
            markets,
            prior.model_copy(
                update={
                    "usable_at": launch.grant.request.information_cutoff + timedelta(microseconds=1)
                }
            ),
        )
    elif attack == "source_naive":
        rows = (
            fpl,
            markets,
            prior.model_copy(update={"received_at": prior.received_at.replace(tzinfo=None)}),
        )
    elif attack == "missing":
        rows = (fpl, markets)
    elif attack == "duplicate":
        rows = (fpl, markets, markets)
    elif attack == "reordered":
        rows = (markets, fpl, prior)
    elif attack == "wrong_mode":
        rows = (fpl, markets, prior.model_copy(update={"source_mode": "CURRENT_TRANSIENT"}))
    elif attack == "fpl_count":
        rows = (fpl.model_copy(update={"requests": fpl.requests + 1}), markets, prior)
    elif attack == "market_count":
        rows = (fpl, markets.model_copy(update={"requests": 2}), prior)
    elif attack == "prior_count":
        rows = (fpl, markets, prior.model_copy(update={"requests": 3}))
    elif attack == "boolean_count":
        rows = (fpl, markets.model_copy(update={"requests": True}), prior)
    elif attack in {"actionability_before_sources", "actionability_at_expiry"}:
        checked = (
            prior.usable_at - timedelta(microseconds=1)
            if attack == "actionability_before_sources"
            else launch.grant.expires_at
        )
        receipt = result.actionability.model_copy(update={"checked_at": checked})
        receipt = receipt.model_copy(
            update={
                "semantic_sha256": canonical_sha256(
                    receipt.model_dump(mode="json", exclude={"semantic_sha256"})
                )
            }
        )
        result = replace(result, actionability=receipt)
    else:
        result = replace(
            result,
            publication_not_before=result.actionability.checked_at - timedelta(microseconds=1),
        )
    changed = presentation.model_copy(update={**updates, "source_vintages": rows})
    result = replace(result, presentation=changed)
    with pytest.raises(AuthorizationError, match="WORKER_RESULT_BINDING_INVALID"):
        validate_current_result(reseal(envelope, launch, result), launch)


def test_expected_deadline_refuses_before_manager_models_paid_factory_or_key(
    tmp_path,
    monkeypatch,
):
    from dmf_pulse.credentials.providers import AutomaticOddsCredentialProvider

    clock = AdvancingClock()
    session = owned_session(tmp_path / "usage", clock, one_shot=True, wrong_deadline=True)
    launch = session.prepare(1)
    called = []

    def denied(name):
        def attempt(*args, **kwargs):
            called.append(name)
            pytest.fail("deadline mismatch reached " + name)

        return attempt

    monkeypatch.setattr(CurrentSourceFactories, "odds", denied("paid factory"))
    monkeypatch.setattr(AutomaticOddsCredentialProvider, "get_credential", denied("paid key"))
    monkeypatch.setattr(command_module, "_rules_authority", denied("rules/model"))
    monkeypatch.setattr(
        command_module.CurrentManagerStateService, "compile_provider_snapshot", denied("manager")
    )
    with pytest.raises(PrivateV1Error) as caught:
        current_module.run_current_recommendation(
            launch, command_module.NullProgress(), clock=clock
        )
    assert caught.value.code == "OFFICIAL_DEADLINE_SCOPE_MISMATCH" and called == []
    audit = session._ledger.audit()
    assert audit.reservation_count == 1 and audit.claim_count == 1 and audit.attempt_count == 8
    with pytest.raises(AuthorizationError, match="ONE_SHOT_CONSUMED"):
        session.prepare(1)
    assert session._ledger.audit() == audit


def test_expected_deadline_requires_aware_time_and_normalizes_utc():
    with pytest.raises(PrivateV1Error) as caught:
        PrivateV1OneCommandService(_expected_deadline_at=datetime(2026, 9, 4, 17, 30))
    assert caught.value.code == "USAGE_INVALID"
    offset = datetime.fromisoformat("2026-09-04T19:30:00+02:00")
    service = PrivateV1OneCommandService(_expected_deadline_at=offset)
    assert service._expected_deadline_at == datetime(2026, 9, 4, 17, 30, tzinfo=UTC)
    assert PrivateV1OneCommandService()._expected_deadline_at is None
