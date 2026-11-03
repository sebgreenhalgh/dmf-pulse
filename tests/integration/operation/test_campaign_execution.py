"""Owned full source-wrapper chain and real PostgreSQL gates; no real providers.

Numerical kernels are exercised separately at real settings. These cases inject
an explicit controlled-kernel outcome/failure to verify source/financial order,
fractional advancing clocks, private profiles and response-completion custody.
They cannot generate a real-publication terminal.
"""

import json
import socket
from datetime import timedelta
from types import SimpleNamespace

import pytest

from dmf_pulse.dashboard import current_sources
from dmf_pulse.dashboard.authorization import RouteBudget
from dmf_pulse.ingestion.fpl.direct import DirectFplCredentialProvider
from dmf_pulse.ingestion.odds.client import OddsHttpResponse
from dmf_pulse.ingestion.openfootball import config as score_configuration
from dmf_pulse.ingestion.openfootball.config import load_provider_config
from dmf_pulse.operation import (
    campaign_execution,
    campaign_journal,
    campaign_sources,
)
from dmf_pulse.operation import (
    quota as quota_module,
)
from dmf_pulse.operation.campaign_execution import execute_active_session
from dmf_pulse.operation.diagnostics import DiagnosticLog
from dmf_pulse.operation.enrollment import rights_fingerprint
from dmf_pulse.operation.journal import OperationJournal
from dmf_pulse.private_v1.errors import PrivateV1Error
from tests.integration.operation import test_campaign_journal as support
from tests.unit.dashboard.post_gw10_support import CANARY, NOW, OwnedFpl, odds_body, owned_bodies
from tests.unit.ingestion.odds_private_test_support import owned_profile as owned_odds_profile
from tests.unit.ingestion.openfootball.conftest import FakeTransport, synthetic_snapshot
from tests.unit.ingestion.openfootball.test_private_operator_profile import (
    LICENCE_SHA,
)
from tests.unit.ingestion.openfootball.test_private_operator_profile import (
    owned_profile as owned_score_profile,
)

case = support.case
journal_engine = support.journal_engine
clean_postgres_test = support.clean_postgres_test
campaign_case = support.campaign_case
pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def flow(campaign_case, repository_root, monkeypatch, request):
    c = campaign_case
    config, score_bodies = synthetic_snapshot()
    sources = []
    for source in c.original.policy.qualifications:
        routes = source.scope.routes
        if source.scope.provider == "FPL":
            routes = tuple(
                route.model_copy(update={"path": route.path.replace("/17/", "/42/")})
                for route in routes
            )
        if source.scope.provider == "OPENFOOTBALL":
            routes = tuple(
                RouteBudget(
                    host="raw.githubusercontent.com", path=config.raw_path(path), maximum_calls=1
                )
                for path in score_bodies
            )
            source = source.model_copy(
                update={"profile": owned_score_profile(), "permission_evidence_sha256": LICENCE_SHA}
            )
        elif source.scope.provider == "ODDS":
            source = source.model_copy(
                update={
                    "profile": owned_odds_profile(
                        at=NOW - timedelta(days=3),
                        account_scope="qualified private Odds account: "
                        + c.original.policy.odds_account_ref,
                    )
                }
            )
        sources.append(
            source.model_copy(
                update={
                    "scope": source.scope.model_copy(
                        update={
                            "routes": routes,
                            "profile_id": source.profile.rights_profile_id,
                            "profile_sha256": rights_fingerprint(source.profile),
                        }
                    )
                }
            )
        )
    policy = c.original.policy.model_copy(update={"entry_id": 42, "qualifications": tuple(sources)})
    c.original.policy = policy
    c.original.journal = OperationJournal(policy, c.original.engine.connect)
    c.journal.original = c.original.journal
    c.authority.normal_policy = policy
    c.authority.proposal = c.authority.proposal.model_copy(update={"entry_id": 42})
    monkeypatch.setattr(
        campaign_journal, "CAMPAIGN_POLICY_SHA", c.authority.proposal.semantic_sha256
    )
    c.now[0] = NOW + timedelta(microseconds=123456)
    c.events = []
    c.failures = []
    original_failed = DiagnosticLog.failed

    def record_owned_failure(log, error):
        trace = error.__traceback__
        locations = []
        while trace is not None:
            module = trace.tb_frame.f_globals.get("__name__", "")
            if module.startswith("dmf_pulse."):
                locations.append((module, trace.tb_frame.f_code.co_name))
            trace = trace.tb_next
        fields = (
            [
                {"loc": item["loc"], "type": item["type"]}
                for item in error.errors(
                    include_input=False, include_context=False, include_url=False
                )
            ]
            if type(error).__name__ == "ValidationError"
            else []
        )
        c.failures.append((type(error).__name__, getattr(error, "code", None), locations, fields))
        return original_failed(log, error)

    monkeypatch.setattr(DiagnosticLog, "failed", record_owned_failure)
    target_fixture_count = getattr(request, "param", 10)
    source_bodies = owned_bodies(repository_root)
    if target_fixture_count != 10:
        bootstrap = json.loads(source_bodies["/api/bootstrap-static/"])
        bootstrap["teams"] = [
            team for team in bootstrap["teams"] if team["id"] <= target_fixture_count * 2
        ]
        bootstrap["elements"] = [
            player for player in bootstrap["elements"] if player["team"] <= target_fixture_count * 2
        ]
        source_bodies["/api/bootstrap-static/"] = json.dumps(bootstrap).encode()
        fixtures = json.loads(source_bodies["/api/fixtures/"])
        source_bodies["/api/fixtures/"] = json.dumps(
            [fixture for fixture in fixtures if fixture["team_h"] <= target_fixture_count * 2]
        ).encode()
    fpl = OwnedFpl(source_bodies)
    score = FakeTransport(score_bodies)
    raw_odds = json.dumps(json.loads(odds_body(repository_root))[:target_fixture_count]).encode()

    class OwnedFplTransport:
        requires_supplier_permission = True

        def send(self, request):
            c.events.append(("FPL", request.path))
            return fpl.send(request)

    class OwnedFplCredential(DirectFplCredentialProvider):
        def __init__(self, **_kwargs):
            super().__init__({"DMF_FPL_BEARER_TOKEN": CANARY})

        def check_expiry(self):
            return None

    class OwnedOddsCredential:
        def __init__(self, **_kwargs):
            return None

        def get_credential(self):
            return CANARY

    class OwnedQuota:
        def send(self, request, credential):
            assert credential == CANARY
            c.events.append(("QUOTA", request.path))
            return OddsHttpResponse(200, "application/json", support.support.headers(0), b"")

    class OwnedOdds:
        transport_id = "stdlib_http_client"  # owned native-shaped provenance test

        def __init__(self, *, on_response_headers=None):
            self.observer = on_response_headers

        def send(self, request, credential):
            assert credential == CANARY
            c.events.append(("ODDS_PAID", request.path))
            headers = support.support.headers(2)
            self.observer(200, headers)
            return OddsHttpResponse(200, "application/json", headers, raw_odds)

    class OwnedScores:
        def send(self, request):
            c.events.append(("OPENFOOTBALL", request.path))
            return score.send(request)

    def no_socket(*_args, **_kwargs):
        pytest.fail("engineering source chain attempted a real Python socket")

    monkeypatch.setattr(socket, "create_connection", no_socket)
    monkeypatch.setattr(current_sources, "DirectUrllibTransport", OwnedFplTransport)
    monkeypatch.setattr(campaign_execution, "DirectUrllibTransport", OwnedFplTransport)
    monkeypatch.setattr(current_sources, "AutomaticFplCredentialProvider", OwnedFplCredential)
    monkeypatch.setattr(current_sources, "AutomaticOddsCredentialProvider", OwnedOddsCredential)
    monkeypatch.setattr(quota_module, "AutomaticOddsCredentialProvider", OwnedOddsCredential)
    monkeypatch.setattr(campaign_sources, "NativeQuotaTransport", OwnedQuota)
    monkeypatch.setattr(current_sources, "HttpClientOddsTransport", OwnedOdds)
    monkeypatch.setattr(current_sources, "HttpClientOpenFootballTransport", OwnedScores)
    monkeypatch.setattr(score_configuration, "load_provider_config", lambda: config)
    # The accepted default config is retained; only the four returned owned
    # historical documents and licence are supplied through the existing seam.
    assert config.commit_sha == load_provider_config().commit_sha

    def clock():
        value = c.now[0]
        c.now[0] += timedelta(milliseconds=10)
        return value

    c.clock, c.fpl, c.score = clock, fpl, score
    return c


@pytest.mark.parametrize("controlled_failure", [False, True])
def test_full_owned_chain_never_charges_before_complete_controlled_gate(
    flow, monkeypatch, controlled_failure
):
    c = flow
    c.model_cutoffs = []

    def owned_kernel(execution, *, controlled, progress):
        assert execution.scenario_count == 256 and execution.root_seed == 42
        c.model_cutoffs.append(execution.current_state.information_cutoff)
        if controlled:
            if controlled_failure:
                raise PrivateV1Error("CURRENT_INPUT_CONTRACT_FAILED", CANARY)
            c.events.append(("CONTROLLED_GATE", "OWNED_KERNEL_OUTCOME_INJECTION"))
            return SimpleNamespace(
                controlled_proof=lambda: {
                    "classification": "REAL_FPL_CONTROLLED_MARKET_ENGINEERING",
                    "fpl_input_sha256": execution.current_state.fpl_input.semantic_sha256,
                    "execution_input_sha256": execution.semantic_sha256,
                    "decision_sha256": "d" * 64,
                    "stage8_stage9_stage12_passed": True,
                    "real_recommendation_publication": False,
                    "paid_provider_gets_in_controlled_computation": 0,
                }
            )
        raise PrivateV1Error("CURRENT_INPUT_CONTRACT_FAILED", CANARY)

    monkeypatch.setattr(campaign_execution, "run_diagnostic_kernel", owned_kernel)
    session = c.journal.begin_session("PAID_ELIGIBLE", now=c.clock())
    messages = []
    execute_active_session(
        c.journal,
        session.session_key,
        NOW + timedelta(hours=1),
        clock=c.clock,
        send=messages.append,
    )
    receipt = c.journal.session_receipt(session.session_key)
    assert receipt["terminal"]["outcome"] == "FAILED"
    assert receipt["terminal"]["error_code"] == "CURRENT_INPUT_CONTRACT_FAILED", (
        c.failures,
        c.events[-3:],
    )
    assert len(c.model_cutoffs) == (1 if controlled_failure else 2), repr(c.failures)
    assert all(cutoff.microsecond == 0 for cutoff in c.model_cutoffs)
    assert len(c.fpl.completed) == 16  # fresh discovery plus the one full snapshot
    assert len(c.score.requests) == 4
    assert CANARY not in str(receipt) and CANARY not in str(messages)
    if controlled_failure:
        assert not any(provider == "ODDS_PAID" for provider, _ in c.events)
        assert c.original.original.audit().reservation_count == 0
        assert len([event for event in c.events if event[0] == "QUOTA"]) == 1
    else:
        providers = [provider for provider, _ in c.events]
        assert providers.index("CONTROLLED_GATE") < providers.index("ODDS_PAID")
        assert providers.count("QUOTA") == 2 and providers.count("ODDS_PAID") == 1
        assert c.original.original.audit().reservation_count == 1
        settled = [
            row
            for row in receipt["records"]
            if row["payload"]["value"].get("subtype") == "ACTUAL_QUOTA"
        ]
        assert len(settled) == 1 and settled[0]["payload"]["value"]["last_request_cost"] == 2
        assert settled[0]["payload"]["value"]["consistent"] is True


@pytest.mark.parametrize("flow", [3], indirect=True)
def test_owned_complete_controller_publishes_bound_view_and_stops_campaign(flow):
    c = flow
    session = c.journal.begin_session("PAID_ELIGIBLE", now=c.clock())
    messages = []
    execute_active_session(
        c.journal,
        session.session_key,
        NOW + timedelta(hours=1),
        clock=c.clock,
        send=messages.append,
    )
    receipt = c.journal.session_receipt(session.session_key)
    assert receipt["terminal"]["outcome"] == "REAL_PUBLICATION", c.failures
    view = receipt["terminal"]["view"]
    assert view["team"]["decision"]["scenario_count"] == 256
    assert len(view["team"]["decision"]["tactics"]["starting_xi"]) == 11
    assert len(view["team"]["current_squad"]) == 15
    assert view["projected_count"] > 15
    assert "GW10 diagnostic / forecasts unvalidated" in view["restrictions"]
    assert len(c.fpl.completed) == 16 and len(c.score.requests) == 4
    assert (
        c.original.original.audit().reservation_count
        == c.original.original.audit().attempt_count
        == 1
    )
    assert view["market_quota_receipt"]["last_request_cost"] == 2
    assert CANARY not in str(receipt) and CANARY not in str(messages)
    c.journal.close(session.session_key, worker_and_transports_quiescent=True, now=c.clock())
    c.journal.inspect_previous(session.session_key, receipt["terminal_sha256"], now=c.clock())
    from dmf_pulse.operation.models import OperationError

    with pytest.raises(OperationError, match="DIAGNOSTIC_CAMPAIGN_ALREADY_SUCCEEDED"):
        c.journal.begin_session("PAID_ELIGIBLE", now=c.clock())
