"""Network-blocked provider-shaped E2E through the one-command orchestration boundary."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.chips.compiler import compile_optimisation_chip_rules
from dmf_pulse.chips.inventory import build_chip_inventory
from dmf_pulse.fpl_points.player_prior import load_packaged_player_prior
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectFplRunAttestation,
    DirectHttpRequest,
    DirectHttpResponse,
)
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.current import build_current_odds_input
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload
from dmf_pulse.ingestion.openfootball.config import load_rights_profiles as load_score_rights
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorService
from dmf_pulse.private_v1.one_command import (
    OneCommandRequest,
    PrivateV1OneCommandService,
)
from dmf_pulse.rules.chips import build_chip_rules_view
from dmf_pulse.rules.compiler import compile_ruleset
from tests.unit.ingestion.current_identity_test_support import KICKOFF
from tests.unit.ingestion.current_manager_test_support import (
    _synthetic_bootstrap,
    _synthetic_fixtures,
)
from tests.unit.ingestion.openfootball.conftest import FakeTransport as ScoreTransport
from tests.unit.ingestion.openfootball.conftest import synthetic_snapshot

pytestmark = pytest.mark.unit
RUN_AT = datetime(2026, 9, 1, 12, tzinfo=UTC)
TARGET_KICKOFF = datetime(2026, 9, 5, 14, tzinfo=UTC)


class _DirectTransport:
    def __init__(self, bodies: tuple[bytes, ...]) -> None:
        self.bodies = list(bodies)
        self.requests: list[DirectHttpRequest] = []

    def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
        self.requests.append(request)
        if not self.bodies:
            raise AssertionError("unexpected direct FPL request")
        return DirectHttpResponse(200, "application/json", self.bodies.pop(0))


class _OddsService:
    def __init__(self, value: object) -> None:
        self.value = value

    def acquire(self, *, information_cutoff: object, commence_to: object) -> object:
        del information_cutoff, commence_to
        return self.value


def _position_fallback_source_ids() -> dict[str, int]:
    prior = load_packaged_player_prior()
    profiles = {item.player_id: item for item in prior.artifact.profiles}
    donors = tuple(
        item.source_player_id
        for item in prior.artifact.lineage
        if {
            item.goal_source_level,
            item.assist_source_level,
            item.auxiliary_source_level,
        }
        == {"FPL_POSITION"}
    )
    assert len(donors) >= 4
    penalty_donors = tuple(
        item.source_player_id
        for item in prior.artifact.lineage
        if item.source_player_id in donors and profiles[item.player_id].penalty_taker_share > 0
    )
    assert len(penalty_donors) >= 4
    return dict(zip(("GK", "DEF", "MID", "FWD"), penalty_donors[:4], strict=True))


def _provider_sources(repository_root: Path) -> tuple[tuple[bytes, ...], bytes]:
    bootstrap = _synthetic_bootstrap(repository_root)
    source_teams = bootstrap["teams"]
    original_players = bootstrap["elements"]
    assert isinstance(source_teams, list)
    assert isinstance(original_players, list)
    teams = []
    for team_id in range(1, 7):
        team = deepcopy(source_teams[(team_id - 1) % len(source_teams)])
        team.update(
            {
                "id": team_id,
                "code": 9000 + team_id,
                "name": f"One Command Club {team_id}",
                "short_name": f"OC{team_id}",
            }
        )
        teams.append(team)
    templates = {int(item["element_type"]): item for item in original_players}
    position_types = (1, 1, *(2 for _ in range(6)), *(3 for _ in range(7)), *(4 for _ in range(5)))
    position_name = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    fallbacks = _position_fallback_source_ids()
    used_ids = set(fallbacks.values())
    players = []
    ids_by_team_position: dict[tuple[int, str], list[int]] = {}
    next_id = 50_000
    for team_id in range(1, 7):
        fallback_used: set[str] = set()
        for offset, element_type in enumerate(position_types, start=1):
            position = position_name[element_type]
            if team_id == 6 and position not in fallback_used:
                element_id = fallbacks[position]
                fallback_used.add(position)
            else:
                while next_id in used_ids:
                    next_id += 1
                element_id = next_id
                used_ids.add(element_id)
                next_id += 1
            player = deepcopy(templates[element_type])
            player.update(
                {
                    "id": element_id,
                    "code": 100_000 + element_id,
                    "element_type": element_type,
                    "team": team_id,
                    "first_name": "OneCommand",
                    "second_name": f"Player {team_id}-{offset}",
                    "web_name": f"OC{team_id}P{offset}",
                    "now_cost": 50,
                    "status": "a",
                    "can_select": False,
                    "removed": False,
                    "starts": 1 if offset <= 11 else 0,
                    "minutes": 90 if offset <= 11 else 0,
                }
            )
            players.append(player)
            ids_by_team_position.setdefault((team_id, position), []).append(element_id)
    bootstrap["teams"] = teams
    bootstrap["elements"] = players
    bootstrap["events"][0].update(
        {
            "finished": True,
            "data_checked": True,
            "is_previous": True,
            "is_current": False,
        }
    )
    bootstrap["events"][1].update({"is_next": True, "finished": False, "data_checked": False})
    bootstrap["events"][1]["deadline_time"] = "2026-09-04T17:30:00Z"
    fixture_template = _synthetic_fixtures(repository_root)[0]
    fixtures = []
    fixture_id = 100
    for gameweek, kickoff_base in (
        (1, KICKOFF - timedelta(days=7)),
        (2, TARGET_KICKOFF),
    ):
        for index, (home, away) in enumerate(((1, 2), (3, 4), (5, 6))):
            fixture_id += 1
            fixture = deepcopy(fixture_template)
            fixture.update(
                {
                    "id": fixture_id,
                    "code": 700_000 + fixture_id,
                    "event": gameweek,
                    "kickoff_time": (kickoff_base + timedelta(hours=index))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "team_h": home,
                    "team_a": away,
                    "finished": gameweek == 1,
                    "started": gameweek == 1,
                    "finished_provisional": False,
                }
            )
            fixtures.append(fixture)

    selection = {
        1: ("GK", "DEF", "MID"),
        2: ("GK", "DEF", "FWD"),
        3: ("DEF", "MID", "FWD"),
        4: ("DEF", "MID", "FWD"),
        5: ("DEF", "MID", "MID"),
    }
    selected: dict[tuple[int, str], list[int]] = {
        key: list(value) for key, value in ids_by_team_position.items()
    }
    squad: list[int] = []
    for team_id, positions in selection.items():
        for position in positions:
            squad.append(selected[(team_id, position)].pop(0))
    position_by_id = {int(item["id"]): position_name[int(item["element_type"])] for item in players}
    defenders = [item for item in squad if position_by_id[item] == "DEF"]
    midfielders = [item for item in squad if position_by_id[item] == "MID"]
    forwards = [item for item in squad if position_by_id[item] == "FWD"]
    starters = [
        next(item for item in squad if position_by_id[item] == "GK"),
        *defenders[:4],
        *midfielders[:4],
        *forwards[:2],
    ]
    remaining = [item for item in squad if item not in starters]
    bench_gk = next(item for item in remaining if position_by_id[item] == "GK")
    bench_outfield = [item for item in remaining if item != bench_gk]
    ordered = [*starters, bench_gk, *bench_outfield]
    candidate_id = next(int(item["id"]) for item in players if int(item["id"]) not in squad)
    next(item for item in players if int(item["id"]) == candidate_id)["can_select"] = True
    ruleset = compile_ruleset(repository_root / "config/rules/fpl-2026-27")
    chip_bundle = compile_optimisation_chip_rules(build_chip_rules_view(ruleset))
    inventory = build_chip_inventory(chip_bundle, current_gameweek=2)
    chip_names = {
        "WILDCARD": "wildcard",
        "FREE_HIT": "freehit",
        "BENCH_BOOST": "bboost",
        "TRIPLE_CAPTAIN": "3xc",
    }
    chip_numbers: dict[str, int] = {}
    chips = []
    for token in inventory.tokens:
        chip_numbers[token.chip_key] = chip_numbers.get(token.chip_key, 0) + 1
        chips.append(
            {
                "name": chip_names[token.chip_key],
                "number": chip_numbers[token.chip_key],
                "status_for_entry": (
                    "available" if token.status.value == "AVAILABLE" else "unavailable"
                ),
                "played_by_entry": [],
            }
        )
    current_team = {
        "picks": [
            {
                "element": element_id,
                "position": position,
                "selling_price": 50,
                "purchase_price": 50,
                "multiplier": 1 if position <= 11 else 0,
                "is_captain": position == 1,
                "is_vice_captain": position == 2,
            }
            for position, element_id in enumerate(ordered, start=1)
        ],
        "chips": chips,
        "transfers": {
            "cost": 0,
            "status": "cost",
            "limit": 1,
            "made": 0,
            "bank": 100,
            "value": 850,
        },
    }
    public_picks = {
        "picks": [
            {"element": item, "position": index, "multiplier": 1 if index <= 11 else 0}
            for index, item in enumerate(ordered, start=1)
        ]
    }
    live = {
        "elements": [
            {
                "id": int(item["id"]),
                "stats": {"minutes": int(item["minutes"]), "starts": int(item["starts"])},
            }
            for item in players
        ]
    }
    direct_bodies = (
        json.dumps(bootstrap).encode(),
        json.dumps(fixtures).encode(),
        b'{"id":42,"started_event":1,"summary_overall_points":60,"summary_overall_rank":10}',
        b'{"current":[{"event":1,"points":60,"total_points":60,"overall_rank":10,'
        b'"bank":100,"value":850,"event_transfers":0,"event_transfers_cost":0}]}',
        b"[]",
        json.dumps(public_picks).encode(),
        json.dumps(current_team).encode(),
        json.dumps(live).encode(),
    )
    return direct_bodies, json.dumps(fixtures).encode()


def _odds_input(repository_root: Path) -> object:
    raw = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    template = raw[0]
    events = []
    for index, (home, away) in enumerate(((1, 2), (3, 4), (5, 6))):
        event = deepcopy(template)
        old_home = event["home_team"]
        old_away = event["away_team"]
        home_name = f"One Command Club {home}"
        away_name = f"One Command Club {away}"
        event.update(
            {
                "id": f"one-command-event-{index + 1}",
                "commence_time": (TARGET_KICKOFF + timedelta(hours=index))
                .isoformat()
                .replace("+00:00", "Z"),
                "home_team": home_name,
                "away_team": away_name,
            }
        )
        for bookmaker in event["bookmakers"]:
            bookmaker["last_update"] = "2026-09-01T11:55:00Z"
            for market in bookmaker["markets"]:
                market["last_update"] = "2026-09-01T11:55:00Z"
                if market["key"] != "h2h":
                    continue
                for outcome in market["outcomes"]:
                    if outcome["name"] == old_home:
                        outcome["name"] = home_name
                    elif outcome["name"] == old_away:
                        outcome["name"] = away_name
        events.append(event)
    body = json.dumps(events, separators=(",", ":")).encode()
    profile: RightsProfile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    target = (
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?regions=uk&"
        "markets=h2h%2Ctotals&oddsFormat=decimal&dateFormat=iso&"
        "commenceTimeFrom=2026-09-01T12%3A00%3A00%2B00%3A00"
    )
    return build_current_odds_input(
        parse_odds_payload(body),
        profile=profile,
        source_snapshot_id=uuid5(NAMESPACE_URL, "one-command-odds-snapshot"),
        request_started_at=RUN_AT,
        received_at=RUN_AT,
        information_cutoff=RUN_AT,
        usable_at=RUN_AT,
        quota=QuotaState(
            remaining=100,
            used=2,
            last_cost=2,
            observed_at=RUN_AT,
            source=QuotaSource.RESPONSE_HEADERS,
        ),
        request_fingerprint="1" * 64,
        sanitized_target=target,
        attempt_count=1,
        transport_call_count=1,
        transport_id="injected",
        provider_request_id_sha256=canonical_sha256("one-command-request"),
    )


def test_network_blocked_synthetic_one_command_runs_actual_decision_stack(
    repository_root: Path,
) -> None:
    direct_bodies, _ = _provider_sources(repository_root)
    marker = "synthetic-token"
    direct_transport = _DirectTransport(direct_bodies)
    odds = _odds_input(repository_root)
    score_config, score_bodies = synthetic_snapshot()

    def direct_factory(attestation: DirectFplRunAttestation) -> DirectFplClient:
        return DirectFplClient(
            attestation,
            transport=direct_transport,
            credential_provider=DirectFplCredentialProvider({"DMF_FPL_BEARER_TOKEN": marker}),
            sleeper=lambda _: None,
            pace_seconds=0,
        )

    def score_factory(clock):
        return CurrentScorePriorService(
            provider_config=score_config,
            rights_profiles=load_score_rights(),
            transport=ScoreTransport(score_bodies),
            clock=clock,
            provider_config_identity="a" * 64,
            rights_config_identity="b" * 64,
        )

    service = PrivateV1OneCommandService(
        direct_client_factory=direct_factory,
        odds_service_factory=lambda clock: _OddsService(odds),
        score_service_factory=score_factory,
        clock=lambda: RUN_AT,
    )
    result = service.run(
        OneCommandRequest(
            entry_id=42,
            code_sha="a" * 40,
            run_at=RUN_AT,
            operator_approved_at=RUN_AT - timedelta(minutes=1),
            scenario_count=32,
            root_seed=42,
        )
    )

    assert result.status == "REAL_PRIVATE_TRANSIENT_RECOMMENDATION"
    assert result.persistence_performed is False
    assert result.fpl_request_count == 8
    assert result.report.startswith("DMF PULSE - GW2\n\nRECOMMENDATION")
    assert "No action:" in result.report
    assert "Captain:" in result.report
    assert "FPL_API_OPERATOR_INITIATED_ACCEPTED_CONTRACTUAL_RISK" in result.report
    assert len(direct_transport.requests) == 8
    assert direct_transport.bodies == []
