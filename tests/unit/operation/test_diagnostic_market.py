"""Controlled prices cannot become observed markets or durable quota evidence."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from dmf_pulse.dashboard.current_sources import GuardedOddsTransport
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectFplRunAttestation,
)
from dmf_pulse.ingestion.fpl.direct_payloads import acquire_direct_fpl_snapshot
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.operation.diagnostic_market import controlled_market_for_snapshot
from tests.unit.private_v1.test_one_command import RUN_AT, _DirectTransport, _provider_sources


@pytest.mark.parametrize("identity", ["stdlib_http_client", "stdlib_urllib", "injected", "unknown"])
def test_guard_preserves_native_transport_identity_and_injected_delegate_stays_injected(identity):
    wrapper = GuardedOddsTransport(SimpleNamespace(), SimpleNamespace(transport_id=identity))
    assert wrapper.transport_id == (identity if identity.startswith("stdlib_") else "injected")


def test_controlled_market_uses_exact_owned_fpl_fixtures_without_any_new_get(repository_root: Path):
    bodies, _ = _provider_sources(repository_root)
    transport = _DirectTransport(bodies)
    client = DirectFplClient(
        DirectFplRunAttestation(attested_at=RUN_AT),
        transport=transport,
        credential_provider=DirectFplCredentialProvider(
            {"DMF_FPL_BEARER_TOKEN": "owned-placeholder"}
        ),
        clock=lambda: RUN_AT,
        sleeper=lambda _: None,
        pace_seconds=0,
    )
    snapshot = acquire_direct_fpl_snapshot(
        client, entry_id=42, captured_at=RUN_AT, clock=lambda: RUN_AT
    )
    previous = len(transport.requests)
    controlled = controlled_market_for_snapshot(
        snapshot, load_rights_profiles()["the_odds_api_private_analytics_v1"], assembled_at=RUN_AT
    )
    assert len(transport.requests) == previous == 8
    assert controlled.actual_provider_gets == controlled.actual_provider_credits == 0
    assert controlled.odds.provenance.transport_id == "injected"
    fixtures = [
        fixture
        for fixture in snapshot.fpl_input.fixtures
        if fixture.event_identity == snapshot.fpl_input.target_event.identity
    ]
    assert {event.commence_time for event in controlled.odds.events} == {
        fixture.kickoff_at for fixture in fixtures
    }
    assert len(controlled.odds.events) == len(fixtures)
    names = {team.official_name for team in snapshot.fpl_input.teams}
    assert all(
        event.provider_home_team in names and event.provider_away_team in names
        for event in controlled.odds.events
    )
