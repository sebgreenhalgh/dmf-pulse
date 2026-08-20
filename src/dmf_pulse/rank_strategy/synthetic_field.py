"""Weighted shared-scenario simulation for an approved synthetic overall field."""

from __future__ import annotations

from collections import defaultdict
from math import log
from typing import Any

from pydantic import ValidationError

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.models import (
    ManagerMultiplierSet,
    ManagerTeamPlan,
    RankTiePolicy,
    SampleRightsStatus,
)
from dmf_pulse.rank_strategy.rank_simulator import (
    rank_probability_mass,
    weighted_rank_quantile,
)
from dmf_pulse.rank_strategy.synthetic_models import (
    SyntheticApproximationStatus,
    SyntheticBandScenarioCount,
    SyntheticOverallDistribution,
    SyntheticOverallPopulation,
    SyntheticOverallRankResult,
    SyntheticOverallScenarioOutcome,
    SyntheticPopulationDiagnostics,
)

_PERMITTED_OVERALL_RIGHTS = {
    SampleRightsStatus.SYNTHETIC_APPROVED,
    SampleRightsStatus.REPOSITORY_APPROVED,
}
_PERCENTILES = (
    ("p10", 0.10),
    ("p25", 0.25),
    ("p50", 0.50),
    ("p75", 0.75),
    ("p90", 0.90),
)


def _semantic_plan_hash(plan: ManagerTeamPlan) -> str:
    """Hash scoring/tie state while deliberately ignoring representative identity."""

    return semantic_sha256(plan.model_dump(mode="json", exclude={"manager_id", "plan_id"}))


def _validate_sealed_multiplier_set(value: ManagerMultiplierSet) -> None:
    for scenario in value.scenarios:
        payload = scenario.model_dump(mode="json", exclude={"multiplier_hash"})
        if scenario.multiplier_hash != semantic_sha256(payload):
            raise RankStrategyError(
                "RANK_SYNTHETIC_SCENARIO_MULTIPLIER_HASH_INVALID",
                "synthetic field received a mutated scenario multiplier",
                manager_id=value.manager_id,
                scenario_id=scenario.scenario_id,
                outcome_draw_id=scenario.outcome_draw_id,
            )
    payload = value.model_dump(mode="json", exclude={"multiplier_set_hash"})
    if value.multiplier_set_hash != semantic_sha256(payload):
        raise RankStrategyError(
            "RANK_SYNTHETIC_MULTIPLIER_SET_HASH_INVALID",
            "synthetic field received a mutated manager multiplier set",
            manager_id=value.manager_id,
        )


def _validate_inputs(
    population: SyntheticOverallPopulation,
    multiplier_sets: tuple[ManagerMultiplierSet, ...],
    tie_policy: RankTiePolicy,
    target_rank: int | None,
) -> tuple[
    dict[str, ManagerMultiplierSet],
    dict[str, ManagerTeamPlan],
    str,
    str,
    str,
    dict[str, str],
    tuple[tuple[str, str, float], ...],
]:
    population_payload = population.model_dump(mode="json", exclude={"population_hash"})
    if population.population_hash != semantic_sha256(population_payload):
        raise RankStrategyError(
            "RANK_SYNTHETIC_POPULATION_HASH_INVALID",
            "synthetic population changed after sealing",
            population_id=population.population_id,
        )
    if population.rights_status not in _PERMITTED_OVERALL_RIGHTS:
        raise RankStrategyError(
            "RANK_SYNTHETIC_RIGHTS_INVALID",
            "overall field simulation requires synthetic or repository-approved rights",
            population_id=population.population_id,
            rights_status=population.rights_status.value,
        )
    if (
        population.mass_scrape_used
        or population.final_rank_hindsight_used
        or population.definitive_overall_win_model
    ):
        raise RankStrategyError(
            "RANK_SYNTHETIC_FORBIDDEN_INPUT",
            "scraped, hindsight or definitive-win overall inputs are forbidden",
            population_id=population.population_id,
        )
    try:
        SyntheticOverallPopulation.model_validate(population.model_dump(mode="python"))
        RankTiePolicy.model_validate(tie_policy.model_dump(mode="python"))
    except ValidationError as exc:
        raise RankStrategyError(
            "RANK_SYNTHETIC_INPUT_INVALID",
            "synthetic population or tie-policy contract is malformed",
            population_id=population.population_id,
        ) from exc
    if not tie_policy.rules_verified:
        raise RankStrategyError(
            "RANK_TIE_RULES_INACTIVE",
            "synthetic overall simulation requires a verified active tie policy",
            policy_id=tie_policy.policy_id,
        )
    if target_rank is not None and (
        target_rank < 1 or target_rank > population.total_population_count
    ):
        raise RankStrategyError(
            "RANK_TARGET_INVALID",
            "target rank must lie inside the represented overall population",
            target_rank=target_rank,
            population_size=population.total_population_count,
        )

    representatives = tuple(
        representative for band in population.bands for representative in band.representatives
    )
    plans = {
        population.target_plan.manager_id: population.target_plan,
        **{item.manager_plan.manager_id: item.manager_plan for item in representatives},
    }
    expected_manager_ids = tuple(sorted(plans))
    set_by_manager = {item.manager_id: item for item in multiplier_sets}
    if len(set_by_manager) != len(multiplier_sets) or tuple(sorted(set_by_manager)) != (
        expected_manager_ids
    ):
        raise RankStrategyError(
            "RANK_SYNTHETIC_MANAGER_SET_MISMATCH",
            "manager multiplier sets must exactly match target and representatives",
            expected=list(expected_manager_ids),
            actual=sorted(set_by_manager),
        )
    for manager_id, plan in plans.items():
        multiplier_set = set_by_manager[manager_id]
        _validate_sealed_multiplier_set(multiplier_set)
        if multiplier_set.plan_id != plan.plan_id:
            raise RankStrategyError(
                "RANK_SYNTHETIC_MANAGER_PLAN_MISMATCH",
                "manager multiplier plan IDs must match the synthetic population",
                manager_id=manager_id,
            )

    target_set = set_by_manager[population.target_plan.manager_id]
    baseline_identity = tuple(
        (item.scenario_id, item.outcome_draw_id, item.weight) for item in target_set.scenarios
    )
    for manager_id in expected_manager_ids:
        item = set_by_manager[manager_id]
        if item.raw_projection_hash != target_set.raw_projection_hash:
            raise RankStrategyError(
                "RANK_RAW_PROJECTION_MISMATCH",
                "every synthetic representative must use identical raw projections",
                manager_id=manager_id,
            )
        if item.scenario_set_hash != target_set.scenario_set_hash:
            raise RankStrategyError(
                "RANK_SHARED_SCENARIO_HASH_MISMATCH",
                "every synthetic representative must use the shared football scenario set",
                manager_id=manager_id,
            )
        identity = tuple(
            (scenario.scenario_id, scenario.outcome_draw_id, scenario.weight)
            for scenario in item.scenarios
        )
        if identity != baseline_identity:
            raise RankStrategyError(
                "RANK_SHARED_SCENARIO_IDENTITY_MISMATCH",
                "synthetic representatives cannot use independent football draws or weights",
                manager_id=manager_id,
            )
    return (
        set_by_manager,
        plans,
        target_set.scenario_set_hash,
        target_set.raw_projection_hash,
        semantic_sha256(tie_policy.model_dump(mode="json")),
        {
            manager_id: set_by_manager[manager_id].multiplier_set_hash
            for manager_id in expected_manager_ids
        },
        baseline_identity,
    )


def _is_strictly_ahead(
    *,
    rival_points: int,
    rival_transfers: int,
    target_points: int,
    target_transfers: int,
) -> bool:
    return rival_points > target_points or (
        rival_points == target_points and rival_transfers < target_transfers
    )


def _is_exactly_tied(
    *,
    rival_points: int,
    rival_transfers: int,
    target_points: int,
    target_transfers: int,
) -> bool:
    return rival_points == target_points and rival_transfers == target_transfers


def _population_diagnostics(
    population: SyntheticOverallPopulation,
) -> SyntheticPopulationDiagnostics:
    representatives = tuple(
        representative for band in population.bands for representative in band.representatives
    )
    represented_count = sum(item.population_count for item in representatives)
    semantic_counts: defaultdict[str, int] = defaultdict(int)
    for representative in representatives:
        semantic_counts[_semantic_plan_hash(representative.manager_plan)] += (
            representative.population_count
        )
    squared_share_sum = sum((count / represented_count) ** 2 for count in semantic_counts.values())
    effective_count = 1.0 / squared_share_sum
    maximum_share = max(count / represented_count for count in semantic_counts.values())
    band_shares = tuple(band.population_count / represented_count for band in population.bands)
    entropy = -sum(share * log(share) for share in band_shares if share > 0.0)
    return SyntheticPopulationDiagnostics(
        represented_manager_count=represented_count,
        input_representative_count=len(representatives),
        semantic_representative_count=len(semantic_counts),
        effective_representative_count=effective_count,
        maximum_representative_population_share=maximum_share,
        band_population_entropy=entropy,
        known_truth=population.known_truth,
        approximation_status=(
            SyntheticApproximationStatus.KNOWN_TRUTH_EXHAUSTIVE
            if population.known_truth
            else SyntheticApproximationStatus.WEIGHTED_REPRESENTATIVE_APPROXIMATION
        ),
    )


def _seal_distribution(payload: dict[str, Any]) -> SyntheticOverallDistribution:
    unsealed = SyntheticOverallDistribution.model_construct(
        **payload,
        distribution_hash="0" * 64,
    )
    semantic_payload = unsealed.model_dump(mode="json", exclude={"distribution_hash"})
    return SyntheticOverallDistribution(
        **payload,
        distribution_hash=semantic_sha256(semantic_payload),
    )


def _seal_result(payload: dict[str, Any]) -> SyntheticOverallRankResult:
    unsealed = SyntheticOverallRankResult.model_construct(
        **payload,
        result_hash="0" * 64,
    )
    semantic_payload = unsealed.model_dump(mode="json", exclude={"result_hash"})
    return SyntheticOverallRankResult(
        **payload,
        result_hash=semantic_sha256(semantic_payload),
    )


def simulate_synthetic_overall_rank(
    population: SyntheticOverallPopulation,
    multiplier_sets: tuple[ManagerMultiplierSet, ...],
    tie_policy: RankTiePolicy,
    *,
    target_rank: int | None = None,
) -> SyntheticOverallRankResult:
    """Evaluate a weighted approved overall field on common football scenarios.

    Representative managers are never expanded into scraped identities. Integer
    population counts enter only the rank arithmetic, while every plan is scored
    against the same Stage-9 scenario and outcome-draw identity as the target.
    """

    (
        set_by_manager,
        _plans,
        scenario_hash,
        projection_hash,
        tie_policy_hash,
        multiplier_set_hashes,
        baseline_identity,
    ) = _validate_inputs(population, multiplier_sets, tie_policy, target_rank)
    scenario_maps = {
        manager_id: {
            (item.scenario_id, item.outcome_draw_id): item for item in multiplier_set.scenarios
        }
        for manager_id, multiplier_set in set_by_manager.items()
    }
    target_id = population.target_plan.manager_id
    outcomes: list[SyntheticOverallScenarioOutcome] = []
    rank_outcomes: list[tuple[int, float]] = []
    for scenario_id, outcome_draw_id, weight in baseline_identity:
        identity = (scenario_id, outcome_draw_id)
        target_points = (
            population.target_plan.cumulative_points + scenario_maps[target_id][identity].net_points
        )
        target_transfers = population.target_plan.counted_transfers
        band_counts: list[SyntheticBandScenarioCount] = []
        managers_ahead = 0
        managers_tied = 0
        for band in population.bands:
            band_ahead = 0
            band_tied = 0
            for representative in band.representatives:
                plan = representative.manager_plan
                scenario = scenario_maps[plan.manager_id][identity]
                final_points = plan.cumulative_points + scenario.net_points
                if _is_strictly_ahead(
                    rival_points=final_points,
                    rival_transfers=plan.counted_transfers,
                    target_points=target_points,
                    target_transfers=target_transfers,
                ):
                    band_ahead += representative.population_count
                elif _is_exactly_tied(
                    rival_points=final_points,
                    rival_transfers=plan.counted_transfers,
                    target_points=target_points,
                    target_transfers=target_transfers,
                ):
                    band_tied += representative.population_count
            managers_ahead += band_ahead
            managers_tied += band_tied
            band_counts.append(
                SyntheticBandScenarioCount(
                    band_id=band.band_id,
                    population_count=band.population_count,
                    managers_strictly_ahead=band_ahead,
                    managers_exactly_tied=band_tied,
                )
            )
        rank = 1 + managers_ahead
        outcomes.append(
            SyntheticOverallScenarioOutcome(
                scenario_id=scenario_id,
                outcome_draw_id=outcome_draw_id,
                weight=weight,
                target_final_points=target_points,
                target_counted_transfers=target_transfers,
                managers_strictly_ahead=managers_ahead,
                managers_exactly_tied=managers_tied,
                rank=rank,
                band_counts=tuple(sorted(band_counts, key=lambda item: item.band_id)),
            )
        )
        rank_outcomes.append((rank, weight))

    sorted_outcomes = tuple(
        sorted(outcomes, key=lambda item: (item.scenario_id, item.outcome_draw_id))
    )
    pmf = rank_probability_mass(rank_outcomes)
    percentiles = {
        label: weighted_rank_quantile(pmf, probability) for label, probability in _PERCENTILES
    }
    probability_target = (
        None
        if target_rank is None
        else sum(item.probability for item in pmf if item.rank <= target_rank)
    )
    distribution = _seal_distribution(
        {
            "target_manager_id": target_id,
            "population_size": population.total_population_count,
            "population_hash": population.population_hash,
            "scenario_set_hash": scenario_hash,
            "raw_projection_hash": projection_hash,
            "tie_policy_id": tie_policy.policy_id,
            "tie_policy_hash": tie_policy_hash,
            "manager_multiplier_set_hashes": multiplier_set_hashes,
            "target_rank": target_rank,
            "rank_pmf": pmf,
            "expected_rank": sum(item.rank * item.probability for item in pmf),
            "median_rank": weighted_rank_quantile(pmf, 0.50),
            "rank_percentiles": dict(sorted(percentiles.items())),
            "probability_target_rank": probability_target,
            "overall_rank_one_probability": sum(item.probability for item in pmf if item.rank == 1),
            "outcomes": sorted_outcomes,
            "confidence": population.confidence,
            "approximation_only": True,
            "definitive_overall_win_model": False,
        }
    )
    diagnostics = _population_diagnostics(population)
    return _seal_result(
        {
            "population_id": population.population_id,
            "population_hash": population.population_hash,
            "rights_status": population.rights_status,
            "provenance_ids": population.provenance_ids,
            "source_bundle_ids": population.source_bundle_ids,
            "upstream_hashes": population.upstream_hashes,
            "information_cutoff": population.information_cutoff,
            "distribution": distribution,
            "diagnostics": diagnostics,
            "approximation_only": True,
            "definitive_overall_win_model": False,
        }
    )
