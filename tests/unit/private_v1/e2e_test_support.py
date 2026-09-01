"""Repository-owned synthetic family for the private V1 end-to-end path."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.manual_override import ManualFixtureMinutesInput
from dmf_pulse.chips.compiler import compile_optimisation_chip_rules
from dmf_pulse.chips.inventory import build_chip_inventory
from dmf_pulse.football_events.score_prior_request import ScorePriorRequest
from dmf_pulse.football_events.service import load_score_baseline_policy
from dmf_pulse.fpl_points.models import MonteCarloPolicy, ProjectionMode
from dmf_pulse.fpl_points.player_prior import load_packaged_player_prior
from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateService,
    bind_current_unified_state_request,
)
from dmf_pulse.ingestion.fpl.current import CurrentFplInputRequest, CurrentFplInputService
from dmf_pulse.ingestion.fpl.manager_current import (
    CurrentManagerStateService,
    bind_current_manager_state_request,
)
from dmf_pulse.ingestion.odds.config import load_rights_profiles as load_odds_rights
from dmf_pulse.ingestion.odds.current import build_current_odds_input
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.optimisation.manager_state import selling_price_tenths
from dmf_pulse.private_v1.models import (
    PrivateCandidateActionPolicy,
    PrivateCanonicalPlayerIdentity,
    PrivateCanonicalPlayerIdentityMap,
    PrivateCanonicalTeamIdentity,
    PrivateCurrentOwnership,
    PrivateCurrentOwnershipMember,
    PrivateFixtureScorePrior,
    PrivateV1ExecutionInput,
    seal_candidate_action_policy,
    seal_canonical_player_identity_map,
    seal_current_ownership,
    seal_execution_input,
    seal_fixture_score_prior,
)
from dmf_pulse.private_v1.service import load_packaged_event_allocation_config
from dmf_pulse.rules.chips import build_chip_rules_view
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules
from tests.unit.ingestion.current_identity_test_support import (
    fixture_binding,
    fixture_plan,
    resolve_bridge,
    team_mapping,
    team_plan,
)
from tests.unit.ingestion.current_manager_test_support import active_target_rules
from tests.unit.ingestion.current_unified_state_test_support import CurrentUnifiedTestContext
from tests.unit.markets.current_market_test_support import (
    _fresh_odds,
    build_from_context,
    recompose,
)

_CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
_CAPTURED = datetime(2026, 8, 21, 16, 0, tzinfo=UTC)
_COMPETITION_ID = UUID("30000000-0000-7000-8000-000000000001")
_PLAYER_NAMESPACE = UUID("ccf8cdba-7dca-4d52-958f-c62d64325aa9")
_DONOR_NAMESPACE = UUID("7151293c-5b5d-5cc3-9689-c4e728ea8b55")
_DONOR_VERSION = "gw1-current-availability-stage7-v1"


def _lookup_sha(entity_type: str, namespace: str, external_id: int) -> str:
    return canonical_sha256(
        {
            "entity_type": entity_type,
            "external_id_text": str(external_id),
            "identifier_namespace": namespace,
            "provider_key": "official_fpl",
            "provider_product": "fantasy_premierleague",
            "season_code": "2026/27",
        }
    )


def _donor_team_id(source_team_id: int) -> str:
    identity = _lookup_sha("TEAM", "fpl.team.id", source_team_id)
    return str(uuid5(_DONOR_NAMESPACE, "\x1f".join((_DONOR_VERSION, "team", identity))))


def _selected_rosters() -> dict[int, tuple[tuple[int, int], ...]]:
    prior = load_packaged_player_prior().artifact
    source_by_profile = {item.player_id: item.source_player_id for item in prior.lineage}
    result: dict[int, tuple[tuple[int, int], ...]] = {}
    for team_id in range(1, 7):
        profiles = tuple(item for item in prior.profiles if item.team_id == _donor_team_id(team_id))
        goalkeepers = sorted(
            (
                source_by_profile[item.player_id]
                for item in profiles
                if item.goalkeeper_saves_per90 > 0
            ),
        )[:2]
        outfield = sorted(
            (
                source_by_profile[item.player_id]
                for item in profiles
                if item.goalkeeper_saves_per90 == 0
            ),
        )[:18]
        assert len(goalkeepers) == 2 and len(outfield) == 18
        positions = (2,) * 7 + (3,) * 7 + (4,) * 4
        result[team_id] = tuple((item, 1) for item in goalkeepers) + tuple(
            zip(outfield, positions, strict=True)
        )
    return result


def _build_fpl_input(repository_root: Path, working: Path):
    source = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap = json.loads((source / "bootstrap.json").read_text(encoding="utf-8"))
    fixtures_source = json.loads((source / "fixtures.json").read_text(encoding="utf-8"))
    assert isinstance(bootstrap, dict) and isinstance(fixtures_source, list)
    original_teams = bootstrap["teams"]
    original_players = bootstrap["elements"]
    templates = {int(item["element_type"]): item for item in original_players}
    teams = []
    for team_id in range(1, 7):
        team = deepcopy(original_teams[(team_id - 1) % len(original_teams)])
        team.update(
            {
                "id": team_id,
                "code": 3100 + team_id,
                "name": f"Private Synthetic Club {team_id}",
                "short_name": f"PV{team_id}",
            }
        )
        teams.append(team)
    players = []
    for ordinal, (team_id, roster) in enumerate(_selected_rosters().items()):
        for local_index, (element_id, element_type) in enumerate(roster):
            player = deepcopy(templates[element_type])
            player.update(
                {
                    "id": element_id,
                    "code": 800000 + ordinal * 100 + local_index,
                    "element_type": element_type,
                    "team": team_id,
                    "now_cost": 45 + local_index,
                    "first_name": f"Private{team_id}",
                    "second_name": f"Synthetic{local_index + 1}",
                    "web_name": f"PV{team_id}P{local_index + 1}",
                    "status": "a",
                    "chance_of_playing_this_round": None,
                    "chance_of_playing_next_round": None,
                    "news": "",
                    "news_added": None,
                }
            )
            players.append(player)
    fixture_template = fixtures_source[0]
    fixtures = []
    for index, (home, away) in enumerate(((1, 2), (3, 4), (5, 6)), start=1):
        fixture = deepcopy(fixture_template)
        fixture.update(
            {
                "id": 100 + index,
                "code": 910100 + index,
                "event": 1,
                "kickoff_time": f"2026-08-22T{12 + index * 2:02d}:00:00Z",
                "team_h": home,
                "team_a": away,
            }
        )
        fixtures.append(fixture)
    bootstrap["teams"] = teams
    bootstrap["elements"] = players
    working.mkdir(parents=True, exist_ok=True)
    bootstrap_path = working / "bootstrap.json"
    fixture_path = working / "fixtures.json"
    bootstrap_path.write_text(json.dumps(bootstrap, sort_keys=True), encoding="utf-8")
    fixture_path.write_text(json.dumps(fixtures, sort_keys=True), encoding="utf-8")
    clock = iter((_CAPTURED + timedelta(minutes=5), _CAPTURED + timedelta(minutes=6)))
    return CurrentFplInputService(clock=lambda: next(clock)).compile(
        CurrentFplInputRequest(
            bootstrap_path=bootstrap_path,
            fixtures_path=fixture_path,
            competition_key="PL",
            season_code="2026/27",
            target_gameweek=1,
            captured_at=_CAPTURED,
            information_cutoff=_CUTOFF,
            rights_profile_id="fpl_official_private_manual_v1",
        )
    )


def _manager_squad_ids(fpl_input: Any) -> tuple[int, ...]:
    players = {
        (int(item.team_identity.external_id_text), item.position.value): []
        for item in fpl_input.players
    }
    for player in fpl_input.players:
        players[(int(player.team_identity.external_id_text), player.position.value)].append(
            player.provider_element_id
        )
    for values in players.values():
        values.sort()
    selected = (
        players[(1, "GK")][0],
        players[(1, "DEF")][0],
        players[(1, "MID")][0],
        players[(2, "GK")][0],
        players[(2, "DEF")][0],
        players[(2, "MID")][0],
        players[(3, "DEF")][0],
        players[(3, "MID")][0],
        players[(3, "FWD")][0],
        players[(4, "DEF")][0],
        players[(4, "MID")][0],
        players[(4, "FWD")][0],
        players[(5, "DEF")][0],
        players[(5, "MID")][0],
        players[(5, "FWD")][0],
    )
    return tuple(sorted(selected))


def _compile_manager(working: Path, fpl_input: Any, ruleset: Any, capability: Any):
    transfer_rules = build_multi_gameweek_transfer_rules(
        ruleset, projection_mode=ProjectionMode.PRODUCTION, capability=capability
    )
    chip_rules = compile_optimisation_chip_rules(build_chip_rules_view(ruleset))
    by_id = {item.provider_element_id: item for item in fpl_input.players}
    squad_ids = _manager_squad_ids(fpl_input)
    by_position: dict[str, list[int]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    squad = []
    for element_id in squad_ids:
        player = by_id[element_id]
        by_position[player.position.value].append(element_id)
        purchase = player.current_price_tenths
        squad.append(
            {
                "official_fpl_element_id": element_id,
                "purchase_price_tenths": purchase,
                "observed_selling_price_tenths": selling_price_tenths(
                    purchase_price_tenths=purchase,
                    current_price_tenths=purchase,
                    rule=transfer_rules.selling_price_rule,
                ),
            }
        )
    starters = (
        by_position["GK"][0],
        *by_position["DEF"][:4],
        *by_position["MID"][:4],
        *by_position["FWD"][:2],
    )
    bench_outfield = (by_position["DEF"][4], by_position["MID"][4], by_position["FWD"][2])
    inventory = build_chip_inventory(chip_rules, current_gameweek=1)
    declaration = {
        "schema_version": "1.0.0",
        "source_class": "OPERATOR_DECLARED",
        "season_code": "2026/27",
        "target_gameweek": 1,
        "information_cutoff": _CUTOFF.isoformat().replace("+00:00", "Z"),
        "attestation": {
            "declaration_method": "OPERATOR_DECLARED",
            "attestation_status": "HUMAN_ATTESTED",
            "provider_verification": "NOT_PROVIDER_VERIFIED",
            "declared_at": (_CAPTURED + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "attested_at": (_CAPTURED + timedelta(minutes=11)).isoformat().replace("+00:00", "Z"),
            "operator_reference": "repository-synthetic-private-v1",
        },
        "squad": squad,
        "bank_tenths": 200,
        "free_transfers": 1,
        "lineup": {
            "starting_xi_element_ids": sorted(starters),
            "bench_goalkeeper_element_id": by_position["GK"][1],
            "bench_outfield_element_ids": list(bench_outfield),
            "captain_element_id": by_position["MID"][0],
            "vice_captain_element_id": by_position["FWD"][0],
        },
        "chip_tokens": [
            {
                "token_id": item.token_id,
                "status": item.status.value,
                "selected_at_gameweek": None,
                "active_from_gameweek": None,
                "used_at_gameweek": None,
            }
            for item in inventory.tokens
        ],
        "overall_points": None,
        "overall_rank": None,
    }
    path = working / "manager.json"
    path.write_text(json.dumps(declaration, sort_keys=True), encoding="utf-8")
    request = bind_current_manager_state_request(path, fpl_input, ruleset, capability)
    clock = iter((_CAPTURED + timedelta(minutes=12), _CAPTURED + timedelta(minutes=13)))
    return CurrentManagerStateService(clock=lambda: next(clock)).compile(
        request, fpl_input=fpl_input, ruleset=ruleset, capability=capability
    )


def _replace_participants(event: dict[str, Any], home: str, away: str) -> None:
    old_home = str(event["home_team"])
    old_away = str(event["away_team"])
    event["home_team"] = home
    event["away_team"] = away
    for bookmaker in event["bookmakers"]:
        for market in bookmaker["markets"]:
            for outcome in market["outcomes"]:
                if outcome["name"] == old_home:
                    outcome["name"] = home
                elif outcome["name"] == old_away:
                    outcome["name"] = away


def _build_odds(repository_root: Path):
    raw = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    assert isinstance(raw, list)
    template = raw[0]
    events = []
    for index, (home, away) in enumerate(((1, 2), (3, 4), (5, 6)), start=1):
        event = deepcopy(template)
        event["id"] = f"private-v1-event-{index}"
        event["commence_time"] = f"2026-08-22T{12 + index * 2:02d}:00:00Z"
        _replace_participants(
            event, f"Private Synthetic Club {home}", f"Private Synthetic Club {away}"
        )
        events.append(event)
    received = _CAPTURED + timedelta(minutes=20)
    body = json.dumps(events, allow_nan=False, separators=(",", ":")).encode()
    odds = build_current_odds_input(
        parse_odds_payload(body),
        profile=load_odds_rights()["the_odds_api_private_analytics_v1"],
        source_snapshot_id=UUID("00000000-0000-0000-0000-000000008501"),
        request_started_at=received - timedelta(seconds=1),
        received_at=received,
        information_cutoff=_CUTOFF,
        usable_at=received + timedelta(minutes=1),
        quota=QuotaState(
            remaining=498,
            used=2,
            last_cost=2,
            observed_at=received,
            source=QuotaSource.RESPONSE_HEADERS,
        ),
        request_fingerprint="1" * 64,
        sanitized_target=(
            "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?"
            "regions=uk&markets=h2h%2Ctotals&oddsFormat=decimal&dateFormat=iso&"
            "commenceTimeFrom=2026-08-21T17%3A30%3A00Z"
        ),
        attempt_count=1,
        transport_call_count=1,
        transport_id="injected",
        provider_request_id_sha256="2" * 64,
    )
    return _fresh_odds(odds)


def _unified_context(repository_root: Path, working: Path) -> CurrentUnifiedTestContext:
    fpl_input = _build_fpl_input(repository_root, working)
    ruleset, capability = active_target_rules(repository_root)
    manager = _compile_manager(working, fpl_input, ruleset, capability)
    odds = _build_odds(repository_root)
    by_team = {item.provider_team_id: item for item in fpl_input.teams}
    approved = _CAPTURED + timedelta(minutes=55)
    aliases = team_plan(
        fpl_input,
        mappings=tuple(
            team_mapping(
                f"Private Synthetic Club {team_id}", by_team[team_id], approved_at=approved
            )
            for team_id in range(1, 7)
        ),
        approved_at=approved,
    )
    targets = tuple(sorted(fpl_input.fixtures, key=lambda item: item.provider_fixture_id))
    mapping_plan = fixture_plan(
        fpl_input,
        odds,
        aliases,
        bindings=tuple(
            fixture_binding(
                fpl_input,
                odds,
                aliases,
                fixture=fixture,
                provider_event_id=f"private-v1-event-{index}",
                approved_at=approved,
            )
            for index, fixture in enumerate(targets, start=1)
        ),
        approved_at=approved,
    )
    identity = resolve_bridge(
        fpl_input,
        odds,
        aliases,
        mapping_plan,
        decided_at=_CAPTURED + timedelta(minutes=60),
    )
    request = bind_current_unified_state_request(
        fpl_input, odds, identity, manager, ruleset, capability
    )
    bundle = CurrentUnifiedStateService().compose(
        request,
        fpl_input=fpl_input,
        odds_input=odds,
        identity_map=identity,
        manager_state=manager,
        ruleset=ruleset,
        capability=capability,
    )
    return CurrentUnifiedTestContext(
        fpl_input=fpl_input,
        odds_input=odds,
        identity_map=identity,
        manager_state=manager,
        ruleset=ruleset,
        capability=capability,
        request=request,
        bundle=bundle,
    )


def _identity_map(context: CurrentUnifiedTestContext) -> PrivateCanonicalPlayerIdentityMap:
    teams = tuple(
        PrivateCanonicalTeamIdentity(
            official_fpl_team_id=item.provider_team_id,
            canonical_team_id=UUID(f"20000000-0000-7000-8000-{item.provider_team_id:012d}"),
        )
        for item in sorted(context.fpl_input.teams, key=lambda value: value.provider_team_id)
    )
    players = tuple(
        PrivateCanonicalPlayerIdentity(
            official_fpl_element_id=item.provider_element_id,
            official_fpl_team_id=int(item.team_identity.external_id_text),
            canonical_player_id=uuid5(_PLAYER_NAMESPACE, str(item.provider_element_id)),
        )
        for item in sorted(context.fpl_input.players, key=lambda value: value.provider_element_id)
    )
    return seal_canonical_player_identity_map(
        PrivateCanonicalPlayerIdentityMap.model_construct(
            source_class="REPOSITORY_SYNTHETIC",
            resolved_at=_CAPTURED + timedelta(minutes=45),
            information_cutoff=_CUTOFF,
            teams=teams,
            players=players,
            semantic_sha256="0" * 64,
        )
    )


def _manual_team(team_id: str, players: tuple[Any, ...]) -> dict[str, Any]:
    ordered = sorted(players, key=lambda item: str(item.canonical_player_id))
    goalkeeper_ids = [item.canonical_player_id for item in ordered if item.position.value == "GK"]
    outfield_ids = [item.canonical_player_id for item in ordered if item.position.value != "GK"]
    scenarios = []
    for scenario_index in range(4):
        starting_goalkeeper = goalkeeper_ids[scenario_index % 2]
        starting_outfield = {
            outfield_ids[(scenario_index * 5 + offset) % len(outfield_ids)] for offset in range(10)
        }
        starters = {starting_goalkeeper, *starting_outfield}
        rows = []
        for player_index, item in enumerate(ordered):
            starting = item.canonical_player_id in starters
            rows.append(
                {
                    "player_id": str(item.canonical_player_id),
                    "position": item.position.value,
                    "role": "START" if starting else "BENCH",
                    "official_minutes": (
                        90 - 10 * ((player_index + scenario_index) % 4)
                        if starting
                        else 20 * ((player_index + scenario_index) % 2)
                    ),
                }
            )
        scenarios.append(
            {
                "scenario_id": f"SCENARIO_{scenario_index + 1:02d}",
                "count": 64,
                "players": rows,
            }
        )
    return {
        "team_id": team_id,
        "bench_size": 9,
        "bench_goalkeeper_slots": 1,
        "scenarios": tuple(scenarios),
        "hard_overrides": (),
    }


def _manual_inputs(
    context: CurrentUnifiedTestContext, identities: PrivateCanonicalPlayerIdentityMap, view: Any
):
    mapped_by_element = {item.official_fpl_element_id: item for item in identities.players}
    current_by_team: dict[int, list[Any]] = {
        item.official_fpl_team_id: [] for item in identities.teams
    }
    current_players = {item.provider_element_id: item for item in context.fpl_input.players}
    for mapping in identities.players:
        player = current_players[mapping.official_fpl_element_id]
        current_by_team[mapping.official_fpl_team_id].append(
            player.model_copy(update={"canonical_player_id": mapping.canonical_player_id})
        )
    team_uuid = {
        item.official_fpl_team_id: str(item.canonical_team_id) for item in identities.teams
    }
    fixture_by_official = {item.provider_fixture_id: item for item in context.fpl_input.fixtures}
    results = []
    for item in sorted(view.fixtures, key=lambda value: value.official_fpl_fixture_id):
        fixture = fixture_by_official[item.official_fpl_fixture_id]
        home = int(fixture.home_team_identity.external_id_text)
        away = int(fixture.away_team_identity.external_id_text)
        fixture_id = str(item.canonical_fixture_id)
        provenance = {
            "supplier_type": "PRIVATE_OPERATOR",
            "operator_ref": "repository-synthetic-private-v1",
            "evidence_type": "ANALYST_SCENARIO_JUDGEMENT",
            "source_ref": "REPOSITORY_SYNTHETIC_INPUT",
            "source_timestamp": (_CAPTURED + timedelta(minutes=41)).isoformat(),
            "entered_at": (_CAPTURED + timedelta(minutes=42)).isoformat(),
            "usable_at": (_CAPTURED + timedelta(minutes=43)).isoformat(),
            "adjustment_type": "SOFT_SCENARIO_MIXTURE",
            "reason": "Repository-owned deterministic end-to-end scenario.",
            "expires_at": (_CUTOFF + timedelta(days=1)).isoformat(),
            "fixture_scope_id": fixture_id,
            "classification": "PRIVATE_TRANSIENT",
            "persistence_class": "TRANSIENT_PRIVATE",
            "model_derived": False,
            "production_suitable": False,
        }
        results.append(
            ManualFixtureMinutesInput.model_validate(
                {
                    "schema_version": "private-manual-transient-minutes-v1",
                    "fixture_id": fixture_id,
                    "home_team_id": team_uuid[home],
                    "away_team_id": team_uuid[away],
                    "as_of": _CUTOFF,
                    "information_cutoff": _CUTOFF,
                    "provenance": provenance,
                    "home": _manual_team(team_uuid[home], tuple(current_by_team[home])),
                    "away": _manual_team(team_uuid[away], tuple(current_by_team[away])),
                }
            )
        )
    assert len(mapped_by_element) == 120
    return tuple(results)


def build_execution_input(
    repository_root: Path,
    working: Path,
) -> PrivateV1ExecutionInput:
    """Build the complete deterministic TEST-mode input without network access."""

    context = _unified_context(repository_root, working)
    context = recompose(context, context.odds_input)
    view, _market_request, markets = build_from_context(context)
    identities = _identity_map(context)
    manual = _manual_inputs(context, identities, view)
    manual_by_fixture = {item.fixture_id: item for item in manual}
    score_bundles = tuple(
        seal_fixture_score_prior(
            PrivateFixtureScorePrior.model_construct(
                source_class="REPOSITORY_OWNED_SYNTHETIC",
                fixture_id=item.canonical_fixture_id,
                competition_id=_COMPETITION_ID,
                home_team_id=UUID(manual_by_fixture[str(item.canonical_fixture_id)].home_team_id),
                away_team_id=UUID(manual_by_fixture[str(item.canonical_fixture_id)].away_team_id),
                as_of=_CUTOFF,
                score_prior_request=ScorePriorRequest(
                    home_goal_rate=Decimal("1.600000"),
                    away_goal_rate=Decimal("1.300000"),
                ),
                current_bundle=None,
                semantic_sha256="0" * 64,
            )
        )
        for item in sorted(view.fixtures, key=lambda value: str(value.canonical_fixture_id))
    )
    squad_ids = tuple(sorted(item.official_fpl_element_id for item in context.manager_state.squad))
    ownership = seal_current_ownership(
        PrivateCurrentOwnership.model_construct(
            source_class="OPERATOR_DECLARED_PRIVATE_TRANSIENT",
            attestation_status="HUMAN_ATTESTED",
            provider_verification="NOT_PROVIDER_VERIFIED",
            target_gameweek=1,
            declared_at=_CAPTURED + timedelta(minutes=47),
            attested_at=_CAPTURED + timedelta(minutes=48),
            information_cutoff=_CUTOFF,
            members=tuple(
                PrivateCurrentOwnershipMember(official_fpl_element_id=item, acquired_gameweek=1)
                for item in squad_ids
            ),
            semantic_sha256="0" * 64,
        )
    )
    current_squad = set(squad_ids)
    incoming = next(
        item.provider_element_id
        for item in sorted(context.fpl_input.players, key=lambda value: value.provider_element_id)
        if item.position.value == "GK"
        and int(item.team_identity.external_id_text) == 1
        and item.provider_element_id not in current_squad
    )
    candidates = seal_candidate_action_policy(
        PrivateCandidateActionPolicy.model_construct(
            allowed_transfer_in_element_ids=(incoming,),
            maximum_transfers=1,
            rationale=(
                "One explicit repository-owned synthetic goalkeeper candidate; the club cap "
                "leaves exactly one feasible transfer pairing."
            ),
            semantic_sha256="0" * 64,
        )
    )
    mc_policy = MonteCarloPolicy(
        minimum_effective_scenarios=1.0,
        maximum_mean_mcse=100.0,
        maximum_probability_se=1.0,
        maximum_quantile_span=100,
        quantiles=(0.1, 0.5, 0.9),
        thresholds=(5, 10, 15),
        batch_count=2,
    )
    allocation = load_packaged_event_allocation_config()
    allocation = allocation.model_copy(
        update={
            "model_version_id": "private-v1-repository-synthetic-allocation-v1",
            "source_tag": "TEST_SYNTHETIC",
            "auxiliary_source_tag": "TEST_SYNTHETIC",
            "goal_time_lower": 1.0,
            "goal_time_upper": 50.0,
            "penalty_goal_probability": 0.0,
            "set_piece_goal_probability": 0.0,
            "direct_free_kick_goal_probability": 0.0,
            "own_goal_probability": 0.0,
            "extra_penalty_attempt_probability": 0.0,
            "extra_penalty_save_probability": 0.0,
        }
    )
    player_prior = load_packaged_player_prior()
    provisional = PrivateV1ExecutionInput.model_construct(
        run_id="PRIVATE_V1_SYNTHETIC_E2E",
        code_sha="a" * 40,
        projection_mode=ProjectionMode.TEST,
        retention_class="SYNTHETIC_REPLAY_ALLOWED",
        synthetic_source_attestation="REPOSITORY_OWNED_SYNTHETIC_ONLY",
        current_state=context.bundle,
        player_identity_map=identities,
        market_identity_view=view,
        market_constraints=markets,
        score_priors=score_bundles,
        manual_minutes=manual,
        ownership=ownership,
        candidate_action_policy=candidates,
        ruleset=context.ruleset,
        full_season_capability=context.capability,
        root_seed=1729,
        scenario_count=1,
        stage9_monte_carlo_policy=mc_policy,
        stage9_monte_carlo_policy_sha256=canonical_sha256(mc_policy.model_dump(mode="json")),
        event_allocation_config=allocation,
        event_allocation_config_sha256=canonical_sha256(allocation.model_dump(mode="json")),
        expected_stage8_policy_sha256=load_score_baseline_policy().sha256,
        expected_player_prior_artifact_sha256=player_prior.artifact.artifact_sha256,
        expected_player_prior_acceptance_sha256=(
            player_prior.historical_acceptance.acceptance_sha256
        ),
        require_stage9_mc_pass=False,
        semantic_sha256="0" * 64,
    )
    return seal_execution_input(provisional)


__all__ = ["build_execution_input"]
