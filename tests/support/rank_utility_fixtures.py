"""Synthetic Stage-15 rank-utility fixtures."""

from __future__ import annotations

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.rank_strategy.models import (
    ManagerScenarioStanding,
    MiniLeagueScenarioOutcome,
    RankDistribution,
    RankMass,
)
from dmf_pulse.rank_strategy.utility_models import (
    RankActivationContext,
    RankPlanCandidate,
    RankPlanSource,
    RankUtilityPolicy,
)

RAW_HASH = "a" * 64
SCENARIO_HASH = "b" * 64
SCENARIO_WEIGHTS = {"s1|d1": 0.5, "s2|d2": 0.5}


def rank_distribution(
    _plan_id: str,
    pmf: dict[int, float],
    *,
    population_size: int = 10,
    confidence: str = "A",
    raw_hash: str = RAW_HASH,
    scenario_hash: str = SCENARIO_HASH,
) -> RankDistribution:
    masses = tuple(
        RankMass(rank=rank, probability=probability) for rank, probability in sorted(pmf.items())
    )
    expected_rank = sum(item.rank * item.probability for item in masses)

    def quantile(probability: float) -> int:
        cumulative = 0.0
        for mass in masses:
            cumulative += mass.probability
            if cumulative + 1e-15 >= probability:
                return mass.rank
        return masses[-1].rank

    median_rank = quantile(0.5)
    percentiles = {
        label: quantile(probability)
        for label, probability in (
            ("p10", 0.10),
            ("p25", 0.25),
            ("p50", 0.50),
            ("p75", 0.75),
            ("p90", 0.90),
        )
    }
    if population_size < max(item.rank for item in masses):
        raise ValueError("fixture population cannot be smaller than its PMF support")
    outcomes: list[MiniLeagueScenarioOutcome] = []
    for index, mass in enumerate(masses, start=1):
        scenario_id = f"rank-pmf-{index:03d}"
        outcome_draw_id = f"rank-draw-{index:03d}"
        rivals = [f"rival-{rival_index:03d}" for rival_index in range(1, population_size)]
        standings: list[ManagerScenarioStanding] = []
        for rival_index, manager_id in enumerate(rivals, start=1):
            rival_rank = rival_index if rival_index < mass.rank else rival_index + 1
            standings.append(
                ManagerScenarioStanding(
                    manager_id=manager_id,
                    scenario_id=scenario_id,
                    outcome_draw_id=outcome_draw_id,
                    cumulative_points=1_000,
                    gameweek_net_points=1_000 - rival_rank,
                    final_points=2_000 - rival_rank,
                    counted_transfers=rival_rank,
                    rank=rival_rank,
                    shared_rank=False,
                )
            )
        standings.append(
            ManagerScenarioStanding(
                manager_id="sebastian",
                scenario_id=scenario_id,
                outcome_draw_id=outcome_draw_id,
                cumulative_points=1_000,
                gameweek_net_points=1_000 - mass.rank,
                final_points=2_000 - mass.rank,
                counted_transfers=mass.rank,
                rank=mass.rank,
                shared_rank=False,
            )
        )
        canonical_standings = tuple(sorted(standings, key=lambda item: item.manager_id))
        outcomes.append(
            MiniLeagueScenarioOutcome(
                scenario_id=scenario_id,
                outcome_draw_id=outcome_draw_id,
                weight=mass.probability,
                standings=canonical_standings,
                winner_manager_ids=tuple(
                    item.manager_id for item in canonical_standings if item.rank == 1
                ),
            )
        )
    payload = {
        "target_manager_id": "sebastian",
        "population_size": population_size,
        "scenario_set_hash": scenario_hash,
        "raw_projection_hash": raw_hash,
        "tie_policy_id": "verified-classic",
        "tie_policy_hash": "c" * 64,
        "target_rank": None,
        "rank_pmf": masses,
        "expected_rank": expected_rank,
        "median_rank": median_rank,
        "rank_percentiles": percentiles,
        "probability_target_rank": None,
        "mini_league_win_probability": sum(
            (item.probability for item in masses if item.rank == 1),
            0.0,
        ),
        "outcomes": tuple(outcomes),
        "confidence": confidence,
    }
    unsealed = RankDistribution.model_construct(**payload, distribution_hash="0" * 64)
    return RankDistribution(
        **payload,
        distribution_hash=semantic_sha256(
            unsealed.model_dump(mode="json", exclude={"distribution_hash"})
        ),
    )


def candidate(
    plan_id: str,
    expected_points: float,
    pmf: dict[int, float] | None = None,
    *,
    population_size: int = 10,
    confidence: str = "A",
    leverage: float = 0.0,
    template_beta: float = 0.0,
    tracking_error: float = 0.0,
    raw_ownership: float | None = None,
    effective_ownership: float | None = None,
    raw_hash: str = RAW_HASH,
    scenario_hash: str = SCENARIO_HASH,
) -> RankPlanCandidate:
    scenario_points = {
        "s1|d1": expected_points - 2.0,
        "s2|d2": expected_points + 2.0,
    }
    score_hash = semantic_sha256(
        {
            "scenario_set_hash": scenario_hash,
            "scenario_points": scenario_points,
            "scenario_weights": SCENARIO_WEIGHTS,
        }
    )
    return RankPlanCandidate(
        plan_id=plan_id,
        source_stage=RankPlanSource.SYNTHETIC_TEST,
        raw_projection_hash=raw_hash,
        scenario_set_hash=scenario_hash,
        scenario_points=scenario_points,
        scenario_weights=SCENARIO_WEIGHTS,
        expected_points=expected_points,
        rank_distribution=(
            None
            if pmf is None
            else rank_distribution(
                plan_id,
                pmf,
                population_size=population_size,
                confidence=confidence,
                raw_hash=raw_hash,
                scenario_hash=scenario_hash,
            )
        ),
        measured_leverage_score=leverage,
        template_beta=template_beta,
        tracking_error=tracking_error,
        mean_raw_ownership=raw_ownership,
        mean_effective_ownership=effective_ownership,
        scenario_score_hash=score_hash,
    )


def context(
    *,
    gameweek: int = 20,
    confidence: str = "A",
    explicit: bool = True,
    current_rank: int | None = 100_000,
    human_review: bool = False,
    **gate_overrides: bool,
) -> RankActivationContext:
    values = {
        "target_rules_active": True,
        "rules_verified": True,
        "rights_valid": True,
        "cohort_valid": True,
        "opponent_data_valid": True,
    }
    values.update(gate_overrides)
    return RankActivationContext(
        gameweek=gameweek,
        season_gameweeks=38,
        current_rank=current_rank,
        user_selected_explicit_target=explicit,
        rank_model_confidence=confidence,
        human_review_available=human_review,
        **values,
    )


def policy(
    *,
    points_epsilon: float = 1.0,
    material_threshold: float = 0.5,
    early_through: int = 8,
    minimum_confidence: str = "C",
    minimum_gain: float = 0.0,
) -> RankUtilityPolicy:
    return RankUtilityPolicy(
        points_epsilon=points_epsilon,
        material_points_threshold=material_threshold,
        early_season_through_gameweek=early_through,
        minimum_rank_confidence=minimum_confidence,
        minimum_target_probability_gain=minimum_gain,
    )
