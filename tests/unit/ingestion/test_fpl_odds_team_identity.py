"""CURRENT-FPL-STATE-001B exact transient team identity contracts."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.odds import mapping as mapping_module
from dmf_pulse.ingestion.odds.identity import (
    bind_current_team_resolution_request,
    resolve_current_team_identities,
)
from dmf_pulse.ingestion.odds.mapping import CurrentTeamAliasMapping, CurrentTeamAliasPlan
from tests.unit.ingestion.current_identity_test_support import (
    CUTOFF,
    DECIDED,
    FPL_USABLE,
    ODDS_USABLE,
    TEAM_APPROVED,
    build_fpl_input,
    build_odds_input,
    make_identity,
    rehash_odds_input,
    resolve_team_map,
    team_mapping,
    team_plan,
)

pytestmark = pytest.mark.unit


def test_exact_explicit_gw2_team_resolution_is_transient_and_hash_bound(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    odds_input = build_odds_input(repository_root, extra_event=True)
    plan = team_plan(fpl_input)

    result = resolve_team_map(fpl_input, odds_input, plan)

    assert result.contract == "FPL_ODDS_TEAM_IDENTITY_MAP"
    assert result.target_gameweek == 2
    assert result.information_cutoff < fpl_input.target_event.deadline_at
    assert result.storage_mode == "TRANSIENT_IN_MEMORY"
    assert result.persistence_performed is False
    assert result.database_accessed is False
    assert result.fpl_derived_storage == "DENY"
    assert result.odds_raw_payload_retained is False
    assert result.team("Alpha Athletic").official_fpl_team_id == 1
    assert result.team("Beta Borough").official_fpl_team_id == 2
    assert result.team_alias_plan_sha256 == plan.sha256
    assert len(result.semantic_sha256) == 64
    assert not hasattr(mapping_module, "load_current_team_alias_plan")
    assert not hasattr(mapping_module, "load_current_fixture_mapping_plan")


def test_team_plan_and_resolution_are_order_independent(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    odds_input = build_odds_input(repository_root)
    first_plan = team_plan(fpl_input)
    second_plan = team_plan(fpl_input, mappings=tuple(reversed(first_plan.team_mappings)))

    first = resolve_team_map(fpl_input, odds_input, first_plan)
    second = resolve_team_map(fpl_input, odds_input, second_plan)

    assert first_plan.sha256 == second_plan.sha256
    assert first.semantic_sha256 == second.semantic_sha256
    assert first.team_mappings == second.team_mappings


@pytest.mark.parametrize(
    "provider_text",
    (
        "Beta Boro",
        "alpha athletic",
        "Alpha-Athletic",
        "Alpha Athleti",
        "Alpha",
    ),
)
def test_unapproved_variants_never_fuzzy_match(
    repository_root: Path,
    tmp_path: Path,
    provider_text: str,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    odds_input = build_odds_input(repository_root)
    event = odds_input.events[0].model_copy(update={"provider_away_team": provider_text})
    changed = rehash_odds_input(odds_input, events=(event,))

    with pytest.raises(IngestionError) as raised:
        resolve_team_map(fpl_input, changed, team_plan(fpl_input))

    assert raised.value.code == "MAPPING_CONFLICT"


def test_duplicate_provider_alias_and_many_aliases_to_one_team_are_rejected(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    by_id = {team.provider_team_id: team for team in fpl_input.teams}
    duplicate_text = (
        team_mapping("Shared", by_id[1]),
        team_mapping("Shared", by_id[2]),
    )
    duplicate_team = (
        team_mapping("Alpha Athletic", by_id[1]),
        team_mapping("Beta Borough", by_id[1]),
    )

    with pytest.raises(ValidationError, match="provider team alias"):
        team_plan(fpl_input, mappings=duplicate_text)
    with pytest.raises(ValidationError, match="target is duplicated"):
        team_plan(fpl_input, mappings=duplicate_team)


def test_unknown_current_team_and_stale_official_name_fail_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    by_id = {team.provider_team_id: team for team in fpl_input.teams}
    unknown = CurrentTeamAliasMapping(
        provider_team_text="Beta Borough",
        official_fpl_team_id=999,
        canonical_team_identity=make_identity("TEAM", "fpl.team.id", 999),
        official_fpl_team_name="Synthetic Unknown",
        evidence_class="APPROVED_MANUAL",
        reviewer="Synthetic Test Reviewer",
        approved_at=TEAM_APPROVED,
    )
    unknown_plan = team_plan(
        fpl_input,
        mappings=(team_mapping("Alpha Athletic", by_id[1]), unknown),
    )
    stale_plan = team_plan(
        fpl_input,
        mappings=(
            team_mapping("Alpha Athletic", by_id[1], official_name="Former Alpha"),
            team_mapping("Beta Borough", by_id[2]),
        ),
    )

    for plan in (unknown_plan, stale_plan):
        with pytest.raises(IngestionError) as raised:
            resolve_team_map(fpl_input, build_odds_input(repository_root), plan)
        assert raised.value.code == "MAPPING_CONFLICT"


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("competition_key", "SYNTHETIC_PL"),
        ("season_code", "2025/26"),
        ("provider", "another_provider"),
        ("evidence_class", "TEST_ONLY"),
        ("status", "APPROVED_FOR_TEST"),
        ("contract_version", "obsolete-fpl-odds-team-alias-plan-v1"),
        ("mapping_algorithm_version", "obsolete-fpl-odds-exact-v1"),
    ),
)
def test_wrong_context_test_authority_and_obsolete_labels_are_rejected(
    repository_root: Path,
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    values = team_plan(build_fpl_input(repository_root, tmp_path)).model_dump(mode="python")
    values[field] = replacement

    with pytest.raises(ValidationError):
        CurrentTeamAliasPlan.model_validate(values)


def test_plan_provenance_and_timezone_are_strict(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    values = team_plan(fpl_input).model_dump(mode="python")
    values["approved_at"] = TEAM_APPROVED - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="provenance"):
        CurrentTeamAliasPlan.model_validate(values)

    values = team_plan(fpl_input).model_dump(mode="python")
    values["approved_at"] = datetime(2026, 8, 1, 12)
    with pytest.raises(ValidationError, match="timezone-aware"):
        CurrentTeamAliasPlan.model_validate(values)


def test_common_cutoff_mismatch_and_mapping_decision_window_fail_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    plan = team_plan(fpl_input)
    mismatched_odds = build_odds_input(repository_root, cutoff=CUTOFF - timedelta(seconds=1))
    with pytest.raises(IngestionError) as cutoff_error:
        resolve_team_map(fpl_input, mismatched_odds, plan)
    assert cutoff_error.value.code == "MAPPING_CONFLICT"

    odds_input = build_odds_input(repository_root)
    for decided_at in (FPL_USABLE - timedelta(seconds=1), CUTOFF + timedelta(seconds=1)):
        with pytest.raises(IngestionError) as raised:
            resolve_team_map(fpl_input, odds_input, plan, decided_at=decided_at)
        assert raised.value.code == "POST_CUTOFF"


def test_future_plan_or_alias_approval_is_post_cutoff(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    odds_input = build_odds_input(repository_root)
    future = CUTOFF + timedelta(seconds=1)
    plan = team_plan(fpl_input, approved_at=future)

    with pytest.raises(IngestionError) as raised:
        resolve_team_map(fpl_input, odds_input, plan)

    assert raised.value.code == "POST_CUTOFF"


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("fpl_input_semantic_sha256", "a" * 64),
        ("fpl_identity_view_sha256", "b" * 64),
        ("odds_provider_provenance_sha256", "c" * 64),
        ("odds_identity_semantic_sha256", "d" * 64),
        ("team_alias_plan_sha256", "e" * 64),
        ("team_alias_plan_version", "9.9.9"),
    ),
)
def test_bound_lineage_substitution_fails_closed(
    repository_root: Path,
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    odds_input = build_odds_input(repository_root)
    plan = team_plan(fpl_input)
    request = bind_current_team_resolution_request(
        fpl_input, odds_input, plan, mapping_decided_at=DECIDED
    ).model_copy(update={field: replacement})

    with pytest.raises(IngestionError) as raised:
        resolve_current_team_identities(fpl_input, odds_input, plan, request)

    assert raised.value.code == "MAPPING_CONFLICT"


def test_source_and_alias_plan_substitution_after_binding_fail_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    odds_input = build_odds_input(repository_root)
    plan = team_plan(fpl_input)
    request = bind_current_team_resolution_request(
        fpl_input, odds_input, plan, mapping_decided_at=DECIDED
    )

    changed_team = fpl_input.teams[0].model_copy(update={"official_name": "Tampered Name"})
    changed_fpl = fpl_input.model_copy(update={"teams": (changed_team, *fpl_input.teams[1:])})
    changed_odds = build_odds_input(repository_root, price_delta=0.125)
    changed_plan = plan.model_copy(update={"plan_version": "1.0.1"})
    for fpl_value, odds_value, plan_value in (
        (changed_fpl, odds_input, plan),
        (fpl_input, changed_odds, plan),
        (fpl_input, odds_input, changed_plan),
    ):
        with pytest.raises(IngestionError) as raised:
            resolve_current_team_identities(fpl_value, odds_value, plan_value, request)
        assert raised.value.code == "MAPPING_CONFLICT"


def test_fpl_and_odds_rights_substitution_fail_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    odds_input = build_odds_input(repository_root)
    plan = team_plan(fpl_input)
    altered_fpl = fpl_input.model_copy(
        update={"rights": fpl_input.rights.model_copy(update={"derived_storage": "ALLOW"})}
    )
    altered_odds = odds_input.model_copy(
        update={"rights": odds_input.rights.model_copy(update={"transient_processing": "DENY"})}
    )

    for fpl_value, odds_value in ((altered_fpl, odds_input), (fpl_input, altered_odds)):
        request = bind_current_team_resolution_request(
            fpl_value, odds_value, plan, mapping_decided_at=DECIDED
        )
        with pytest.raises(IngestionError) as raised:
            resolve_current_team_identities(fpl_value, odds_value, plan, request)
        assert raised.value.code == "RIGHTS_BLOCKED"


def test_mapping_decision_requires_aware_utc_time(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    fpl_input = build_fpl_input(repository_root, tmp_path)
    odds_input = build_odds_input(repository_root)
    with pytest.raises(ValidationError, match="timezone-aware"):
        bind_current_team_resolution_request(
            fpl_input,
            odds_input,
            team_plan(fpl_input),
            mapping_decided_at=datetime(2026, 8, 24, 10, 30),
        )

    assert FPL_USABLE <= DECIDED
    assert ODDS_USABLE <= DECIDED
