"""Explicit refresh, history preservation and browser credential boundaries."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from dmf_pulse.credentials.service import CredentialService
from dmf_pulse.dashboard.app import create_app
from dmf_pulse.dashboard.runtime import DeskRuntime
from dmf_pulse.operation.analysis_store import AnalysisStore
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.persistent_desk import PersistentDeskRuntime
from tests.unit.credentials.test_fpl_jwt import token
from tests.unit.credentials.test_service import NOW, MemoryVault
from tests.unit.dashboard.test_dashboard import CODE, pair, request
from tests.unit.operation.test_analysis_store import owned_snapshot as owned_snapshot
from tests.unit.operation.test_analysis_store import publish


@pytest.fixture
def persisted(tmp_path, owned_snapshot):
    store = AnalysisStore(tmp_path / "history" / "derived.sqlite")
    store.initialize()
    publish(store, owned_snapshot)
    return store


def runtime(store, *, check=lambda: None, prepare=lambda *_: DeskRuntime()):
    vault = MemoryVault()
    service = CredentialService(lambda: vault, clock=lambda: NOW)
    result = PersistentDeskRuntime(
        store,
        local_check=check,
        register=lambda secret: service.set_fpl_jwt(
            secret, minimum_remaining_seconds=1200, maximum_remaining_seconds=86400
        ),
        prepare=prepare,
        provenance="OWNED_SYNTHETIC",
    )
    return result, vault, service


def test_launch_and_browser_gets_read_saved_view_without_credentials_or_jobs(persisted):
    calls = []
    desk, vault, _ = runtime(
        persisted,
        check=lambda: calls.append("check"),
        prepare=lambda *_: pytest.fail("GET started acquisition"),
    )
    application = create_app(runtime=desk, pairing_code=CODE, port=8765)
    cookie = pair(application)
    for path in (
        "/api/context",
        "/api/status",
        "/api/desk",
        "/api/history",
        "/api/analysis/status",
    ):
        status, _, body = request(application, path, browser_header=cookie)
        assert status == 200, body
    assert not calls and not vault.events
    assert desk.view().job_id == persisted.snapshot().run_id
    assert desk.view().information_cutoff == persisted.snapshot().view.information_cutoff
    desk.close()


def test_ineligible_refresh_does_not_prompt_register_or_replace_history(persisted):
    def consumed():
        raise OperationError("GAMEWEEK_ACQUISITION_ALREADY_RECORDED")

    desk, vault, _ = runtime(persisted, check=consumed)
    before = desk.view()
    assert desk.refresh(1).error_code == "GAMEWEEK_ACQUISITION_ALREADY_RECORDED"
    assert desk.credential_challenge() is None
    assert desk.view() == before and not vault.events
    assert desk.submit_fpl(SecretStr(token()), "invented").status == "BLOCKED"
    assert not vault.events
    desk.close()


def test_browser_expiry_registration_deduplication_and_failure_preserves_saved_view(persisted):
    reached, release = Event(), Event()
    calls = []

    def prepare(progress, cancelled):
        calls.append("prepare")
        progress("Checking owned admission.")
        reached.set()
        assert release.wait(5)
        raise OperationError("CURRENT_SNAPSHOT_INVALID")

    desk, vault, service = runtime(persisted, prepare=prepare)
    application = create_app(runtime=desk, pairing_code=CODE, port=8765)
    cookie = pair(application)
    status, _, body = request(
        application, "/api/refresh", method="POST", body={"horizon": 1}, browser_header=cookie
    )
    assert status == 200
    challenge = json.loads(body)["credential_challenge"]
    fresh = token()
    status, _, body = request(
        application,
        "/api/credentials/fpl",
        method="POST",
        browser_header=cookie,
        body={"token": fresh, "challenge": challenge},
    )
    assert status == 200 and json.loads(body)["status"] == "RUNNING"
    assert fresh.encode() not in body
    assert reached.wait(5)
    assert service.status("fpl").expires_at == NOW + timedelta(hours=1)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: desk.refresh(1), range(16)))
    assert all(row.status == "RUNNING" for row in results)
    assert calls == ["prepare"]
    assert desk.submit_fpl(SecretStr(fresh), challenge).status == "BLOCKED"
    assert [event for event in vault.events if event == ("write", "fpl")] == [("write", "fpl")]
    release.set()
    desk._thread.join(5)
    assert desk.tick().error_code == "CURRENT_SNAPSHOT_INVALID"
    assert desk.view().job_id == persisted.snapshot().run_id
    assert request(application, "/api/desk", browser_header=cookie)[0] == 200
    assert fresh.encode() not in persisted.path.read_bytes()
    assert len(persisted.query("select * from failed_attempts")) == 1
    desk.close()


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"host": "attacker.invalid"}, 403),
        ({"origin": "https://attacker.invalid"}, 403),
        ({"x-dmf-action": "wrong"}, 403),
        ({"sec-fetch-site": "cross-site"}, 403),
        ({"x-forwarded-for": "127.0.0.1"}, 403),
        ({"content-type": "text/plain"}, 403),
    ],
)
def test_browser_token_boundary_never_registers_cross_origin(persisted, change, expected):
    desk, vault, _ = runtime(persisted)
    application = create_app(runtime=desk, pairing_code=CODE, port=8765)
    cookie = pair(application)
    desk.refresh(1)
    value = {"token": token(), "challenge": desk.credential_challenge()}
    status, _, body = request(
        application,
        "/api/credentials/fpl",
        method="POST",
        browser_header=cookie,
        body=value,
        headers=change,
    )
    assert status == expected
    assert value["token"].encode() not in body and not vault.events
    desk.close()


def test_invalid_expired_or_oversized_jwt_is_safe_and_does_not_start(persisted):
    desk, vault, _ = runtime(persisted, prepare=lambda *_: pytest.fail("invalid JWT started"))
    application = create_app(runtime=desk, pairing_code=CODE, port=8765)
    cookie = pair(application)
    for jwt in (
        "owned-invalid",
        token(expiry=int((NOW - timedelta(seconds=1)).timestamp())),
        "owned-oversized" * 500,
    ):
        desk.refresh(1)
        status, _, body = request(
            application,
            "/api/credentials/fpl",
            method="POST",
            browser_header=cookie,
            body={"token": jwt, "challenge": desk.credential_challenge()},
        )
        assert status in {200, 413}
        if status == 200:
            assert json.loads(body)["status"] == "BLOCKED"
        assert jwt.encode() not in body
    assert not vault.rows
    assert desk.view() is not None
    desk.close()


def test_history_selection_and_restart_restore_without_preflight(persisted, owned_snapshot):
    second = owned_snapshot.model_copy(
        update={
            "run_id": "new-run",
            "view": owned_snapshot.view.model_copy(
                update={
                    "job_id": "new-run",
                    "generated_at": owned_snapshot.view.generated_at + timedelta(days=1),
                }
            ),
        }
    )
    publish(persisted, second, "b" * 64)
    desk, _, _ = runtime(persisted, check=lambda: pytest.fail("historical selection preflight"))
    assert desk.view().job_id == "new-run"
    assert desk.select_run(owned_snapshot.run_id).job_id == owned_snapshot.run_id
    assert len(desk.history()) == 2
    desk.close()
    restored, _, _ = runtime(persisted)
    assert restored.view().job_id == "new-run"
    restored.close()


def test_cancel_preparation_keeps_single_job_until_cleanup(persisted):
    reached, release = Event(), Event()

    def prepare(progress, cancelled):
        reached.set()
        assert release.wait(5)
        assert cancelled.is_set()
        return DeskRuntime()

    desk, _, _ = runtime(persisted, prepare=prepare)
    desk.refresh(1)
    desk.submit_fpl(SecretStr(token()), desk.credential_challenge())
    assert reached.wait(5)
    desk.cancel()
    assert desk.refresh(1).error_code == "REFRESH_CLEANUP_IN_PROGRESS"
    assert desk.view() is not None
    release.set()
    desk.close()
    assert not desk._thread.is_alive()


def test_browser_reopen_requires_direct_local_navigation_and_preserves_history(persisted):
    desk, _, _ = runtime(persisted)
    application = create_app(
        runtime=desk, pairing_code=CODE, port=8765, trusted_local_navigation=True
    )
    headers = {"sec-fetch-site": "none", "sec-fetch-mode": "navigate", "sec-fetch-dest": "document"}
    status, first, _ = request(application, "/", headers=headers)
    assert status == 200
    status, second, _ = request(application, "/", headers=headers)
    assert status == 200 and second["set-cookie"] != first["set-cookie"]
    cookie = second["set-cookie"].split(";", 1)[0]
    assert request(application, "/api/desk", browser_header=cookie)[0] == 200
    desk.close()


def test_authenticated_publication_reconciles_staged_snapshot_and_rejects_mismatch(
    tmp_path, owned_snapshot, monkeypatch
):
    from dmf_pulse.operation import standing
    from tests.unit.operation.standing_support import owned_policy

    store = AnalysisStore(tmp_path / "recover" / "history.sqlite")
    store.initialize()
    digest = store.stage(owned_snapshot)
    policy = owned_policy(tmp_path)
    monkeypatch.setattr(standing, "require_policy", lambda: policy)
    publication = {
        "value": {"analysis_sha256": digest, "view": owned_snapshot.view.model_dump(mode="json")},
        "sha256": "c" * 64,
        "at": NOW,
    }
    journal = SimpleNamespace(
        analysis_publications=lambda: [publication],
        local_refresh_check=lambda **_: None,
        contains_event=lambda _: False,
    )
    recovered = PersistentDeskRuntime.production(policy, journal, store)
    assert recovered.view().job_id == owned_snapshot.run_id
    assert store.snapshot() == owned_snapshot
    recovered.close()
    publication["value"]["view"]["job_id"] = "unbound-view"
    with pytest.raises(OperationError, match="REAL_PRIVATE_PUBLICATION_REQUIRED"):
        PersistentDeskRuntime.production(policy, journal, store)


def test_historical_player_details_match_retained_engine_projections(persisted, owned_snapshot):
    desk, _, _ = runtime(persisted)
    row = next(row for row in owned_snapshot.view.players if row.expected_points is not None)
    detail = desk.player(row.catalogue.official_id)
    assert detail.catalogue == row.catalogue
    assert detail.gameweeks[owned_snapshot.view.gameweeks[0]].expected_points == row.expected_points
    assert all(set(f.summaries) == {row.catalogue.player_id} for f in detail.fixtures)
    desk.close()


def test_history_comparison_reads_both_runs_without_changing_selection_or_admission(
    persisted, owned_snapshot
):
    later = owned_snapshot.model_copy(
        update={
            "run_id": "comparison-later",
            "view": owned_snapshot.view.model_copy(
                update={
                    "job_id": "comparison-later",
                    "generated_at": owned_snapshot.view.generated_at + timedelta(days=1),
                }
            ),
        }
    )
    publish(persisted, later, "b" * 64)
    desk, vault, _ = runtime(
        persisted,
        check=lambda: pytest.fail("comparison admission"),
        prepare=lambda *_: pytest.fail("comparison calculation"),
    )
    application = create_app(runtime=desk, pairing_code=CODE, port=8765)
    cookie = pair(application)
    before = persisted.path.read_bytes()
    status, _, body = request(
        application,
        "/api/history/compare",
        method="POST",
        browser_header=cookie,
        body={"first_run_id": owned_snapshot.run_id, "second_run_id": later.run_id},
    )
    value = json.loads(body)
    assert (
        status == 200
        and value["attribution"] == "OBSERVED_DIFFERENCES_ONLY_NO_CAUSAL_OR_VALIDATION_CLAIM"
    )
    assert all(row["expected_points_delta"] in {0, None} for row in value["players"])
    assert value["first"]["validation"] == value["second"]["validation"] == "UNVALIDATED"
    assert (
        desk.view().job_id == later.run_id
        and persisted.path.read_bytes() == before
        and not vault.events
    )
    status, _, _ = request(
        application,
        "/api/history/compare",
        method="POST",
        browser_header=cookie,
        body={"first_run_id": later.run_id, "second_run_id": later.run_id},
    )
    assert status == 422
    desk.close()


def test_near_expiry_explicit_refresh_renews_browser_window_without_grant_retry(persisted):
    reached, release = Event(), Event()

    def prepare(progress, cancelled):
        reached.set()
        assert release.wait(5)
        assert not cancelled.is_set()
        raise OperationError("CURRENT_SNAPSHOT_INVALID")

    desk, _, _ = runtime(persisted, prepare=prepare)
    elapsed = [0.0]
    application = create_app(
        runtime=desk, pairing_code=CODE, port=8765, elapsed_clock=lambda: elapsed[0]
    )
    cookie = pair(application)
    elapsed[0] = 3599.0
    status, headers, body = request(
        application, "/api/refresh", method="POST", browser_header=cookie, body={"horizon": 1}
    )
    assert status == 200 and "Max-Age=3600" in headers["set-cookie"]
    challenge = json.loads(body)["credential_challenge"]
    status, _, body = request(
        application,
        "/api/credentials/fpl",
        method="POST",
        browser_header=cookie,
        body={"token": token(), "challenge": challenge},
    )
    assert status == 200 and reached.wait(5)
    elapsed[0] = 4800.0
    status, _, body = request(application, "/api/status", browser_header=cookie)
    assert status == 200 and json.loads(body)["status"] == "RUNNING"
    release.set()
    desk._thread.join(5)
    assert desk.tick().error_code == "CURRENT_SNAPSHOT_INVALID"
    desk.close()
