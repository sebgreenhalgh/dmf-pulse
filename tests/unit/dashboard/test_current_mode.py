"""Current architecture reaches actual clients, models and paired browser views offline."""

from __future__ import annotations

import asyncio
import json
import pickle
import selectors
from dataclasses import replace
from datetime import timedelta

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard import current as current_module
from dmf_pulse.dashboard.app import create_app
from dmf_pulse.dashboard.authorization import (
    AuthorizationError,
    RefreshAuthorizer,
    production_approvals,
)
from dmf_pulse.dashboard.current import (
    CurrentAcquisitionGuard,
    CurrentRefreshSession,
    CurrentWorkerResult,
    current_worker,
    implementation_fingerprint,
    profile_fingerprint,
    resolved_profiles,
    run_current_recommendation,
    validate_current_result,
)
from dmf_pulse.dashboard.current_sources import OwnedFplTransport, OwnedOddsTransport
from dmf_pulse.dashboard.runtime import DeskRuntime
from dmf_pulse.dashboard.synthetic import DEMO_TIME
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import DirectHttpResponse
from dmf_pulse.ingestion.odds.client import OddsHttpResponse
from dmf_pulse.private_v1.progress import NullProgress

pytestmark = pytest.mark.unit
PAIRING = "owned-current-mode-pairing-only"


class _Selector(selectors.SelectSelector):
    def select(self, timeout=None):
        assert not self.get_map()
        return []


class _Loop(asyncio.SelectorEventLoop):
    def _make_self_pipe(self):
        self._ssock = self._csock = None

    def _close_self_pipe(self):
        return


def request(app, path, *, cookie=None, body=None):
    async def execute():
        payload = b"" if body is None else json.dumps(body).encode()
        headers = {"host": "127.0.0.1:8765"}
        if cookie:
            headers["cookie"] = cookie
        if body is not None:
            headers.update(
                {
                    "origin": "http://127.0.0.1:8765",
                    "content-type": "application/json",
                    "x-dmf-action": "operator",
                }
            )
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET" if body is None else "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            "client": ("127.0.0.1", 2222),
            "server": ("127.0.0.1", 8765),
        }
        sent = False
        wait = asyncio.Event()
        responses = []

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": payload, "more_body": False}
            await wait.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            responses.append(message)

        await app(scope, receive, send)
        start = next(r for r in responses if r["type"] == "http.response.start")
        data = b"".join(r.get("body", b"") for r in responses if r["type"] == "http.response.body")
        return (
            start["status"],
            dict((k.decode(), v.decode()) for k, v in start["headers"]),
            json.loads(data),
        )

    with asyncio.Runner(loop_factory=lambda: _Loop(selector=_Selector())) as runner:
        return runner.run(execute())


class _Pipe:
    def __init__(self):
        self.messages = []
        self.closed = False

    def send(self, value):
        self.messages.append(value)

    def close(self):
        self.closed = True


class _Worker:
    def __init__(self, messages=(), *, fail_close=False):
        self.messages = list(messages)
        self.closed = False
        self.fail_close = fail_close

    def receive(self):
        return self.messages.pop(0) if self.messages else None

    def alive(self):
        return not self.closed

    def close(self):
        if self.fail_close:
            raise RuntimeError("owned cleanup attack")
        self.closed = True


def _change_approval(session, **changes):
    session._approval = session._approval.model_copy(update=changes)
    session._authorizer = RefreshAuthorizer.for_owned_sources(
        session._approval, session._ledger, clock=session._clock
    )


@pytest.fixture(scope="module", params=[1, 3])
def complete_current(request, tmp_path_factory):
    # Exactly the current_worker entrypoint is executed through the paired ASGI
    # refresh route. Process spawn is covered separately by installed-wheel proof.
    horizon = request.param
    directory = tmp_path_factory.mktemp(f"current-{horizon}")
    session = CurrentRefreshSession.owned(directory / "usage")
    launches, workers, results = [], [], []

    def factory(launch):
        launches.append(launch)
        pipe = _Pipe()
        current_worker(pipe, horizon, launch)
        assert pipe.closed
        results.extend(value.result for kind, value in pipe.messages if kind == "current_result")
        worker = _Worker(pipe.messages)
        workers.append(worker)
        return worker

    runtime = DeskRuntime(
        current_session=session, current_worker_factory=factory, clock=lambda: DEMO_TIME
    )
    app = create_app(runtime=runtime, pairing_code=PAIRING, port=8765)
    _, headers, context = globals()["request"](app, "/api/session", body={"pairing_code": PAIRING})
    cookie = headers.get("set-cookie", "").split(";", 1)[0]
    assert context["synthetic_sources"] and context["execution_mode"] == "PRIVATE_CURRENT"
    status, _, state = globals()["request"](
        app, "/api/refresh", cookie=cookie, body={"horizon": horizon}
    )
    assert status == 200 and state["status"] == "RUNNING"
    for _ in range(20):
        _, _, state = globals()["request"](app, "/api/status", cookie=cookie)
        if state["status"] != "RUNNING":
            break
    assert state["status"] == "COMPLETE", state
    assert len(results) == 1
    yield app, cookie, runtime, session, launches[0], workers[0], results[0], horizon
    runtime.close()


def test_current_browser_full_stack_same_run_projections_components_and_optimizer(complete_current):
    app, cookie, _, _, _, worker, result, horizon = complete_current
    status, headers, view = request(app, "/api/desk", cookie=cookie)
    assert status == 200 and headers["cache-control"].startswith("no-store")
    assert worker.closed and view["dataset_mode"] == "SYNTHETIC_CURRENT_MODE"
    assert (view["catalogue_count"], view["projected_count"], view["blocked_count"]) == (
        121,
        120,
        1,
    )
    assert len(view["gameweeks"]) == horizon
    assert view["team"]["decision"] == result.decision.model_dump(mode="json")
    decision = view["team"]["decision"]
    tactics = decision.get("do_now", decision)["tactics"]
    assert len(tactics["starting_xi"]) == 11 and len(view["team"]["current_squad"]) == 15
    for row in view["players"]:
        if row["catalogue"]["player_id"] is None:
            assert row["expected_points"] is None
            continue
        player = row["catalogue"]["player_id"]
        expected = result.presentation.gameweeks[0].summaries[player]
        assert row["expected_points"] == expected.expected_points
        detail_status, _, detail = request(
            app, f"/api/players/{row['catalogue']['official_id']}", cookie=cookie
        )
        assert detail_status == 200 and detail["job_id"] == view["job_id"]
        for gameweek in result.presentation.gameweeks:
            summary = gameweek.summaries[player]
            assert detail["gameweeks"][str(gameweek.gameweek)] == summary.model_dump(mode="json")
            assert len(summary.component_breakdown) == 13
        if horizon == 3:
            assert row["three_gameweek_expected_points"] == sum(
                g.summaries[player].expected_points for g in result.presentation.gameweeks
            )
    _, _, eligibility = request(app, "/api/eligibility", cookie=cookie)
    assert eligibility["state"] == "ENGINEERING_READY"
    assert eligibility["source_classification"] == "OWNED_SYNTHETIC"
    assert eligibility["qualified_quota_snapshot_remaining"] == 100


def test_current_performance_is_complete_owned_cohort_and_never_real_accuracy(complete_current):
    app, cookie, *_ = complete_current
    _, headers, report = request(app, "/api/performance", cookie=cookie)
    assert headers["cache-control"].startswith("no-store")
    operational = report["operational_report"]
    assert operational["scored_targets"] == operational["expected_targets"] == 8
    assert operational["real_cohort_size"] == 0 and operational["promotion"] == "FORBIDDEN"
    assert len(operational["champion_components"]) == 13
    assert all(row["status"] == "UNAVAILABLE" for row in operational["benchmarks"])
    assert report["real_cohort_status"] == "NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT"


def test_current_reload_does_not_reserve_or_acquire(complete_current):
    app, cookie, _, session, *_ = complete_current
    before = sorted(p.name for p in session._ledger.path.iterdir())
    for _ in range(3):
        _, _, context = request(app, "/api/context", cookie=cookie)
        assert context["synthetic_sources"] and not context["demo"]
        request(app, "/api/eligibility", cookie=cookie)
    assert sorted(p.name for p in session._ledger.path.iterdir()) == before


@pytest.mark.parametrize(
    "attack",
    ["deadline", "capture", "gameweek", "gameweek_hash", "fixture_hash", "resealed_deadline"],
)
def test_current_presentation_cannot_be_replaced_or_resealed(complete_current, attack):
    _, _, _, _, launch, _, result, _ = complete_current
    presentation = result.presentation
    digest = canonical_sha256(presentation.model_dump(mode="json"))
    envelope = CurrentWorkerResult(
        result,
        launch.grant.semantic_sha256,
        digest,
        current_module._result_authentication(launch, result, digest),
    )
    validate_current_result(envelope, launch)
    if attack in {"deadline", "resealed_deadline"}:
        altered = presentation.model_copy(
            update={"deadline_at": presentation.deadline_at + timedelta(seconds=1)}
        )
    elif attack == "capture":
        altered = presentation.model_copy(
            update={"source_captured_at": DEMO_TIME - timedelta(seconds=1)}
        )
    elif attack in {"gameweek", "gameweek_hash"}:
        row = presentation.gameweeks[0].model_copy(
            update={"gameweek": 999} if attack == "gameweek" else {"result_sha256": "0" * 64}
        )
        altered = presentation.model_copy(update={"gameweeks": (row, *presentation.gameweeks[1:])})
    else:
        row = presentation.fixtures[0].model_copy(update={"result_sha256": "0" * 64})
        altered = presentation.model_copy(update={"fixtures": (row, *presentation.fixtures[1:])})
    changed = replace(result, presentation=altered)
    mutated = replace(envelope, result=changed)
    if attack == "resealed_deadline":
        new_digest = canonical_sha256(altered.model_dump(mode="json"))
        mutated = replace(
            mutated,
            presentation_sha256=new_digest,
            authentication_sha256=current_module._result_authentication(
                launch, changed, new_digest
            ),
        )
    with pytest.raises(AuthorizationError, match="WORKER_RESULT_BINDING_INVALID"):
        validate_current_result(mutated, launch)
    if attack != "resealed_deadline":
        # Recomputing an unkeyed presentation digest cannot restore IPC custody.
        with pytest.raises(AuthorizationError, match="WORKER_RESULT_BINDING_INVALID"):
            validate_current_result(
                replace(
                    mutated, presentation_sha256=canonical_sha256(altered.model_dump(mode="json"))
                ),
                launch,
            )


def test_current_bare_unbound_worker_result_is_never_published(complete_current, tmp_path):
    *_, result, horizon = complete_current
    session = CurrentRefreshSession.owned(tmp_path / "usage")
    worker = _Worker([("result", result)])
    runtime = DeskRuntime(
        current_session=session,
        current_worker_factory=lambda launch: worker,
        clock=lambda: DEMO_TIME,
    )
    runtime.refresh(horizon)
    assert runtime.view() is None and worker.closed
    assert runtime.tick().error_code == "RECOMMENDATION_BLOCKED"
    runtime.close()


@pytest.mark.parametrize(
    "attack,expected",
    [
        ("missing", "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED"),
        ("expired", "AUTHORIZATION_EXPIRED"),
        ("revoked", "AUTHORIZATION_REVOKED"),
        ("credentials", "CREDENTIAL_UNAVAILABLE"),
        ("manager", "MANAGER_SCOPE_INVALID"),
        ("profile", "SOURCE_PROFILE_CHANGED"),
        ("quota", "QUOTA_EXHAUSTED"),
        ("deadline", "AUTHORIZATION_DEADLINE_INVALID"),
    ],
)
def test_current_denials_before_worker_or_transport(tmp_path, attack, expected):
    session = CurrentRefreshSession.owned(tmp_path / "usage")
    credentials, workers = [], []
    session._credentials_available = lambda: (credentials.append(True), attack != "credentials")[1]
    if attack == "missing":
        session._approval = None
    elif attack == "expired":
        _change_approval(session, expires_at=DEMO_TIME - timedelta(seconds=1))
    elif attack == "revoked":
        _change_approval(session, status="REVOKED")
    elif attack == "manager":
        session._entry_id = 999
    elif attack == "profile":
        scopes = session._approval.source_scopes
        _change_approval(
            session,
            source_scopes=(scopes[0].model_copy(update={"profile_sha256": "0" * 64}), *scopes[1:]),
        )
    elif attack == "quota":
        _change_approval(
            session,
            plan_quota=session._approval.plan_quota.model_copy(update={"remaining_credits": 1}),
        )
    elif attack == "deadline":
        session._deadline = DEMO_TIME
    runtime = DeskRuntime(
        current_session=session,
        current_worker_factory=lambda launch: workers.append(launch),
        clock=lambda: DEMO_TIME,
    )
    state = runtime.refresh(1)
    assert state.error_code == expected and not workers
    assert credentials == ([True] if attack == "credentials" else [])
    assert runtime.view() is None
    runtime.close()


def test_current_one_shot_is_consumed_before_missing_credential(tmp_path):
    session = CurrentRefreshSession.owned(tmp_path / "usage")
    _change_approval(session, usage="ONE_SHOT")
    session._credentials_available = lambda: False
    with pytest.raises(AuthorizationError, match="CREDENTIAL_UNAVAILABLE"):
        session.prepare(1)
    with pytest.raises(AuthorizationError, match="ONE_SHOT_CONSUMED"):
        session.prepare(1)


def test_current_launch_contains_no_credential_or_raw_source_bytes(tmp_path):
    session = CurrentRefreshSession.owned(tmp_path / "usage")
    launch = session.prepare(1)
    body = pickle.dumps(launch)
    assert b"placeholder" not in body and b"DMF_FPL_BEARER_TOKEN" not in body
    assert b"THE_ODDS_API_KEY" not in body and b"bootstrap-static" in body
    assert b"elements" not in body and b"current_team" not in body
    assert production_approvals() == ()
    assert len(implementation_fingerprint()) == 40
    assert all(len(profile_fingerprint(profile)) == 64 for profile in resolved_profiles().values())


def test_guard_is_single_claim_route_bounded_and_closes_acquisition(tmp_path):
    launch = CurrentRefreshSession.owned(tmp_path / "usage").prepare(1)
    guard = CurrentAcquisitionGuard(launch, lambda: DEMO_TIME)
    route = launch.grant.request.source_scopes[0].routes[0]
    guard.before_send("FPL", "GET", route.host, route.path)
    with pytest.raises(AuthorizationError, match="SOURCE_REQUEST_BUDGET_EXHAUSTED"):
        guard.before_send("FPL", "GET", route.host, route.path)
    with pytest.raises(AuthorizationError, match="SOURCE_ROUTE_NOT_AUTHORIZED"):
        guard.before_send("FPL", "GET", route.host, "/unapproved/")
    with pytest.raises(AuthorizationError, match="REFRESH_GRANT_ALREADY_CLAIMED"):
        CurrentAcquisitionGuard(launch, lambda: DEMO_TIME)
    guard.finish_acquisition()
    with pytest.raises(AuthorizationError, match="ACQUISITION_CLOSED"):
        guard.before_send("FPL", "GET", route.host, route.path)
    guard.check()  # Computation can continue after acquisition closes.


def test_launch_entry_profile_and_code_reject_before_source_factory(tmp_path, monkeypatch):
    launch = CurrentRefreshSession.owned(tmp_path / "usage").prepare(1)
    monkeypatch.setattr(
        current_module,
        "CurrentSourceFactories",
        lambda **kwargs: pytest.fail("source factory reached"),
    )
    for altered, code in [
        (replace(launch, entry_id=999), "MANAGER_SCOPE_INVALID"),
        (
            replace(
                launch,
                grant=launch.grant.model_copy(
                    update={
                        "request": launch.grant.request.model_copy(
                            update={"implementation_sha": "0" * 40}
                        )
                    }
                ),
            ),
            "IMPLEMENTATION_IDENTITY_CHANGED",
        ),
    ]:
        with pytest.raises(AuthorizationError, match=code):
            run_current_recommendation(altered, NullProgress())


@pytest.mark.parametrize(
    "attack", ["manager", "fixture", "market", "unavailable", "invalid-json", "deadline"]
)
def test_actual_current_clients_reject_bad_owned_source_before_model(tmp_path, monkeypatch, attack):
    launch = CurrentRefreshSession.owned(tmp_path / "usage").prepare(1)
    fpl_send, odds_send = OwnedFplTransport.send, OwnedOddsTransport.send
    sends = []

    def fpl(self, request):
        sends.append(("FPL", request.path))
        if attack == "unavailable":
            raise IngestionError("SOURCE_UNAVAILABLE", "owned failure contains no provider value")
        response = fpl_send(self, request)
        body = json.loads(response.body)
        if attack == "invalid-json":
            return DirectHttpResponse(200, "application/json", b"{")
        if attack == "manager" and "/my-team/" in request.path:
            body["picks"][0]["element"] = 999999
        if attack == "fixture" and request.path == "/api/fixtures/":
            body[0]["team_h"] = 999999
        if attack == "deadline" and request.path == "/api/bootstrap-static/":
            for event in body["events"]:
                if event["is_next"]:
                    event["deadline_time"] = (DEMO_TIME - timedelta(seconds=1)).isoformat()
        return DirectHttpResponse(200, "application/json", json.dumps(body).encode())

    def odds(self, request, credential):
        sends.append(("ODDS", request.path))
        response = odds_send(self, request, credential)
        return (
            OddsHttpResponse(response.status_code, response.content_type, response.headers, b"[]")
            if attack == "market"
            else response
        )

    monkeypatch.setattr(OwnedFplTransport, "send", fpl)
    monkeypatch.setattr(OwnedOddsTransport, "send", odds)
    pipe = _Pipe()
    current_worker(pipe, 1, launch)
    assert pipe.closed and not any(
        kind in {"result", "current_result"} for kind, _ in pipe.messages
    )
    assert any(kind == "error" for kind, _ in pipe.messages)
    assert sends and len(sends) <= 9
    if attack in {"invalid-json", "unavailable", "deadline"}:
        assert not any(provider == "ODDS" for provider, _ in sends)
    if attack == "unavailable":
        assert pipe.messages[-1] == ("error", "SOURCE_NOT_AVAILABLE")


@pytest.mark.parametrize("phase", ["Acquiring current FPL state", "Stage9 model execution"])
def test_current_singleflight_cancel_clears_during_acquisition_or_model(tmp_path, phase):
    session = CurrentRefreshSession.owned(tmp_path / "usage")
    workers = []

    def factory(launch):
        worker = _Worker([("progress", phase)])
        workers.append(worker)
        return worker

    runtime = DeskRuntime(
        current_session=session, current_worker_factory=factory, clock=lambda: DEMO_TIME
    )
    first = runtime.refresh(1)
    assert runtime.refresh(3).job_id == first.job_id and len(workers) == 1
    assert runtime.tick().status == "RUNNING"
    assert runtime.cancel().status == "CANCELLED" and workers[0].closed
    assert runtime.view() is None
    runtime.close()


def test_current_deadline_clock_reversal_session_expiry_and_cleanup(tmp_path):
    now = [DEMO_TIME]
    session = CurrentRefreshSession.owned(tmp_path / "usage")
    worker = _Worker()
    runtime = DeskRuntime(
        current_session=session, current_worker_factory=lambda launch: worker, clock=lambda: now[0]
    )
    runtime.refresh(1)
    now[0] += timedelta(seconds=901)
    assert runtime.tick().error_code == "AUTHORIZATION_EXPIRED" and worker.closed
    assert runtime.view() is None
    runtime.close()

    other = CurrentRefreshSession.owned(tmp_path / "other")
    bad = _Worker(fail_close=True)
    runtime = DeskRuntime(
        current_session=other, current_worker_factory=lambda launch: bad, clock=lambda: DEMO_TIME
    )
    runtime.refresh(1)
    runtime.cancel()
    assert runtime.tick().error_code == "WORKER_CLEANUP_FAILED"
    assert runtime.refresh(1).error_code == "SESSION_CLOSED"

    third = CurrentRefreshSession.owned(tmp_path / "third")
    worker = _Worker()
    elapsed = [0.0]
    runtime = DeskRuntime(
        current_session=third, current_worker_factory=lambda launch: worker, clock=lambda: DEMO_TIME
    )
    app = create_app(
        runtime=runtime, pairing_code=PAIRING, port=8765, elapsed_clock=lambda: elapsed[0]
    )
    _, headers, _ = request(app, "/api/session", body={"pairing_code": PAIRING})
    cookie = headers.get("set-cookie", "").split(";", 1)[0]
    request(app, "/api/refresh", cookie=cookie, body={"horizon": 1})
    elapsed[0] = 3601
    response_status, _, _ = request(app, "/api/status", cookie=cookie)
    assert response_status == 401 and worker.closed
    runtime.close()


def test_unenrolled_production_cannot_resolve_control_database_or_credentials(monkeypatch):
    monkeypatch.setattr(
        current_module, "_postgres_ledger", lambda *args: pytest.fail("database reached")
    )
    monkeypatch.setattr(
        current_module, "_credentials_available", lambda: pytest.fail("credentials reached")
    )
    with pytest.raises(AuthorizationError, match="RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED"):
        CurrentRefreshSession.enrolled(
            authorization_id="NOT-ENROLLED", entry_id=42, deadline_at=DEMO_TIME
        )


@pytest.mark.parametrize("qualified", [None, DEMO_TIME + timedelta(days=2)])
def test_enrolled_deadline_must_match_trusted_scope_before_database(
    tmp_path, monkeypatch, qualified
):
    owned = CurrentRefreshSession.owned(tmp_path / "usage")
    approval = owned._approval.model_copy(
        update={
            "classification": "PRIVATE_CURRENT",
            "ledger_backend": "POSTGRES",
            "qualified_deadline_at": qualified,
            "source_scopes": tuple(
                row.model_copy(update={"source_kind": "RIGHTS_QUALIFIED_PRIVATE"})
                for row in owned._approval.source_scopes
            ),
        }
    )
    monkeypatch.setattr(current_module, "production_approvals", lambda: (approval,))
    monkeypatch.setattr(
        current_module, "_postgres_ledger", lambda *args: pytest.fail("database reached")
    )
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_DEADLINE_SCOPE_MISMATCH"):
        CurrentRefreshSession.enrolled(
            authorization_id=approval.authorization_id,
            entry_id=42,
            deadline_at=DEMO_TIME + timedelta(days=1),
        )


def test_content_fingerprint_excludes_exact_enrollment_metadata_only(tmp_path, monkeypatch):
    root = tmp_path / "owned-package"
    metadata = root / "dashboard" / "resources" / "production_refresh_enrollments.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("owned metadata v1", encoding="utf-8")
    code = root / "authorization.py"
    code.write_text("owned executable v1", encoding="utf-8")
    resource = metadata.with_name("another_policy.json")
    resource.write_text("owned policy v1", encoding="utf-8")
    monkeypatch.setattr(current_module, "files", lambda name: root)
    initial = implementation_fingerprint()
    metadata.write_text("owned metadata v2", encoding="utf-8")
    assert implementation_fingerprint() == initial
    code.write_text("owned executable v2", encoding="utf-8")
    after_code = implementation_fingerprint()
    assert after_code != initial
    resource.write_text("owned policy v2", encoding="utf-8")
    assert implementation_fingerprint() != after_code
