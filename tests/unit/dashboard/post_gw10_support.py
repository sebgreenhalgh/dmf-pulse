"""Generated owned 2026/27 provider shapes. No real source records or credentials."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.dashboard.current_sources import GuardedFplTransport
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectHttpResponse,
)
from dmf_pulse.operation.diagnostics import DiagnosticLog
from tests.unit.private_v1.test_one_command import _provider_sources

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)
KICKOFF = NOW.replace(hour=14) + timedelta(days=4)
CANARY = "owned-test-auth-cookie-canary-no-real-credential"


def owned_bodies(repository_root):
    original, _ = _provider_sources(repository_root)
    bodies = [json.loads(body) for body in original]
    bootstrap = bodies[0]
    team_template = deepcopy(bootstrap["teams"][-1])
    player_templates = [deepcopy(row) for row in bootstrap["elements"] if row["team"] == 6]
    for team_id in range(7, 21):
        team = deepcopy(team_template)
        team.update(
            id=team_id,
            code=9000 + team_id,
            name=f"One Command Club {team_id}",
            short_name=f"OC{team_id}",
        )
        bootstrap["teams"].append(team)
        for offset, template in enumerate(player_templates, 1):
            row = deepcopy(template)
            element = 100_000 + team_id * 100 + offset
            row.update(
                id=element,
                code=200_000 + element,
                team=team_id,
                web_name=f"Owned{team_id}P{offset}",
                can_select=False,
            )
            bootstrap["elements"].append(row)
    for player in bootstrap["elements"]:
        player["minutes"] *= 8
        player["starts"] *= 8
        # Documented optional/provider-shaped fields; never a retained real row.
        player["chance_of_playing_next_round"] = None
        player["chance_of_playing_this_round"] = None
        player["news"] = ""
    template = deepcopy(bootstrap["events"][1])
    events = []
    for gw in range(1, 13):
        row = deepcopy(template)
        row.update(
            id=gw,
            name=f"Gameweek {gw}",
            deadline_time=(KICKOFF - timedelta(days=7 * (10 - gw), hours=2)).isoformat(),
            finished=gw <= 8,
            data_checked=gw <= 8,
            is_previous=gw == 8,
            is_current=gw == 9,
            is_next=gw == 10,
        )
        events.append(row)
    bootstrap["events"] = events
    old_fixture = deepcopy(bodies[1][0])
    fixtures = []
    for gw in range(1, 13):
        for pair in range(10):
            row = deepcopy(old_fixture)
            row.update(
                id=gw * 100 + pair + 1,
                code=900_000 + gw * 100 + pair,
                event=gw,
                team_h=pair * 2 + 1,
                team_a=pair * 2 + 2,
                kickoff_time=(
                    KICKOFF - timedelta(days=7 * (10 - gw)) + timedelta(hours=pair)
                ).isoformat(),
                finished=gw <= 8,
                started=gw <= 9,
                finished_provisional=False,
            )
            fixtures.append(row)
    bodies[1] = fixtures
    bodies[2].update(summary_overall_points=480, summary_overall_rank=10)
    history = deepcopy(bodies[3]["current"][0])
    bodies[3]["current"] = [
        {**history, "event": gw, "points": 60 if gw <= 8 else 0, "total_points": min(gw, 8) * 60}
        for gw in range(1, 10)
    ]
    bodies[6]["transfers"]["limit"] = 5
    live = {
        "elements": [
            {
                "id": row["id"],
                "stats": {"minutes": row["minutes"] // 8, "starts": row["starts"] // 8},
            }
            for row in bootstrap["elements"]
        ]
    }
    payloads = {
        "/api/bootstrap-static/": bootstrap,
        "/api/fixtures/": fixtures,
        "/api/entry/42/": bodies[2],
        "/api/entry/42/history/": bodies[3],
        "/api/entry/42/transfers/": bodies[4],
        "/api/entry/42/event/8/picks/": bodies[5],
        "/api/my-team/42/": bodies[6],
        **{f"/api/event/{gw}/live/": deepcopy(live) for gw in range(1, 9)},
    }
    return {
        path: json.dumps(value, separators=(",", ":")).encode() for path, value in payloads.items()
    }


class OwnedGuard:
    def __init__(self, diagnostics, allowed):
        self.diagnostics = diagnostics
        self.allowed = set(allowed)
        self.attempts = []
        self.expired = False

    def preflight_send(self, provider, method, host, path):
        if (provider, method, host, path) not in self.allowed:
            raise AuthorizationError("SOURCE_ROUTE_NOT_AUTHORIZED")

    def before_send(self, provider, method, host, path):
        self.preflight_send(provider, method, host, path)
        identity = (provider, method, host, path)
        if identity in self.attempts:
            raise AuthorizationError("SOURCE_REQUEST_BUDGET_EXHAUSTED")
        self.attempts.append(identity)
        self.diagnostics.admitted(provider, method, host, path)

    def before_transport(self):
        if self.expired:
            raise AuthorizationError("ACQUISITION_CUTOFF_PASSED")

    def transport_started(self):
        self.diagnostics.transport_started()

    def response_completed(self, status):
        self.diagnostics.response_completed(status)

    def transport_failed(self, error):
        self.diagnostics.failed(error)

    def credential_failed(self, code):
        raise AssertionError("owned credentials must remain available")

    def finish_acquisition(self):
        return None


class OwnedFpl:
    def __init__(self, bodies, fault=None):
        self.bodies = bodies
        self.fault = fault
        self.completed = []

    def send(self, request):
        if request.path not in self.bodies:
            raise AssertionError("unexpected owned FPL route")
        if request.path.startswith("/api/my-team/"):
            assert request.headers["X-API-Authorization"] == "Bearer " + CANARY
        if self.fault is not None:
            value = self.fault(request)
            if value is not None:
                return value
        self.completed.append(request.path)
        return DirectHttpResponse(200, "application/json", self.bodies[request.path])


def direct_factory(bodies, log=None, fault=None):
    diagnostics = log or DiagnosticLog()
    transport = OwnedFpl(bodies, fault)
    guard = OwnedGuard(
        diagnostics, {("FPL", "GET", "fantasy.premierleague.com", path) for path in bodies}
    )

    def factory(attestation):
        return DirectFplClient(
            attestation,
            transport=GuardedFplTransport(guard, transport),
            credential_provider=DirectFplCredentialProvider({"DMF_FPL_BEARER_TOKEN": CANARY}),
            maximum_attempts=1,
            sleeper=lambda _: None,
            pace_seconds=0,
            clock=lambda: NOW,
            before_credential=lambda method, host, path: guard.preflight_send(
                "FPL", method, host, path
            ),
        )

    return factory, guard, transport, diagnostics


def odds_body(repository_root):
    template = json.loads((repository_root / "fixtures/odds/ODD-005/happy_path.json").read_bytes())[
        0
    ]
    events = []
    for pair in range(10):
        row = deepcopy(template)
        old_home, old_away = row["home_team"], row["away_team"]
        row.update(
            id=f"owned-recovery-event-{pair}",
            home_team=f"One Command Club {pair * 2 + 1}",
            away_team=f"One Command Club {pair * 2 + 2}",
            commence_time=(KICKOFF + timedelta(hours=pair)).isoformat(),
        )
        for book in row["bookmakers"]:
            book["last_update"] = (NOW - timedelta(minutes=5)).isoformat()
            for market in book["markets"]:
                market["last_update"] = (NOW - timedelta(minutes=5)).isoformat()
                for outcome in market["outcomes"]:
                    if outcome["name"] == old_home:
                        outcome["name"] = row["home_team"]
                    elif outcome["name"] == old_away:
                        outcome["name"] = row["away_team"]
        events.append(row)
    return json.dumps(events, separators=(",", ":")).encode()


def full_owned_service(repository_root, log):
    from dmf_pulse.dashboard.current_sources import GuardedOddsTransport, GuardedScoreTransport
    from dmf_pulse.dashboard.runtime import PipeProgress
    from dmf_pulse.ingestion.odds.client import OddsClient, OddsHttpResponse
    from dmf_pulse.ingestion.odds.config import load_rights_profiles
    from dmf_pulse.ingestion.odds.credentials import EnvironmentOddsCredentialProvider
    from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
    from dmf_pulse.ingestion.odds.transient import CurrentOddsTransientService
    from dmf_pulse.ingestion.openfootball.config import load_rights_profiles as score_rights
    from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorService
    from dmf_pulse.private_v1.one_command import PrivateV1OneCommandService
    from tests.unit.ingestion.openfootball.conftest import FakeTransport, synthetic_snapshot

    bodies = owned_bodies(repository_root)
    factory, guard, fpl, _ = direct_factory(bodies, log)
    score_config, score_bodies = synthetic_snapshot()
    guard.allowed.add(("ODDS", "GET", "api.the-odds-api.com", "/v4/sports/soccer_epl/odds"))
    guard.allowed.update(
        ("OPENFOOTBALL", "GET", "raw.githubusercontent.com", score_config.raw_path(path))
        for path in score_bodies
    )
    raw_odds = odds_body(repository_root)

    class OwnedOdds:
        transport_id = "injected"

        def __init__(self):
            self.calls = 0

        def send(self, request, credential):
            assert credential == CANARY
            self.calls += 1
            assert self.calls == 1
            return OddsHttpResponse(
                200,
                "application/json",
                {"x-requests-remaining": "98", "x-requests-used": "2", "x-requests-last": "2"},
                raw_odds,
            )

    odds_transport = OwnedOdds()
    credentials = EnvironmentOddsCredentialProvider(environment={"THE_ODDS_API_KEY": CANARY})
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]

    def odds(clock):
        def client(rights, **kwargs):
            return OddsClient(
                rights,
                credential_provider=credentials,
                transport_factory=lambda: GuardedOddsTransport(guard, odds_transport),
                clock=clock,
                maximum_attempts=1,
            )

        return CurrentOddsTransientService(
            credential_provider=credentials,
            client_factory=client,
            rights_profile=profile,
            quota=QuotaState(
                remaining=100,
                used=0,
                last_cost=0,
                observed_at=NOW,
                source=QuotaSource.RESPONSE_HEADERS,
            ),
            require_known_quota=True,
            maximum_attempts=1,
            clock=clock,
        )

    score_transport = FakeTransport(score_bodies)

    def score(clock):
        return CurrentScorePriorService(
            provider_config=score_config,
            rights_profiles=score_rights(),
            transport=GuardedScoreTransport(guard, score_transport),
            clock=clock,
            provider_config_identity="a" * 64,
            rights_config_identity="b" * 64,
        )

    messages = []
    service = PrivateV1OneCommandService(
        direct_client_factory=factory,
        odds_service_factory=odds,
        score_service_factory=score,
        _provider_request_guard=guard.before_transport,
        progress=PipeProgress(messages.append, diagnostics=log),
        collect_presentation=True,
        clock=lambda: NOW,
    )
    return service, guard, fpl, odds_transport, score_transport, messages
