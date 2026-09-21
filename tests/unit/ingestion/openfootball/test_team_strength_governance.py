from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_DNS, uuid5

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    APPROVED_GOVERNANCE_SEMANTIC_SHA256,
    APPROVED_IDENTITY_SEMANTIC_SHA256,
    SourceFreshnessState,
    classify_source_freshness,
    eligibility_not_before,
    load_current_team_strength_governance,
    load_historical_team_identity,
    resolve_openfootball_team,
)


@pytest.mark.contract
def test_historical_identity_registry_is_complete_and_canonical() -> None:
    identity = load_historical_team_identity()

    assert identity.canonical_club_count == 42
    assert identity.record_count == 56
    assert identity.alias_count == 56
    assert identity.additional_alias_count == 14
    assert len(identity.seasons_covered) == 17
    assert identity.seasons_covered == tuple(
        f"{year}/{str(year + 1)[-2:]}" for year in range(2010, 2027)
    )
    assert identity.unresolved_club_count == 0
    assert identity.ambiguous_mapping_count == 0
    assert len({club.canonical_team_id for club in identity.canonical_clubs}) == 42
    assert all(club.canonical_team_id.version == 7 for club in identity.canonical_clubs)
    assert all(
        club.registered_at == datetime.fromtimestamp((club.canonical_team_id.int >> 80) / 1000, UTC)
        for club in identity.canonical_clubs
    )
    assert identity.root_semantic_sha256 == APPROVED_IDENTITY_SEMANTIC_SHA256


@pytest.mark.contract
def test_every_source_name_and_season_maps_exactly_once() -> None:
    identity = load_historical_team_identity()
    expanded = [
        (season, record.source_team_name, record.canonical_team_id)
        for record in identity.records
        for season in record.season_scope
    ]

    assert len(expanded) == len({(season, alias) for season, alias, _ in expanded})
    for season, alias, expected in expanded:
        assert (
            resolve_openfootball_team(
                identity,
                season_code=season,
                source_team_name=alias,
            )
            == expected
        )


@pytest.mark.contract
def test_alias_variants_converge_without_normalization() -> None:
    identity = load_historical_team_identity()

    old = resolve_openfootball_team(
        identity, season_code="2019/20", source_team_name="Manchester City"
    )
    current = resolve_openfootball_team(
        identity, season_code="2020/21", source_team_name="Manchester City FC"
    )
    assert old == current
    with pytest.raises(IngestionError, match="not exactly resolved"):
        resolve_openfootball_team(
            identity, season_code="2020/21", source_team_name="manchester city fc"
        )
    with pytest.raises(IngestionError, match="not exactly resolved"):
        resolve_openfootball_team(
            identity, season_code="2020/21", source_team_name="Manchester City"
        )


@pytest.mark.parametrize(
    ("club_name", "early_season", "late_season"),
    [
        ("Burnley FC", "2014/15", "2025/26"),
        ("Leeds United FC", "2020/21", "2025/26"),
        ("Sunderland AFC", "2016/17", "2026/27"),
        ("Hull City AFC", "2013/14", "2026/27"),
        ("Ipswich Town FC", "2024/25", "2026/27"),
    ],
)
def test_relegation_and_repromotion_preserve_identity(
    club_name: str, early_season: str, late_season: str
) -> None:
    identity = load_historical_team_identity()
    club = next(item for item in identity.canonical_clubs if item.canonical_name == club_name)
    early_alias = next(
        record.source_team_name
        for record in identity.records
        if record.canonical_team_id == club.canonical_team_id
        and early_season in record.season_scope
    )
    late_alias = next(
        record.source_team_name
        for record in identity.records
        if record.canonical_team_id == club.canonical_team_id and late_season in record.season_scope
    )

    assert resolve_openfootball_team(
        identity, season_code=early_season, source_team_name=early_alias
    ) == resolve_openfootball_team(identity, season_code=late_season, source_team_name=late_alias)


def test_canonical_ids_are_frozen_registrations_not_names_or_source_order() -> None:
    identity = load_historical_team_identity()
    forward = {club.canonical_name: club.canonical_team_id for club in identity.canonical_clubs}
    reverse = {
        club.canonical_name: club.canonical_team_id for club in reversed(identity.canonical_clubs)
    }

    assert forward == reverse
    assert all(
        team_id != uuid5(NAMESPACE_DNS, name) and team_id.hex not in name
        for name, team_id in forward.items()
    )
    assert all(
        club.id_generation_method == "NONDETERMINISTIC_UUIDV7_REGISTRATION"
        for club in identity.canonical_clubs
    )


def test_current_fpl_ids_are_external_and_season_scoped() -> None:
    identity = load_historical_team_identity()
    external = [
        club.current_fpl_external_identifier
        for club in identity.canonical_clubs
        if club.current_fpl_external_identifier is not None
    ]

    assert len(external) == 20
    assert {item.season_scope for item in external} == {"2026/27"}
    assert {item.provider_key for item in external} == {"official_fpl"}
    assert {item.source_snapshot_sha256 for item in external} == {
        "faff6a660d48d3fde513b9601379f33086240db9b07598101f48169c68cbd1e7"
    }
    assert len({item.external_id_text for item in external}) == 20
    canonical_ids = {str(club.canonical_team_id) for club in identity.canonical_clubs}
    assert canonical_ids.isdisjoint({item.external_id_text for item in external})


@pytest.mark.contract
def test_locked_governance_policy_is_exact_and_nonactivating() -> None:
    policy = load_current_team_strength_governance()
    materiality = policy.materiality_policy

    assert materiality.calibration_relative_harm_limit == Decimal("0.01")
    assert materiality.subgroup_relative_harm_limit == Decimal("0.01")
    assert materiality.player_xp_materiality_per_gw == Decimal("0.15")
    assert materiality.transfer_horizon_materiality_points == Decimal("0.50")
    assert materiality.transfer_horizon_gameweeks == 3
    assert materiality.root_action_switch_always_material is True
    assert materiality.prospective_min_gameweeks == 10
    assert materiality.prospective_min_labelled_fixtures == 100
    assert materiality.production_promotion_requires_separate_human_approval is True
    assert policy.model_implementation_present is False
    assert policy.production_active is False
    assert policy.selected_shadow_policy.output_rate_strictly_positive is True
    assert policy.selected_shadow_policy.maximum_output_rate == Decimal("8.000000")
    assert policy.semantic_sha256 == APPROVED_GOVERNANCE_SEMANTIC_SHA256


def test_eligibility_is_second_midnight_utc() -> None:
    assert eligibility_not_before(date(2026, 9, 19)) == datetime(2026, 9, 21, tzinfo=UTC)


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(0), SourceFreshnessState.FRESH),
        (timedelta(hours=24), SourceFreshnessState.FRESH),
        (timedelta(hours=24, microseconds=1), SourceFreshnessState.DEGRADED),
        (timedelta(hours=72), SourceFreshnessState.DEGRADED),
        (timedelta(hours=72, microseconds=1), SourceFreshnessState.STALE_BLOCKED),
    ],
)
def test_freshness_boundaries(age: timedelta, expected: SourceFreshnessState) -> None:
    cutoff = datetime(2026, 9, 21, 12, tzinfo=UTC)

    assert (
        classify_source_freshness(
            cutoff=cutoff,
            latest_successful_usable_retrieval=cutoff - age,
            missing_due=0,
            canonical_mapping_valid=True,
            status_unambiguous=True,
            schema_valid=True,
            source_lineage_valid=True,
        )
        is expected
    )


@pytest.mark.parametrize(
    "update",
    [
        {"missing_due": 1},
        {"canonical_mapping_valid": False},
        {"status_unambiguous": False},
        {"schema_valid": False},
        {"source_lineage_valid": False},
    ],
)
def test_each_validation_failure_blocks_refit(update: dict[str, object]) -> None:
    cutoff = datetime(2026, 9, 21, 12, tzinfo=UTC)
    arguments: dict[str, object] = {
        "cutoff": cutoff,
        "latest_successful_usable_retrieval": cutoff - timedelta(hours=1),
        "missing_due": 0,
        "canonical_mapping_valid": True,
        "status_unambiguous": True,
        "schema_valid": True,
        "source_lineage_valid": True,
    }
    arguments.update(update)

    assert classify_source_freshness(**arguments) is SourceFreshnessState.STALE_BLOCKED  # type: ignore[arg-type]


def test_freshness_rejects_naive_cutoff_and_negative_missing_count() -> None:
    aware = datetime(2026, 9, 21, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone-aware"):
        classify_source_freshness(
            cutoff=datetime(2026, 9, 21, 12),
            latest_successful_usable_retrieval=aware,
            missing_due=0,
            canonical_mapping_valid=True,
            status_unambiguous=True,
            schema_valid=True,
            source_lineage_valid=True,
        )
    with pytest.raises(ValueError, match="nonnegative"):
        classify_source_freshness(
            cutoff=aware,
            latest_successful_usable_retrieval=aware,
            missing_due=-1,
            canonical_mapping_valid=True,
            status_unambiguous=True,
            schema_valid=True,
            source_lineage_valid=True,
        )


def test_future_retrieval_fails_closed() -> None:
    cutoff = datetime(2026, 9, 21, 12, tzinfo=UTC)
    assert (
        classify_source_freshness(
            cutoff=cutoff,
            latest_successful_usable_retrieval=cutoff + timedelta(seconds=1),
            missing_due=0,
            canonical_mapping_valid=True,
            status_unambiguous=True,
            schema_valid=True,
            source_lineage_valid=True,
        )
        is SourceFreshnessState.STALE_BLOCKED
    )


def test_unknown_alias_fails_closed() -> None:
    identity = load_historical_team_identity()
    with pytest.raises(IngestionError) as caught:
        resolve_openfootball_team(
            identity, season_code="2026/27", source_team_name="Unknown United"
        )
    assert caught.value.code == "MAPPING_FAILED"
