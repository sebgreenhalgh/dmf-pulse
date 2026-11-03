"""Twenty owned teams/ten fixtures through the unchanged controlled kernel."""

from datetime import timedelta

from dmf_pulse.ingestion.fpl.direct import DirectFplRunAttestation
from dmf_pulse.ingestion.fpl.direct_payloads import acquire_direct_fpl_snapshot
from dmf_pulse.ingestion.odds.config import load_rights_profiles as odds_profiles
from dmf_pulse.ingestion.openfootball.config import load_rights_profiles
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorService,
)
from dmf_pulse.operation.diagnostic_market import controlled_market_for_snapshot
from dmf_pulse.operation.diagnostic_pipeline import (
    assemble_diagnostic_execution,
    prepare_diagnostic_fpl,
    run_diagnostic_kernel,
)
from dmf_pulse.private_v1.one_command import OneCommandRequest
from tests.unit.dashboard.post_gw10_support import NOW, direct_factory, owned_bodies
from tests.unit.ingestion.openfootball.conftest import FakeTransport, synthetic_snapshot


def test_owned_gw10_full_typed_snapshot_controlled_market_and_stages_8_9_12(repository_root):
    bodies = owned_bodies(repository_root)
    factory, guard, transport, _ = direct_factory(bodies)
    snapshot = acquire_direct_fpl_snapshot(
        factory(DirectFplRunAttestation(attested_at=NOW - timedelta(minutes=1))),
        entry_id=42,
        captured_at=NOW,
        clock=lambda: NOW,
    )
    assert snapshot.target_gameweek == 10 and len(snapshot.fpl_input.teams) == 20
    assert len(transport.completed) == len(guard.attempts) == 15
    prepared = prepare_diagnostic_fpl(
        snapshot, approved_at=NOW - timedelta(minutes=1), observed_at=NOW
    )
    config, scores = synthetic_snapshot()
    prior = CurrentScorePriorService(
        provider_config=config,
        rights_profiles=load_rights_profiles(),
        transport=FakeTransport(scores),
        clock=lambda: NOW,
        provider_config_identity="a" * 64,
        rights_config_identity="b" * 64,
    ).build(
        CurrentScorePriorBuildRequest(
            information_cutoff=NOW, rights_profile_id="openfootball_football_json_score_prior_v1"
        )
    )
    controlled = controlled_market_for_snapshot(
        snapshot, odds_profiles()["the_odds_api_private_analytics_v1"], assembled_at=NOW
    )
    execution = assemble_diagnostic_execution(
        prepared,
        controlled.odds,
        prior,
        OneCommandRequest(
            entry_id=42,
            code_sha="a" * 40,
            run_at=NOW,
            operator_approved_at=NOW - timedelta(minutes=1),
            scenario_count=32,
            root_seed=42,
        ),
        resolved_at=NOW,
    )
    result = run_diagnostic_kernel(execution, controlled=True)
    assert len(result.result.fixture_projections) == 10
    assert result.controlled_proof()["stage8_stage9_stage12_passed"] is True
    assert result.controlled_proof()["real_recommendation_publication"] is False
    assert controlled.actual_provider_gets == controlled.actual_provider_credits == 0
    assert len(transport.completed) == 15
