"""Copied installed-wheel acceptance: paired ASGI, actual spawn worker and owned CLI custody."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import multiprocessing
import os
import re
import selectors
import socket
import sys
import tempfile
from pathlib import Path
from time import monotonic, sleep
from typing import Any

# Only these source/custody identities may differ between two independently
# authenticated input families. Every other field, including ALL numerical
# projection/PMF/covariance/minutes/decision fields and model/rules ids, is exact.
CUSTODY_PATTERNS = (
    "/decision/run_id",
    "/decision/semantic_sha256",
    "/decision/lineage/code_sha",
    "/decision/lineage/current_state_sha256",
    "/decision/lineage/current_manager_state_sha256",
    "/decision/lineage/market_constraints_sha256",
    "/decision/lineage/score_prior_sha256_by_fixture/*",
    "/decision/lineage/stage8_result_sha256_by_fixture/*",
    "/decision/lineage/stage9_result_sha256",
    "/decision/lineage/private_rules_authority_sha256",
    "/decision/lineage/execution_input_sha256",
    "/decision/lineage/optimiser_request_sha256",
    "/decision/lineage/optimiser_result_sha256",
    "/decision/lineage/rolling_execution_input_sha256",
    "/decision/lineage/current_execution_input_sha256",
    "/decision/lineage/stage8_distribution_sha256_by_gameweek/*/*",
    "/decision/lineage/fixture_projection_sha256_by_gameweek/*/*",
    "/decision/lineage/gameweek_projection_sha256_by_gameweek/*",
    "/decision/lineage/future_gameweek_input_sha256_by_gameweek/*",
    "/decision/lineage/scenario_tree_sha256",
    "/decision/lineage/one_gameweek_optimiser_result_sha256",
    "/decision/transfer_frontier/semantic_sha256",
    "/decision/transfer_frontier/optimiser_request_sha256",
    "/decision/transfer_frontier/optimiser_result_sha256",
    "/decision/transfer_frontier/stage9_projection_sha256",
    "/decision/transfer_frontier/points/*/semantic_sha256",
    "/decision/transfer_frontier/points/*/stage11_plan_sha256",
    "/decision/do_now/tactical_plan_sha256",
    "/decision/by_gameweek/*/tactical_plan_sha256",
    "/decision/future_plan/*/tactical_plan_sha256",
    "/presentation/fixtures/*/result_sha256",
    "/presentation/fixtures/*/summaries/*/source_bundle_ids",
    "/presentation/fixtures/*/summaries/*/upstream_stage8_sha256",
    "/presentation/gameweeks/*/result_sha256",
    "/presentation/gameweeks/*/summaries/*/source_bundle_ids",
    "/presentation/gameweeks/*/summaries/*/upstream_stage8_sha256s",
    "/presentation/source_vintages/*/identity_sha256",
)
DISCLOSURE_PATHS = (
    "/decision/action_space_disclosure",
    "/decision/transfer_frontier/action_space_disclosure",
)
SCREEN_TOKEN = re.compile(r"; screen SHA256: ([0-9a-f]{64}); ")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _matches(path: str, pattern: str) -> bool:
    return re.fullmatch(re.escape(pattern).replace(r"\*", "[^/]+"), path) is not None


def compare_exact(left: object, right: object) -> dict[str, Any]:
    """No tolerance and no broad suffix/lineage dropping; retain every mismatch."""
    excluded: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    numeric_fields = 0
    checked_fields = 0

    def visit(a: Any, b: Any, path: str) -> None:
        nonlocal numeric_fields, checked_fields
        if a != b and path in DISCLOSURE_PATHS and isinstance(a, str) and isinstance(b, str):
            # Screening receipts hash source/run custody. All action-space text,
            # numeric counts, declared policy and exactness limits remain exact.
            aa, bb = SCREEN_TOKEN.findall(a), SCREEN_TOKEN.findall(b)
            if len(aa) == len(bb) == 1 and SCREEN_TOKEN.sub(
                "; screen SHA256: <custody>; ", a
            ) == SCREEN_TOKEN.sub("; screen SHA256: <custody>; ", b):
                checked_fields += 1
                excluded.append(
                    {
                        "path": path,
                        "left": a,
                        "right": b,
                        "reason": "single embedded screening custody SHA only",
                    }
                )
                return
        if a != b and any(_matches(path, pattern) for pattern in CUSTODY_PATTERNS):
            values = [*a, *b] if isinstance(a, list) and isinstance(b, list) else [a, b]
            if path.endswith("/run_id"):
                valid = all(
                    isinstance(value, str) and value.startswith("ACCEL00") for value in values
                )
            else:
                valid = all(
                    isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value)
                    for value in values
                )
            if valid and (not isinstance(a, list) or len(a) == len(b)):
                excluded.append({"path": path, "left": a, "right": b})
                return
        # The two owned market fixtures have explicit different quota header
        # vintages. This is control metadata, never a forecast numerical field.
        if path == "/presentation/market_quota_remaining" and (a, b) == (98, 100):
            excluded.append(
                {
                    "path": path,
                    "left": a,
                    "right": b,
                    "reason": "owned current response headers98; accepted compiled demo100",
                }
            )
            return
        if isinstance(a, dict) and isinstance(b, dict):
            if a.keys() != b.keys():
                mismatches.append(
                    {"path": path, "reason": "keys", "left": sorted(a), "right": sorted(b)}
                )
            for key in sorted(a.keys() & b.keys()):
                visit(a[key], b[key], path + "/" + str(key))
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                mismatches.append(
                    {"path": path, "reason": "length", "left": len(a), "right": len(b)}
                )
            for index, (aa, bb) in enumerate(zip(a, b, strict=False)):
                visit(aa, bb, path + "/" + str(index))
        else:
            checked_fields += 1
            if type(a) in (int, float) or type(b) in (int, float):
                numeric_fields += 1
            if a != b or type(a) is not type(b):
                mismatches.append({"path": path, "reason": "value_or_type", "left": a, "right": b})

    visit(left, right, "")
    return {
        "checked_fields": checked_fields,
        "numeric_fields": numeric_fields,
        "excluded": excluded,
        "mismatches": mismatches,
    }


def _control_root() -> Path:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-root", type=Path, required=True)
    return parser.parse_args().control_root.resolve()


def _install_network_guard() -> None:
    """Spawn executes this script as __mp_main__ before importing its target."""
    root = _control_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"network-guard-{os.getpid()}.json"
    state: dict[str, Any] = {
        "role": __name__,
        "pid": os.getpid(),
        "self_test_denials": 0,
        "unexpected_denials": 0,
    }
    testing = True

    def audit(event: str, args: tuple[object, ...]) -> None:
        del args  # Never retain socket addresses, URLs, bodies or credentials.
        if event in {
            "socket.connect",
            "socket.bind",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyaddr",
        }:
            state["self_test_denials" if testing else "unexpected_denials"] += 1
            path.write_bytes(_canonical(state))
            raise RuntimeError("OWNED_ACCEPTANCE_NETWORK_BLOCKED")

    sys.addaudithook(audit)
    try:
        socket.getaddrinfo("owned-acceptance.invalid", 0)
    except RuntimeError as error:
        assert str(error) == "OWNED_ACCEPTANCE_NETWORK_BLOCKED"
    else:
        raise AssertionError("network audit guard self-test did not reject DNS")
    testing = False
    assert state["self_test_denials"] == 1


class _NoIoSelector(selectors.SelectSelector):
    def select(self, timeout: float | None = None) -> list[Any]:
        del timeout
        assert not self.get_map(), "in-memory ASGI acceptance registered an IO descriptor"
        return []


class _NoIoLoop(asyncio.SelectorEventLoop):
    def _make_self_pipe(self) -> None:
        self._ssock = self._csock = None

    def _close_self_pipe(self) -> None:
        return


def request(
    app: Any, path: str, *, method: str = "GET", body: object = None, cookie: str | None = None
) -> tuple[int, dict[str, str], bytes]:
    async def execute() -> tuple[int, dict[str, str], bytes]:
        headers = {"host": "127.0.0.1:8765"}
        if method == "POST":
            headers.update(
                {
                    "origin": "http://127.0.0.1:8765",
                    "content-type": "application/json",
                    "x-dmf-action": "operator",
                }
            )
        if cookie:
            headers["cookie"] = cookie
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8765),
        }
        sent = False
        wait = asyncio.Event()
        responses = []

        async def receive() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {
                    "type": "http.request",
                    "body": b"" if body is None else _canonical(body),
                    "more_body": False,
                }
            await wait.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            responses.append(message)

        await app(scope, receive, send)
        start = next(value for value in responses if value["type"] == "http.response.start")
        output = b"".join(
            value.get("body", b"") for value in responses if value["type"] == "http.response.body"
        )
        return (
            start["status"],
            {key.decode(): value.decode() for key, value in start["headers"]},
            output,
        )

    with asyncio.Runner(loop_factory=lambda: _NoIoLoop(selector=_NoIoSelector())) as runner:
        return runner.run(execute())


def _case(horizon: int, root: Path) -> dict[str, Any]:
    from dmf_pulse.dashboard.current import CurrentRefreshSession

    from dmf_pulse.dashboard.app import create_app
    from dmf_pulse.dashboard.runtime import DeskRuntime, ProcessWorker
    from dmf_pulse.dashboard.synthetic import DEMO_TIME
    from dmf_pulse.private_v1.one_command import OneCommandResult

    started = monotonic()
    runtime = DeskRuntime(
        current_session=CurrentRefreshSession.owned(root / f"ledger-{horizon}"),
        clock=lambda: DEMO_TIME,
    )
    app = create_app(runtime=runtime, pairing_code="owned-current-wheel-pairing-only", port=8765)
    reference = None
    try:
        assert request(app, "/api/desk")[0] == 401
        status, headers, body = request(
            app,
            "/api/session",
            method="POST",
            body={"pairing_code": "owned-current-wheel-pairing-only"},
        )
        assert status == 200
        context = json.loads(body)
        assert (
            context["execution_mode"] == "PRIVATE_CURRENT" and context["synthetic_sources"] is True
        )
        assert context["demo"] is False
        cookie = headers.get("set-cookie", "").split(";", 1)[0]
        status, _, body = request(
            app, "/api/refresh", method="POST", body={"horizon": horizon}, cookie=cookie
        )
        assert status == 200 and json.loads(body)["status"] == "RUNNING"
        job = json.loads(body)["job_id"]
        worker = runtime._worker
        assert isinstance(worker, ProcessWorker)
        child_pid = worker._process.pid
        assert child_pid is not None and child_pid != os.getpid()
        # Run the accepted CLI synthetic service in its unchanged default
        # process concurrently, polling both pipes so large results cannot block.
        reference = ProcessWorker(horizon)
        reference_pid = reference._process.pid
        baseline = None
        assert (
            json.loads(
                request(
                    app, "/api/refresh", method="POST", body={"horizon": horizon}, cookie=cookie
                )[2]
            )["job_id"]
            == job
        )
        while monotonic() - started < 890:
            status, _, body = request(app, "/api/status", cookie=cookie)
            state = json.loads(body)
            if reference is not None:
                for _ in range(64):
                    message = reference.receive()
                    if message is None:
                        break
                    kind, payload = message
                    if kind == "result":
                        assert isinstance(payload, OneCommandResult)
                        baseline = payload
                        reference.close()
                        reference = None
                        break
                    assert kind == "progress", (kind, payload)
            if state["status"] != "RUNNING" and (
                state["status"] != "COMPLETE" or baseline is not None
            ):
                break
            sleep(0.05)
        assert status == 200 and state["status"] == "COMPLETE", state
        assert runtime._worker is None
        result = runtime._result
        assert result is not None and result.presentation is not None
        assert result.fpl_request_count == 8 and result.persistence_performed is False
        status, headers, body = request(app, "/api/desk", cookie=cookie)
        assert status == 200 and "no-store" in headers["cache-control"]
        desk = json.loads(body)
        assert desk["dataset_mode"] == "SYNTHETIC_CURRENT_MODE"
        assert (desk["catalogue_count"], desk["projected_count"], desk["blocked_count"]) == (
            121,
            120,
            1,
        )
        assert len(desk["gameweeks"]) == horizon and len(desk["team"]["current_squad"]) == 15
        assert desk["team"]["decision"] == result.decision.model_dump(mode="json")
        detail_count = 0
        for row in desk["players"]:
            status, _, body = request(
                app, f"/api/players/{row['catalogue']['official_id']}", cookie=cookie
            )
            assert status == 200
            detail = json.loads(body)
            if row["catalogue"]["player_id"] is None:
                assert detail["gameweeks"] == {}
                continue
            for gameweek in result.presentation.gameweeks:
                expected = gameweek.summaries[row["catalogue"]["player_id"]].model_dump(mode="json")
                assert detail["gameweeks"][str(gameweek.gameweek)] == expected
                detail_count += 1
        model_seconds = monotonic() - started
        assert baseline is not None and baseline.presentation is not None
        parity = compare_exact(
            {
                "decision": result.decision.model_dump(mode="json"),
                "presentation": result.presentation.model_dump(mode="json"),
            },
            {
                "decision": baseline.decision.model_dump(mode="json"),
                "presentation": baseline.presentation.model_dump(mode="json"),
            },
        )
        parity_path = root / f"parity-{horizon}.json"
        parity_path.write_bytes(_canonical(parity))
        assert not parity["mismatches"], {
            "parity_mismatches": parity["mismatches"][:10],
            "retained": parity_path.name,
        }
        records = [
            json.loads(path.read_bytes())
            for path in (root / f"ledger-{horizon}").glob("[0-9]*.json")
        ]
        assert sum(row["kind"] == "RESERVATION" for row in records) == 1
        assert sum(row["kind"] == "CLAIM" for row in records) == 1
        assert sum(row["kind"] == "ATTEMPT" for row in records) == 13
        logout_status, _, _ = request(app, "/api/logout", method="POST", body={}, cookie=cookie)
        assert logout_status == 200
        unauthenticated_status, _, _ = request(app, "/api/desk", cookie=cookie)
        assert unauthenticated_status == 401
        assert runtime._result is None and runtime._worker is None
        assert all(child.pid != child_pid for child in multiprocessing.active_children())
        return {
            "horizon": horizon,
            "catalogue": 121,
            "projected": 120,
            "blocked": 1,
            "player_gameweek_details_equal": detail_count,
            "actual_spawn_child_pid": child_pid,
            "reference_spawn_child_pid": reference_pid,
            "reference_service": "DEFAULT_DEMO_PROCESS_ACCEPTED_CLI_SYNTHETIC",
            "default_process_worker": True,
            "same_run_browser_decision_equal": True,
            "all_numeric_projection_and_decision_fields_exact": True,
            "checked_fields": parity["checked_fields"],
            "numeric_fields": parity["numeric_fields"],
            "custody_exclusion_count": len(parity["excluded"]),
            "custody_inventory_sha256": hashlib.sha256(parity_path.read_bytes()).hexdigest(),
            "owned_transport_attempts": {"FPL": 8, "ODDS": 1, "OPENFOOTBALL": 4},
            "external_provider_requests": 0,
            "worker_seconds": model_seconds,
            "case_seconds": monotonic() - started,
            "cleanup": "CONFIRMED",
        }
    finally:
        if reference is not None:
            reference.close()
        runtime.close()


def _cli(root: Path) -> dict[str, Any]:
    from dmf_pulse.player_evidence.demo import owned_demo
    from dmf_pulse.player_lab.runner import operational_synthetic_evaluation
    from typer.testing import CliRunner

    from dmf_pulse.cli.app import app

    runner = CliRunner()
    cohort, labels, report = (
        root / name for name in ("cohort.json", "labels.json", "evaluation.json")
    )
    commands = [
        ["player-lab", "freeze-owned", "--output", str(cohort)],
        ["player-lab", "labels-owned", "--cohort", str(cohort), "--output", str(labels)],
        [
            "player-lab",
            "score",
            "--cohort",
            str(cohort),
            "--labels",
            str(labels),
            "--output",
            str(report),
        ],
    ]
    for command in commands:
        value = runner.invoke(app, command)
        assert value.exit_code == 0, {
            "command": command[:2],
            "exit_code": value.exit_code,
            "output": value.output[:500],
        }
    expected = operational_synthetic_evaluation()
    actual = json.loads(report.read_bytes())
    assert actual == expected.model_dump(mode="json")
    assert actual["real_cohort_size"] == 0 and actual["promotion"] == "FORBIDDEN"
    value = runner.invoke(app, ["player-evidence", "demo"])
    assert value.exit_code == 0
    evidence = owned_demo()
    assert json.loads(value.stdout) == {
        **evidence.model_dump(mode="json"),
        "semantic_sha256": evidence.semantic_sha256,
    }
    return {
        "cohort_freeze_labels_score": "PASS",
        "report_exact_service_equality": True,
        "scored_targets": actual["scored_targets"],
        "real_cohort_size": 0,
        "player_evidence_exact_service_equality": True,
        "player_evidence_players": len(evidence.players),
    }


def _paused_current_worker(pipe: Any, horizon: int, launch: Any, phase: str) -> None:
    """Owned-only process harness; no product pause flag or alternate engine."""
    from dmf_pulse.dashboard.current import current_worker
    from dmf_pulse.dashboard.current_sources import OwnedFplTransport

    from dmf_pulse.private_v1.service import PrivateV1RecommendationService

    assert launch.grant.classification == "OWNED_SYNTHETIC"

    def pause(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pipe.send(("progress", f"OWNED_TEST_{phase.upper()}_PAUSED"))
        multiprocessing.Event().wait(90)
        raise AssertionError("owned cancellation probe was not terminated")

    if phase == "acquisition":
        OwnedFplTransport.send = pause
    elif phase == "modelling":
        PrivateV1RecommendationService.run = pause
    else:
        raise AssertionError("unknown owned cancellation phase")
    current_worker(pipe, horizon, launch)


def _cancellation(phase: str, root: Path) -> dict[str, Any]:
    from dmf_pulse.dashboard.current import CurrentRefreshSession

    from dmf_pulse.dashboard.app import create_app
    from dmf_pulse.dashboard.runtime import DeskRuntime, ProcessWorker
    from dmf_pulse.dashboard.synthetic import DEMO_TIME

    started = monotonic()

    def factory(launch: Any) -> ProcessWorker:
        return ProcessWorker(1, _target=_paused_current_worker, _arguments=(launch, phase))

    runtime = DeskRuntime(
        current_session=CurrentRefreshSession.owned(root / f"cancel-{phase}"),
        current_worker_factory=factory,
        clock=lambda: DEMO_TIME,
        run_timeout_seconds=90,
    )
    app = create_app(runtime=runtime, pairing_code="owned-cancel-wheel-pairing-only", port=8765)
    try:
        code, headers, _ = request(
            app,
            "/api/session",
            method="POST",
            body={"pairing_code": "owned-cancel-wheel-pairing-only"},
        )
        assert code == 200
        cookie = headers.get("set-cookie", "").split(";", 1)[0]
        code, _, _ = request(app, "/api/refresh", method="POST", body={"horizon": 1}, cookie=cookie)
        assert code == 200
        worker = runtime._worker
        assert isinstance(worker, ProcessWorker)
        child_pid = worker._process.pid
        marker = f"OWNED_TEST_{phase.upper()}_PAUSED"
        while monotonic() - started < 90:
            _, _, body = request(app, "/api/status", cookie=cookie)
            state = json.loads(body)
            if marker in state["stages"] or state["status"] != "RUNNING":
                break
            sleep(0.05)
        assert state["status"] == "RUNNING" and marker in state["stages"], state
        code, _, body = request(app, "/api/cancel", method="POST", body={}, cookie=cookie)
        assert code == 200 and json.loads(body)["status"] == "CANCELLED"
        assert runtime._worker is None and runtime._result is None and runtime.view() is None
        assert worker._process._closed is True
        assert all(child.pid != child_pid for child in multiprocessing.active_children())
        withheld_status, _, _ = request(app, "/api/desk", cookie=cookie)
        assert withheld_status == 409
        records = [
            json.loads(path.read_bytes()) for path in (root / f"cancel-{phase}").glob("[0-9]*.json")
        ]
        attempts = sum(row["kind"] == "ATTEMPT" for row in records)
        assert attempts == (1 if phase == "acquisition" else 13)
        assert sum(row["kind"] == "RESERVATION" for row in records) == 1
        return {
            "phase": phase,
            "actual_spawn_child_pid": child_pid,
            "pause_marker_observed": True,
            "terminated_and_handle_closed": True,
            "result_withheld": True,
            "reservation_still_spent": True,
            "owned_attempts_before_cancellation": attempts,
            "seconds": monotonic() - started,
        }
    finally:
        runtime.close()


def main() -> None:
    root = _control_root()
    with tempfile.TemporaryDirectory(prefix="owned-runs-", dir=root) as temporary:
        work = Path(temporary)
        try:
            cases = [_case(horizon, work) for horizon in (1, 3)]
            cancellations = [_cancellation(phase, work) for phase in ("acquisition", "modelling")]
            cli = _cli(work)
        finally:
            # Preserve mismatches before disposing of the temporary owned data.
            for horizon in (1, 3):
                path = work / f"parity-{horizon}.json"
                if path.is_file():
                    (root / path.name).write_bytes(path.read_bytes())
    guards = [json.loads(path.read_bytes()) for path in root.glob("network-guard-*.json")]
    for case in [*cases, *cancellations]:
        assert any(
            row["pid"] == case["actual_spawn_child_pid"] and row["role"] == "__mp_main__"
            for row in guards
        )
    for case in cases:
        assert any(
            row["pid"] == case["reference_spawn_child_pid"] and row["role"] == "__mp_main__"
            for row in guards
        )
    assert all(row["self_test_denials"] == 1 and row["unexpected_denials"] == 0 for row in guards)
    print(
        json.dumps(
            {
                "status": "PASS",
                "classification": "OWNED_SYNTHETIC_ENGINEERING_ONLY",
                "horizons": [1, 3],
                "external_provider_requests": 0,
                "all_numeric_projection_and_decision_fields_exact": True,
                "no_full_semantic_hash_parity_claim": True,
                "custody_patterns": CUSTODY_PATTERNS,
                "disclosure_token_paths": DISCLOSURE_PATHS,
                "cases": cases,
                "cancellations": cancellations,
                "installed_cli": cli,
                "network_guards": guards,
                "cleanup": "CONFIRMED",
            },
            sort_keys=True,
        )
    )


if __name__ in {"__main__", "__mp_main__"}:
    _install_network_guard()
if __name__ == "__main__":
    main()
