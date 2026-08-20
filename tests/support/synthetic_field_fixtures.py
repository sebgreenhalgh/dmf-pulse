"""Rights-safe tiny overall-field fixtures for checkpoint 15.05."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.prices.models import ConfidenceGrade
from dmf_pulse.rank_strategy.manager_multipliers import calculate_manager_multipliers
from dmf_pulse.rank_strategy.models import (
    ManagerMultiplierSet,
    ManagerTeamPlan,
    SampleRightsStatus,
)
from dmf_pulse.rank_strategy.synthetic_models import (
    SyntheticBandSelectionBasis,
    SyntheticManagerRepresentative,
    SyntheticOverallPopulation,
    SyntheticRankBand,
)
from tests.support.rank_strategy_fixtures import (
    manager_plan,
    multiplier_policy,
    rank_players,
    rank_rules,
)


def representative(
    representative_id: str,
    plan: ManagerTeamPlan,
    population_count: int,
) -> SyntheticManagerRepresentative:
    return SyntheticManagerRepresentative(
        representative_id=representative_id,
        manager_plan=plan,
        population_count=population_count,
    )


def rank_band(
    band_id: str,
    best_rank: int,
    worst_rank: int,
    *representatives: SyntheticManagerRepresentative,
    selection_basis: SyntheticBandSelectionBasis = (
        SyntheticBandSelectionBasis.SYNTHETIC_GENERATOR
    ),
) -> SyntheticRankBand:
    return SyntheticRankBand(
        band_id=band_id,
        best_rank=best_rank,
        worst_rank=worst_rank,
        population_count=sum(item.population_count for item in representatives),
        selection_basis=selection_basis,
        representatives=tuple(sorted(representatives, key=lambda item: item.representative_id)),
    )


def seal_population(**payload: Any) -> SyntheticOverallPopulation:
    unsealed = SyntheticOverallPopulation.model_construct(
        **payload,
        population_hash="0" * 64,
    )
    semantic_payload = unsealed.model_dump(mode="json", exclude={"population_hash"})
    return SyntheticOverallPopulation(
        **payload,
        population_hash=semantic_sha256(semantic_payload),
    )


def tiny_known_truth_population(
    *,
    target_plan: ManagerTeamPlan | None = None,
    bands: tuple[SyntheticRankBand, ...] | None = None,
    rights_status: SampleRightsStatus = SampleRightsStatus.SYNTHETIC_APPROVED,
    known_truth: bool = True,
) -> SyntheticOverallPopulation:
    target_plan = target_plan or manager_plan(
        "sebastian",
        captain="p12",
        cumulative_points=100,
        counted_transfers=5,
    )
    if bands is None:
        bands = (
            rank_band(
                "band-a",
                1,
                2,
                representative(
                    "rep-a",
                    manager_plan(
                        "rival-a",
                        captain="p13",
                        cumulative_points=101,
                        counted_transfers=4,
                    ),
                    2,
                ),
            ),
            rank_band(
                "band-b",
                3,
                5,
                representative(
                    "rep-b",
                    manager_plan(
                        "rival-b",
                        captain="p14",
                        cumulative_points=99,
                        counted_transfers=6,
                    ),
                    1,
                ),
                representative(
                    "rep-c",
                    manager_plan(
                        "rival-c",
                        captain="p12",
                        cumulative_points=98,
                        counted_transfers=5,
                        hit_points=4,
                    ),
                    1,
                ),
            ),
        )
    represented_count = sum(item.population_count for item in bands)
    return seal_population(
        population_id="tiny-known-truth-field",
        target_plan=target_plan,
        rights_status=rights_status,
        generated_at=datetime(2026, 8, 20, 10, tzinfo=UTC),
        information_cutoff=datetime(2026, 8, 20, 12, tzinfo=UTC),
        total_population_count=represented_count + 1,
        bands=tuple(sorted(bands, key=lambda item: item.band_id)),
        known_truth=known_truth,
        confidence=ConfidenceGrade.A if known_truth else ConfidenceGrade.B,
        provenance_ids=("fixture:tiny-known-truth-field",),
        source_bundle_ids=("source:synthetic-rank-stage15",),
        upstream_hashes=("4" * 64,),
        mass_scrape_used=False,
        final_rank_hindsight_used=False,
        definitive_overall_win_model=False,
    )


def population_plans(population: SyntheticOverallPopulation) -> tuple[ManagerTeamPlan, ...]:
    values = [population.target_plan]
    values.extend(
        representative.manager_plan
        for band in population.bands
        for representative in band.representatives
    )
    return tuple(sorted(values, key=lambda item: item.manager_id))


def multiplier_sets_for_population(
    population: SyntheticOverallPopulation,
    scenarios,
) -> tuple[ManagerMultiplierSet, ...]:
    return tuple(
        calculate_manager_multipliers(
            plan,
            scenarios,
            rank_players(),
            rank_rules(),
            multiplier_policy(),
        )
        for plan in population_plans(population)
    )
