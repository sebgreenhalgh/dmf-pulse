"""Provider-shaped offline L1 vertical slice; all four computational stages real."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.odds.client import OddsHttpResponse
from dmf_pulse.ingestion.openfootball import service as league
from dmf_pulse.private_v1 import automatic_inputs, one_command
from dmf_pulse.private_v1 import team_strength_live as live
from dmf_pulse.private_v1.rolling import PrivateV1RollingRecommendationService
from tests.unit.ingestion.openfootball.conftest import FakeTransport, synthetic_snapshot
from tests.unit.private_v1.l1_test_support import deny_writes
from tests.unit.private_v1.team_strength_shadow_support import PAIRS, STAMP
from tests.unit.private_v1.test_one_command import _DirectTransport, _provider_sources
from tests.unit.private_v1.test_team_strength_l1 import offline_run, request, service
from tests.unit.private_v1.test_team_strength_l1 import readiness as readiness

pytestmark = pytest.mark.unit


def sources(root):
    bodies, _ = _provider_sources(root)
    shift = timedelta(days=30)

    def shifted(value):
        if isinstance(value, dict):
            return {key: shifted(item) for key, item in value.items()}
        if isinstance(value, list):
            return [shifted(item) for item in value]
        if isinstance(value, str) and value.startswith("2026-") and value.endswith("Z"):
            return (datetime.fromisoformat(value) + shift).isoformat().replace("+00:00", "Z")
        return value

    payloads = [shifted(json.loads(body)) for body in bodies]
    fixtures = payloads[1]
    # Unique ordered pairs throughout the horizon, as in the accepted P0 registry.
    for index, fixture in enumerate(fixtures[3:]):
        fixture["team_h"], fixture["team_a"] = PAIRS[index // 3][index % 3]
    events = []
    template = json.loads((root / "fixtures/odds/ODD-005/happy_path.json").read_bytes())[0]
    for fixture in fixtures[3:9]:
        event = deepcopy(template)
        home, away = (
            f"One Command Club {fixture['team_h']}",
            f"One Command Club {fixture['team_a']}",
        )
        old_home, old_away = event["home_team"], event["away_team"]
        event.update(
            id=f"synthetic-l1-{fixture['id']}",
            home_team=home,
            away_team=away,
            commence_time=fixture["kickoff_time"],
        )
        for book in event["bookmakers"]:
            book["last_update"] = STAMP.isoformat().replace("+00:00", "Z")
            for market in book["markets"]:
                market["last_update"] = book["last_update"]
                for outcome in market["outcomes"]:
                    if outcome["name"] == old_home:
                        outcome["name"] = home
                    elif outcome["name"] == old_away:
                        outcome["name"] = away
        events.append(event)
    return tuple(json.dumps(payload).encode() for payload in payloads), json.dumps(events).encode()


def test_real_one_preparation_two_canonical_worlds_no_private_writes(
    readiness, repository_root, monkeypatch, tmp_path
):
    direct_bodies, odds_body = sources(repository_root)
    fpl = _DirectTransport(direct_bodies)

    class Odds:
        transport_id = "injected"

        def __init__(self):
            self.calls = 0
            self.requests = []

        def send(self, request, credential):
            self.calls += 1
            self.requests.append(request)
            return OddsHttpResponse(
                200,
                "application/json",
                {"x-requests-remaining": "100", "x-requests-used": "2", "x-requests-last": "2"},
                odds_body,
            )

    odds = Odds()
    config, bodies = synthetic_snapshot()
    public = FakeTransport(bodies)
    # Source doubles only; accepted league aggregation and all maths remain real.
    monkeypatch.setattr(league, "load_provider_config", lambda: config)
    monkeypatch.setattr(league, "provider_config_sha256", lambda: canonical_sha256(config))
    count = {"prepare": 0, "stage7_fit": 0, "worlds": 0}
    original_request = one_command.OneCommandRequest
    original_prepare = one_command.acquire_direct_fpl_snapshot
    original_fit = automatic_inputs.fit_projection_artifact
    original_run = PrivateV1RollingRecommendationService.run
    state = {"after_acquisition": False}
    active = service(fpl_transport=fpl, odds_transport=odds, public_transport=public)
    errors = []
    blocked = active._blocked

    def diagnostic(stage, reason):
        # Generated-data-only test debugging; the production terminal boundary
        # never emits exception details.
        error = sys.exception()
        errors.append(str(error))
        while error is not None and error.__context__ is not None:
            error = error.__context__
            errors.append(str(error))
        return blocked(stage, reason)

    monkeypatch.setattr(active, "_blocked", diagnostic)

    def request_for_synthetic_test(**kwargs):
        value = original_request(**kwargs)
        assert value.scenario_count == 256 and value.root_seed == 20260901
        assert value.run_at.microsecond == 0
        # Two draws keep this generated-data test small. Production has neither
        # an operator knob nor any scenario-count/search-budget substitution.
        return replace(value, scenario_count=2)

    def preparation(*args, **kwargs):
        count["prepare"] += 1
        return original_prepare(*args, **kwargs)

    def fit(*args, **kwargs):
        count["stage7_fit"] += 1
        assert active._gate.closed
        state["after_acquisition"] = True
        return original_fit(*args, **kwargs)

    def run(self, execution, **kwargs):
        count["worlds"] += 1
        assert active._gate.closed
        with pytest.raises(ValueError):
            # Verify audit closure without altering the comparison counters: the
            # dedicated gate tests cover rejection counter increments separately.
            other = service()
            other.guard_network_event()
        assert len(fpl.requests) == 8 and odds.calls == 1 and len(public.requests) == 4
        return original_run(self, execution, **kwargs)

    monkeypatch.setattr(live, "OneCommandRequest", request_for_synthetic_test)
    monkeypatch.setattr(one_command, "acquire_direct_fpl_snapshot", preparation)
    monkeypatch.setattr(automatic_inputs, "fit_projection_artifact", fit)
    monkeypatch.setattr(PrivateV1RollingRecommendationService, "run", run)
    # The final one-command guard must allow deterministic computation after the
    # network cutoff. Acquisition metadata clocks remain genuine within window.
    active._clock = lambda: (
        STAMP + timedelta(hours=1)
        if state["after_acquisition"]
        else STAMP + timedelta(minutes=1, microseconds=123456)
    )
    with deny_writes():
        result = offline_run(active, request(readiness), readiness)
    assert result["status"] == "CURRENT_TEAM_STRENGTH_001P_L2_LIVE_OBSERVATION_COMPLETE", (
        result,
        count,
        errors,
    )
    assert count == {"prepare": 1, "stage7_fit": 1, "worlds": 2}
    assert len(fpl.requests) == 8 and odds.calls == 1 and len(public.requests) == 4
    assert result["provider_counters_before"] == result["provider_counters_after"]
    assert result["provider_requests_during_solves"] == 0
    assert all(result["controls"].values())
    assert result["input"]["horizon"] == [2, 3, 4]
    assert result["input"]["dataset_mode"] == "LIVE_OBSERVED"
    assert result["projection_movement"]["player_gameweek_count"] == 360
    assert len(result["prior_movement_by_gameweek"]) == 3
    assert all(len(world["continuation_transfer_counts"]) == 2 for world in result["worlds"])
    assert not result["persistence"] and not result["production_activation"]
    assert not result["parameter_mixture_active"] and not result["ordinary_path_changed"]
    text = json.dumps(result)
    assert all(
        value not in text
        for value in (
            "entry_id",
            "player_movements",
            "synthetic-test-only",
            "bookmakers",
            "headers",
        )
    )
