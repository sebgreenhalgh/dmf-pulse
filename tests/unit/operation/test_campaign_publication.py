"""Owned native-shaped provenance only; no real HTTP, authority or publication.

The positive fixture computes the unchanged real configuration (256 scenarios,
seed42) once. Its three-fixture owned league limits test cost; the separate
twenty-team/ten-fixture case exercises full fixture coverage.
"""

import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.dashboard.authorization import RefreshGrant, RefreshRequest
from dmf_pulse.ingestion.fpl.direct import DirectFplRunAttestation
from dmf_pulse.ingestion.fpl.direct_payloads import acquire_direct_fpl_snapshot
from dmf_pulse.ingestion.odds.config import load_rights_profiles as odds_profiles
from dmf_pulse.ingestion.odds.current import build_current_odds_input
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.ingestion.openfootball.config import load_rights_profiles
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorService,
)
from dmf_pulse.operation.campaign_journal import DiagnosticSession
from dmf_pulse.operation.campaign_publication import LABEL, build_diagnostic_publication
from dmf_pulse.operation.diagnostic_pipeline import (
    assemble_diagnostic_execution,
    prepare_diagnostic_fpl,
    run_diagnostic_kernel,
)
from dmf_pulse.operation.models import OperationError
from dmf_pulse.private_v1.one_command import OneCommandRequest
from tests.unit.dashboard.post_gw10_support import NOW, direct_factory, odds_body, owned_bodies
from tests.unit.ingestion.openfootball.conftest import FakeTransport, synthetic_snapshot
from tests.unit.operation.standing_support import owned_policy


@pytest.fixture(scope="module")
def publication_case(repository_root, tmp_path_factory):
    policy = owned_policy(tmp_path_factory.mktemp("owned-publication-policy")).model_copy(
        update={"entry_id": 42}
    )
    cutoff = NOW + timedelta(seconds=1140)
    bodies = owned_bodies(repository_root)
    bootstrap = json.loads(bodies["/api/bootstrap-static/"])
    bootstrap["teams"] = [team for team in bootstrap["teams"] if team["id"] <= 6]
    bootstrap["elements"] = [player for player in bootstrap["elements"] if player["team"] <= 6]
    bodies["/api/bootstrap-static/"] = json.dumps(bootstrap).encode()
    bodies["/api/fixtures/"] = json.dumps(
        [
            fixture
            for fixture in json.loads(bodies["/api/fixtures/"])
            if fixture["team_h"] <= 6 and fixture["team_a"] <= 6
        ]
    ).encode()
    factory, _, _, _ = direct_factory(bodies)
    snapshot = acquire_direct_fpl_snapshot(
        factory(DirectFplRunAttestation(attested_at=NOW - timedelta(minutes=1))),
        entry_id=42,
        captured_at=cutoff,
        clock=lambda: NOW,
    )
    prepared = prepare_diagnostic_fpl(
        snapshot, approved_at=NOW - timedelta(minutes=1), observed_at=NOW
    )
    config, scores = synthetic_snapshot()
    prior = CurrentScorePriorService(
        provider_config=config,
        rights_profiles=load_rights_profiles(),
        transport=FakeTransport(scores),
        clock=lambda: NOW + timedelta(seconds=1),
        provider_config_identity="a" * 64,
        rights_config_identity="b" * 64,
    ).build(
        CurrentScorePriorBuildRequest(
            information_cutoff=cutoff, rights_profile_id="openfootball_football_json_score_prior_v1"
        )
    )
    markets = json.loads(odds_body(repository_root))[:3]
    # Explicitly owned native-shaped metadata: no transport is called here.
    received = NOW + timedelta(seconds=7)
    odds = build_current_odds_input(
        parse_odds_payload(json.dumps(markets).encode()),
        profile=odds_profiles()["the_odds_api_private_analytics_v1"],
        source_snapshot_id=uuid5(NAMESPACE_URL, "owned-diagnostic-publication"),
        request_started_at=NOW + timedelta(seconds=6),
        received_at=received,
        usable_at=received,
        information_cutoff=cutoff,
        quota=QuotaState(
            remaining=498,
            used=2,
            last_cost=2,
            observed_at=received,
            source=QuotaSource.RESPONSE_HEADERS,
        ),
        request_fingerprint="1" * 64,
        sanitized_target="https://api.the-odds-api.com/v4/sports/soccer_epl/odds?regions=uk&markets=h2h%2Ctotals&oddsFormat=decimal&dateFormat=iso&commenceTimeFrom="
        + cutoff.strftime("%Y-%m-%dT%H%%3A%M%%3A%SZ"),
        attempt_count=1,
        transport_call_count=1,
        transport_id="stdlib_http_client",
        provider_request_id_sha256=None,
    )
    execution = assemble_diagnostic_execution(
        prepared,
        odds,
        prior,
        OneCommandRequest(
            entry_id=42,
            code_sha=policy.implementation_sha,
            run_at=cutoff,
            operator_approved_at=NOW - timedelta(minutes=1),
            scenario_count=256,
            root_seed=42,
        ),
        resolved_at=received,
    )
    kernel = run_diagnostic_kernel(execution, controlled=False)
    key, authority_sha = "c" * 64, "b" * 64
    session = DiagnosticSession(
        1,
        key,
        key,
        "PAID_ELIGIBLE",
        NOW - timedelta(minutes=1),
        NOW + timedelta(minutes=29),
        authority_sha,
    )
    authority = SimpleNamespace(
        normal_policy=policy,
        proposal=SimpleNamespace(
            semantic_sha256="a" * 64,
            gameweek=10,
            entry_id=42,
            original_ledger_id=policy.ledger_id,
            deadline_not_after=snapshot.fpl_input.target_event.deadline_at,
        ),
        signed_campaign=SimpleNamespace(semantic_sha256=authority_sha),
    )
    request = RefreshRequest(
        authorization_id=f"OPR003-{key}",
        implementation_sha=policy.implementation_sha,
        review_sha256=policy.independent_review_sha256,
        operator_ref=policy.owner_ref,
        purpose=policy.purpose,
        season_code=policy.season_code,
        horizon=1,
        source_scopes=tuple(q.scope for q in policy.qualifications),
        information_cutoff=NOW + timedelta(seconds=305),
        deadline_at=snapshot.fpl_input.target_event.deadline_at,
    )
    grant = RefreshGrant(
        reservation_id="d" * 64,
        ledger_id=policy.ledger_id,
        ledger_backend="POSTGRES",
        approval_sha256="e" * 64,
        classification="PRIVATE_CURRENT",
        request=request,
        issued_at=NOW + timedelta(seconds=5),
        expires_at=NOW + timedelta(seconds=905),
    )
    return dict(
        authority=authority,
        session=session,
        prepared=prepared,
        prior=prior,
        kernel=kernel,
        grant=grant,
        credential_expires_at=NOW + timedelta(hours=1),
        completed_at=NOW + timedelta(seconds=9),
    )


def test_owned_provenance_contract_builds_one_bound_unvalidated_view(publication_case):
    publication = build_diagnostic_publication(**publication_case)
    assert LABEL in publication.view.restrictions and LABEL in publication.view.team.report
    assert len(publication.view.team.current_squad) == 15
    assert len(publication.view.team.decision.tactics.starting_xi) == 11
    assert publication.view.team.decision.scenario_count == 256
    projected = [row for row in publication.view.players if row.expected_points is not None]
    summaries = publication_case["kernel"].result.gameweek_projection.player_summaries
    for row in projected:
        summary = summaries[row.catalogue.player_id]
        assert row.points_p10 == summary.selected_percentiles["p10"]
        assert row.points_p90 == summary.selected_percentiles["p90"]
        assert row.median_points == summary.median_points
        assert row.points_standard_deviation == summary.points_standard_deviation
        assert row.monte_carlo_mean_se == summary.monte_carlo_mean_se
    assert publication.proof.model_cutoff > publication_case["grant"].request.information_cutoff
    assert publication.proof.fpl_usable_at < publication_case["grant"].issued_at
    assert publication.proof.odds_request_started_at > publication_case["grant"].issued_at


def test_controlled_kernel_can_never_be_published_as_real(publication_case):
    values = {
        **publication_case,
        "kernel": replace(
            publication_case["kernel"], classification="CONTROLLED_MARKET_ENGINEERING"
        ),
    }
    with pytest.raises(OperationError, match="REAL_SOURCE_AND_KERNEL_BINDING_REQUIRED"):
        build_diagnostic_publication(**values)


@pytest.mark.parametrize("completed", [NOW, NOW + timedelta(seconds=905), NOW + timedelta(hours=1)])
def test_model_completion_outside_bound_is_withheld(publication_case, completed):
    with pytest.raises(OperationError, match="PUBLICATION_CHRONOLOGY_INVALID"):
        build_diagnostic_publication(**{**publication_case, "completed_at": completed})


def test_insufficient_credential_lifetime_withholds_result(publication_case):
    with pytest.raises(OperationError, match="PUBLICATION_CHRONOLOGY_INVALID"):
        build_diagnostic_publication(
            **{**publication_case, "credential_expires_at": NOW + timedelta(seconds=8)}
        )
