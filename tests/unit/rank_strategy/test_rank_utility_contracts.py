from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmf_pulse.rank_strategy.rank_utility import evaluate_rank_strategy
from dmf_pulse.rank_strategy.utility_models import (
    ProjectionInvarianceEvidence,
    RankActivationContext,
    RankObjectiveMode,
    RankPlanCandidate,
    RankStrategyDecision,
    RankTargetDefinition,
)
from tests.support.rank_utility_fixtures import candidate, context, policy

pytestmark = pytest.mark.unit


def test_target_definition_rejects_partial_or_inverted_band() -> None:
    with pytest.raises(ValidationError):
        RankTargetDefinition(band_best_rank=1)
    with pytest.raises(ValidationError):
        RankTargetDefinition(band_best_rank=10, band_worst_rank=2)
    with pytest.raises(ValidationError):
        RankTargetDefinition(target_rank=10, band_best_rank=1, band_worst_rank=5)
    with pytest.raises(ValidationError):
        RankTargetDefinition(prize_band_id="winner")


def test_activation_context_rejects_gameweek_after_season() -> None:
    payload = context().model_dump(mode="python")
    payload["gameweek"] = 39
    payload["season_gameweeks"] = 38
    with pytest.raises(ValidationError):
        RankActivationContext.model_validate(payload)


def test_candidate_rejects_points_weights_hash_and_rank_surface_mismatch() -> None:
    base = candidate("base", 60.0, {1: 0.5, 2: 0.5})
    mutations = (
        lambda payload: payload.update(expected_points=61.0),
        lambda payload: payload.update(scenario_score_hash="0" * 64),
        lambda payload: payload.update(scenario_weights={"s1|d1": 0.2, "s2|d2": 0.2}),
        lambda payload: payload.update(scenario_points={"s2|d2": 62.0, "s1|d1": 58.0}),
        lambda payload: payload.update(
            rank_distribution={**payload["rank_distribution"], "raw_projection_hash": "c" * 64}
        ),
        lambda payload: payload.update(
            rank_distribution={**payload["rank_distribution"], "scenario_set_hash": "c" * 64}
        ),
    )
    for mutation in mutations:
        payload = base.model_dump(mode="python")
        mutation(payload)
        with pytest.raises(ValidationError):
            RankPlanCandidate.model_validate(payload)


def test_projection_invariance_contract_rejects_changed_scenario_scores() -> None:
    with pytest.raises(ValidationError):
        ProjectionInvarianceEvidence(
            identical=True,
            raw_projection_hash="a" * 64,
            scenario_set_hash="b" * 64,
            before_score_hashes={"a": "c" * 64},
            after_score_hashes={"a": "d" * 64},
            code="RAW_PROJECTIONS_AND_SCENARIO_SCORES_IDENTICAL",
        )
    with pytest.raises(ValidationError):
        ProjectionInvarianceEvidence(
            identical=False,
            raw_projection_hash="a" * 64,
            scenario_set_hash="b" * 64,
            before_score_hashes={"a": "c" * 64},
            after_score_hashes={"a": "c" * 64},
            code="RAW_PROJECTIONS_AND_SCENARIO_SCORES_IDENTICAL",
        )


def test_decision_contract_rejects_plan_and_delta_mismatch() -> None:
    result = evaluate_rank_strategy(
        request_id="decision-contract",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=(
            candidate("points", 60.0, {1: 0.2, 2: 0.8}),
            candidate("target", 59.5, {1: 0.8, 2: 0.2}),
        ),
        context=context(),
        policy=policy(material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )
    mutations = (
        lambda payload: payload.update(points_optimal_plan_id="other"),
        lambda payload: payload.update(rank_optimal_plan_id="other"),
        lambda payload: payload.update(selected_plan_id="other"),
        lambda payload: payload.update(expected_points_difference=99.0),
        lambda payload: payload.update(target_probability_difference=99.0),
        lambda payload: payload.update(evaluations=tuple(reversed(payload["evaluations"]))),
        lambda payload: payload.update(effective_objective=RankObjectiveMode.PURE_POINTS),
        lambda payload: payload.update(decision_hash="0" * 64),
    )
    for mutation in mutations:
        payload = result.model_dump(mode="python")
        mutation(payload)
        with pytest.raises(ValidationError):
            RankStrategyDecision.model_validate(payload)


def test_decision_hash_and_input_candidates_are_deterministic_and_immutable() -> None:
    candidates = (
        candidate("points", 60.0, {1: 0.2, 2: 0.8}),
        candidate("target", 59.5, {1: 0.8, 2: 0.2}),
    )
    before = tuple(item.model_dump(mode="json") for item in candidates)
    first = evaluate_rank_strategy(
        request_id="deterministic",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=candidates,
        context=context(),
        policy=policy(material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )
    second = evaluate_rank_strategy(
        request_id="deterministic",
        objective=RankObjectiveMode.TARGET_RANK,
        candidates=tuple(reversed(candidates)),
        context=context(),
        policy=policy(material_threshold=1.0),
        target=RankTargetDefinition(target_rank=1),
    )
    assert first == second
    assert first.decision_hash == second.decision_hash
    assert tuple(item.model_dump(mode="json") for item in candidates) == before
    assert first.projection_invariance.identical is True
