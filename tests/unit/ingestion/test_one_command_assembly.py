"""Offline one-command payload and automatic assembly boundary proofs."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateService,
    bind_current_unified_state_request,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplDirectInputRequest, CurrentFplInputService
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectFplRunAttestation,
    DirectHttpRequest,
    DirectHttpResponse,
)
from dmf_pulse.ingestion.fpl.direct_payloads import (
    DirectEntry,
    DirectEntryHistory,
    DirectFplSnapshot,
    DirectPublicPicks,
    acquire_direct_fpl_snapshot,
    parse_direct_entry,
    parse_direct_event_live,
    parse_direct_history,
    parse_direct_public_picks,
    parse_direct_transfers,
)
from dmf_pulse.ingestion.fpl.manager_current import CurrentManagerStateService
from dmf_pulse.ingestion.fpl.manager_provider import parse_provider_current_team
from dmf_pulse.ingestion.odds.automatic_mapping import build_automatic_current_identity_map
from dmf_pulse.markets.current import (
    CurrentMarketCanonicalFixture,
    CurrentMarketCanonicalIdentityView,
    CurrentMarketCanonicalOperator,
    CurrentMarketConstraintService,
    bind_current_market_constraint_request,
    build_transient_current_market_identity_view,
    current_market_identity_view_sha256,
)
from dmf_pulse.private_v1.automatic_inputs import (
    build_automatic_model_minutes,
    build_automatic_ownership,
    build_automatic_player_identity_map,
    build_full_candidate_policy,
)
from dmf_pulse.private_v1.models import (
    PrivateCanonicalPlayerIdentity,
    PrivateCanonicalPlayerIdentityMap,
    PrivateCanonicalTeamIdentity,
    seal_canonical_player_identity_map,
)
from tests.unit.ingestion.current_identity_test_support import (
    CUTOFF,
    build_odds_input,
    rehash_odds_input,
)
from tests.unit.ingestion.current_manager_test_support import (
    FPL_CAPTURED,
    _synthetic_bootstrap,
    _synthetic_fixtures,
)
from tests.unit.ingestion.test_fpl_manager_provider import _context

pytestmark = pytest.mark.unit


class _DirectResponses:
    def __init__(self, bodies: tuple[bytes, ...]) -> None:
        self.bodies = list(bodies)
        self.calls: list[DirectHttpRequest] = []

    def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
        self.calls.append(request)
        return DirectHttpResponse(200, "application/json", self.bodies.pop(0))


def _provider_names_for_synthetic_clubs(value):
    events = []
    for event in value.events:
        bookmakers = []
        for bookmaker in event.bookmakers:
            markets = []
            for market in bookmaker.markets:
                outcomes = tuple(
                    outcome.model_copy(
                        update={
                            "provider_name": (
                                "Synthetic Club 2"
                                if outcome.outcome == "HOME"
                                else "Synthetic Club 1"
                                if outcome.outcome == "AWAY"
                                else outcome.provider_name
                            )
                        }
                    )
                    for outcome in market.outcomes
                )
                markets.append(market.model_copy(update={"outcomes": outcomes}))
            bookmakers.append(bookmaker.model_copy(update={"markets": tuple(markets)}))
        events.append(
            event.model_copy(
                update={
                    "provider_home_team": "Synthetic Club 2",
                    "provider_away_team": "Synthetic Club 1",
                    "bookmakers": tuple(bookmakers),
                }
            )
        )
    return rehash_odds_input(value, events=tuple(events))


def test_direct_auxiliary_payloads_are_strict_and_missing_live_is_not_zero() -> None:
    entry = parse_direct_entry(b'{"id":42,"started_event":1,"summary_overall_points":8}')
    history = parse_direct_history(
        b'{"current":[{"event":1,"points":8,"total_points":8,"bank":5,'
        b'"value":1000,"event_transfers":0,"event_transfers_cost":0}]}'
    )
    picks = parse_direct_public_picks(
        json.dumps(
            {
                "picks": [
                    {"element": index, "position": index, "multiplier": 0} for index in range(1, 16)
                ]
            }
        ).encode()
    )
    transfers = parse_direct_transfers(
        b'[{"element_in":2,"element_in_cost":55,"element_out":1,'
        b'"element_out_cost":50,"event":2,"time":"2026-08-24T10:00:00Z"}]'
    )
    live = parse_direct_event_live(
        b'{"elements":[{"id":1,"stats":{"minutes":90,"starts":1}},{"id":2,"stats":{}}]}'
    )

    assert entry.id == 42
    assert history.current[0].event == 1
    assert len(picks.picks) == 15
    assert transfers[0].event == 2
    assert live.elements[1].stats.minutes is None
    assert live.elements[1].stats.starts is None

    with pytest.raises(IngestionError):
        parse_direct_entry(b'{"id":42,"id":43,"started_event":1}')
    with pytest.raises(IngestionError):
        parse_direct_entry(b'{"id":NaN,"started_event":1}')
    with pytest.raises(IngestionError):
        parse_direct_history(
            b'{"current":[{"event":2,"points":0,"total_points":0,"bank":0,"value":1,'
            b'"event_transfers":0,"event_transfers_cost":0},{"event":1,"points":0,'
            b'"total_points":0,"bank":0,"value":1,"event_transfers":0,'
            b'"event_transfers_cost":0}]}'
        )
    with pytest.raises(IngestionError):
        parse_direct_transfers(b"{}")
    duplicate_transfer = (
        b'{"element_in":2,"element_in_cost":55,"element_out":1,"element_out_cost":50,'
        b'"event":2,"time":"2026-08-24T10:00:00Z"}'
    )
    with pytest.raises(IngestionError):
        parse_direct_transfers(b"[" + duplicate_transfer + b"," + duplicate_transfer + b"]")
    with pytest.raises(IngestionError):
        parse_direct_transfers(
            b'[{"element_in":2,"element_in_cost":55,"element_out":1,'
            b'"element_out_cost":50,"event":2,"time":"2026-08-24T10:00:00"}]'
        )
    with pytest.raises(IngestionError):
        parse_direct_public_picks(
            json.dumps(
                {
                    "picks": [
                        {"element": index, "position": index, "multiplier": 0}
                        for index in range(1, 15)
                    ]
                }
            ).encode()
        )
    with pytest.raises(IngestionError):
        parse_direct_event_live(b'{"elements":[{"id":1,"stats":{}},{"id":1,"stats":{}}]}')


def test_direct_snapshot_resolves_target_and_auth_state_without_previous_pick_substitution(
    repository_root: Path,
) -> None:
    _, _, _, current_team = _context(repository_root)
    marker = "synthetic-token"
    bootstrap = _synthetic_bootstrap(repository_root)
    seen_teams: set[int] = set()
    for player in bootstrap["elements"]:
        team_id = int(player["team"])
        if team_id not in seen_teams:
            player["penalties_order"] = 1
            player["penalties_text"] = ""
            seen_teams.add(team_id)
    transport = _DirectResponses(
        (
            json.dumps(bootstrap).encode(),
            json.dumps(_synthetic_fixtures(repository_root)).encode(),
            b'{"id":42,"started_event":1,"summary_overall_points":0}',
            b'{"current":[]}',
            b"[]",
            json.dumps(current_team).encode(),
        )
    )
    client = DirectFplClient(
        DirectFplRunAttestation(attested_at=FPL_CAPTURED),
        transport=transport,
        credential_provider=DirectFplCredentialProvider({"DMF_FPL_BEARER_TOKEN": marker}),
        sleeper=lambda _: None,
        pace_seconds=0,
    )

    snapshot = acquire_direct_fpl_snapshot(client, entry_id=42, captured_at=FPL_CAPTURED)

    assert snapshot.target_gameweek == 2
    assert snapshot.latest_public_picks is None
    assert (
        snapshot.current_team.picks
        == parse_provider_current_team(json.dumps(current_team).encode()).picks
    )
    assert snapshot.request_count == 6
    assert transport.calls[-1].path == "/api/my-team/42/"
    assert snapshot.current_penalty_hierarchy is not None
    assert len(snapshot.current_penalty_hierarchy.entries) == len(bootstrap["teams"])
    assert (
        snapshot.current_penalty_hierarchy.source_bootstrap_payload_sha256
        == snapshot.fpl_input.provenance.bootstrap_payload_sha256
    )


def test_provider_observed_unified_state_and_transient_market_identity_are_accepted(
    repository_root: Path,
) -> None:
    fpl, ruleset, capability, provider_body = _context(repository_root)
    provider = parse_provider_current_team(json.dumps(provider_body).encode())
    manager = CurrentManagerStateService(clock=lambda: CUTOFF).compile_provider_snapshot(
        provider,
        fpl_input=fpl,
        ruleset=ruleset,
        capability=capability,
        observed_at=CUTOFF,
    )
    odds = _provider_names_for_synthetic_clubs(build_odds_input(repository_root, cutoff=CUTOFF))
    bridge = build_automatic_current_identity_map(fpl, odds, decided_at=CUTOFF)
    request = bind_current_unified_state_request(fpl, odds, bridge, manager, ruleset, capability)
    current = CurrentUnifiedStateService().compose(
        request,
        fpl_input=fpl,
        odds_input=odds,
        identity_map=bridge,
        manager_state=manager,
        ruleset=ruleset,
        capability=capability,
    )
    view = build_transient_current_market_identity_view(current, resolved_at=CUTOFF)
    markets = CurrentMarketConstraintService().build(
        bind_current_market_constraint_request(current, view),
        source=current,
        identity_view=view,
    )

    assert current.manager_state.source_class == "PROVIDER_OBSERVED"
    assert current.rights.official_fpl_automated_access == "ALLOW"
    assert current.runtime.network_called is False
    assert view.authority == "OPERATOR_INITIATED_DETERMINISTIC"
    assert view.database_read_performed is False
    assert markets.target_gameweek == 2


def test_ownership_and_full_candidate_universe_are_automatic(repository_root: Path) -> None:
    fpl, ruleset, capability, provider_body = _context(repository_root)
    provider = parse_provider_current_team(json.dumps(provider_body).encode())
    manager = CurrentManagerStateService(clock=lambda: CUTOFF).compile_provider_snapshot(
        provider,
        fpl_input=fpl,
        ruleset=ruleset,
        capability=capability,
        observed_at=CUTOFF,
    )
    eligible_fpl = fpl.model_copy(
        update={
            "players": tuple(
                item.model_copy(update={"can_select": True, "removed": False})
                for item in fpl.players
            )
        }
    )
    public = DirectPublicPicks(
        picks=tuple(
            {
                "element": item.element,
                "position": item.position,
                "multiplier": item.multiplier,
            }
            for item in provider.picks
        )
    )
    snapshot = DirectFplSnapshot(
        captured_at=CUTOFF,
        target_gameweek=2,
        fpl_input=eligible_fpl,
        entry=DirectEntry(id=42, started_event=1),
        history=DirectEntryHistory(current=()),
        transfers=(),
        latest_public_picks=public,
        current_team=provider,
        live_by_gameweek={},
        request_count=7,
        endpoint_classes=("BOOTSTRAP",),
    )

    identities = build_automatic_player_identity_map(snapshot, manager)
    ownership = build_automatic_ownership(snapshot, manager)
    candidates = build_full_candidate_policy(snapshot, manager, ruleset)
    squad = {item.official_fpl_element_id for item in manager.squad}
    expected_incoming = {
        item.provider_element_id
        for item in eligible_fpl.players
        if item.provider_element_id not in squad
    }

    assert {item.official_fpl_element_id for item in ownership.members} == squad
    assert all(item.acquired_gameweek == 1 for item in ownership.members)
    assert set(candidates.allowed_transfer_in_element_ids) == expected_incoming
    assert candidates.maximum_transfers == manager.free_transfers == 2
    assert "PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1" in candidates.rationale
    assert len(identities.players) == len(eligible_fpl.players)

    for free_transfers, expected_maximum in ((0, 0), (1, 1), (2, 2)):
        policy = build_full_candidate_policy(
            snapshot,
            manager.model_copy(update={"free_transfers": free_transfers}),
            ruleset,
        )
        assert policy.maximum_transfers == expected_maximum
        assert set(policy.allowed_transfer_in_element_ids) == expected_incoming

    oversized_players = tuple(
        eligible_fpl.players[-1].model_copy(
            update={"provider_element_id": 10_000 + index, "can_select": True, "removed": False}
        )
        for index in range(1001)
    )
    oversized_snapshot = snapshot.model_copy(
        update={"fpl_input": eligible_fpl.model_copy(update={"players": oversized_players})}
    )
    with pytest.raises(IngestionError, match="selectable player universe exceeds"):
        build_full_candidate_policy(oversized_snapshot, manager, ruleset)


def test_automatic_stage7_uses_accepted_model_with_global_shrinkage_when_history_missing(
    repository_root: Path,
) -> None:
    bootstrap = _synthetic_bootstrap(repository_root)
    templates = {int(item["element_type"]): item for item in bootstrap["elements"]}
    positions = (1, 1, *(2 for _ in range(6)), *(3 for _ in range(7)), *(4 for _ in range(5)))
    players = []
    for team_id in (1, 2):
        for offset, element_type in enumerate(positions, start=1):
            element_id = team_id * 1000 + offset
            player = deepcopy(templates[element_type])
            player.update(
                {
                    "id": element_id,
                    "code": 80000 + element_id,
                    "element_type": element_type,
                    "team": team_id,
                    "first_name": "Synthetic",
                    "second_name": f"Player {element_id}",
                    "web_name": f"P{element_id}",
                    "now_cost": 50,
                    "status": "a",
                    "can_select": True,
                    "removed": False,
                    "starts": 0,
                    "minutes": 0,
                }
            )
            players.append(player)
    bootstrap["elements"] = players
    fpl = CurrentFplInputService(clock=lambda: CUTOFF).compile_direct(
        CurrentFplDirectInputRequest(
            competition_key="PL",
            season_code="2026/27",
            target_gameweek=2,
            captured_at=CUTOFF,
            information_cutoff=CUTOFF,
        ),
        bootstrap_body=json.dumps(bootstrap).encode(),
        fixtures_body=json.dumps(_synthetic_fixtures(repository_root)).encode(),
    )
    team_ids = {
        item.provider_team_id: uuid5(
            NAMESPACE_URL, f"one-command-model-team-{item.provider_team_id}"
        )
        for item in fpl.teams
        if item.provider_team_id in {1, 2}
    }
    identities = seal_canonical_player_identity_map(
        PrivateCanonicalPlayerIdentityMap.model_construct(
            source_class="OPERATOR_INITIATED_DETERMINISTIC",
            resolved_at=CUTOFF,
            information_cutoff=CUTOFF,
            teams=tuple(
                PrivateCanonicalTeamIdentity(
                    official_fpl_team_id=team_id, canonical_team_id=canonical_id
                )
                for team_id, canonical_id in sorted(team_ids.items())
            ),
            players=tuple(
                PrivateCanonicalPlayerIdentity(
                    official_fpl_element_id=item.provider_element_id,
                    official_fpl_team_id=int(item.team_identity.external_id_text),
                    canonical_player_id=uuid5(
                        NAMESPACE_URL, f"one-command-model-player-{item.provider_element_id}"
                    ),
                )
                for item in fpl.players
                if int(item.team_identity.external_id_text) in {1, 2}
            ),
            semantic_sha256="0" * 64,
        )
    )
    fixture = next(
        item for item in fpl.fixtures if item.event_identity == fpl.target_event.identity
    )
    canonical_fixture_id = uuid5(NAMESPACE_URL, "one-command-model-target-fixture")
    canonical_fixture = CurrentMarketCanonicalFixture(
        official_fpl_fixture_id=fixture.provider_fixture_id,
        official_fpl_fixture_lookup_sha256=fixture.identity.canonical_lookup_sha256,
        provider_event_id="synthetic-odds-event",
        provider_event_identity_sha256="1" * 64,
        canonical_fixture_id=canonical_fixture_id,
        official_fpl_external_mapping_id=uuid5(NAMESPACE_URL, "one-command-model-fpl-map"),
        odds_event_external_mapping_id=uuid5(NAMESPACE_URL, "one-command-model-odds-map"),
        fixture_binding_sha256="2" * 64,
    )
    operator = CurrentMarketCanonicalOperator(
        bookmaker_key="synthetic",
        bookmaker_title="Synthetic",
        canonical_operator_id=uuid5(NAMESPACE_URL, "one-command-model-operator"),
        canonical_operator_key="transient:synthetic",
        external_mapping_id=uuid5(NAMESPACE_URL, "one-command-model-operator-map"),
        target_occurrence_times_sha256="3" * 64,
    )
    provisional_view = CurrentMarketCanonicalIdentityView.model_construct(
        authority="OPERATOR_INITIATED_DETERMINISTIC",
        resolved_at=CUTOFF,
        resolution_cutoff=CUTOFF,
        database_read_performed=False,
        provider_id=uuid5(NAMESPACE_URL, "one-command-model-provider"),
        fixtures=(canonical_fixture,),
        operators=(operator,),
        semantic_sha256="0" * 64,
    )
    view = provisional_view.model_copy(
        update={"semantic_sha256": current_market_identity_view_sha256(provisional_view)}
    )
    _, _, _, current_team_body = _context(repository_root)
    snapshot = DirectFplSnapshot(
        captured_at=CUTOFF,
        target_gameweek=2,
        fpl_input=fpl,
        entry=DirectEntry(id=42, started_event=1),
        history=DirectEntryHistory(current=()),
        transfers=(),
        latest_public_picks=None,
        current_team=parse_provider_current_team(json.dumps(current_team_body).encode()),
        live_by_gameweek={},
        request_count=6,
        endpoint_classes=("BOOTSTRAP",),
    )

    result = build_automatic_model_minutes(snapshot, identities, view)

    assert len(result) == 1
    assert result[0].model_family == "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1"
    assert result[0].model_derived is True
    assert "NO_USABLE_CURRENT_SEASON_PLAYER_HISTORY_GLOBAL_PRIORS_ONLY" in result[0].warnings
    assert len(result[0].home.scenarios) == 256
