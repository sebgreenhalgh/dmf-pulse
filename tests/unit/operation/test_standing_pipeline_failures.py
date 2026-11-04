"""Unknown/ambiguous source contracts stop ordinary execution before paid access."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.dashboard.runtime import PipeProgress
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.operation.diagnostics import DiagnosticLog
from dmf_pulse.operation.standing_pipeline import StandingOneGameweekService
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.one_command import OneCommandRequest
from tests.unit.operation.standing_pipeline_support import (
    GW11_NOW,
    gw11_direct_factory,
    owned_gw11_bodies,
)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("unknown_status", "CURRENT_MANAGER_CHIP_STATUS_UNSUPPORTED"),
        ("ambiguous_future", "DIAGNOSTIC_MANAGER_CHIP_MAPPING_AMBIGUOUS"),
        ("oversize_status", "VALIDATION_FAILED"),
    ],
)
def test_invalid_owned_gw11_manager_never_reaches_paid_factory(repository_root, fault, code):
    bodies = owned_gw11_bodies(repository_root, played=False, future_copies=True)
    manager = json.loads(bodies["/api/my-team/42/"])
    canary = "OWNED_PRIVATE_STATUS_CANARY"
    if fault == "unknown_status":
        manager["chips"][0]["status_for_entry"] = canary
    elif fault == "oversize_status":
        manager["chips"][0]["status_for_entry"] = canary * 3
    else:
        manager["chips"][1]["status_for_entry"] = "available"
    bodies["/api/my-team/42/"] = json.dumps(manager).encode()
    diagnostics = DiagnosticLog(clock=lambda: GW11_NOW)
    factory, _, transport, _ = gw11_direct_factory(bodies, diagnostics)

    def forbidden(_):
        pytest.fail("source contract failure reached an Odds or score factory")

    service = StandingOneGameweekService(
        direct_client_factory=factory,
        odds_service_factory=forbidden,
        score_service_factory=forbidden,
        progress=PipeProgress(lambda _: None, diagnostics=diagnostics),
        clock=lambda: GW11_NOW,
    )
    with pytest.raises(IngestionError) as failed:
        service.run(
            OneCommandRequest(
                entry_id=42,
                code_sha="a" * 40,
                run_at=GW11_NOW,
                operator_approved_at=GW11_NOW - timedelta(minutes=1),
                scenario_count=256,
                root_seed=42,
            )
        )
    assert failed.value.code == code
    diagnostics.failed(failed.value)
    assert not any(e.source_schema_proof is not None for e in diagnostics.events)
    assert canary not in diagnostics.report().model_dump_json()
    assert len(transport.completed) == (7 if fault == "oversize_status" else 17)


@pytest.mark.parametrize(
    "changes",
    [
        {"entry_id": True},
        {"entry_id": 0},
        {"horizon_gameweeks": 3},
        {"run_at": GW11_NOW.replace(tzinfo=None)},
        {"operator_approved_at": None},
        {"operator_approved_at": GW11_NOW.replace(tzinfo=None)},
        {"operator_approved_at": GW11_NOW + timedelta(seconds=1)},
    ],
)
def test_invalid_ordinary_request_is_refused_before_any_factory(changes):
    def forbidden(_):
        pytest.fail("invalid ordinary request reached a source factory")

    service = StandingOneGameweekService(
        direct_client_factory=forbidden,
        odds_service_factory=forbidden,
        score_service_factory=forbidden,
        progress=PipeProgress(lambda _: None, diagnostics=DiagnosticLog(clock=lambda: GW11_NOW)),
    )
    request = OneCommandRequest(
        entry_id=42,
        code_sha="a" * 40,
        run_at=GW11_NOW,
        operator_approved_at=GW11_NOW - timedelta(minutes=1),
        scenario_count=256,
        root_seed=42,
    )
    with pytest.raises(PrivateV1Error) as failed:
        service.run(replace(request, **changes))
    assert failed.value.code == "USAGE_INVALID"


def test_missing_private_diagnostic_channel_refuses_before_source_resolution():
    def forbidden(_):
        pytest.fail("missing ordinary audit channel reached source resolution")

    service = StandingOneGameweekService(direct_client_factory=forbidden)
    with pytest.raises(AuthorizationError) as failed:
        service.run(
            OneCommandRequest(
                entry_id=42,
                code_sha="a" * 40,
                run_at=GW11_NOW,
                operator_approved_at=GW11_NOW - timedelta(minutes=1),
            )
        )
    assert failed.value.code == "WORKER_RESULT_BINDING_INVALID"


@pytest.mark.parametrize(
    "fault,code",
    [
        ("deadline", "OFFICIAL_DEADLINE_SCOPE_MISMATCH"),
        ("cutoff", "POST_CUTOFF"),
        ("clock_regression", "DECISION_CLOCK_INVALID"),
    ],
)
def test_ordinary_time_and_official_deadline_guards_precede_paid_access(
    repository_root, fault, code
):
    bodies = owned_gw11_bodies(repository_root)
    log = DiagnosticLog(clock=lambda: GW11_NOW)
    factory, _, transport, _ = gw11_direct_factory(bodies, log)
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        if fault == "cutoff":
            return GW11_NOW + timedelta(seconds=1)
        if fault == "clock_regression" and calls > 1:
            return GW11_NOW - timedelta(seconds=1)
        return GW11_NOW

    def forbidden(_):
        pytest.fail("invalid ordinary time/deadline reached a paid or score factory")

    service = StandingOneGameweekService(
        direct_client_factory=factory,
        odds_service_factory=forbidden,
        score_service_factory=forbidden,
        progress=PipeProgress(lambda _: None, diagnostics=log),
        clock=clock,
        _expected_deadline_at=GW11_NOW + timedelta(days=1) if fault == "deadline" else None,
    )
    with pytest.raises((PrivateV1Error, IngestionError)) as failed:
        service.run(
            OneCommandRequest(
                entry_id=42,
                code_sha="a" * 40,
                run_at=GW11_NOW,
                operator_approved_at=GW11_NOW - timedelta(minutes=1),
            )
        )
    assert failed.value.code == code
    assert transport.completed and not any(e.source_schema_proof is not None for e in log.events)
