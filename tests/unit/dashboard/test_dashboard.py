"""Real-stack synthetic browser API acceptance plus adversarial lifecycle/security."""

from __future__ import annotations

import asyncio
import json
import selectors
from dataclasses import replace
from datetime import timedelta
from importlib.resources import files

import pytest

from dmf_pulse.dashboard.app import create_app
from dmf_pulse.dashboard.runtime import DeskRuntime, PipeProgress
from dmf_pulse.dashboard.synthetic import DEMO_TIME, demo_inputs, run_synthetic_recommendation
from dmf_pulse.dashboard.views import desk_view
from dmf_pulse.private_v1.presentation import CataloguePlayer, GameweekPresentation
from dmf_pulse.private_v1.progress import NullProgress

pytestmark = pytest.mark.unit
CODE = "synthetic-pairing-code-acceptance-only"


class _NoIoSelector(selectors.SelectSelector):
    def select(self, timeout=None):
        assert not self.get_map(), "ASGI acceptance must use no socket/file transport"
        return []


class _NoIoLoop(asyncio.SelectorEventLoop):
    # CPython's Windows socketpair fallback calls TCP connect even for its own
    # wakeup pipe. These entirely in-memory ASGI requests need no cross-thread IO.
    # Keep the repository socket/DNS guard intact, and reject any registered FD.
    def _make_self_pipe(self):
        self._ssock = self._csock = None

    def _close_self_pipe(self):
        return


@pytest.fixture(scope="module")
def model_run():
    # Injected packaged provider-shaped sources; real Stage 7/8/9/10/11, no sockets.
    return run_synthetic_recommendation(1, NullProgress())


class Worker:
    def __init__(self, messages=(), *, alive=True, fail_close=False):
        self.messages = list(messages)
        self.running = alive
        self.fail_close = fail_close
        self.closed = False

    def receive(self):
        return self.messages.pop(0) if self.messages else None

    def alive(self):
        return self.running

    def close(self):
        if self.fail_close:
            raise RuntimeError("synthetic cleanup failure")
        self.running = False
        self.closed = True


def runtime_for(result, **kwargs):
    worker = Worker([("progress", "Stage 9 complete"), ("result", result)])
    runtime = DeskRuntime(
        demo=True, clock=lambda: DEMO_TIME, worker_factory=lambda _: worker, **kwargs
    )
    return runtime, worker


def request(
    app, path, *, method="GET", body=None, browser_header=None, headers=None, client="127.0.0.1"
):
    async def execute():
        payload = (
            b"" if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
        )
        request_headers = {"host": "127.0.0.1:8765"}
        if method == "POST":
            request_headers.update(
                {
                    "origin": "http://127.0.0.1:8765",
                    "content-type": "application/json",
                    "x-dmf-action": "operator",
                }
            )
        if browser_header:
            request_headers["cookie"] = browser_header
        request_headers.update(headers or {})
        query = b""
        clean_path = path
        if "?" in path:
            clean_path, query_text = path.split("?", 1)
            query = query_text.encode()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": clean_path,
            "raw_path": clean_path.encode(),
            "query_string": query,
            "root_path": "",
            "headers": [(key.encode(), value.encode()) for key, value in request_headers.items()],
            "client": (client, 12345),
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
        start = next(item for item in responses if item["type"] == "http.response.start")
        output = b"".join(
            item.get("body", b"") for item in responses if item["type"] == "http.response.body"
        )
        return start["status"], dict((k.decode(), v.decode()) for k, v in start["headers"]), output

    with asyncio.Runner(loop_factory=lambda: _NoIoLoop(selector=_NoIoSelector())) as runner:
        return runner.run(execute())


def pair(app):
    status, headers, body = request(app, "/api/session", method="POST", body={"pairing_code": CODE})
    assert status == 200, body
    assert "HttpOnly" in headers["set-cookie"] and "SameSite=strict" in headers["set-cookie"]
    return headers["set-cookie"].split(";", 1)[0]


def test_real_stack_refresh_player_table_detail_comparison_and_evaluation(model_run):
    runtime, worker = runtime_for(model_run)
    app = create_app(runtime=runtime, pairing_code=CODE, port=8765)
    cookie = pair(app)
    assert (
        request(app, "/api/refresh", method="POST", browser_header=cookie, body={"horizon": 1})[0]
        == 200
    )
    status, headers, body = request(app, "/api/desk", browser_header=cookie)
    assert status == 200 and headers["cache-control"].startswith("no-store")
    view = json.loads(body)
    assert view["catalogue_count"] == 121 and view["projected_count"] == 120
    assert view["blocked_count"] == 1 and view["dataset_mode"] == "SYNTHETIC_DEMONSTRATION"
    assert view["team"]["decision"] == model_run.decision.model_dump(mode="json")
    assert len(view["team"]["decision"]["tactics"]["starting_xi"]) == 11
    assert len(view["team"]["current_squad"]) == 15
    assert worker.closed
    presentation = model_run.presentation
    for row in view["players"]:
        if row["catalogue"]["player_id"] is None:
            assert (
                row["expected_points"] is None
                and row["catalogue"]["unavailable_reason"] == "REMOVED_UNMAPPED"
            )
            continue
        summary = presentation.gameweeks[0].summaries[row["catalogue"]["player_id"]]
        assert row["expected_points"] == summary.expected_points
        assert row["three_gameweek_expected_points"] is None
    first, second = (row["catalogue"]["official_id"] for row in view["players"][:2])
    status, _, body = request(app, f"/api/players/{first}", browser_header=cookie)
    assert status == 200
    detail = json.loads(body)
    player_id = detail["catalogue"]["player_id"]
    assert detail["gameweeks"]["2"] == presentation.gameweeks[0].summaries[player_id].model_dump(
        mode="json"
    )
    assert len(detail["gameweeks"]["2"]["component_breakdown"]) == 13
    assert request(app, f"/api/compare/{first}/{second}", browser_header=cookie)[0] == 200
    assert request(app, f"/api/compare/{first}/{first}", browser_header=cookie)[0] == 422
    assert request(app, "/api/players/99999999", browser_header=cookie)[0] == 404
    report = json.loads(request(app, "/api/performance", browser_header=cookie)[2])
    assert report["real_cohort_status"] == "NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT"
    assert report["synthetic_report"]["count"] == 8
    assert b"placeholder" not in body
    runtime.close()


@pytest.mark.parametrize(
    "path,method,headers,client,expected",
    [
        ("/api/status", "GET", {}, "127.0.0.1", 401),
        ("/", "GET", {"host": "evil.example:8765"}, "127.0.0.1", 403),
        ("/", "GET", {}, "192.168.0.2", 403),
        ("/?secret=value", "GET", {}, "127.0.0.1", 403),
        ("/", "GET", {"forwarded": "host=evil"}, "127.0.0.1", 403),
        ("/", "GET", {"x-forwarded-host": "evil"}, "127.0.0.1", 403),
        ("/", "GET", {"origin": "https://evil.example"}, "127.0.0.1", 403),
        ("/", "GET", {"sec-fetch-site": "cross-site"}, "127.0.0.1", 403),
        ("/api/session", "POST", {"x-dmf-action": "wrong"}, "127.0.0.1", 403),
        ("/api/session", "POST", {"content-type": "text/plain"}, "127.0.0.1", 403),
        ("/api/session", "POST", {"origin": "null"}, "127.0.0.1", 403),
        ("/", "DELETE", {}, "127.0.0.1", 405),
    ],
)
def test_loopback_auth_origin_csrf_and_headers(path, method, headers, client, expected):
    app = create_app(runtime=DeskRuntime(), pairing_code=CODE, port=8765)
    status, response_headers, _ = request(
        app, path, method=method, headers=headers, client=client, body={}
    )
    assert status == expected
    assert response_headers["cache-control"].startswith("no-store")
    assert "frame-ancestors 'none'" in response_headers["content-security-policy"]


def test_pairing_validation_rate_bound_assets_live_block_and_logout():
    calls = []
    runtime = DeskRuntime(worker_factory=lambda horizon: calls.append(horizon))
    app = create_app(runtime=runtime, pairing_code=CODE, port=8765)
    assert request(app, "/api/session", method="POST", body={"pairing_code": True})[0] == 422
    cookie = pair(app)
    assert request(app, "/api/session", method="POST", body={"pairing_code": CODE})[0] == 403
    for name in ("desk.js", "desk.css"):
        assert request(app, f"/assets/{name}")[0] == 200
    assert request(app, "/assets/secret.json")[0] == 404
    assert request(app, "/")[0] == 200
    for horizon in (True, False, "1", 2, 4):
        assert (
            request(
                app, "/api/refresh", method="POST", body={"horizon": horizon}, browser_header=cookie
            )[0]
            == 422
        )
    result = json.loads(
        request(app, "/api/refresh", method="POST", body={"horizon": 1}, browser_header=cookie)[2]
    )
    assert result["error_code"] == "RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED" and calls == []
    assert request(app, "/api/desk", browser_header=cookie)[0] == 409
    assert request(app, "/api/performance", browser_header=cookie)[0] == 200
    assert request(app, "/api/cancel", method="POST", body={}, browser_header=cookie)[0] == 200
    assert request(app, "/api/logout", method="POST", body={}, browser_header=cookie)[0] == 200
    assert request(app, "/api/status", browser_header=cookie)[0] == 401
    app2 = create_app(runtime=DeskRuntime(), pairing_code=CODE, port=8765)
    for _ in range(6):
        assert (
            request(app2, "/api/session", method="POST", body={"pairing_code": "incorrect"})[0]
            == 403
        )
    assert request(app2, "/api/session", method="POST", body={"pairing_code": CODE})[0] == 403
    assert request(app2, "/api/session", method="POST", body=b"x" * 4097)[0] == 413


def test_singleflight_cancel_timeout_failure_and_poisoned_cleanup():
    calls = []
    worker = Worker()
    runtime = DeskRuntime(
        demo=True, worker_factory=lambda horizon: (calls.append(horizon), worker)[1]
    )
    first = runtime.refresh(1)
    assert runtime.refresh(3).job_id == first.job_id and calls == [1]
    runtime.cancel()
    assert worker.closed and runtime.view() is None
    runtime.close()
    assert runtime.refresh(1).error_code == "SESSION_CLOSED"
    elapsed = [0.0]
    worker = Worker()
    runtime = DeskRuntime(
        demo=True,
        worker_factory=lambda _: worker,
        elapsed_clock=lambda: elapsed[0],
        run_timeout_seconds=1,
    )
    runtime.refresh(1)
    elapsed[0] = 1.0
    assert runtime.tick().error_code == "RUN_TIMEOUT" and worker.closed
    broken = Worker(fail_close=True)
    calls.clear()
    runtime = DeskRuntime(demo=True, worker_factory=lambda h: (calls.append(h), broken)[1])
    runtime.refresh(1)
    assert runtime.cancel().error_code == "WORKER_CLEANUP_FAILED"
    assert runtime.refresh(3).error_code == "SESSION_CLOSED" and calls == [1]
    assert runtime._worker is broken
    broken.fail_close = False
    runtime.close()
    assert broken.closed


@pytest.mark.parametrize(
    "messages,alive,code",
    [
        ([("error", "never disclose this marker")], True, "RECOMMENDATION_BLOCKED"),
        ([], False, "WORKER_STOPPED"),
        ([("result", object())], True, "RECOMMENDATION_BLOCKED"),
    ],
)
def test_safe_worker_failures(messages, alive, code):
    worker = Worker(messages, alive=alive)
    runtime = DeskRuntime(demo=True, worker_factory=lambda _: worker)
    runtime.refresh(1)
    assert runtime.tick().error_code == code and worker.closed


def test_expiry_rollback_changed_report_and_missingness(model_run):
    elapsed = [0.0]
    runtime, _ = runtime_for(model_run, elapsed_clock=lambda: elapsed[0], lifetime_seconds=10)
    runtime.refresh(1)
    assert runtime.view().expires_in_seconds == 10
    elapsed[0] = 7
    assert runtime.view().expires_in_seconds == 3
    elapsed[0] = 10
    assert runtime.view() is None and runtime.tick().status == "EXPIRED"
    for invalid in (replace(model_run, report="changed"), replace(model_run, presentation=None)):
        runtime, worker = runtime_for(invalid)
        runtime.refresh(1)
        assert runtime.view() is None and worker.closed
    clock = [DEMO_TIME]
    runtime = DeskRuntime(
        demo=True, clock=lambda: clock[0], worker_factory=lambda _: Worker([("result", model_run)])
    )
    runtime.refresh(1)
    assert runtime.view() is not None
    clock[0] -= timedelta(seconds=1)
    assert runtime.view() is None and runtime.tick().status == "BLOCKED"
    presentation = model_run.presentation
    removed = CataloguePlayer(
        official_id=99998,
        player_id=None,
        name="Synthetic removed",
        team="Synthetic",
        position="MID",
        price_tenths=50,
        unavailable_reason="REMOVED_UNMAPPED",
    )
    modified = replace(
        model_run,
        presentation=presentation.model_copy(
            update={"catalogue": (*presentation.catalogue, removed)}
        ),
    )
    view = desk_view(
        modified,
        job_id="synthetic",
        mode="SYNTHETIC_DEMONSTRATION",
        generated_at=DEMO_TIME,
        expires_at=DEMO_TIME + timedelta(minutes=1),
    )
    assert (
        view.catalogue_count == 122
        and view.blocked_count == 2
        and view.players[-1].expected_points is None
    )
    summary = presentation.gameweeks[0]
    bad = next(iter(summary.summaries.values())).model_copy(update={"expected_points": 999.0})
    with pytest.raises(ValueError, match="reconcile"):
        GameweekPresentation.model_validate(
            {**summary.model_dump(), "summaries": {bad.player_id: bad}}
        )


def test_import_assets_and_progress_contract():
    assert len(demo_inputs()) == 14
    script = files("dmf_pulse.dashboard.resources").joinpath("desk.js").read_text(encoding="utf-8")
    assert "localStorage" not in script and "indexedDB" not in script
    messages = []
    progress = PipeProgress(messages.append)
    with progress.stage(started="Stage 7", completed="Ready", failed="Failed"):
        progress.message("Running")
    progress.failure("stage", "SAFE_CODE")
    progress.finish()
    assert progress.failure_reported and [m[1] for m in messages] == [
        "Stage 7",
        "Running",
        "Ready",
        "Completed",
    ]
    with pytest.raises(ValueError):
        DeskRuntime(lifetime_seconds=901)
    with pytest.raises(ValueError):
        create_app(runtime=DeskRuntime(), pairing_code="short", port=8765)
