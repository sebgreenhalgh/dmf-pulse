"""Owned complete provider path and fault injection; never a live acceptance."""

from datetime import timedelta

import pytest

from dmf_pulse.dashboard.runtime import PipeProgress
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import DirectFplRunAttestation, DirectHttpResponse
from dmf_pulse.ingestion.fpl.direct_payloads import acquire_direct_fpl_snapshot
from dmf_pulse.ingestion.fpl.manager_current import CurrentManagerStateService
from dmf_pulse.operation.diagnostics import DiagnosticLog
from dmf_pulse.private_v1.one_command import _rules_authority
from tests.unit.dashboard.post_gw10_support import (
    CANARY,
    NOW,
    direct_factory,
    full_owned_service,
    owned_bodies,
)


def test_owned_20_club_gw10_reaches_stage8_9_12_with_complete_request_evidence(repository_root):
    from dmf_pulse.dashboard.views import desk_view
    from dmf_pulse.private_v1.one_command import OneCommandRequest

    log = DiagnosticLog()
    service, guard, fpl, odds, score, messages = full_owned_service(repository_root, log)
    result = service.run(
        OneCommandRequest(
            entry_id=42,
            code_sha="a" * 40,
            run_at=NOW,
            operator_approved_at=NOW - timedelta(minutes=1),
            scenario_count=32,
            root_seed=42,
        )
    )
    view = desk_view(
        result,
        job_id="owned-recovery",
        mode="SYNTHETIC_CURRENT_MODE",
        generated_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    assert view.dataset_mode == "SYNTHETIC_CURRENT_MODE"
    assert len(view.team.current_squad) == 15
    assert len(view.team.decision.tactics.starting_xi) == 11
    assert "Captain:" in result.report
    stages = {event.stage for event in log.report().events if event.kind == "STAGE_COMPLETED"}
    assert {"STAGE8_EVENTS", "STAGE9_POINTS", "STAGE12_DECISION"} <= stages
    assert result.fpl_request_count == 15 and len(fpl.completed) == 15
    assert odds.calls == 1 and len(score.requests) == 4
    assert len(guard.attempts) == 20 and len(log.report().requests) == 20
    assert all(
        row.response_completed_at is not None and row.http_status == 200
        for row in log.report().requests
    )
    assert CANARY not in log.report().model_dump_json() and CANARY not in str(messages)


def test_owned_20_club_eight_history_snapshot_and_authenticated_manager(repository_root):
    bodies = owned_bodies(repository_root)
    factory, guard, transport, log = direct_factory(bodies)
    snapshot = acquire_direct_fpl_snapshot(
        factory(DirectFplRunAttestation(attested_at=NOW)),
        entry_id=42,
        captured_at=NOW,
        clock=lambda: NOW,
    )
    assert snapshot.target_gameweek == 10 and len(snapshot.fpl_input.teams) == 20
    assert len(snapshot.fpl_input.players) == 400
    assert tuple(snapshot.live_by_gameweek) == tuple(range(1, 9))
    assert "/api/event/9/live/" not in transport.completed
    assert snapshot.request_count == 15 and len(guard.attempts) == 15
    assert all(row.response_completed_at is not None for row in log.report().requests)
    rules, capability, authority = _rules_authority(NOW)
    manager = CurrentManagerStateService(clock=lambda: NOW).compile_provider_snapshot(
        snapshot.current_team,
        fpl_input=snapshot.fpl_input,
        ruleset=rules,
        capability=capability,
        observed_at=NOW,
        overall_points=snapshot.entry.summary_overall_points,
        overall_rank=snapshot.entry.summary_overall_rank,
        private_rules_authority=authority,
    )
    assert manager.semantic_sha256
    assert CANARY not in log.report().model_dump_json()


@pytest.mark.parametrize(
    "failure", ["timeout", "http401", "malformed", "missing", "expired", "unexpected"]
)
def test_owned_fpl_failures_keep_stage_category_and_completion(repository_root, failure):
    bodies = owned_bodies(repository_root)
    log = DiagnosticLog()
    sent = []
    progress = PipeProgress(sent.append, diagnostics=log)

    def fault(request):
        if request.path != "/api/event/8/live/":
            return None
        if failure == "timeout":
            raise IngestionError("READ_TIMEOUT", CANARY)
        if failure == "unexpected":
            raise KeyError(CANARY)
        if failure == "http401":
            return DirectHttpResponse(401, "application/json", CANARY.encode())
        if failure == "malformed":
            return DirectHttpResponse(200, "application/json", b"{" + CANARY.encode())
        if failure == "missing":
            return DirectHttpResponse(200, "application/json", b'{"elements":[{"id":1}]}')
        return None

    factory, guard, _transport, _ = direct_factory(bodies, log, fault)
    if failure == "expired":
        original = guard.before_transport

        def expiry():
            if len(guard.attempts) == 15:
                guard.expired = True
            original()

        guard.before_transport = expiry
    with (
        pytest.raises(Exception),
        progress.stage(
            started="Acquiring current FPL state...",
            completed="FPL state ready",
            failed="current FPL state",
        ),
    ):
        acquire_direct_fpl_snapshot(
            factory(DirectFplRunAttestation(attested_at=NOW - timedelta(minutes=1))),
            entry_id=42,
            captured_at=NOW,
            clock=lambda: NOW,
        )
    report = log.report()
    assert len(report.requests) == 15 and report.failure is not None
    assert report.failure.code != "CURRENT_SOURCE_OR_RUN_BLOCKED"
    assert all(row.response_completed_at is not None for row in report.requests[:-1])
    completed = report.requests[-1].response_completed_at is not None
    assert completed == (failure in {"http401", "malformed", "missing"})
    assert (
        report.failure.category
        == {
            "timeout": "TRANSPORT",
            "http401": "CREDENTIAL",
            "malformed": "RESPONSE_CONTRACT",
            "missing": "RESPONSE_CONTRACT",
            "expired": "AUTHORIZATION",
            "unexpected": "INTERNAL_EXCEPTION",
        }[failure]
    )
    assert CANARY not in report.model_dump_json() and CANARY not in str(sent)
