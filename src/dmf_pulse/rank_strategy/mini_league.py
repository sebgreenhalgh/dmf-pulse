"""Exact shared-scenario named mini-league simulation."""

from __future__ import annotations

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.rank_strategy.cohorts import require_permitted_sample
from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.models import (
    CohortKind,
    CohortSample,
    ManagerMultiplierSet,
    ManagerScenarioStanding,
    MiniLeagueScenarioOutcome,
    RankDistribution,
    RankTiePolicy,
)
from dmf_pulse.rank_strategy.rank_simulator import (
    competition_ranks,
    rank_probability_mass,
    weighted_rank_quantile,
)


def _validate_exact_league(
    sample: CohortSample,
    multiplier_sets: tuple[ManagerMultiplierSet, ...],
    tie_policy: RankTiePolicy,
    target_manager_id: str,
) -> tuple[dict[str, ManagerMultiplierSet], str, str]:
    require_permitted_sample(sample)
    if sample.kind not in {CohortKind.NAMED_MINI_LEAGUE, CohortKind.SYNTHETIC}:
        raise RankStrategyError(
            "RANK_EXACT_LEAGUE_KIND_INVALID",
            "exact mini-league simulation requires an authorised named league or synthetic fixture",
            sample_id=sample.sample_id,
            kind=sample.kind.value,
        )
    if not tie_policy.rules_verified:
        raise RankStrategyError(
            "RANK_TIE_RULES_INACTIVE",
            "rank simulation requires a verified active tie policy",
            policy_id=tie_policy.policy_id,
        )
    member_ids = tuple(sorted(member.manager_plan.manager_id for member in sample.members))
    if len(member_ids) < 2:
        raise RankStrategyError(
            "RANK_LEAGUE_TOO_SMALL",
            "exact mini-league simulation requires at least two managers",
        )
    if target_manager_id not in member_ids:
        raise RankStrategyError(
            "RANK_TARGET_MANAGER_UNKNOWN",
            "target manager is absent from the exact mini-league",
            target_manager_id=target_manager_id,
        )
    set_by_manager = {item.manager_id: item for item in multiplier_sets}
    if len(set_by_manager) != len(multiplier_sets) or tuple(sorted(set_by_manager)) != member_ids:
        raise RankStrategyError(
            "RANK_MANAGER_SET_MISMATCH",
            "manager multiplier sets must exactly match mini-league membership",
            expected=list(member_ids),
            actual=sorted(set_by_manager),
        )
    sample_plan_ids = {
        member.manager_plan.manager_id: member.manager_plan.plan_id for member in sample.members
    }
    if any(item.plan_id != sample_plan_ids[item.manager_id] for item in multiplier_sets):
        raise RankStrategyError(
            "RANK_MANAGER_PLAN_MISMATCH",
            "manager multiplier plan IDs must match the exact observed league state",
        )

    baseline = multiplier_sets[0]
    baseline_identity = tuple(
        (item.scenario_id, item.outcome_draw_id, item.weight) for item in baseline.scenarios
    )
    for item in multiplier_sets[1:]:
        if item.raw_projection_hash != baseline.raw_projection_hash:
            raise RankStrategyError(
                "RANK_RAW_PROJECTION_MISMATCH",
                "all managers must use identical raw football/FPL projections",
                manager_id=item.manager_id,
            )
        if item.scenario_set_hash != baseline.scenario_set_hash:
            raise RankStrategyError(
                "RANK_SHARED_SCENARIO_HASH_MISMATCH",
                "all managers must use the same shared football scenario set",
                manager_id=item.manager_id,
            )
        identity = tuple(
            (scenario.scenario_id, scenario.outcome_draw_id, scenario.weight)
            for scenario in item.scenarios
        )
        if identity != baseline_identity:
            raise RankStrategyError(
                "RANK_SHARED_SCENARIO_IDENTITY_MISMATCH",
                "manager scenario identities and weights must be identical",
                manager_id=item.manager_id,
            )
    return set_by_manager, baseline.scenario_set_hash, baseline.raw_projection_hash


def simulate_mini_league_rank(
    sample: CohortSample,
    multiplier_sets: tuple[ManagerMultiplierSet, ...],
    tie_policy: RankTiePolicy,
    *,
    target_manager_id: str,
    target_rank: int | None = None,
) -> RankDistribution:
    """Enumerate an exact two-or-more-manager classic mini-league.

    Every manager is scored against the same football scenario identity. Manager
    uncertainty can be layered on later, but independent football draws are never
    generated here.
    """

    if target_rank is not None and target_rank < 1:
        raise RankStrategyError(
            "RANK_TARGET_INVALID",
            "target rank must be a positive integer when supplied",
            target_rank=target_rank,
        )
    set_by_manager, scenario_hash, projection_hash = _validate_exact_league(
        sample,
        multiplier_sets,
        tie_policy,
        target_manager_id,
    )
    plans = {member.manager_plan.manager_id: member.manager_plan for member in sample.members}
    scenario_maps = {
        manager_id: {
            (item.scenario_id, item.outcome_draw_id): item for item in multiplier_set.scenarios
        }
        for manager_id, multiplier_set in set_by_manager.items()
    }
    baseline = multiplier_sets[0]
    outcomes: list[MiniLeagueScenarioOutcome] = []
    target_rank_outcomes: list[tuple[int, float]] = []
    for baseline_scenario in baseline.scenarios:
        identity = (baseline_scenario.scenario_id, baseline_scenario.outcome_draw_id)
        final_state = {
            manager_id: (
                plans[manager_id].cumulative_points
                + scenario_maps[manager_id][identity].net_points,
                plans[manager_id].counted_transfers,
            )
            for manager_id in sorted(plans)
        }
        ranks = competition_ranks(final_state)
        rank_counts = {
            rank: sum(value == rank for value in ranks.values()) for rank in set(ranks.values())
        }
        standings = tuple(
            ManagerScenarioStanding(
                manager_id=manager_id,
                scenario_id=identity[0],
                outcome_draw_id=identity[1],
                cumulative_points=plans[manager_id].cumulative_points,
                gameweek_net_points=scenario_maps[manager_id][identity].net_points,
                final_points=final_state[manager_id][0],
                counted_transfers=final_state[manager_id][1],
                rank=ranks[manager_id],
                shared_rank=rank_counts[ranks[manager_id]] > 1,
            )
            for manager_id in sorted(plans)
        )
        outcome = MiniLeagueScenarioOutcome(
            scenario_id=identity[0],
            outcome_draw_id=identity[1],
            weight=baseline_scenario.weight,
            standings=standings,
            winner_manager_ids=tuple(item.manager_id for item in standings if item.rank == 1),
        )
        outcomes.append(outcome)
        target_rank_outcomes.append((ranks[target_manager_id], baseline_scenario.weight))

    pmf = rank_probability_mass(target_rank_outcomes)
    percentiles = {
        label: weighted_rank_quantile(pmf, probability)
        for label, probability in (
            ("p10", 0.10),
            ("p25", 0.25),
            ("p50", 0.50),
            ("p75", 0.75),
            ("p90", 0.90),
        )
    }
    expected_rank = sum(item.rank * item.probability for item in pmf)
    probability_target = (
        None
        if target_rank is None
        else sum(item.probability for item in pmf if item.rank <= target_rank)
    )
    win_probability = sum(item.probability for item in pmf if item.rank == 1)
    result = RankDistribution(
        target_manager_id=target_manager_id,
        population_size=len(plans),
        scenario_set_hash=scenario_hash,
        raw_projection_hash=projection_hash,
        tie_policy_id=tie_policy.policy_id,
        target_rank=target_rank,
        rank_pmf=pmf,
        expected_rank=expected_rank,
        median_rank=weighted_rank_quantile(pmf, 0.50),
        rank_percentiles=dict(sorted(percentiles.items())),
        probability_target_rank=probability_target,
        mini_league_win_probability=win_probability,
        outcomes=tuple(sorted(outcomes, key=lambda item: (item.scenario_id, item.outcome_draw_id))),
        confidence=sample.confidence,
        distribution_hash="0" * 64,
    )
    payload = result.model_dump(mode="json", exclude={"distribution_hash"})
    return result.model_copy(update={"distribution_hash": semantic_sha256(payload)})
