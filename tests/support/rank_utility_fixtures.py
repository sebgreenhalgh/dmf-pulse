"""Synthetic Stage-15 rank-utility fixtures."""

from __future__ import annotations

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.rank_strategy.models import RankDistribution, RankMass
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
    plan_id: str,
    pmf: dict[int, float],
    *,
    confidence: str = "A",
    raw_hash: str = RAW_HASH,
    scenario_hash: str = SCENARIO_HASH,
) -> RankDistribution:
    masses = tuple(
        RankMass(rank=rank, probability=probability)
        for rank, probability in sorted(pmf.items())
    )
    expected_rank = sum(item.rank * item.probability for item in masses)
    ordered: list[int] = []
    for item in masses:
        ordered.extend([item.rank] * max(1, round(item.probability * 100)))
    median_rank = ordered[len(ordered) // 2]
    percentiles = {
        "p10": masses[0].rank,
        "p25": masses[0].rank,
        "p50": median_rank,
        "p75": masses[-1].rank,
        "p90": masses[-1].rank,
    }
    return RankDistribution(
        target_manager_id="sebastian",
        population_size=max(item.rank for item in masses),
        scenario_set_hash=scenario_hash,
        raw_projection_hash=raw_hash,
        tie_policy_id="verified-classic",
        target_rank=None,
        rank_pmf=masses,
        expected_rank=expected_rank,
        median_rank=median_rank,
        rank_percentiles=percentiles,
        probability_target_rank=None,
        mini_league_win_probability=sum(
            (item.probability for item in masses if item.rank == 1),
            0.0,
        ),
        outcomes=(),
        confidence=confidence,
        distribution_hash=semantic_sha256({"plan_id": plan_id, "pmf": pmf}),
    )


def candidate(
    plan_id: str,
    expected_points: float,
    pmf: dict[int, float] | None = None,
    *,
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
