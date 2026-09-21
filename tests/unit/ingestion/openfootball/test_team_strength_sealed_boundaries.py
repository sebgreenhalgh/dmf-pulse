"""Resealing cannot turn contradictory synthetic source evidence into valid data."""

from __future__ import annotations

from datetime import UTC, timedelta, timezone
from uuid import UUID

import pytest

from dmf_pulse.ingestion.openfootball import team_strength_data as data
from tests.unit.football_events.test_team_strength_hardening import reseal
from tests.unit.ingestion.openfootball.test_team_strength_data import STAMP, dataset, registry


def test_source_purpose_hash_and_path_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    resource = dataset().sources[0].lineage.resource
    with pytest.raises(ValueError, match="path"):
        resource.model_copy(update={"season": "2025/26"})
    monkeypatch.setattr(data, "rights_config_sha256", lambda: "a" * 64)
    with pytest.raises(ValueError, match="rights authority"):
        data.require_team_strength_rights()


@pytest.mark.parametrize("change", ["uuid", "self", "order", "pair", "competition", "membership"])
def test_fixture_registry_canonical_constraints(change: str) -> None:
    value = registry()
    row = value.fixtures[0]
    with pytest.raises(ValueError):
        if change == "uuid":
            row.model_copy(update={"fixture_id": UUID(int=1)})
        elif change == "self":
            row.model_copy(update={"away_team_id": row.home_team_id})
        elif change == "order":
            reseal(value, fixtures=(row, row))
        elif change == "pair":
            other = row.model_copy(
                update={"fixture_id": UUID("019a0100-0000-7000-8000-000000000003")}
            )
            reseal(value, fixtures=(row, other))
        elif change == "competition":
            reseal(value, competition_id=UUID("019a0100-0000-7000-8000-000000000004"))
        else:
            reseal(value, fixtures=(row.model_copy(update={"season": "2029/30"}),))


@pytest.mark.parametrize("change", ["partial", "fulltime", "lineage", "training"])
def test_score_and_nested_lineage_constraints(change: str) -> None:
    value = dataset()
    source = value.sources[0]
    row = source.matches[0]
    with pytest.raises(ValueError):
        if change == "partial":
            reseal(row, home_goals=None)
        elif change == "fulltime":
            reseal(row, home_goals=None, away_goals=None)
        elif change == "lineage":
            reseal(source, matches=(reseal(row, source_snapshot_sha256="a" * 64),))
        else:
            reseal(value.matches[0], observation=reseal(row, finality="NOT_FINAL"))


@pytest.mark.parametrize(
    "change", ["future", "live", "competition", "duplicate", "forecast", "eligibility", "binding"]
)
def test_dataset_consistency_not_just_hash(change: str) -> None:
    value = dataset()
    updates = {}
    if change == "future":
        updates["training_cutoff"] = STAMP + timedelta(seconds=1)
    elif change == "live":
        updates["training_cutoff"] = STAMP - timedelta(seconds=1)
    elif change == "competition":
        updates["competition_id"] = UUID("019a0100-0000-7000-8000-000000000004")
    elif change == "duplicate":
        updates["sources"] = (value.sources[0], value.sources[0])
    elif change == "forecast":
        updates["forecast_season"] = "2029/30"
    elif change == "eligibility":
        updates["missing_due"] = 1
    else:
        updates["sources"] = (reseal(value.sources[0], fixture_registry_sha256="a" * 64),)
    with pytest.raises(ValueError):
        reseal(value, **updates)


def test_live_validation_at_cutoff_is_not_before_cutoff() -> None:
    value = dataset()
    source = value.sources[0]
    lineage = reseal(source.lineage, validated_at=STAMP, usable_at=STAMP)
    row = reseal(source.matches[0], source_snapshot_sha256=lineage.semantic_sha256)
    revised = reseal(source, lineage=lineage, matches=(row,))
    with pytest.raises(ValueError, match="strictly before"):
        data._eligible((revised,), STAMP, STAMP, "LIVE_OBSERVED")


def test_equivalent_aware_offsets_have_identical_semantic_identity() -> None:
    value = dataset()
    offset = STAMP.astimezone(timezone(timedelta(hours=2)))
    other = data.build_dataset(
        sources=value.sources,
        fixtures=value.fixture_registry,
        expected_fixture_registry_sha256=value.fixture_registry.semantic_sha256,
        information_cutoff=offset,
        training_cutoff=offset,
        forecast_season=value.forecast_season,
        mode=value.dataset_mode,
    )
    assert other == value and other.information_cutoff.tzinfo is UTC
    source = value.sources[0].lineage
    equivalent = reseal(
        source,
        **{
            name: getattr(source, name).astimezone(timezone(timedelta(hours=-5)))
            for name in ("retrieval_started_at", "received_at", "validated_at", "usable_at")
        },
    )
    assert equivalent == source
    with pytest.raises(ValueError, match="timezone-aware"):
        reseal(source, received_at=source.received_at.replace(tzinfo=None))
