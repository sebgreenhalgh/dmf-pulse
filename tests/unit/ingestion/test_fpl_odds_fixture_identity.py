"""CURRENT-FPL-STATE-001B exact current fixture identity acceptance."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplFixture
from dmf_pulse.ingestion.odds.identity import (
    CurrentFixtureCoverage,
    FplOddsIdentityMap,
    ResolvedCurrentFixture,
    ResolvedCurrentTeam,
    _fpl_odds_identity_map_sha256,
    _team_identity_map_sha256,
    bind_current_fixture_resolution_request,
    current_odds_identity_semantic_sha256,
    resolve_current_fixture_identities,
)
from dmf_pulse.ingestion.odds.mapping import (
    CurrentFixtureBinding,
    CurrentFixtureMappingPlan,
)
from tests.unit.ingestion.current_identity_test_support import (
    CUTOFF,
    DEADLINE,
    DECIDED,
    KICKOFF,
    ODDS_USABLE,
    OUTSIDE_PROVIDER_EVENT_ID,
    TARGET_PROVIDER_EVENT_ID,
    build_fpl_input,
    build_odds_input,
    fixture_binding,
    fixture_plan,
    make_identity,
    rehash_odds_input,
    resolve_bridge,
    resolve_team_map,
    target_fixture,
    team_mapping,
    team_plan,
)

pytestmark = pytest.mark.unit


def _context(repository_root: Path, tmp_path: Path, *, extra_event: bool = False):
    fpl_input = build_fpl_input(repository_root, tmp_path)
    odds_input = build_odds_input(repository_root, extra_event=extra_event)
    aliases = team_plan(fpl_input)
    bindings = fixture_plan(fpl_input, odds_input, aliases)
    return fpl_input, odds_input, aliases, bindings


def _clone_fixture(
    base: CurrentFplFixture,
    *,
    fixture_id: int,
    kickoff_at: datetime,
) -> CurrentFplFixture:
    return base.model_copy(
        update={
            "identity": make_identity("FIXTURE", "fpl.fixture.id", fixture_id),
            "provider_fixture_id": fixture_id,
            "provider_code": 900000 + fixture_id,
            "kickoff_at": kickoff_at,
        }
    )


def _rehash_result(result: FplOddsIdentityMap, **updates: object) -> FplOddsIdentityMap:
    changed = result.model_copy(update=updates)
    return changed.model_copy(update={"semantic_sha256": _fpl_odds_identity_map_sha256(changed)})


def test_complete_gw2_mapping_with_earlier_cutoff_and_extra_provider_event(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, bindings = _context(repository_root, tmp_path, extra_event=True)

    result = resolve_bridge(fpl_input, odds_input, aliases, bindings)
    mapped = result.fixture(TARGET_PROVIDER_EVENT_ID)

    assert result.target_gameweek == 2
    assert result.information_cutoff == CUTOFF
    assert result.information_cutoff < result.official_deadline_at == DEADLINE
    assert mapped.provider_commence_time == mapped.official_fpl_kickoff_at == KICKOFF
    assert mapped.official_deadline_at < mapped.official_fpl_kickoff_at
    assert mapped.official_home_team_id == 2
    assert mapped.official_away_team_id == 1
    assert result.coverage.status == "COMPLETE"
    assert result.coverage.all_provider_event_count == 2
    assert result.coverage.bound_provider_event_count == 1
    assert result.coverage.target_fpl_fixture_count == 1
    assert result.coverage.mapped_event_count == 1
    assert result.coverage.outside_target_provider_event_count == 1
    assert result.coverage.outside_target_provider_event_ids == (OUTSIDE_PROVIDER_EVENT_ID,)
    assert result.storage_mode == "TRANSIENT_IN_MEMORY"
    assert result.persistence_performed is False
    assert result.database_accessed is False
    assert result.fpl_derived_storage == "DENY"
    assert result.odds_raw_payload_retained is False
    assert result.kickoff_policy == "EXACT_UTC_EQUALITY"


def test_unrelated_outside_target_participants_remain_supported(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(
        repository_root,
        tmp_path,
        additional_teams=(("Gamma City", "GAM"), ("Delta United", "DEL")),
    )
    odds_input = build_odds_input(
        repository_root,
        extra_event_participants=("Gamma City", "Delta United"),
    )
    by_id = {team.provider_team_id: team for team in fpl_input.teams}
    base = team_plan(fpl_input)
    aliases = team_plan(
        fpl_input,
        mappings=(
            *base.team_mappings,
            team_mapping("Gamma City", by_id[3]),
            team_mapping("Delta United", by_id[4]),
        ),
    )

    result = resolve_bridge(
        fpl_input,
        odds_input,
        aliases,
        fixture_plan(fpl_input, odds_input, aliases),
    )

    assert result.observed_provider_team_texts == (
        "Alpha Athletic",
        "Beta Borough",
        "Delta United",
        "Gamma City",
    )
    assert {mapping.provider_team_text for mapping in result.team_mappings} == set(
        result.observed_provider_team_texts
    )
    assert result.coverage.outside_target_provider_event_ids == (OUTSIDE_PROVIDER_EVENT_ID,)


def test_provider_event_order_is_deterministic_and_price_order_is_identity_invariant(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    first_odds = build_odds_input(repository_root, extra_event=True)
    second_odds = build_odds_input(
        repository_root,
        extra_event=True,
        reverse_events=True,
        reverse_bookmakers=True,
        price_delta=0.125,
    )
    aliases = team_plan(fpl_input)
    bindings = fixture_plan(fpl_input, first_odds, aliases)

    first = resolve_bridge(fpl_input, first_odds, aliases, bindings)
    second = resolve_bridge(fpl_input, second_odds, aliases, bindings)

    assert current_odds_identity_semantic_sha256(
        first_odds
    ) == current_odds_identity_semantic_sha256(second_odds)
    assert first.odds_provider_provenance_sha256 != second.odds_provider_provenance_sha256
    assert first.team_identity_map_semantic_sha256 != second.team_identity_map_semantic_sha256
    assert first.source_lineage_sha256 != second.source_lineage_sha256
    assert first.semantic_sha256 == second.semantic_sha256
    assert first.fixture_mappings == second.fixture_mappings
    assert first.coverage == second.coverage


def test_unknown_bound_provider_event_is_rejected(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, _bindings = _context(repository_root, tmp_path)
    binding = fixture_binding(fpl_input, odds_input, aliases).model_copy(
        update={"provider_event_id": "synthetic-missing-event"}
    )
    plan = fixture_plan(fpl_input, odds_input, aliases, bindings=(binding,))

    with pytest.raises(IngestionError) as raised:
        resolve_bridge(fpl_input, odds_input, aliases, plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["reason"] == "BOUND_PROVIDER_EVENT_NOT_FOUND"


def test_duplicate_provider_event_and_duplicate_fpl_fixture_are_ambiguous(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, _bindings = _context(repository_root, tmp_path)
    duplicated_odds = rehash_odds_input(
        odds_input, events=(odds_input.events[0], odds_input.events[0])
    )
    odds_plan = fixture_plan(fpl_input, duplicated_odds, aliases)
    with pytest.raises(IngestionError) as odds_error:
        resolve_bridge(fpl_input, duplicated_odds, aliases, odds_plan)
    assert odds_error.value.details["reason"] == "DUPLICATE_PROVIDER_EVENT_IDENTITY"

    base = target_fixture(fpl_input)
    duplicated_fpl = fpl_input.model_copy(update={"fixtures": (*fpl_input.fixtures, base)})
    duplicate_binding = fixture_binding(duplicated_fpl, odds_input, aliases, fixture=base)
    fpl_plan = fixture_plan(duplicated_fpl, odds_input, aliases, bindings=(duplicate_binding,))
    with pytest.raises(IngestionError) as fpl_error:
        resolve_bridge(duplicated_fpl, odds_input, aliases, fpl_plan)
    assert fpl_error.value.details["reason"] == "DUPLICATE_OFFICIAL_FIXTURE_IDENTITY"


def test_reversed_home_away_and_one_second_kickoff_change_fail_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, _bindings = _context(repository_root, tmp_path)
    base = odds_input.events[0]
    cases = (
        (
            base.model_copy(
                update={
                    "provider_home_team": base.provider_away_team,
                    "provider_away_team": base.provider_home_team,
                }
            ),
            "HOME_AWAY_ORIENTATION_MISMATCH",
        ),
        (
            base.model_copy(update={"commence_time": base.commence_time + timedelta(seconds=1)}),
            "EXACT_KICKOFF_MISMATCH",
        ),
    )
    for event, reason in cases:
        changed_odds = rehash_odds_input(odds_input, events=(event,))
        plan = fixture_plan(fpl_input, changed_odds, aliases)
        with pytest.raises(IngestionError) as raised:
            resolve_bridge(fpl_input, changed_odds, aliases, plan)
        assert raised.value.code == "MAPPING_CONFLICT"
        assert raised.value.details["reason"] == reason


def test_explicit_binding_orientation_kickoff_and_fpl_identity_are_exact(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, _bindings = _context(repository_root, tmp_path)
    base = fixture_binding(fpl_input, odds_input, aliases)
    home = aliases.team("Beta Borough")
    away = aliases.team("Alpha Athletic")
    reversed_values = base.model_dump(mode="python")
    reversed_values.update(
        {
            "expected_home_team_id": away.official_fpl_team_id,
            "expected_home_team_identity": away.canonical_team_identity,
            "expected_away_team_id": home.official_fpl_team_id,
            "expected_away_team_identity": home.canonical_team_identity,
        }
    )
    reversed_binding = CurrentFixtureBinding.model_validate(reversed_values)
    stale_kickoff = base.model_copy(
        update={"expected_commence_time": KICKOFF + timedelta(seconds=1)}
    )
    stale_identity = base.model_copy(
        update={
            "official_fpl_fixture_id": 999,
            "canonical_fixture_identity": make_identity("FIXTURE", "fpl.fixture.id", 999),
        }
    )
    cases = (
        (reversed_binding, "EXPLICIT_BINDING_CONTRADICTS_PROVIDER_EVENT"),
        (stale_kickoff, "EXPLICIT_BINDING_CONTRADICTS_PROVIDER_EVENT"),
        (stale_identity, "BINDING_OUTSIDE_TARGET_GAMEWEEK"),
    )
    for binding, reason in cases:
        plan = fixture_plan(fpl_input, odds_input, aliases, bindings=(binding,))
        with pytest.raises(IngestionError) as raised:
            resolve_bridge(fpl_input, odds_input, aliases, plan)
        assert raised.value.code == "MAPPING_CONFLICT"
        assert raised.value.details["reason"] == reason


def test_binding_to_non_target_gameweek_fixture_is_rejected(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, _bindings = _context(repository_root, tmp_path)
    non_target = next(
        fixture
        for fixture in fpl_input.fixtures
        if fixture.event_identity != fpl_input.target_event.identity
    )
    binding = fixture_binding(fpl_input, odds_input, aliases, fixture=non_target)
    plan = fixture_plan(fpl_input, odds_input, aliases, bindings=(binding,))

    with pytest.raises(IngestionError) as raised:
        resolve_bridge(fpl_input, odds_input, aliases, plan)

    assert raised.value.details["reason"] == "BINDING_OUTSIDE_TARGET_GAMEWEEK"


def test_bound_provider_event_before_or_at_deadline_is_quality_blocked(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    aliases = team_plan(fpl_input)
    for commence_time in (DEADLINE - timedelta(seconds=1), DEADLINE):
        odds_input = build_odds_input(repository_root, target_commence_time=commence_time)
        plan = fixture_plan(fpl_input, odds_input, aliases)
        with pytest.raises(IngestionError) as raised:
            resolve_bridge(fpl_input, odds_input, aliases, plan)
        assert raised.value.code == "QUALITY_BLOCKED"
        assert raised.value.details["reason"] == "EVENT_BEFORE_OR_AT_OFFICIAL_DEADLINE"


def test_missing_target_coverage_and_multiple_exact_candidates_block(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, _bindings = _context(repository_root, tmp_path)
    base = target_fixture(fpl_input)
    missing_candidate = _clone_fixture(
        base, fixture_id=103, kickoff_at=KICKOFF + timedelta(hours=2)
    )
    expanded = fpl_input.model_copy(update={"fixtures": (*fpl_input.fixtures, missing_candidate)})
    base_binding = fixture_binding(expanded, odds_input, aliases, fixture=base)
    missing_plan = fixture_plan(expanded, odds_input, aliases, bindings=(base_binding,))
    with pytest.raises(IngestionError) as missing:
        resolve_bridge(expanded, odds_input, aliases, missing_plan)
    assert missing.value.code == "QUALITY_BLOCKED"
    assert missing.value.details["reason"] == "INCOMPLETE_TARGET_FIXTURE_COVERAGE"

    duplicate_candidate = _clone_fixture(base, fixture_id=104, kickoff_at=KICKOFF)
    ambiguous = fpl_input.model_copy(
        update={"fixtures": (*fpl_input.fixtures, duplicate_candidate)}
    )
    ambiguous_binding = fixture_binding(ambiguous, odds_input, aliases, fixture=base)
    ambiguous_plan = fixture_plan(ambiguous, odds_input, aliases, bindings=(ambiguous_binding,))
    with pytest.raises(IngestionError) as duplicate:
        resolve_bridge(ambiguous, odds_input, aliases, ambiguous_plan)
    assert duplicate.value.code == "MAPPING_CONFLICT"
    assert duplicate.value.details["reason"] == "MULTIPLE_EXACT_CANDIDATES"


def test_fixture_plan_rejects_one_to_many_and_many_to_one_bindings(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, _bindings = _context(
        repository_root, tmp_path, extra_event=True
    )
    base_fixture = target_fixture(fpl_input)
    second_fixture = _clone_fixture(
        base_fixture, fixture_id=103, kickoff_at=KICKOFF + timedelta(hours=2)
    )
    first = fixture_binding(fpl_input, odds_input, aliases)
    one_to_many = fixture_binding(fpl_input, odds_input, aliases, fixture=second_fixture)
    many_to_one = first.model_copy(update={"provider_event_id": OUTSIDE_PROVIDER_EVENT_ID})

    with pytest.raises(ValidationError, match="provider event binding"):
        fixture_plan(fpl_input, odds_input, aliases, bindings=(first, one_to_many))
    with pytest.raises(ValidationError, match="fixture binding"):
        fixture_plan(fpl_input, odds_input, aliases, bindings=(first, many_to_one))


def test_unbound_exact_duplicate_candidate_is_ambiguous(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    odds_input = build_odds_input(repository_root, colliding_extra=True)
    aliases = team_plan(fpl_input)
    plan = fixture_plan(fpl_input, odds_input, aliases)

    with pytest.raises(IngestionError) as raised:
        resolve_bridge(fpl_input, odds_input, aliases, plan)

    assert raised.value.code == "MAPPING_CONFLICT"
    assert raised.value.details["mapping_outcome"] == "AMBIGUOUS"
    assert raised.value.details["reason"] == "UNBOUND_EXACT_TARGET_CANDIDATE"


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
def test_bound_fixture_lineage_substitution_fails_closed(
    repository_root: Path,
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    fpl_input, odds_input, aliases, plan = _context(repository_root, tmp_path)
    teams = resolve_team_map(fpl_input, odds_input, aliases)
    request = bind_current_fixture_resolution_request(
        fpl_input,
        odds_input,
        aliases,
        teams,
        plan,
        mapping_decided_at=DECIDED,
    ).model_copy(update={field: replacement})

    with pytest.raises(IngestionError) as raised:
        resolve_current_fixture_identities(fpl_input, odds_input, aliases, teams, plan, request)

    assert raised.value.code == "MAPPING_CONFLICT"


def test_fixture_plan_source_and_team_map_substitution_fail_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, plan = _context(repository_root, tmp_path)
    teams = resolve_team_map(fpl_input, odds_input, aliases)
    source_changed = plan.model_copy(update={"fpl_identity_view_sha256": "a" * 64})
    changed_request = bind_current_fixture_resolution_request(
        fpl_input,
        odds_input,
        aliases,
        teams,
        source_changed,
        mapping_decided_at=DECIDED,
    )
    with pytest.raises(IngestionError) as source_error:
        resolve_current_fixture_identities(
            fpl_input, odds_input, aliases, teams, source_changed, changed_request
        )
    assert source_error.value.code == "MAPPING_CONFLICT"

    request = bind_current_fixture_resolution_request(
        fpl_input,
        odds_input,
        aliases,
        teams,
        plan,
        mapping_decided_at=DECIDED,
    )
    altered_teams = teams.model_copy(update={"semantic_sha256": "b" * 64})
    with pytest.raises(IngestionError) as team_error:
        resolve_current_fixture_identities(
            fpl_input, odds_input, aliases, altered_teams, plan, request
        )
    assert team_error.value.code == "MAPPING_CONFLICT"


def test_fixture_approval_must_be_fresh_not_future_and_decision_pre_cutoff(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, _plan = _context(repository_root, tmp_path)
    stale_at = ODDS_USABLE - timedelta(seconds=1)
    stale_binding = fixture_binding(fpl_input, odds_input, aliases, approved_at=stale_at)
    stale_plan = fixture_plan(
        fpl_input,
        odds_input,
        aliases,
        bindings=(stale_binding,),
        approved_at=stale_at,
    )
    with pytest.raises(IngestionError, match="predates") as stale:
        resolve_bridge(fpl_input, odds_input, aliases, stale_plan)
    assert stale.value.code == "MAPPING_CONFLICT"

    future_at = DECIDED + timedelta(seconds=1)
    future_binding = fixture_binding(fpl_input, odds_input, aliases, approved_at=future_at)
    future_plan = fixture_plan(
        fpl_input,
        odds_input,
        aliases,
        bindings=(future_binding,),
        approved_at=future_at,
    )
    with pytest.raises(IngestionError) as future:
        resolve_bridge(fpl_input, odds_input, aliases, future_plan)
    assert future.value.code == "POST_CUTOFF"

    valid_plan = fixture_plan(fpl_input, odds_input, aliases)
    with pytest.raises(IngestionError) as post_cutoff:
        resolve_bridge(
            fpl_input,
            odds_input,
            aliases,
            valid_plan,
            decided_at=CUTOFF + timedelta(seconds=1),
        )
    assert post_cutoff.value.code == "POST_CUTOFF"


def test_fpl_reschedule_after_binding_requires_fresh_plan(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, plan = _context(repository_root, tmp_path)
    teams = resolve_team_map(fpl_input, odds_input, aliases)
    request = bind_current_fixture_resolution_request(
        fpl_input,
        odds_input,
        aliases,
        teams,
        plan,
        mapping_decided_at=DECIDED,
    )
    target = target_fixture(fpl_input)
    rescheduled = target.model_copy(update={"kickoff_at": KICKOFF + timedelta(hours=1)})
    changed_fpl = fpl_input.model_copy(
        update={
            "fixtures": tuple(
                rescheduled if item == target else item for item in fpl_input.fixtures
            )
        }
    )

    with pytest.raises(IngestionError) as raised:
        resolve_current_fixture_identities(changed_fpl, odds_input, aliases, teams, plan, request)

    assert raised.value.code == "MAPPING_CONFLICT"


def test_resolved_fixture_rejects_internal_identity_and_time_tampering(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, plan = _context(repository_root, tmp_path)
    mapped = resolve_bridge(fpl_input, odds_input, aliases, plan).fixture(TARGET_PROVIDER_EVENT_ID)
    cases = (
        ({"official_fpl_fixture_id": 999}, "fixture context"),
        ({"official_home_team_id": 999}, "fixture context"),
        ({"provider_away_team": mapped.provider_home_team}, "participants"),
        (
            {"official_fpl_kickoff_at": mapped.official_fpl_kickoff_at + timedelta(seconds=1)},
            "match exactly",
        ),
        (
            {
                "provider_commence_time": DEADLINE,
                "official_fpl_kickoff_at": DEADLINE,
            },
            "after the official deadline",
        ),
        ({"provider_event_identity_sha256": "f" * 64}, "event identity hash"),
    )
    for updates, message in cases:
        values = mapped.model_dump(mode="python")
        values.update(updates)
        with pytest.raises(ValidationError, match=message):
            ResolvedCurrentFixture.model_validate(values)


def test_rehashed_final_map_rejects_nested_context_plan_and_hash_tampering(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input, odds_input, aliases, plan = _context(repository_root, tmp_path)
    result = resolve_bridge(fpl_input, odds_input, aliases, plan)
    mapped = result.fixture(TARGET_PROVIDER_EVENT_ID)
    home, away = result.team_mappings
    late_mapping = mapped.model_copy(update={"binding_approved_at": DECIDED + timedelta(seconds=1)})
    wrong_gameweek = mapped.model_copy(
        update={"official_fpl_gameweek_identity": make_identity("GAMEWEEK", "fpl.event.id", 3)}
    )
    wrong_team_name = mapped.model_copy(update={"official_home_team_name": "Tampered Name"})
    wrong_provider_team = mapped.model_copy(update={"provider_home_team": "Unapproved Team"})
    invalid_team = home.model_copy(update={"official_fpl_team_name": "Tampered Club"})
    invalid_coverage = result.coverage.model_copy(update={"all_provider_event_count": 2})
    cases = (
        (_rehash_result(result, fixture_mappings=(late_mapping,)), "bound plans"),
        (_rehash_result(result, fixture_mappings=(wrong_gameweek,)), "bound plans"),
        (_rehash_result(result, fixture_mappings=(wrong_team_name,)), "bound plans"),
        (
            _rehash_result(result, fixture_mappings=(wrong_provider_team,)),
            "event identity hash",
        ),
        (_rehash_result(result, team_mappings=(invalid_team, away)), "approved alias"),
        (_rehash_result(result, coverage=invalid_coverage), "coverage evidence"),
        (_rehash_result(result, team_alias_plan_sha256="a" * 64), "plan lineage"),
        (_rehash_result(result, fixture_mapping_plan_sha256="b" * 64), "plan lineage"),
        (_rehash_result(result, fpl_identity_view_sha256="c" * 64), "plan lineage"),
        (_rehash_result(result, source_lineage_sha256="d" * 64), "source-lineage"),
    )
    for tampered, message in cases:
        with pytest.raises(ValidationError, match=message):
            FplOddsIdentityMap.model_validate(tampered.model_dump(mode="python"))

    bad_semantic = result.model_copy(update={"semantic_sha256": "e" * 64})
    with pytest.raises(ValidationError, match="semantic hash"):
        FplOddsIdentityMap.model_validate(bad_semantic.model_dump(mode="python"))
    with pytest.raises(IngestionError, match="lacks one resolved"):
        result.fixture("synthetic-missing-event")


def test_rehashed_final_map_rejects_dormant_resolved_team_authority(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(
        repository_root,
        tmp_path,
        additional_teams=(("Unused Town", "UNU"),),
    )
    odds_input = build_odds_input(repository_root)
    aliases = team_plan(fpl_input)
    mapping_plan = fixture_plan(fpl_input, odds_input, aliases)
    team_map = resolve_team_map(fpl_input, odds_input, aliases)
    result = resolve_bridge(fpl_input, odds_input, aliases, mapping_plan)
    unused_team = next(team for team in fpl_input.teams if team.provider_team_id == 3)
    unused_alias = team_mapping("Unused Town", unused_team)
    expanded_aliases = team_plan(
        fpl_input,
        mappings=(*aliases.team_mappings, unused_alias),
    )
    dormant = ResolvedCurrentTeam(
        provider_team_text=unused_alias.provider_team_text,
        official_fpl_team_id=unused_alias.official_fpl_team_id,
        official_fpl_team_identity=unused_alias.canonical_team_identity,
        official_fpl_team_name=unused_alias.official_fpl_team_name,
        mapping_evidence_class=unused_alias.evidence_class,
        mapping_reviewer=unused_alias.reviewer,
        mapping_approved_at=unused_alias.approved_at,
        team_alias_mapping_sha256=unused_alias.sha256,
    )
    dormant_team_map = team_map.model_copy(
        update={
            "team_alias_plan": expanded_aliases,
            "team_alias_plan_sha256": expanded_aliases.sha256,
            "team_mappings": (*team_map.team_mappings, dormant),
        }
    )
    dormant_team_map = dormant_team_map.model_copy(
        update={"semantic_sha256": _team_identity_map_sha256(dormant_team_map)}
    )
    expanded_fixture_plan = mapping_plan.model_copy(
        update={"team_alias_plan_sha256": expanded_aliases.sha256}
    )
    tampered = _rehash_result(
        result,
        team_alias_plan=expanded_aliases,
        team_alias_plan_sha256=expanded_aliases.sha256,
        team_identity_map_semantic_sha256=dormant_team_map.semantic_sha256,
        fixture_mapping_plan=expanded_fixture_plan,
        fixture_mapping_plan_sha256=expanded_fixture_plan.sha256,
        team_mappings=dormant_team_map.team_mappings,
    )

    with pytest.raises(ValidationError, match="dormant or missing team authority"):
        FplOddsIdentityMap.model_validate(tampered.model_dump(mode="python"))


def test_coverage_model_cannot_mark_incomplete_state_complete() -> None:
    with pytest.raises(ValidationError, match="coverage evidence"):
        CurrentFixtureCoverage(
            all_provider_event_count=2,
            bound_provider_event_count=1,
            outside_target_provider_event_count=0,
            target_fpl_fixture_count=1,
            mapped_event_count=1,
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("competition_key", "SYNTHETIC_PL"),
        ("season_code", "2025/26"),
        ("provider", "another_provider"),
        ("evidence_class", "TEST_ONLY"),
        ("status", "APPROVED_FOR_TEST"),
        ("target_gameweek", 3),
        ("contract_version", "obsolete-fpl-odds-fixture-plan-v1"),
        ("mapping_algorithm_version", "obsolete-fpl-odds-exact-v1"),
    ),
)
def test_fixture_plan_rejects_wrong_or_internally_inconsistent_scope(
    repository_root: Path,
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    _fpl_input, _odds_input, _aliases, plan = _context(repository_root, tmp_path)
    values = plan.model_dump(mode="python")
    values[field] = replacement

    with pytest.raises(ValidationError):
        CurrentFixtureMappingPlan.model_validate(values)
