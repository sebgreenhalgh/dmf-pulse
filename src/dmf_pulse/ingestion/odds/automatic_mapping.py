"""Deterministic reviewed current FPL/Odds identity-plan assembly."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplInputBundle, CurrentFplTeam
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
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

_REVIEWER = "PRIVATE-V1-ONE-COMMAND-001A deterministic mapping policy"
_REVIEWED_ALIASES = {
    "afc bournemouth": "Bournemouth",
    "brighton and hove albion": "Brighton",
    "leeds united": "Leeds",
    "manchester city": "Man City",
    "manchester united": "Man Utd",
    "newcastle united": "Newcastle",
    "nottingham forest": "Nott'm Forest",
    "tottenham hotspur": "Spurs",
    "west ham united": "West Ham",
    "wolverhampton wanderers": "Wolves",
}


def _normalise(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _resolve_team(provider_text: str, teams: tuple[CurrentFplTeam, ...]) -> CurrentFplTeam:
    direct = tuple(
        team for team in teams if _normalise(team.official_name) == _normalise(provider_text)
    )
    if len(direct) == 1:
        return direct[0]
    reviewed_name = _REVIEWED_ALIASES.get(_normalise(provider_text))
    reviewed = tuple(team for team in teams if team.official_name == reviewed_name)
    if len(direct) > 1 or len(reviewed) != 1:
        raise IngestionError(
            "MAPPING_CONFLICT",
            f"Odds team identity is not deterministically reviewed: {provider_text}",
        )
    return reviewed[0]


def build_automatic_current_mapping_plans(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    *,
    decided_at: datetime,
) -> tuple[CurrentTeamAliasPlan, CurrentFixtureMappingPlan]:
    """Create exact in-memory plans; any name, orientation, or kickoff ambiguity blocks."""

    if decided_at.tzinfo is None or decided_at.utcoffset() is None:
        raise IngestionError("VALIDATION_FAILED", "mapping decision time must be aware")
    decided = decided_at.astimezone(UTC)
    provider_texts = tuple(
        sorted(
            {
                text
                for event in odds_input.events
                for text in (event.provider_home_team, event.provider_away_team)
            }
        )
    )
    aliases = tuple(
        CurrentTeamAliasMapping(
            provider_team_text=text,
            official_fpl_team_id=(team := _resolve_team(text, fpl_input.teams)).provider_team_id,
            canonical_team_identity=team.identity,
            official_fpl_team_name=team.official_name,
            evidence_class="APPROVED_MANUAL",
            reviewer=_REVIEWER,
            approved_at=decided,
        )
        for text in provider_texts
    )
    team_plan = CurrentTeamAliasPlan(
        plan_id=f"one-command-gw{fpl_input.target_gameweek}-teams",
        plan_version="1.0.0",
        approved_at=decided,
        evidence_class="APPROVED_MANUAL",
        reviewer=_REVIEWER,
        team_mappings=aliases,
    )
    team_by_text = {item.provider_team_text: item for item in aliases}
    target_fixtures = tuple(
        item
        for item in fpl_input.fixtures
        if item.event_identity == fpl_input.target_event.identity
    )
    bindings: list[CurrentFixtureBinding] = []
    for event in odds_input.events:
        home = team_by_text[event.provider_home_team]
        away = team_by_text[event.provider_away_team]
        matches = tuple(
            fixture
            for fixture in target_fixtures
            if fixture.home_team_identity == home.canonical_team_identity
            and fixture.away_team_identity == away.canonical_team_identity
            and fixture.kickoff_at == event.commence_time
        )
        if len(matches) != 1:
            raise IngestionError(
                "MAPPING_CONFLICT", "Odds event does not match one exact target FPL fixture"
            )
        fixture = matches[0]
        bindings.append(
            CurrentFixtureBinding(
                provider_event_id=event.provider_event_id,
                target_gameweek=fpl_input.target_gameweek,
                official_fpl_fixture_id=fixture.provider_fixture_id,
                canonical_fixture_identity=fixture.identity,
                expected_home_team_id=home.official_fpl_team_id,
                expected_home_team_identity=home.canonical_team_identity,
                expected_away_team_id=away.official_fpl_team_id,
                expected_away_team_identity=away.canonical_team_identity,
                expected_commence_time=event.commence_time,
                evidence_class="APPROVED_MANUAL",
                reviewer=_REVIEWER,
                approved_at=decided,
            )
        )
    if {item.official_fpl_fixture_id for item in bindings} != {
        item.provider_fixture_id for item in target_fixtures
    }:
        raise IngestionError(
            "MAPPING_CONFLICT", "Odds response does not cover the exact target FPL fixture set"
        )
    fixture_plan = CurrentFixtureMappingPlan(
        plan_id=f"one-command-gw{fpl_input.target_gameweek}-fixtures",
        plan_version="1.0.0",
        approved_at=decided,
        evidence_class="APPROVED_MANUAL",
        reviewer=_REVIEWER,
        target_gameweek=fpl_input.target_gameweek,
        fpl_input_semantic_sha256=fpl_input.semantic_sha256,
        fpl_identity_view_sha256=current_fpl_identity_view_sha256(fpl_input),
        odds_identity_semantic_sha256=current_odds_identity_semantic_sha256(odds_input),
        team_alias_plan_version=team_plan.plan_version,
        team_alias_plan_sha256=team_plan.sha256,
        fixture_mappings=tuple(sorted(bindings, key=lambda item: item.official_fpl_fixture_id)),
    )
    return team_plan, fixture_plan


def build_automatic_current_identity_map(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    *,
    decided_at: datetime,
) -> FplOddsIdentityMap:
    """Build and resolve both exact transient mapping stages in one deterministic call."""

    team_plan, fixture_plan = build_automatic_current_mapping_plans(
        fpl_input, odds_input, decided_at=decided_at
    )
    team_request = bind_current_team_resolution_request(
        fpl_input, odds_input, team_plan, mapping_decided_at=decided_at
    )
    team_map = resolve_current_team_identities(fpl_input, odds_input, team_plan, team_request)
    fixture_request = bind_current_fixture_resolution_request(
        fpl_input,
        odds_input,
        team_plan,
        team_map,
        fixture_plan,
        mapping_decided_at=decided_at,
    )
    return resolve_current_fixture_identities(
        fpl_input,
        odds_input,
        team_plan,
        team_map,
        fixture_plan,
        fixture_request,
    )


__all__ = [
    "build_automatic_current_identity_map",
    "build_automatic_current_mapping_plans",
]
