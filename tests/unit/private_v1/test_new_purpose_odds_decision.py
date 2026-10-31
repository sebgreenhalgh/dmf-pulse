"""Owned new-profile client-to-decision regressions; no real acquisition or permission."""

from datetime import timedelta

import pytest

from dmf_pulse.ingestion.fpl.direct import DirectFplClient, DirectFplCredentialProvider
from dmf_pulse.ingestion.odds.client import OddsClient, OddsHttpResponse
from dmf_pulse.ingestion.odds.private_operator import PRIVATE_OPERATOR_PROFILE_ID
from dmf_pulse.ingestion.odds.transient import CurrentOddsTransientService
from dmf_pulse.ingestion.openfootball.config import load_rights_profiles as score_profiles
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorService
from dmf_pulse.operation import enrollment
from dmf_pulse.private_v1 import horizon_markets, one_command
from dmf_pulse.private_v1.one_command import OneCommandRequest, PrivateV1OneCommandService
from tests.unit.ingestion.odds_private_test_support import owned_body, owned_registry
from tests.unit.ingestion.openfootball.conftest import FakeTransport as ScoreTransport
from tests.unit.ingestion.openfootball.conftest import synthetic_snapshot
from tests.unit.private_v1.test_one_command import RUN_AT, _DirectTransport, _provider_sources

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("horizon", [1, 3])
def test_actual_new_purpose_odds_client_reaches_complete_unchanged_decision_stack(
    monkeypatch, repository_root, horizon
):
    registry, profile, quota = owned_registry(at=RUN_AT)
    approval = registry.approvals[0].model_copy(
        update={"qualified_deadline_at": RUN_AT + timedelta(days=3, hours=5, minutes=30)}
    )
    registry = registry.model_copy(update={"approvals": (approval,)})
    monkeypatch.setattr(enrollment, "installed_enrollment", lambda: registry)
    direct_bodies, _ = _provider_sources(repository_root)
    direct_transport = _DirectTransport(direct_bodies)
    counters = {"credentials": 0, "transports": 0}
    acquired, current_sources, root_views, future_views = [], [], [], []

    class Credentials:
        def get_credential(self):
            counters["credentials"] += 1
            return "owned-new-purpose-placeholder"

    class Transport:
        transport_id = "injected"

        def send(self, request, credential):
            assert request.method == "GET" and request.path == "/v4/sports/soccer_epl/odds"
            assert request.safe_parameters[:2] == (("regions", "uk"), ("markets", "h2h,totals"))
            assert credential == "owned-new-purpose-placeholder"
            counters["transports"] += 1
            return OddsHttpResponse(
                200,
                "application/json",
                {"x-requests-remaining": "498", "x-requests-used": "2", "x-requests-last": "2"},
                owned_body(repository_root),
            )

    class RecordingOddsService(CurrentOddsTransientService):
        def acquire(self, **kwargs):
            value = super().acquire(**kwargs)
            acquired.append(value)
            return value

    def odds_factory(clock):
        return RecordingOddsService(
            rights_profile=profile,
            credential_provider=Credentials(),
            client_factory=lambda selected, **kwargs: OddsClient(
                selected, transport_factory=Transport, **kwargs
            ),
            quota=quota,
            require_known_quota=True,
            maximum_attempts=1,
            clock=clock,
        )

    def direct_factory(attestation):
        return DirectFplClient(
            attestation,
            transport=direct_transport,
            credential_provider=DirectFplCredentialProvider(
                {"DMF_FPL_BEARER_TOKEN": "placeholder"}
            ),
            pace_seconds=0,
            sleeper=lambda _: None,
        )

    config, bodies = synthetic_snapshot()

    def score_factory(clock):
        return CurrentScorePriorService(
            provider_config=config,
            rights_profiles=score_profiles(),
            transport=ScoreTransport(bodies),
            clock=clock,
            provider_config_identity="a" * 64,
            rights_config_identity="b" * 64,
        )

    original_root = one_command.build_transient_current_market_identity_view
    original_future = horizon_markets._identity_view

    def record_root(source, **kwargs):
        view = original_root(source, **kwargs)
        current_sources.append(source)
        root_views.append(view)
        return view

    def record_future(*args, **kwargs):
        view = original_future(*args, **kwargs)
        future_views.append(view)
        return view

    monkeypatch.setattr(one_command, "build_transient_current_market_identity_view", record_root)
    monkeypatch.setattr(horizon_markets, "_identity_view", record_future)
    result = PrivateV1OneCommandService(
        direct_client_factory=direct_factory,
        odds_service_factory=odds_factory,
        score_service_factory=score_factory,
        collect_presentation=True,
        clock=lambda: RUN_AT,
    ).run(
        OneCommandRequest(
            entry_id=42,
            code_sha="a" * 40,
            run_at=RUN_AT,
            operator_approved_at=RUN_AT - timedelta(minutes=1),
            scenario_count=32 if horizon == 1 else 8,
            root_seed=42 if horizon == 1 else 43,
            horizon_gameweeks=horizon,
        )
    )
    assert counters == {"credentials": 1, "transports": 1}
    assert len(acquired) == len(root_views) == len(current_sources) == 1
    assert acquired[0].rights.rights_profile_id == PRIVATE_OPERATOR_PROFILE_ID
    assert acquired[0] == current_sources[0].odds_input
    assert root_views[0].provider_rights_profile_key == PRIVATE_OPERATOR_PROFILE_ID
    assert result.status == "REAL_PRIVATE_TRANSIENT_RECOMMENDATION"
    assert result.persistence_performed is False and result.fpl_request_count == 8
    assert result.presentation is not None and len(result.presentation.current_squad) == 15
    assert len(result.presentation.gameweeks) == horizon
    assert all(gameweek.summaries for gameweek in result.presentation.gameweeks)
    receipt = result.presentation.market_quota_receipt
    assert receipt is not None
    assert (receipt.remaining_credits, receipt.used_credits, receipt.last_request_cost) == (
        498,
        2,
        2,
    )
    assert receipt.transport_call_count == 1
    root = result.decision if horizon == 1 else result.decision.do_now
    assert len(root.tactics.starting_xi) == 11
    assert root.tactics.captain in root.tactics.starting_xi
    assert root.tactics.vice_captain in root.tactics.starting_xi
    assert root.tactics.captain != root.tactics.vice_captain
    if horizon == 3:
        assert future_views
        assert all(
            view.provider_rights_profile_key == PRIVATE_OPERATOR_PROFILE_ID for view in future_views
        )
