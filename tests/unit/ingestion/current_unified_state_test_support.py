"""Synthetic-only coherent source families for CURRENT-FPL-STATE-001D tests."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.ingestion.current_state import (
    CurrentUnifiedStateBundle,
    CurrentUnifiedStateRequest,
    CurrentUnifiedStateService,
    bind_current_unified_state_request,
    current_unified_state_semantic_sha256,
)
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplInputBundle,
    CurrentFplInputRequest,
    CurrentFplInputService,
)
from dmf_pulse.ingestion.fpl.manager_current import CurrentManagerStateBundle
from dmf_pulse.ingestion.odds.current import (
    CurrentOddsTotalsMarket,
    CurrentOddsTotalsOutcome,
    OddsProviderCurrentInput,
    current_odds_market_semantic_sha256,
)
from dmf_pulse.ingestion.odds.identity import FplOddsIdentityMap
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset

from .current_identity_test_support import (
    DECIDED,
    TARGET_PROVIDER_EVENT_ID,
    build_odds_input,
    fixture_binding,
    fixture_plan,
    resolve_bridge,
    team_mapping,
    team_plan,
)
from .current_manager_test_support import (
    CUTOFF,
    FPL_CAPTURED,
    FPL_RECEIVED,
    FPL_USABLE,
    CurrentManagerTestContext,
    compile_manager,
)
from .current_manager_test_support import build_context as build_manager_context

SECOND_TARGET_PROVIDER_EVENT_ID = "synthetic-provider-gw2-second"


@dataclass(frozen=True)
class CurrentUnifiedTestContext:
    fpl_input: CurrentFplInputBundle
    odds_input: OddsProviderCurrentInput
    identity_map: FplOddsIdentityMap
    manager_state: CurrentManagerStateBundle
    ruleset: CompiledRuleset
    capability: CapabilityArtifact
    request: CurrentUnifiedStateRequest
    bundle: CurrentUnifiedStateBundle


def build_context(repository_root: Path, tmp_path: Path) -> CurrentUnifiedTestContext:
    manager_context = build_manager_context(repository_root, tmp_path / "manager-family")
    fpl_input = manager_context.fpl_input
    odds_input = _with_synthetic_totals(build_odds_input(repository_root, extra_event=True))
    aliases = team_plan(fpl_input)
    fixtures = fixture_plan(fpl_input, odds_input, aliases)
    identity_map = resolve_bridge(fpl_input, odds_input, aliases, fixtures)
    manager_state = compile_manager(manager_context)
    request = bind_current_unified_state_request(
        fpl_input,
        odds_input,
        identity_map,
        manager_state,
        manager_context.ruleset,
        manager_context.capability,
    )
    bundle = CurrentUnifiedStateService().compose(
        request,
        fpl_input=fpl_input,
        odds_input=odds_input,
        identity_map=identity_map,
        manager_state=manager_state,
        ruleset=manager_context.ruleset,
        capability=manager_context.capability,
    )
    return CurrentUnifiedTestContext(
        fpl_input=fpl_input,
        odds_input=odds_input,
        identity_map=identity_map,
        manager_state=manager_state,
        ruleset=manager_context.ruleset,
        capability=manager_context.capability,
        request=request,
        bundle=bundle,
    )


def build_two_fixture_context(repository_root: Path, tmp_path: Path) -> CurrentUnifiedTestContext:
    base_manager = build_manager_context(repository_root, tmp_path / "two-fixture-family")
    fixtures_path = base_manager.working / "synthetic-fixtures.json"
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    assert isinstance(fixtures, list)
    second_fixture = deepcopy(fixtures[-1])
    second_fixture.update(
        {
            "id": 103,
            "code": 900103,
            "event": 2,
            "kickoff_time": "2026-08-29T16:00:00Z",
            "team_h": 3,
            "team_a": 4,
        }
    )
    fixtures.append(second_fixture)
    fixtures_path.write_text(json.dumps(fixtures, sort_keys=True), encoding="utf-8")
    times = iter((FPL_RECEIVED, FPL_USABLE))
    fpl_input = CurrentFplInputService(clock=lambda: next(times)).compile(
        CurrentFplInputRequest(
            bootstrap_path=base_manager.working / "synthetic-bootstrap.json",
            fixtures_path=fixtures_path,
            competition_key="PL",
            season_code="2026/27",
            target_gameweek=2,
            captured_at=FPL_CAPTURED,
            information_cutoff=CUTOFF,
            rights_profile_id="fpl_official_private_manual_v1",
        )
    )
    manager_context = CurrentManagerTestContext(
        repository_root=repository_root,
        working=base_manager.working,
        fpl_input=fpl_input,
        ruleset=base_manager.ruleset,
        capability=base_manager.capability,
        declaration=base_manager.declaration,
    )
    odds_input = _with_second_target_event(
        _with_synthetic_totals(build_odds_input(repository_root, extra_event=True))
    )
    teams = {team.provider_team_id: team for team in fpl_input.teams}
    aliases = team_plan(
        fpl_input,
        mappings=(
            team_mapping("Alpha Athletic", teams[1]),
            team_mapping("Beta Borough", teams[2]),
            team_mapping("Gamma City", teams[3]),
            team_mapping("Delta United", teams[4]),
        ),
    )
    target_fixtures = tuple(
        sorted(
            (
                fixture
                for fixture in fpl_input.fixtures
                if fixture.event_identity == fpl_input.target_event.identity
            ),
            key=lambda fixture: fixture.provider_fixture_id,
        )
    )
    mapping_plan = fixture_plan(
        fpl_input,
        odds_input,
        aliases,
        bindings=(
            fixture_binding(
                fpl_input,
                odds_input,
                aliases,
                fixture=target_fixtures[0],
                provider_event_id=TARGET_PROVIDER_EVENT_ID,
            ),
            fixture_binding(
                fpl_input,
                odds_input,
                aliases,
                fixture=target_fixtures[1],
                provider_event_id=SECOND_TARGET_PROVIDER_EVENT_ID,
            ),
        ),
    )
    identity_map = resolve_bridge(fpl_input, odds_input, aliases, mapping_plan, decided_at=DECIDED)
    manager_state = compile_manager(manager_context, name="two-fixture-manager.json")
    request = bind_current_unified_state_request(
        fpl_input,
        odds_input,
        identity_map,
        manager_state,
        manager_context.ruleset,
        manager_context.capability,
    )
    bundle = CurrentUnifiedStateService().compose(
        request,
        fpl_input=fpl_input,
        odds_input=odds_input,
        identity_map=identity_map,
        manager_state=manager_state,
        ruleset=manager_context.ruleset,
        capability=manager_context.capability,
    )
    return CurrentUnifiedTestContext(
        fpl_input=fpl_input,
        odds_input=odds_input,
        identity_map=identity_map,
        manager_state=manager_state,
        ruleset=manager_context.ruleset,
        capability=manager_context.capability,
        request=request,
        bundle=bundle,
    )


def _with_synthetic_totals(value: OddsProviderCurrentInput) -> OddsProviderCurrentInput:
    event = value.events[0]
    bookmaker = event.bookmakers[0]
    line = Decimal("2.5")
    totals = CurrentOddsTotalsMarket(
        line=line,
        provider_last_update=bookmaker.provider_last_update,
        provider_last_update_state="PUBLISHED",
        outcomes=(
            CurrentOddsTotalsOutcome(
                provider_name="Over 2.5",
                outcome="OVER",
                decimal_price=Decimal("1.91"),
                point=line,
            ),
            CurrentOddsTotalsOutcome(
                provider_name="Under 2.5",
                outcome="UNDER",
                decimal_price=Decimal("1.95"),
                point=line,
            ),
        ),
    )
    changed_bookmaker = bookmaker.model_copy(update={"totals_markets": (totals,)})
    changed_event = event.model_copy(
        update={"bookmakers": (changed_bookmaker, *event.bookmakers[1:])}
    )
    provisional = value.model_copy(update={"events": (changed_event, *value.events[1:])})
    return provisional.model_copy(
        update={"market_semantic_sha256": current_odds_market_semantic_sha256(provisional)}
    )


def _with_second_target_event(value: OddsProviderCurrentInput) -> OddsProviderCurrentInput:
    target = value.events[0]
    bookmakers = []
    for bookmaker in target.bookmakers:
        markets = []
        for market in bookmaker.markets:
            outcomes = tuple(
                outcome.model_copy(
                    update={
                        "provider_name": (
                            "Gamma City"
                            if outcome.outcome == "HOME"
                            else "Delta United"
                            if outcome.outcome == "AWAY"
                            else outcome.provider_name
                        )
                    }
                )
                for outcome in market.outcomes
            )
            markets.append(market.model_copy(update={"outcomes": outcomes}))
        bookmakers.append(bookmaker.model_copy(update={"markets": tuple(markets)}))
    second = target.model_copy(
        update={
            "provider_event_id": SECOND_TARGET_PROVIDER_EVENT_ID,
            "commence_time": datetime.fromisoformat("2026-08-29T16:00:00+00:00"),
            "provider_home_team": "Gamma City",
            "provider_away_team": "Delta United",
            "bookmakers": tuple(bookmakers),
        }
    )
    provisional = value.model_copy(update={"events": (target, second, *value.events[1:])})
    return provisional.model_copy(
        update={"market_semantic_sha256": current_odds_market_semantic_sha256(provisional)}
    )


def verify(context: CurrentUnifiedTestContext, **updates: object) -> CurrentUnifiedStateBundle:
    values: dict[str, object] = {
        "value": context.bundle,
        "request": context.request,
        "fpl_input": context.fpl_input,
        "odds_input": context.odds_input,
        "identity_map": context.identity_map,
        "manager_state": context.manager_state,
        "ruleset": context.ruleset,
        "capability": context.capability,
    }
    values.update(updates)
    return CurrentUnifiedStateService().verify(  # type: ignore[arg-type]
        values.pop("value"), values.pop("request"), **values
    )


def rehash_bundle(
    bundle: CurrentUnifiedStateBundle, **updates: object
) -> CurrentUnifiedStateBundle:
    provisional = bundle.model_copy(update=updates)
    return provisional.model_copy(
        update={"semantic_sha256": current_unified_state_semantic_sha256(provisional)}
    )


def mutate_non_view_fpl(value: CurrentFplInputBundle, mutation: str) -> CurrentFplInputBundle:
    """Return a structurally valid 001A object changed outside 001B/001C reduced views."""

    player = value.players[0]
    if mutation == "player_status":
        changed_player = player.model_copy(update={"status": "u" if player.status != "u" else "a"})
    elif mutation == "chance_this_round":
        chance = 50 if player.chance_of_playing_this_round != 50 else 51
        changed_player = player.model_copy(update={"chance_of_playing_this_round": chance})
    elif mutation == "chance_next_round":
        chance = 25 if player.chance_of_playing_next_round != 25 else 26
        changed_player = player.model_copy(update={"chance_of_playing_next_round": chance})
    elif mutation == "player_news":
        news = (
            "synthetic review mutation"
            if player.news != "synthetic review mutation"
            else "alternate synthetic review mutation"
        )
        changed_player = player.model_copy(update={"news": news})
    elif mutation == "player_news_added":
        changed_time = value.provenance.information_cutoff - timedelta(hours=1)
        if player.news_added == changed_time:
            changed_time -= timedelta(minutes=1)
        changed_player = player.model_copy(update={"news_added": changed_time})
    else:
        changed_player = None
    if changed_player is not None:
        return value.model_copy(update={"players": (changed_player, *value.players[1:])})

    if mutation == "game_settings":
        settings = json.loads(value.game_settings.canonical_json)
        settings["synthetic_review_mutation"] = not bool(settings.get("synthetic_review_mutation"))
        changed_settings = value.game_settings.model_copy(
            update={
                "canonical_json": canonical_json_bytes(settings).decode("utf-8"),
                "semantic_sha256": canonical_sha256(settings),
            }
        )
        return value.model_copy(update={"game_settings": changed_settings})

    if mutation.startswith("non_target_event_"):
        index, event = next(
            (index, event)
            for index, event in enumerate(value.events)
            if event.provider_event_id != value.target_gameweek
        )
        if mutation == "non_target_event_finished":
            updates = {"finished": not bool(event.finished)}
        elif mutation == "non_target_event_data_checked":
            updates = {"data_checked": not bool(event.data_checked)}
        else:
            updates = {
                "is_previous": not bool(event.is_previous),
                "is_current": False,
                "is_next": False,
            }
        changed_event = event.model_copy(update=updates)
        events = tuple(
            changed_event if item == index else child for item, child in enumerate(value.events)
        )
        return value.model_copy(update={"events": events})

    fixture = value.fixtures[0]
    fixture_field = {
        "fixture_finished": "finished",
        "fixture_started": "started",
        "fixture_finished_provisional": "finished_provisional",
    }[mutation]
    changed_fixture = fixture.model_copy(
        update={fixture_field: not bool(getattr(fixture, fixture_field))}
    )
    return value.model_copy(update={"fixtures": (changed_fixture, *value.fixtures[1:])})


__all__ = [
    "CurrentUnifiedTestContext",
    "build_context",
    "build_two_fixture_context",
    "mutate_non_view_fpl",
    "rehash_bundle",
    "verify",
]
