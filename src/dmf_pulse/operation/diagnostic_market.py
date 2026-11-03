"""Clearly injected market engineering data for the exact retained FPL fixtures.

The prices and bookmaker set come from the repository-owned demonstration. They
are neither a provider observation nor quota evidence. No client/HTTP transport,
account ledger or real-publication function is called by this assembler.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard.current_sources import owned_odds_body
from dmf_pulse.ingestion.fpl.direct_payloads import DirectFplSnapshot
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.ingestion.odds.client import build_request
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput, build_current_odds_input
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.operation.models import OperationError


@dataclass(frozen=True, slots=True, repr=False)
class ControlledMarketInput:
    odds: OddsProviderCurrentInput
    classification: str = "INJECTED_REPOSITORY_PRICES_REAL_FPL_FIXTURES_NOT_OBSERVED_MARKETS"
    actual_provider_gets: int = 0
    actual_provider_credits: int = 0


def controlled_market_for_snapshot(
    snapshot: DirectFplSnapshot, profile: RightsProfile, *, assembled_at: datetime
) -> ControlledMarketInput:
    source = snapshot.fpl_input
    cutoff = source.provenance.information_cutoff
    if not source.provenance.usable_at <= assembled_at <= cutoff:
        raise OperationError("DIAGNOSTIC_CONTROLLED_ASSEMBLY_CHRONOLOGY_INVALID")
    names = {team.identity: team.official_name for team in source.teams}
    fixtures = [
        fixture
        for fixture in source.fixtures
        if fixture.event_identity == source.target_event.identity
    ]
    template = json.loads(owned_odds_body())[0]
    events = []
    for fixture in fixtures:
        if fixture.kickoff_at is None or fixture.started is True:
            raise OperationError("DIAGNOSTIC_EXACT_UNSTARTED_FIXTURES_REQUIRED")
        event = copy.deepcopy(template)
        original_home, original_away = event["home_team"], event["away_team"]
        event.update(
            id=f"CONTROLLED_FPL_FIXTURE_{fixture.provider_fixture_id}",
            home_team=names[fixture.home_team_identity],
            away_team=names[fixture.away_team_identity],
            commence_time=fixture.kickoff_at.isoformat(),
        )
        for bookmaker in event["bookmakers"]:
            bookmaker["last_update"] = assembled_at.isoformat()
            for market in bookmaker["markets"]:
                market["last_update"] = assembled_at.isoformat()
                if market["key"] == "h2h":
                    for outcome in market["outcomes"]:
                        if outcome["name"] == original_home:
                            outcome["name"] = event["home_team"]
                        elif outcome["name"] == original_away:
                            outcome["name"] = event["away_team"]
        events.append(event)
    if not events:
        raise OperationError("DIAGNOSTIC_EXACT_UNSTARTED_FIXTURES_REQUIRED")
    body = json.dumps(events).encode()
    parsed = parse_odds_payload(body)
    request = build_request(
        "owned-controlled-placeholder-value",
        commence_from=cutoff,
        commence_to=max(
            fixture.kickoff_at for fixture in fixtures if fixture.kickoff_at is not None
        )
        + timedelta(seconds=1),
    )
    # This is the injected client-contract counter fixture required by the
    # unchanged parser. It never enters paid custody or an actual quota receipt.
    engineering_quota = QuotaState(
        remaining=498,
        used=2,
        last_cost=2,
        observed_at=assembled_at,
        source=QuotaSource.RESPONSE_HEADERS,
    )
    odds = build_current_odds_input(
        parsed,
        profile=profile,
        source_snapshot_id=uuid5(NAMESPACE_URL, "dmf-pulse:controlled:" + parsed.body_sha256),
        request_started_at=assembled_at,
        received_at=assembled_at,
        usable_at=assembled_at,
        information_cutoff=cutoff,
        quota=engineering_quota,
        request_fingerprint=canonical_sha256(
            ["CONTROLLED_ENGINEERING_NO_HTTP", parsed.body_sha256]
        ),
        sanitized_target=request.sanitized_target,
        attempt_count=1,
        transport_call_count=1,
        transport_id="injected",
        provider_request_id_sha256=None,
    )
    return ControlledMarketInput(odds)
