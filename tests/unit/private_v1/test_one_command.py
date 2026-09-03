"""Network-blocked provider-shaped E2E through the one-command orchestration boundary."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
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
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.one_command import (
    OneCommandRequest,
    PrivateV1OneCommandService,
)
from dmf_pulse.private_v1.progress import HumanCliProgress
from dmf_pulse.private_v1.rolling_models import PrivateV1RollingDecision
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
        self.requests: list[tuple[object, object]] = []

    def acquire(self, *, information_cutoff: object, commence_to: object) -> object:
        self.requests.append((information_cutoff, commence_to))
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
                    "penalties_order": 1 if offset == 1 else 0,
                    "penalties_text": "",
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
    for gameweek, deadline in (
        (3, "2026-09-11T17:30:00Z"),
        (4, "2026-09-18T17:30:00Z"),
    ):
        event = deepcopy(bootstrap["events"][1])
        event.update(
            {
                "id": gameweek,
                "name": f"Gameweek {gameweek}",
                "deadline_time": deadline,
                "is_next": False,
                "finished": False,
                "data_checked": False,
            }
        )
        bootstrap["events"].append(event)
    fixture_template = _synthetic_fixtures(repository_root)[0]
    fixtures = []
    fixture_id = 100
    for gameweek, kickoff_base in (
        (1, KICKOFF - timedelta(days=7)),
        (2, TARGET_KICKOFF),
        (3, TARGET_KICKOFF + timedelta(days=7)),
        (4, TARGET_KICKOFF + timedelta(days=14)),
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
    candidate_ids = tuple(
        int(item["id"])
        for item in players
        if int(item["id"]) not in squad
        and int(item["team"]) == 6
        and int(item["element_type"]) in {1, 2}
    )[:2]
    assert len(candidate_ids) == 2
    for candidate_id in candidate_ids:
        next(item for item in players if int(item["id"]) == candidate_id)["can_select"] = True
    chips = [
        {
            "name": name,
            "number": 1,
            "status_for_entry": "available",
            "played_by_entry": [],
        }
        for name in ("wildcard", "freehit", "bboost", "3xc")
    ]
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
            "limit": 2,
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
        "commenceTimeFrom=2026-09-01T12%3A00%3A00Z&"
        "commenceTimeTo=2026-09-05T16%3A00%3A01Z"
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


@pytest.mark.parametrize(
    "updates",
    (
        {"entry_id": True},
        {"entry_id": 0},
        {"horizon_gameweeks": 2},
        {"run_at": datetime(2026, 9, 1, 12)},
        {"operator_approved_at": datetime(2026, 9, 1, 11, 59)},
    ),
)
def test_one_command_preflight_rejects_invalid_usage_before_acquisition(updates) -> None:
    request_values = {
        "entry_id": 42,
        "code_sha": "a" * 40,
        "run_at": RUN_AT,
        "operator_approved_at": RUN_AT - timedelta(minutes=1),
        **updates,
    }
    service = PrivateV1OneCommandService()

    with pytest.raises(PrivateV1Error) as caught:
        service.run(OneCommandRequest(**request_values))

    assert caught.value.code == "USAGE_INVALID"


def test_one_command_preflight_rejects_approval_after_cutoff() -> None:
    with pytest.raises(PrivateV1Error) as caught:
        PrivateV1OneCommandService().run(
            OneCommandRequest(
                entry_id=42,
                code_sha="a" * 40,
                run_at=RUN_AT,
                operator_approved_at=RUN_AT + timedelta(seconds=1),
            )
        )

    assert caught.value.code == "USAGE_INVALID"


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

    odds_service = _OddsService(odds)
    progress_output: list[str] = []
    service = PrivateV1OneCommandService(
        direct_client_factory=direct_factory,
        odds_service_factory=lambda clock: odds_service,
        score_service_factory=score_factory,
        clock=lambda: RUN_AT,
        progress=HumanCliProgress(write=progress_output.append),
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
    assert result.report.startswith("DMF PULSE - GW2\n\nTRANSFER FRONTIER")
    assert "\n\nRECOMMENDATION\n" in result.report
    assert "No action:" in result.report
    assert "Captain:" in result.report
    assert "FPL_API_OPERATOR_INITIATED_ACCEPTED_CONTRACTUAL_RISK" in result.report
    assert "CURRENT_STAGE7_TEAM_MINUTES_RECONCILED_V1" in result.report
    assert "PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1" in result.report
    assert "Exact tactical optimum within the declared bounded transfer candidate set" in (
        result.decision.action_space_disclosure
    )
    assert "Exact tactical optimum within the declared bounded transfer candidate set" in (
        result.report
    )
    assert "ONE_GAMEWEEK_ZERO_TERMINAL_VALUE_OBJECTIVE" in result.report
    assert "global FPL transfer optimum" not in result.report
    assert odds_service.requests == [(RUN_AT, TARGET_KICKOFF + timedelta(hours=2, seconds=1))]
    assert len(direct_transport.requests) == 8
    assert direct_transport.bodies == []
    rendered_progress = "\n".join(progress_output)
    expected_order = (
        "DMF Pulse starting",
        "Acquiring current FPL state...",
        "FPL state ready",
        "Acquiring current market odds...",
        "Market odds ready",
        "Acquiring current score-prior source...",
        "Score-prior source ready",
        "Resolving current identities...",
        "Current identities ready",
        "Building Stage-7 minutes...",
        "Stage 7 fixture 1/3: predicting home team...",
        "Stage 7 fixture 1/3: home prediction ready",
        "Stage 7 fixture 1/3: predicting away team...",
        "Stage 7 fixture 1/3: away prediction ready",
        "Stage 7 fixture 1/3: reconciling team scenarios...",
        "Stage 7 fixture 1/3 ready",
        "Stage 7 fixture 2/3: predicting home team...",
        "Stage 7 fixture 2/3: home prediction ready",
        "Stage 7 fixture 2/3: predicting away team...",
        "Stage 7 fixture 2/3: away prediction ready",
        "Stage 7 fixture 2/3: reconciling team scenarios...",
        "Stage 7 fixture 2/3 ready",
        "Stage 7 fixture 3/3: predicting home team...",
        "Stage 7 fixture 3/3: home prediction ready",
        "Stage 7 fixture 3/3: predicting away team...",
        "Stage 7 fixture 3/3: away prediction ready",
        "Stage 7 fixture 3/3: reconciling team scenarios...",
        "Stage 7 fixture 3/3 ready",
        "Stage-7 minutes ready",
        "Binding current score priors...",
        "Score priors ready",
        "Sealing execution input...",
        "Execution input ready",
        "Stage 8/9 fixture 1/3...",
        "Stage 8/9 fixture 1/3 complete",
        "Stage 8/9 fixture 2/3...",
        "Stage 8/9 fixture 2/3 complete",
        "Stage 8/9 fixture 3/3...",
        "Stage 8/9 fixture 3/3 complete",
        "Stage 8/9 complete",
        "Assembling joint Gameweek scenarios...",
        "Joint Gameweek scenarios ready",
        "Preparing optimiser...",
        "Optimiser ready",
        "Stage-10 tactical batch starting",
        "Stage-10 tactical batch ready",
        "Stage-11 policy selection...",
        "Stage-11 policy selection complete",
        "Verifying captain / vice-captain...",
        "Captain verification complete",
        "Building paired comparator...",
        "Recommendation ready",
        "Total runtime:",
    )
    offsets = [rendered_progress.index(item) for item in expected_order]
    assert offsets == sorted(offsets)
    assert "candidate players:" in rendered_progress
    assert "free transfers available: 2" in rendered_progress
    assert "transfer counts considered: 0,1,2" in rendered_progress
    assert "full selectable incoming universe:" in rendered_progress
    assert "retained transfer candidates:" in rendered_progress
    assert "retained one-transfer actions:" in rendered_progress
    assert "retained two-transfer actions:" in rendered_progress
    assert "exact tactical squads requiring evaluation:" in rendered_progress
    assert "Stage 10 tactical squads: 1/" in rendered_progress
    assert "Stage-10 tactical batch ready" in rendered_progress
    assert "Stage-11 policy selection..." in rendered_progress
    assert "maximum transfers: 2" in rendered_progress
    assert "root action upper bound:" in rendered_progress
    assert "% complete" not in rendered_progress
    assert marker not in rendered_progress
    assert "one-command-event" not in rendered_progress
    assert "entry 42" not in rendered_progress.casefold()


def test_explicit_three_gameweek_one_command_runs_from_one_current_cutoff(
    repository_root: Path,
) -> None:
    direct_bodies, _ = _provider_sources(repository_root)
    direct_transport = _DirectTransport(direct_bodies)
    odds_service = _OddsService(_odds_input(repository_root))
    score_config, score_bodies = synthetic_snapshot()
    marker = "repository-owned-placeholder"

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
        odds_service_factory=lambda clock: odds_service,
        score_service_factory=score_factory,
        clock=lambda: RUN_AT,
    )
    result = service.run(
        OneCommandRequest(
            entry_id=42,
            code_sha="b" * 40,
            run_at=RUN_AT,
            operator_approved_at=RUN_AT - timedelta(minutes=1),
            scenario_count=8,
            root_seed=43,
            horizon_gameweeks=3,
        )
    )

    assert isinstance(result.decision, PrivateV1RollingDecision)
    assert result.decision.horizon_gameweeks == (2, 3, 4)
    assert result.decision.do_now.actionability == "DO_NOW"
    assert all(
        item.actionability == "PROVISIONAL_REOPTIMISE_AT_DEADLINE"
        for item in result.decision.future_plan
    )
    assert tuple(
        item.fixture_coverage.score_prior_only_fixtures for item in result.decision.future_plan
    ) == (3, 3)
    assert result.report.startswith("DMF PULSE - PRIVATE 3-GW ROLLING DECISION")
    assert "GW2 - DO NOW" in result.report
    assert result.report.count("PROVISIONAL - REOPTIMISE AT THAT DEADLINE") == 2
    assert "FUTURE_PRICE_CHANGES_NOT_MODELLED_IN_PRIVATE_3GW_V1" in result.report
    assert "ONE-GW VERSUS 3-GW" in result.report
    assert {
        "horizon_input_construction",
        "stage7_gameweek_2",
        "stage7_gameweek_3",
        "stage7_gameweek_4",
        "stage8_9_gameweek_2",
        "stage8_9_gameweek_3",
        "stage8_9_gameweek_4",
        "joint_scenario_assembly_gameweek_2",
        "joint_scenario_assembly_gameweek_3",
        "joint_scenario_assembly_gameweek_4",
        "action_generation",
        "tactical_batch_evaluation",
        "stage11_policy_solving",
        "report_and_comparator",
    } <= {item.stage for item in result.stage_timings}
    assert result.fpl_request_count == 8
    assert direct_transport.bodies == []
    assert odds_service.requests == [(RUN_AT, TARGET_KICKOFF + timedelta(hours=2, seconds=1))]
    print(
        json.dumps(
            {
                "schema_version": "private-v1-rolling-synthetic-benchmark-v1",
                "stage_timings_ms": {
                    item.stage: str(item.elapsed_ms) for item in result.stage_timings
                },
                "timed_stage_total_ms": str(sum(item.elapsed_ms for item in result.stage_timings)),
            },
            sort_keys=True,
        )
    )
