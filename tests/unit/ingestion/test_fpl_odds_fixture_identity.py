"""Checkpoint-1.4B/C exact current FPL/Odds fixture identity acceptance."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplFixture,
    CurrentFplIdentity,
    CurrentFplInputBundle,
    CurrentFplInputRequest,
    CurrentFplInputService,
)
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from dmf_pulse.ingestion.odds.current import (
    CurrentOddsEvent,
    OddsProviderCurrentInput,
    build_current_odds_input,
)
from dmf_pulse.ingestion.odds.identity import (
    CurrentFixtureCoverage,
    FplOddsIdentityMap,
    ResolvedCurrentFixture,
    _fpl_odds_identity_map_sha256,
    bind_current_fixture_resolution_request,
    bind_current_team_resolution_request,
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

pytestmark = pytest.mark.unit

CAPTURED = datetime(2026, 8, 18, 12, tzinfo=UTC)
FPL_RECEIVED = datetime(2026, 8, 18, 12, 5, tzinfo=UTC)
ODDS_RECEIVED = datetime(2026, 8, 20, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
DECIDED = datetime(2026, 8, 20, 12, 1, tzinfo=UTC)
APPROVED = datetime(2026, 8, 18, 13, tzinfo=UTC)
SOURCE_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000001402")
SANITIZED_TARGET = (
    "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?"
    "regions=uk&markets=h2h%2Ctotals&oddsFormat=decimal&dateFormat=iso&commenceTimeFrom="
    "2026-08-21T17%3A30%3A00Z"
)


def _write_fpl_pair(repository_root: Path, tmp_path: Path) -> tuple[Path, Path]:
    source = repository_root / "fixtures/fpl/FPL-004/happy_path"
    bootstrap_path = tmp_path / "bootstrap.json"
    fixtures_path = tmp_path / "fixtures.json"
    bootstrap_path.write_bytes((source / "bootstrap.json").read_bytes())
    fixtures_path.write_bytes((source / "fixtures.json").read_bytes())
    return bootstrap_path, fixtures_path


def _fpl_input(repository_root: Path, tmp_path: Path) -> CurrentFplInputBundle:
    bootstrap_path, fixtures_path = _write_fpl_pair(repository_root, tmp_path)
    request = CurrentFplInputRequest(
        bootstrap_path=bootstrap_path,
        fixtures_path=fixtures_path,
        competition_key="PL",
        season_code="2026/27",
        captured_at=CAPTURED,
        information_cutoff=CUTOFF,
        rights_profile_id="fpl_official_private_manual_v1",
        gameweek=1,
    )
    return CurrentFplInputService(clock=lambda: FPL_RECEIVED).compile(request)


def _odds_value(repository_root: Path) -> list[dict[str, Any]]:
    value = json.loads(
        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, list)
    return value


def _odds_input(
    repository_root: Path,
    value: object | None = None,
) -> OddsProviderCurrentInput:
    body = json.dumps(
        _odds_value(repository_root) if value is None else value,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()
    parsed = parse_odds_payload(body)
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    return build_current_odds_input(
        parsed,
        profile=profile,
        source_snapshot_id=SOURCE_SNAPSHOT_ID,
        request_started_at=ODDS_RECEIVED - timedelta(seconds=1),
        received_at=ODDS_RECEIVED,
        information_cutoff=CUTOFF,
        usable_at=ODDS_RECEIVED + timedelta(seconds=1),
        quota=QuotaState(
            remaining=499,
            used=2,
            last_cost=2,
            observed_at=ODDS_RECEIVED,
            source=QuotaSource.RESPONSE_HEADERS,
        ),
        request_fingerprint="3" * 64,
        sanitized_target=SANITIZED_TARGET,
        attempt_count=1,
        transport_call_count=1,
        provider_request_id_sha256="4" * 64,
    )


def _identity(
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
    return CurrentFplIdentity(
        season_code=season_code,
        entity_type=entity_type,
        identifier_namespace=namespace,
        external_id_text=str(external_id),
        canonical_lookup_sha256=canonical_sha256(material),
    )


def _clone_fixture(
    base: CurrentFplFixture,
    *,
    fixture_id: int,
    kickoff_at: datetime | None = None,
    event_identity: CurrentFplIdentity | None = None,
) -> CurrentFplFixture:
    return base.model_copy(
        update={
            "identity": _identity("FIXTURE", "fpl.fixture.id", fixture_id),
            "provider_fixture_id": fixture_id,
            "provider_code": fixture_id,
            "event_identity": event_identity or base.event_identity,
            "kickoff_at": kickoff_at if kickoff_at is not None else base.kickoff_at,
        }
    )


def _clone_event(
    base: CurrentOddsEvent,
    *,
    provider_event_id: str | None = None,
    commence_time: datetime | None = None,
    home: str | None = None,
    away: str | None = None,
) -> CurrentOddsEvent:
    return base.model_copy(
        update={
            "provider_event_id": provider_event_id or base.provider_event_id,
            "commence_time": commence_time or base.commence_time,
            "provider_home_team": home or base.provider_home_team,
            "provider_away_team": away or base.provider_away_team,
        }
    )


def _team_mapping(provider_text: str, team: object) -> CurrentTeamAliasMapping:
    return CurrentTeamAliasMapping(
        provider_team_text=provider_text,
        official_fpl_team_id=team.provider_team_id,
        canonical_team_identity=team.identity,
        official_fpl_team_name=team.official_name,
        evidence_class="APPROVED_MANUAL",
        reviewer="Sebastian Greenhalgh",
        approved_at=APPROVED,
    )


def _team_plan(fpl_input: CurrentFplInputBundle) -> CurrentTeamAliasPlan:
    return CurrentTeamAliasPlan(
        plan_id="gw1-2026-27-current-team-aliases",
        plan_version="1.0.0",
        approved_at=APPROVED,
        evidence_class="APPROVED_MANUAL",
        reviewer="Sebastian Greenhalgh",
        team_mappings=(
            _team_mapping("Alpha Athletic", fpl_input.teams[0]),
            _team_mapping("Beta Borough", fpl_input.teams[1]),
        ),
    )


def _team_map(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    team_plan: CurrentTeamAliasPlan,
):
    request = bind_current_team_resolution_request(
        fpl_input,
        odds_input,
        team_plan,
        mapping_decided_at=DECIDED,
    )
    return resolve_current_team_identities(fpl_input, odds_input, team_plan, request)


def _fixture_binding(
    fpl_input: CurrentFplInputBundle,
    odds_event: CurrentOddsEvent,
    *,
    fixture: CurrentFplFixture | None = None,
    provider_event_id: str | None = None,
    approved_at: datetime = APPROVED,
    expected_commence_time: datetime | None = None,
    official_fixture_id: int | None = None,
    official_fixture_identity: CurrentFplIdentity | None = None,
) -> CurrentFixtureBinding:
    selected = fixture or fpl_input.fixtures[0]
    kickoff = expected_commence_time or selected.kickoff_at
    assert kickoff is not None
    return CurrentFixtureBinding(
        provider_event_id=provider_event_id or odds_event.provider_event_id,
        target_gameweek=fpl_input.target_gameweek,
        official_fpl_fixture_id=official_fixture_id or selected.provider_fixture_id,
        canonical_fixture_identity=official_fixture_identity or selected.identity,
        expected_home_team_id=fpl_input.teams[0].provider_team_id,
        expected_home_team_identity=fpl_input.teams[0].identity,
        expected_away_team_id=fpl_input.teams[1].provider_team_id,
        expected_away_team_identity=fpl_input.teams[1].identity,
        expected_commence_time=kickoff,
        evidence_class="APPROVED_MANUAL",
        reviewer="Sebastian Greenhalgh",
        approved_at=approved_at,
    )


def _fixture_plan(
    team_plan: CurrentTeamAliasPlan,
    bindings: tuple[CurrentFixtureBinding, ...],
    *,
    approved_at: datetime = APPROVED,
    target_gameweek: int = 1,
) -> CurrentFixtureMappingPlan:
    return CurrentFixtureMappingPlan(
        plan_id="gw1-2026-27-current-fixtures",
        plan_version="1.0.0",
        approved_at=approved_at,
        evidence_class="APPROVED_MANUAL",
        reviewer="Sebastian Greenhalgh",
        target_gameweek=target_gameweek,
        team_alias_plan_version=team_plan.plan_version,
        team_alias_plan_sha256=team_plan.sha256,
        fixture_mappings=bindings,
    )


def _resolve(
    fpl_input: CurrentFplInputBundle,
    odds_input: OddsProviderCurrentInput,
    team_plan: CurrentTeamAliasPlan,
    fixture_plan: CurrentFixtureMappingPlan,
) -> FplOddsIdentityMap:
    team_map = _team_map(fpl_input, odds_input, team_plan)
    request = bind_current_fixture_resolution_request(
        fpl_input,
        odds_input,
        team_plan,
        team_map,
        fixture_plan,
        mapping_decided_at=DECIDED,
    )
    return resolve_current_fixture_identities(
        fpl_input,
        odds_input,
        team_plan,
        team_map,
        fixture_plan,
        request,
    )


def _default_context(
    repository_root: Path,
    tmp_path: Path,
):
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    team_plan = _team_plan(fpl_input)
    binding = _fixture_binding(fpl_input, odds_input.events[0])
    fixture_plan = _fixture_plan(team_plan, (binding,))
    return fpl_input, odds_input, team_plan, fixture_plan


def _with_rehashed_fixture_mapping(
    result: FplOddsIdentityMap,
    fixture: ResolvedCurrentFixture,
) -> FplOddsIdentityMap:
    return _rehash_identity_map(result, fixture_mappings=(fixture,))


def _rehash_identity_map(
    result: FplOddsIdentityMap,
    **updates: object,
) -> FplOddsIdentityMap:
    tampered = result.model_copy(update=updates)
    return tampered.model_copy(update={"semantic_sha256": _fpl_odds_identity_map_sha256(tampered)})


def test_complete_exact_fixture_mapping_is_usable_transient_and_distinct(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)

    result = _resolve(fpl_input, odds_input, team_plan, fixture_plan)
    mapped = result.fixture("todapi-event-001")

    assert result.contract == "FPL_ODDS_IDENTITY_MAP"
    assert result.quality_status == "USABLE"
    assert result.coverage.status == "COMPLETE"
    assert result.coverage.provider_event_count == 1
    assert result.coverage.target_fpl_fixture_count == 1
    assert result.coverage.mapped_event_count == 1
    assert result.coverage.unmapped_provider_event_ids == ()
    assert result.coverage.unmapped_official_fpl_fixture_ids == ()
    assert result.coverage.ambiguous_provider_event_ids == ()
    assert result.coverage.duplicate_provider_event_ids == ()
    assert result.coverage.duplicate_official_fpl_fixture_ids == ()
    assert mapped.provider_event_id == "todapi-event-001"
    assert mapped.official_fpl_fixture_id == 101
    assert isinstance(mapped.provider_event_id, str)
    assert isinstance(mapped.official_fpl_fixture_id, int)
    assert mapped.provider_commence_time == mapped.official_fpl_kickoff_at
    assert mapped.official_home_team_id == 1
    assert mapped.official_away_team_id == 2
    assert result.kickoff_policy == "EXACT_UTC_EQUALITY"
    assert result.storage_mode == "TRANSIENT_IN_MEMORY"
    assert result.persistence_performed is False
    assert result.database_accessed is False
    assert result.fpl_derived_storage == "DENY"
    assert result.odds_raw_payload_retained is False
    assert len(result.semantic_sha256) == 64
    assert len(result.source_lineage_sha256) == 64


def test_mapping_is_order_independent_and_deterministic(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    first_fixture = fpl_input.fixtures[0]
    first_event = odds_input.events[0]
    assert first_fixture.kickoff_at is not None
    second_kickoff = first_fixture.kickoff_at + timedelta(hours=2)
    second_fixture = _clone_fixture(
        first_fixture,
        fixture_id=102,
        kickoff_at=second_kickoff,
    )
    second_event = _clone_event(
        first_event,
        provider_event_id="todapi-event-002",
        commence_time=second_kickoff,
    )
    expanded_fpl = fpl_input.model_copy(update={"fixtures": (first_fixture, second_fixture)})
    expanded_odds = odds_input.model_copy(update={"events": (first_event, second_event)})
    team_plan = _team_plan(expanded_fpl)
    first_binding = _fixture_binding(expanded_fpl, first_event, fixture=first_fixture)
    second_binding = _fixture_binding(expanded_fpl, second_event, fixture=second_fixture)
    first_plan = _fixture_plan(team_plan, (first_binding, second_binding))
    second_plan = _fixture_plan(team_plan, (second_binding, first_binding))

    first = _resolve(expanded_fpl, expanded_odds, team_plan, first_plan)
    reordered_fpl = expanded_fpl.model_copy(
        update={"fixtures": tuple(reversed(expanded_fpl.fixtures))}
    )
    reordered_odds = expanded_odds.model_copy(
        update={"events": tuple(reversed(expanded_odds.events))}
    )
    second = _resolve(reordered_fpl, reordered_odds, team_plan, second_plan)

    assert first_plan.sha256 == second_plan.sha256
    assert first.semantic_sha256 == second.semantic_sha256
    assert first.fixture_mappings == second.fixture_mappings
    assert [item.provider_event_id for item in first.fixture_mappings] == [
        "todapi-event-001",
        "todapi-event-002",
    ]


def test_bookmaker_outcome_order_and_prices_do_not_change_mapping_semantics(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    original = _odds_value(repository_root)
    altered = _odds_value(repository_root)
    altered[0]["bookmakers"].reverse()
    for bookmaker in altered[0]["bookmakers"]:
        for market in bookmaker["markets"]:
            market["outcomes"].reverse()
    altered[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] += 0.125
    first_odds = _odds_input(repository_root, original)
    second_odds = _odds_input(repository_root, altered)
    team_plan = _team_plan(fpl_input)
    first_plan = _fixture_plan(
        team_plan,
        (_fixture_binding(fpl_input, first_odds.events[0]),),
    )
    second_plan = _fixture_plan(
        team_plan,
        (_fixture_binding(fpl_input, second_odds.events[0]),),
    )

    first = _resolve(fpl_input, first_odds, team_plan, first_plan)
    second = _resolve(fpl_input, second_odds, team_plan, second_plan)

    assert current_odds_identity_semantic_sha256(
        first_odds
    ) == current_odds_identity_semantic_sha256(second_odds)
    assert first.odds_provider_provenance_sha256 != second.odds_provider_provenance_sha256
    assert first.source_lineage_sha256 != second.source_lineage_sha256
    assert first.semantic_sha256 == second.semantic_sha256
    assert first.fixture_mappings == second.fixture_mappings


def test_unknown_provider_event_requires_explicit_binding(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    team_plan = _team_plan(fpl_input)
    wrong_binding = _fixture_binding(
        fpl_input,
        odds_input.events[0],
        provider_event_id="unrelated-provider-event",
    )
    fixture_plan = _fixture_plan(team_plan, (wrong_binding,))

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, odds_input, team_plan, fixture_plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["mapping_outcome"] == "UNKNOWN"
    assert raised.value.details["reason"] == "EXPLICIT_EVENT_BINDING_MISSING"


def test_duplicate_provider_event_is_ambiguous(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    duplicated_odds = odds_input.model_copy(
        update={"events": (odds_input.events[0], odds_input.events[0])}
    )

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, duplicated_odds, team_plan, fixture_plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["mapping_outcome"] == "AMBIGUOUS"
    assert raised.value.details["reason"] == "DUPLICATE_PROVIDER_EVENT_IDENTITY"


def test_duplicate_official_fpl_fixture_is_ambiguous(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    duplicated_fpl = fpl_input.model_copy(
        update={"fixtures": (fpl_input.fixtures[0], fpl_input.fixtures[0])}
    )

    with pytest.raises(IngestionError) as raised:
        _resolve(duplicated_fpl, odds_input, team_plan, fixture_plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["mapping_outcome"] == "AMBIGUOUS"
    assert raised.value.details["reason"] == "DUPLICATE_OFFICIAL_FIXTURE_IDENTITY"


def test_reversed_home_away_does_not_map(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    event = odds_input.events[0]
    reversed_event = _clone_event(
        event,
        home=event.provider_away_team,
        away=event.provider_home_team,
    )
    reversed_odds = odds_input.model_copy(update={"events": (reversed_event,)})

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, reversed_odds, team_plan, fixture_plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["mapping_outcome"] == "UNKNOWN"
    assert raised.value.details["reason"] == "HOME_AWAY_ORIENTATION_MISMATCH"


def test_exact_kickoff_mismatch_does_not_map(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    event = odds_input.events[0]
    shifted = _clone_event(event, commence_time=event.commence_time + timedelta(seconds=1))
    shifted_odds = odds_input.model_copy(update={"events": (shifted,)})

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, shifted_odds, team_plan, fixture_plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["mapping_outcome"] == "UNKNOWN"
    assert raised.value.details["reason"] == "EXACT_KICKOFF_MISMATCH"


def test_two_exact_fpl_candidates_are_ambiguous(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    duplicate_candidate = _clone_fixture(fpl_input.fixtures[0], fixture_id=102)
    expanded_fpl = fpl_input.model_copy(
        update={"fixtures": (fpl_input.fixtures[0], duplicate_candidate)}
    )

    with pytest.raises(IngestionError) as raised:
        _resolve(expanded_fpl, odds_input, team_plan, fixture_plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["mapping_outcome"] == "AMBIGUOUS"
    assert raised.value.details["reason"] == "MULTIPLE_EXACT_CANDIDATES"


def test_two_provider_events_cannot_bind_one_fpl_fixture(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    team_plan = _team_plan(fpl_input)
    first = _fixture_binding(fpl_input, odds_input.events[0])
    second = _fixture_binding(
        fpl_input,
        odds_input.events[0],
        provider_event_id="todapi-event-002",
    )

    with pytest.raises(ValidationError, match="duplicated or ambiguous"):
        _fixture_plan(team_plan, (first, second))


def test_one_provider_event_cannot_bind_two_fpl_fixtures(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    team_plan = _team_plan(fpl_input)
    base = fpl_input.fixtures[0]
    assert base.kickoff_at is not None
    second_fixture = _clone_fixture(
        base,
        fixture_id=102,
        kickoff_at=base.kickoff_at + timedelta(hours=2),
    )
    first = _fixture_binding(fpl_input, odds_input.events[0], fixture=base)
    second = _fixture_binding(
        fpl_input,
        odds_input.events[0],
        fixture=second_fixture,
    )

    with pytest.raises(ValidationError, match="duplicated or ambiguous"):
        _fixture_plan(team_plan, (first, second))


def test_explicit_binding_home_away_orientation_mismatch_fails_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    team_plan = _team_plan(fpl_input)
    base = _fixture_binding(fpl_input, odds_input.events[0])
    values = base.model_dump(mode="python")
    values["expected_home_team_id"] = fpl_input.teams[1].provider_team_id
    values["expected_home_team_identity"] = fpl_input.teams[1].identity
    values["expected_away_team_id"] = fpl_input.teams[0].provider_team_id
    values["expected_away_team_identity"] = fpl_input.teams[0].identity
    reversed_binding = CurrentFixtureBinding.model_validate(values)
    fixture_plan = _fixture_plan(team_plan, (reversed_binding,))

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, odds_input, team_plan, fixture_plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["mapping_outcome"] == "UNKNOWN"
    assert raised.value.details["reason"] == "EXPLICIT_BINDING_CONTRADICTS_PROVIDER_EVENT"


def test_event_outside_target_gameweek_is_unknown(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    team_plan = _team_plan(fpl_input)
    base = fpl_input.fixtures[0]
    assert base.kickoff_at is not None
    outside = base.model_copy(update={"event_identity": _identity("GAMEWEEK", "fpl.event.id", 2)})
    target_other = _clone_fixture(
        base,
        fixture_id=102,
        kickoff_at=base.kickoff_at + timedelta(hours=2),
    )
    mixed_fpl = fpl_input.model_copy(update={"fixtures": (outside, target_other)})
    fixture_plan = _fixture_plan(
        team_plan,
        (_fixture_binding(mixed_fpl, odds_input.events[0], fixture=outside),),
    )

    with pytest.raises(IngestionError) as raised:
        _resolve(mixed_fpl, odds_input, team_plan, fixture_plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["mapping_outcome"] == "UNKNOWN"
    assert raised.value.details["reason"] == "OUTSIDE_TARGET_GAMEWEEK"


def test_provider_event_before_official_deadline_is_quality_blocked(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    early = _clone_event(
        odds_input.events[0],
        commence_time=fpl_input.target_event.deadline_at - timedelta(seconds=1),
    )
    early_odds = odds_input.model_copy(update={"events": (early,)})

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, early_odds, team_plan, fixture_plan)

    assert raised.value.code == "QUALITY_BLOCKED"
    assert raised.value.details["mapping_outcome"] == "QUALITY_BLOCKED"
    assert raised.value.details["reason"] == "EVENT_BEFORE_OFFICIAL_DEADLINE"


def test_incomplete_target_gameweek_coverage_is_quality_blocked(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    base = fpl_input.fixtures[0]
    assert base.kickoff_at is not None
    second = _clone_fixture(
        base,
        fixture_id=102,
        kickoff_at=base.kickoff_at + timedelta(hours=2),
    )
    expanded_fpl = fpl_input.model_copy(update={"fixtures": (base, second)})

    with pytest.raises(IngestionError) as raised:
        _resolve(expanded_fpl, odds_input, team_plan, fixture_plan)

    assert raised.value.code == "QUALITY_BLOCKED"
    assert raised.value.details["mapping_outcome"] == "QUALITY_BLOCKED"
    assert raised.value.details["reason"] == "INCOMPLETE_ONE_TO_ONE_COVERAGE"
    assert raised.value.details["unmapped_official_fpl_fixture_ids"] == (102,)


def test_fixture_plan_approved_after_decision_is_post_cutoff(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    team_plan = _team_plan(fpl_input)
    binding = _fixture_binding(fpl_input, odds_input.events[0])
    fixture_plan = _fixture_plan(
        team_plan,
        (binding,),
        approved_at=CUTOFF + timedelta(seconds=1),
    )

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, odds_input, team_plan, fixture_plan)

    assert raised.value.code == "POST_CUTOFF"


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("competition_key", "SYNTHETIC_PL"),
        ("season_code", "2025/26"),
        ("provider", "another_provider"),
        ("evidence_class", "TEST_ONLY"),
        ("status", "APPROVED_FOR_TEST"),
        ("target_gameweek", 2),
    ),
)
def test_stale_or_test_only_fixture_plan_scope_is_rejected(
    repository_root: Path,
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    _fpl, _odds, _team_plan_value, fixture_plan = _default_context(repository_root, tmp_path)
    values = fixture_plan.model_dump(mode="python")
    values[field] = replacement

    with pytest.raises(ValidationError):
        CurrentFixtureMappingPlan.model_validate(values)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("fpl_input_semantic_sha256", "a" * 64),
        ("fpl_identity_view_sha256", "b" * 64),
        ("odds_provider_provenance_sha256", "c" * 64),
        ("odds_identity_semantic_sha256", "d" * 64),
        ("team_alias_plan_sha256", "e" * 64),
        ("team_identity_map_semantic_sha256", "f" * 64),
        ("fixture_mapping_plan_sha256", "1" * 64),
        ("fixture_mapping_plan_version", "9.9.9"),
    ),
)
def test_bound_source_or_mapping_substitution_fails_closed(
    repository_root: Path,
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    team_map = _team_map(fpl_input, odds_input, team_plan)
    request = bind_current_fixture_resolution_request(
        fpl_input,
        odds_input,
        team_plan,
        team_map,
        fixture_plan,
        mapping_decided_at=DECIDED,
    ).model_copy(update={field: replacement})

    with pytest.raises(IngestionError) as raised:
        resolve_current_fixture_identities(
            fpl_input,
            odds_input,
            team_plan,
            team_map,
            fixture_plan,
            request,
        )

    assert raised.value.code == "MAPPING_CONFLICT"


def test_stale_explicit_binding_kickoff_fails_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    team_plan = _team_plan(fpl_input)
    binding = _fixture_binding(
        fpl_input,
        odds_input.events[0],
        expected_commence_time=odds_input.events[0].commence_time + timedelta(seconds=1),
    )
    fixture_plan = _fixture_plan(team_plan, (binding,))

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, odds_input, team_plan, fixture_plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["mapping_outcome"] == "UNKNOWN"
    assert raised.value.details["reason"] == "EXPLICIT_BINDING_CONTRADICTS_PROVIDER_EVENT"


def test_stale_explicit_binding_fixture_identity_fails_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = _fpl_input(repository_root, tmp_path)
    odds_input = _odds_input(repository_root)
    team_plan = _team_plan(fpl_input)
    wrong_identity = _identity("FIXTURE", "fpl.fixture.id", 999)
    binding = _fixture_binding(
        fpl_input,
        odds_input.events[0],
        official_fixture_id=999,
        official_fixture_identity=wrong_identity,
    )
    fixture_plan = _fixture_plan(team_plan, (binding,))

    with pytest.raises(IngestionError) as raised:
        _resolve(fpl_input, odds_input, team_plan, fixture_plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["mapping_outcome"] == "UNKNOWN"
    assert raised.value.details["reason"] == "EXPLICIT_BINDING_STALE_AGAINST_FPL"


def test_resolved_fixture_rejects_nested_team_identity_mismatch(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    mapped = _resolve(fpl_input, odds_input, team_plan, fixture_plan).fixture("todapi-event-001")
    values = mapped.model_dump(mode="python")
    values["official_home_team_id"] = 999

    with pytest.raises(ValidationError, match="home team identity"):
        ResolvedCurrentFixture.model_validate(values)


def test_resolved_fixture_rejects_wrong_season_gameweek_identity(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    mapped = _resolve(fpl_input, odds_input, team_plan, fixture_plan).fixture("todapi-event-001")
    values = mapped.model_dump(mode="python")
    values["official_fpl_gameweek_identity"] = _identity(
        "GAMEWEEK",
        "fpl.event.id",
        1,
        season_code="2025/26",
    )

    with pytest.raises(ValidationError, match="gameweek identity"):
        ResolvedCurrentFixture.model_validate(values)


def test_resolved_fixture_rejects_remaining_internal_inconsistencies(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    mapped = _resolve(fpl_input, odds_input, team_plan, fixture_plan).fixture("todapi-event-001")
    early = mapped.official_deadline_at - timedelta(seconds=1)
    cases = (
        ({"official_fpl_fixture_id": 999}, "fixture identity"),
        ({"official_away_team_id": 999}, "away team identity"),
        (
            {
                "official_away_team_id": mapped.official_home_team_id,
                "official_away_team_identity": mapped.official_home_team_identity,
            },
            "home and away teams",
        ),
        ({"provider_away_team": mapped.provider_home_team}, "provider home and away"),
        (
            {"official_fpl_kickoff_at": mapped.official_fpl_kickoff_at + timedelta(seconds=1)},
            "kickoff must match",
        ),
        (
            {"provider_commence_time": early, "official_fpl_kickoff_at": early},
            "starts before",
        ),
    )

    for updates, message in cases:
        values = mapped.model_dump(mode="python")
        values.update(updates)
        with pytest.raises(ValidationError, match=message):
            ResolvedCurrentFixture.model_validate(values)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("provider_home_team", "Unreviewed Alias", "team mapping"),
        ("official_home_team_name", "Tampered Name", "team mapping"),
        (
            "binding_approved_at",
            DECIDED + timedelta(seconds=1),
            "binding approval",
        ),
        (
            "official_deadline_at",
            CUTOFF - timedelta(seconds=1),
            "official deadline",
        ),
    ),
)
def test_rehashed_identity_map_rejects_nested_context_tampering(
    repository_root: Path,
    tmp_path: Path,
    field: str,
    replacement: object,
    message: str,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    result = _resolve(fpl_input, odds_input, team_plan, fixture_plan)
    fixture = result.fixture("todapi-event-001").model_copy(update={field: replacement})
    tampered = _with_rehashed_fixture_mapping(result, fixture)

    with pytest.raises(ValidationError, match=message):
        FplOddsIdentityMap.model_validate(tampered.model_dump(mode="python"))


def test_rehashed_identity_map_rejects_remaining_map_inconsistencies(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, team_plan, fixture_plan = _default_context(repository_root, tmp_path)
    result = _resolve(fpl_input, odds_input, team_plan, fixture_plan)
    home, away = result.team_mappings
    wrong_home_identity = _identity(
        "TEAM",
        "fpl.team.id",
        home.official_fpl_team_id,
        season_code="2025/26",
    )
    invalid_team = home.model_copy(update={"official_fpl_team_identity": wrong_home_identity})
    late_team = home.model_copy(update={"mapping_approved_at": DECIDED + timedelta(seconds=1)})
    unused_team = home.model_copy(update={"provider_team_text": "Unused Reviewed Alias"})
    coverage = CurrentFixtureCoverage(
        provider_event_count=2,
        target_fpl_fixture_count=2,
        mapped_event_count=2,
    )
    mapped = result.fixture_mappings[0]
    wrong_season_fixture = mapped.model_copy(
        update={
            "official_fpl_fixture_identity": _identity(
                "FIXTURE",
                "fpl.fixture.id",
                mapped.official_fpl_fixture_id,
                season_code="2025/26",
            ),
            "official_fpl_gameweek_identity": _identity(
                "GAMEWEEK",
                "fpl.event.id",
                result.target_gameweek,
                season_code="2025/26",
            ),
            "official_home_team_identity": _identity(
                "TEAM",
                "fpl.team.id",
                mapped.official_home_team_id,
                season_code="2025/26",
            ),
            "official_away_team_identity": _identity(
                "TEAM",
                "fpl.team.id",
                mapped.official_away_team_id,
                season_code="2025/26",
            ),
        }
    )
    cases = (
        (
            _rehash_identity_map(result, team_mappings=(home, away, home)),
            "team mapping is duplicated",
        ),
        (
            _rehash_identity_map(
                result,
                information_cutoff=result.information_cutoff - timedelta(seconds=1),
            ),
            "deadline and information cutoff",
        ),
        (
            _rehash_identity_map(
                result,
                mapping_decided_at=result.information_cutoff + timedelta(seconds=1),
            ),
            "decision is after",
        ),
        (_rehash_identity_map(result, coverage=coverage), "coverage counts"),
        (
            _rehash_identity_map(result, team_mappings=(invalid_team, away)),
            "team identity contradicts",
        ),
        (
            _rehash_identity_map(result, team_mappings=(late_team, away)),
            "team mapping approval",
        ),
        (
            _with_rehashed_fixture_mapping(result, wrong_season_fixture),
            "target season or Gameweek",
        ),
        (
            _rehash_identity_map(result, team_mappings=(home, away, unused_team)),
            "unused or missing",
        ),
        (
            _rehash_identity_map(result, source_lineage_sha256="f" * 64),
            "source-lineage hash",
        ),
    )

    for tampered, message in cases:
        with pytest.raises(ValidationError, match=message):
            FplOddsIdentityMap.model_validate(tampered.model_dump(mode="python"))

    invalid_semantic = result.model_copy(update={"semantic_sha256": "f" * 64})
    with pytest.raises(ValidationError, match="semantic hash"):
        FplOddsIdentityMap.model_validate(invalid_semantic.model_dump(mode="python"))

    with pytest.raises(IngestionError, match="lacks one resolved"):
        result.fixture("missing-provider-event")
