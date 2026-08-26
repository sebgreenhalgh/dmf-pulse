"""Synthetic construction helpers for CURRENT-FPL-STATE-001B tests."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplFixture,
    CurrentFplIdentity,
    CurrentFplInputBundle,
    CurrentFplInputRequest,
    CurrentFplInputService,
)
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.current import (
    OddsProviderCurrentInput,
    build_current_odds_input,
    current_odds_market_semantic_sha256,
)
from dmf_pulse.ingestion.odds.identity import (
    FplOddsIdentityMap,
    bind_current_fixture_resolution_request,
    bind_current_team_resolution_request,
    current_fpl_identity_view_sha256,
    current_odds_identity_semantic_sha256,
    resolve_current_fixture_identities,
    resolve_current_team_identities,
)
from dmf_pulse.ingestion.odds.mapping import (
    CurrentFixtureBinding,
    CurrentFixtureMappingPlan,
    CurrentTeamAliasMapping,
    CurrentTeamAliasPlan,
)
from dmf_pulse.ingestion.odds.models import QuotaSource, QuotaState
from dmf_pulse.ingestion.odds.parser import parse_odds_payload

FPL_CAPTURED = datetime(2026, 8, 24, 10, tzinfo=UTC)
FPL_RECEIVED = datetime(2026, 8, 24, 10, 5, tzinfo=UTC)
FPL_USABLE = datetime(2026, 8, 24, 10, 6, tzinfo=UTC)
ODDS_RECEIVED = datetime(2026, 8, 24, 10, 10, tzinfo=UTC)
ODDS_USABLE = datetime(2026, 8, 24, 10, 11, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 26, 12, tzinfo=UTC)
DEADLINE = datetime(2026, 8, 28, 17, 30, tzinfo=UTC)
KICKOFF = datetime(2026, 8, 29, 14, tzinfo=UTC)
TEAM_APPROVED = datetime(2026, 8, 1, 12, tzinfo=UTC)
FIXTURE_APPROVED = datetime(2026, 8, 24, 10, 20, tzinfo=UTC)
DECIDED = datetime(2026, 8, 24, 10, 30, tzinfo=UTC)
TARGET_PROVIDER_EVENT_ID = "synthetic-provider-gw2"
OUTSIDE_PROVIDER_EVENT_ID = "synthetic-provider-later"
SOURCE_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000001501")


def make_identity(
    entity_type: str,
    namespace: str,
    external_id: int,
    *,
    season_code: str = "2026/27",
) -> CurrentFplIdentity:
    material = {
        "entity_type": entity_type,
        "external_id_text": str(external_id),
        "identifier_namespace": namespace,
        "provider_key": "official_fpl",
        "provider_product": "fantasy_premierleague",
        "season_code": season_code,
    }
    return CurrentFplIdentity.model_validate(
        {
            **material,
            "canonical_lookup_sha256": canonical_sha256(material),
        }
    )


def build_fpl_input(
    repository_root: Path,
    tmp_path: Path,
    *,
    cutoff: datetime = CUTOFF,
) -> CurrentFplInputBundle:
    source = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap = json.loads((source / "bootstrap.json").read_text(encoding="utf-8"))
    fixtures = json.loads((source / "fixtures.json").read_text(encoding="utf-8"))
    assert isinstance(bootstrap, dict)
    assert isinstance(fixtures, list)
    gw2 = deepcopy(fixtures[0])
    gw2.update(
        {
            "id": 102,
            "code": 900102,
            "event": 2,
            "kickoff_time": "2026-08-29T14:00:00Z",
            "team_h": 2,
            "team_a": 1,
        }
    )
    fixtures.append(gw2)
    tmp_path.mkdir(parents=True, exist_ok=True)
    bootstrap_path = tmp_path / "bootstrap.json"
    fixtures_path = tmp_path / "fixtures.json"
    bootstrap_path.write_text(json.dumps(bootstrap, sort_keys=True), encoding="utf-8")
    fixtures_path.write_text(json.dumps(fixtures, sort_keys=True), encoding="utf-8")
    request = CurrentFplInputRequest(
        bootstrap_path=bootstrap_path,
        fixtures_path=fixtures_path,
        competition_key="PL",
        season_code="2026/27",
        target_gameweek=2,
        captured_at=FPL_CAPTURED,
        information_cutoff=cutoff,
        rights_profile_id="fpl_official_private_manual_v1",
    )
    times = iter((FPL_RECEIVED, FPL_USABLE))
    return CurrentFplInputService(clock=lambda: next(times)).compile(request)


def _odds_value(repository_root: Path) -> list[dict[str, Any]]:
    value = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, list)
    return value


def _set_participants(event: dict[str, Any], home: str, away: str) -> None:
    old_home = str(event["home_team"])
    old_away = str(event["away_team"])
    event["home_team"] = home
    event["away_team"] = away
    for bookmaker in event["bookmakers"]:
        for market in bookmaker["markets"]:
            if market["key"] != "h2h":
                continue
            for outcome in market["outcomes"]:
                if outcome["name"] == old_home:
                    outcome["name"] = home
                elif outcome["name"] == old_away:
                    outcome["name"] = away


def build_odds_input(
    repository_root: Path,
    *,
    cutoff: datetime = CUTOFF,
    extra_event: bool = False,
    colliding_extra: bool = False,
    price_delta: float = 0.0,
    reverse_events: bool = False,
    reverse_bookmakers: bool = False,
    target_commence_time: datetime = KICKOFF,
    source_snapshot_id: UUID = SOURCE_SNAPSHOT_ID,
) -> OddsProviderCurrentInput:
    value = _odds_value(repository_root)
    event = value[0]
    event["id"] = TARGET_PROVIDER_EVENT_ID
    event["commence_time"] = target_commence_time.isoformat().replace("+00:00", "Z")
    _set_participants(event, "Beta Borough", "Alpha Athletic")
    if reverse_bookmakers:
        event["bookmakers"].reverse()
        for bookmaker in event["bookmakers"]:
            for market in bookmaker["markets"]:
                market["outcomes"].reverse()
    if price_delta:
        for bookmaker in event["bookmakers"]:
            for market in bookmaker["markets"]:
                for outcome in market["outcomes"]:
                    outcome["price"] = float(outcome["price"]) + price_delta
    if extra_event or colliding_extra:
        extra = deepcopy(event)
        extra["id"] = OUTSIDE_PROVIDER_EVENT_ID
        if not colliding_extra:
            extra["commence_time"] = "2026-09-05T14:00:00Z"
            _set_participants(extra, "Alpha Athletic", "Beta Borough")
        value.append(extra)
    if reverse_events:
        value.reverse()
    body = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    cutoff_text = cutoff.isoformat().replace("+00:00", "Z").replace(":", "%3A")
    target = (
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?"
        "regions=uk&markets=h2h%2Ctotals&oddsFormat=decimal&dateFormat=iso&"
        f"commenceTimeFrom={cutoff_text}"
    )
    return build_current_odds_input(
        parse_odds_payload(body),
        profile=load_rights_profiles()["the_odds_api_private_analytics_v1"],
        source_snapshot_id=source_snapshot_id,
        request_started_at=ODDS_RECEIVED - timedelta(seconds=1),
        received_at=ODDS_RECEIVED,
        information_cutoff=cutoff,
        usable_at=ODDS_USABLE,
        quota=QuotaState(
            remaining=498,
            used=2,
            last_cost=2,
            observed_at=ODDS_RECEIVED,
            source=QuotaSource.RESPONSE_HEADERS,
        ),
        request_fingerprint="1" * 64,
        sanitized_target=target,
        attempt_count=1,
        transport_call_count=1,
        transport_id="injected",
        provider_request_id_sha256="2" * 64,
    )


def rehash_odds_input(
    odds_input: OddsProviderCurrentInput,
    *,
    events: tuple[object, ...],
) -> OddsProviderCurrentInput:
    provisional = odds_input.model_copy(
        update={"events": events, "market_semantic_sha256": "0" * 64}
    )
    return provisional.model_copy(
        update={"market_semantic_sha256": current_odds_market_semantic_sha256(provisional)}
    )


def team_mapping(
    provider_text: str,
    team: object,
    *,
    approved_at: datetime = TEAM_APPROVED,
    official_name: str | None = None,
) -> CurrentTeamAliasMapping:
    return CurrentTeamAliasMapping(
        provider_team_text=provider_text,
        official_fpl_team_id=team.provider_team_id,
        canonical_team_identity=team.identity,
        official_fpl_team_name=official_name or team.official_name,
        evidence_class="APPROVED_MANUAL",
        reviewer="Synthetic Test Reviewer",
        approved_at=approved_at,
    )


def team_plan(
    fpl_input: CurrentFplInputBundle,
    *,
    approved_at: datetime = TEAM_APPROVED,
    mappings: tuple[CurrentTeamAliasMapping, ...] | None = None,
) -> CurrentTeamAliasPlan:
    by_id = {team.provider_team_id: team for team in fpl_input.teams}
    return CurrentTeamAliasPlan(
        plan_id="synthetic-current-team-aliases",
        plan_version="1.0.0",
        approved_at=approved_at,
        evidence_class="APPROVED_MANUAL",
        reviewer="Synthetic Test Reviewer",
        team_mappings=mappings
        or (
            team_mapping("Alpha Athletic", by_id[1], approved_at=approved_at),
            team_mapping("Beta Borough", by_id[2], approved_at=approved_at),
        ),
    )


def target_fixture(fpl_input: CurrentFplInputBundle) -> CurrentFplFixture:
    matches = [
        fixture
        for fixture in fpl_input.fixtures
        if fixture.event_identity == fpl_input.target_event.identity
    ]
    assert len(matches) == 1
    return matches[0]


def fixture_binding(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    plan: CurrentTeamAliasPlan,
    *,
    fixture: CurrentFplFixture | None = None,
    provider_event_id: str = TARGET_PROVIDER_EVENT_ID,
    approved_at: datetime = FIXTURE_APPROVED,
    expected_commence_time: datetime | None = None,
) -> CurrentFixtureBinding:
    selected = fixture or target_fixture(fpl_input)
    event = next(item for item in odds_input.events if item.provider_event_id == provider_event_id)
    home = plan.team(event.provider_home_team)
    away = plan.team(event.provider_away_team)
    assert selected.kickoff_at is not None
    return CurrentFixtureBinding(
        provider_event_id=provider_event_id,
        target_gameweek=fpl_input.target_gameweek,
        official_fpl_fixture_id=selected.provider_fixture_id,
        canonical_fixture_identity=selected.identity,
        expected_home_team_id=home.official_fpl_team_id,
        expected_home_team_identity=home.canonical_team_identity,
        expected_away_team_id=away.official_fpl_team_id,
        expected_away_team_identity=away.canonical_team_identity,
        expected_commence_time=expected_commence_time or selected.kickoff_at,
        evidence_class="APPROVED_MANUAL",
        reviewer="Synthetic Test Reviewer",
        approved_at=approved_at,
    )


def fixture_plan(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    plan: CurrentTeamAliasPlan,
    *,
    bindings: tuple[CurrentFixtureBinding, ...] | None = None,
    approved_at: datetime = FIXTURE_APPROVED,
) -> CurrentFixtureMappingPlan:
    return CurrentFixtureMappingPlan(
        plan_id="synthetic-current-fixture-bindings",
        plan_version="1.0.0",
        approved_at=approved_at,
        evidence_class="APPROVED_MANUAL",
        reviewer="Synthetic Test Reviewer",
        target_gameweek=fpl_input.target_gameweek,
        fpl_input_semantic_sha256=fpl_input.semantic_sha256,
        fpl_identity_view_sha256=current_fpl_identity_view_sha256(fpl_input),
        odds_identity_semantic_sha256=current_odds_identity_semantic_sha256(odds_input),
        team_alias_plan_version=plan.plan_version,
        team_alias_plan_sha256=plan.sha256,
        fixture_mappings=bindings or (fixture_binding(fpl_input, odds_input, plan),),
    )


def resolve_team_map(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    plan: CurrentTeamAliasPlan,
    *,
    decided_at: datetime = DECIDED,
):
    request = bind_current_team_resolution_request(
        fpl_input,
        odds_input,
        plan,
        mapping_decided_at=decided_at,
    )
    return resolve_current_team_identities(fpl_input, odds_input, plan, request)


def resolve_bridge(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    plan: CurrentTeamAliasPlan,
    mapping_plan: CurrentFixtureMappingPlan,
    *,
    decided_at: datetime = DECIDED,
) -> FplOddsIdentityMap:
    team_map = resolve_team_map(fpl_input, odds_input, plan, decided_at=decided_at)
    request = bind_current_fixture_resolution_request(
        fpl_input,
        odds_input,
        plan,
        team_map,
        mapping_plan,
        mapping_decided_at=decided_at,
    )
    return resolve_current_fixture_identities(
        fpl_input,
        odds_input,
        plan,
        team_map,
        mapping_plan,
        request,
    )
