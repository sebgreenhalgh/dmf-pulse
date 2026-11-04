"""Owned whole-result parity and real next-event schema regression, never live."""

from datetime import timedelta

import pytest

from dmf_pulse.dashboard.runtime import PipeProgress
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectFplRunAttestation,
)
from dmf_pulse.ingestion.fpl.direct_payloads import acquire_direct_fpl_snapshot
from dmf_pulse.ingestion.odds.config import load_rights_profiles as odds_profiles
from dmf_pulse.ingestion.openfootball.config import load_rights_profiles
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorService
from dmf_pulse.operation import standing_pipeline
from dmf_pulse.operation.diagnostic_market import controlled_market_for_snapshot
from dmf_pulse.operation.diagnostics import DiagnosticLog
from dmf_pulse.private_v1.one_command import OneCommandRequest, PrivateV1OneCommandService
from tests.unit.ingestion.openfootball.conftest import FakeTransport, synthetic_snapshot
from tests.unit.operation.standing_pipeline_support import (
    GW11_NOW,
    gw11_direct_factory,
    owned_gw11_bodies,
)
from tests.unit.operation.test_diagnostic_pipeline import CaptureAcceptedInput
from tests.unit.private_v1.test_one_command import (
    RUN_AT,
    _DirectTransport,
    _odds_input,
    _OddsService,
    _provider_sources,
)


def score_factory(clock):
    config, scores = synthetic_snapshot()
    return CurrentScorePriorService(
        provider_config=config,
        rights_profiles=load_rights_profiles(),
        transport=FakeTransport(scores),
        clock=clock,
        provider_config_identity="a" * 64,
        rights_config_identity="b" * 64,
    )


def test_full_256_scenario_result_and_presentation_match_accepted_service(
    repository_root, monkeypatch
):
    bodies, _ = _provider_sources(repository_root)
    original, adapted = _DirectTransport(bodies), _DirectTransport(bodies)
    odds = _odds_input(repository_root)
    captured = []
    prepare = standing_pipeline.prepare_diagnostic_fpl

    def preserve(snapshot, **kwargs):
        before = snapshot.model_dump_json()
        result = prepare(snapshot, **kwargs)
        captured.append((snapshot, before))
        return result

    monkeypatch.setattr(standing_pipeline, "prepare_diagnostic_fpl", preserve)

    def client(attestation, transport):
        return DirectFplClient(
            attestation,
            transport=transport,
            credential_provider=DirectFplCredentialProvider(
                {"DMF_FPL_BEARER_TOKEN": "owned-" + "synthetic-placeholder"}
            ),
            clock=lambda: RUN_AT,
            sleeper=lambda _: None,
            pace_seconds=0,
        )

    request = OneCommandRequest(
        entry_id=42,
        code_sha="a" * 40,
        run_at=RUN_AT,
        operator_approved_at=RUN_AT - timedelta(minutes=1),
        scenario_count=256,
        root_seed=42,
    )
    captures = [CaptureAcceptedInput(), CaptureAcceptedInput()]
    results = []
    log = DiagnosticLog(clock=lambda: RUN_AT)
    for cls, transport, capture in (
        (PrivateV1OneCommandService, original, captures[0]),
        (standing_pipeline.StandingOneGameweekService, adapted, captures[1]),
    ):
        results.append(
            cls(
                direct_client_factory=lambda a, t=transport: client(a, t),
                odds_service_factory=lambda clock: _OddsService(odds),
                score_service_factory=score_factory,
                recommendation_service=capture,
                collect_presentation=True,
                clock=lambda: RUN_AT,
                progress=PipeProgress(lambda _: None, diagnostics=log),
            ).run(request)
        )
    assert captures[0].execution.model_dump(mode="json") == captures[1].execution.model_dump(
        mode="json"
    )
    assert results[0] == results[1]
    assert results[0].presentation.model_dump(mode="json") == results[1].presentation.model_dump(
        mode="json"
    )
    assert results[1].decision.scenario_count == 256
    assert len(original.requests) == len(adapted.requests) == 8
    assert not original.bodies and not adapted.bodies
    assert len(captured) == 1 and captured[0][0].model_dump_json() == captured[0][1]
    proofs = [e for e in log.events if e.source_schema_proof is not None]
    assert len(proofs) == 1
    assert proofs[0].source_schema_proof.snapshot_sha256


@pytest.mark.parametrize("played,future_copies", [(True, False), (True, True)])
def test_owned_gw11_256_scenario_kernel_preserves_original_manager_source(
    repository_root, monkeypatch, played, future_copies
):
    bodies = owned_gw11_bodies(repository_root, played=played, future_copies=future_copies)
    preview_factory, _, _, _ = gw11_direct_factory(bodies)
    snapshot = acquire_direct_fpl_snapshot(
        preview_factory(DirectFplRunAttestation(attested_at=GW11_NOW - timedelta(minutes=1))),
        entry_id=42,
        captured_at=GW11_NOW,
        clock=lambda: GW11_NOW,
    )
    assert snapshot.target_gameweek == 11
    odds = controlled_market_for_snapshot(
        snapshot, odds_profiles()["the_odds_api_private_analytics_v1"], assembled_at=GW11_NOW
    ).odds
    log = DiagnosticLog(clock=lambda: GW11_NOW)
    factory, _, transport, _ = gw11_direct_factory(bodies, log)
    captured = []
    prepare = standing_pipeline.prepare_diagnostic_fpl

    def preserve(value, **kwargs):
        before = value.model_dump_json()
        result = prepare(value, **kwargs)
        captured.append((value, before))
        return result

    monkeypatch.setattr(standing_pipeline, "prepare_diagnostic_fpl", preserve)
    result = standing_pipeline.StandingOneGameweekService(
        direct_client_factory=factory,
        odds_service_factory=lambda clock: _OddsService(odds),
        score_service_factory=score_factory,
        progress=PipeProgress(lambda _: None, diagnostics=log),
        collect_presentation=True,
        clock=lambda: GW11_NOW,
    ).run(
        OneCommandRequest(
            entry_id=42,
            code_sha="a" * 40,
            run_at=GW11_NOW,
            operator_approved_at=GW11_NOW - timedelta(minutes=1),
            scenario_count=256,
            root_seed=42,
        )
    )
    assert result.decision.target_gameweek == 11 and result.decision.scenario_count == 256
    assert result.decision.stage9_monte_carlo_status == "PASS"
    assert len(transport.completed) == result.fpl_request_count == 17
    assert captured[0][0].model_dump_json() == captured[0][1]
    proof = next(e.source_schema_proof for e in log.events if e.source_schema_proof is not None)
    assert proof.target_gameweek == 11 and proof.chip_schema_proof.translated_played_records == 1
    assert proof.chip_schema_proof.omitted_inactive_records == (4 if future_copies else 0)
    assert result.presentation is not None and len(result.presentation.fixtures) == 10
