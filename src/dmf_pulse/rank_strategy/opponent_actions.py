"""Cutoff-safe probabilistic opponent action modelling for RANK-015."""

from __future__ import annotations

from itertools import product
from math import exp, log, prod

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.prices.models import ConfidenceGrade
from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.opponent_models import (
    JointOpponentActionDistribution,
    JointOpponentActionScenario,
    OpponentActionCandidate,
    OpponentActionDistribution,
    OpponentActionProbability,
    OpponentBehaviourProfile,
    OpponentChipAction,
    OpponentObservedState,
)

_CONFIDENCE_ORDER = {
    ConfidenceGrade.A: 0,
    ConfidenceGrade.B: 1,
    ConfidenceGrade.C: 2,
    ConfidenceGrade.D: 3,
    ConfidenceGrade.E: 4,
}


def _worst_confidence(*values: ConfidenceGrade) -> ConfidenceGrade:
    return max(values, key=_CONFIDENCE_ORDER.__getitem__)


def _utility(
    candidate: OpponentActionCandidate,
    profile: OpponentBehaviourProfile,
) -> float:
    features = candidate.features
    value = (
        profile.points_coefficient * features.perceived_expected_points
        + profile.popularity_coefficient * features.popularity_signal
        + profile.recent_form_coefficient * features.recent_form_signal
        + profile.price_pressure_coefficient * features.price_pressure_signal
        + profile.relative_risk_coefficient * features.relative_risk_signal
        - profile.hit_point_penalty * candidate.manager_plan.transfer_hit_points
        + profile.chip_biases.get(candidate.chip_action, 0.0)
    )
    if candidate.transfer_count == 0:
        value += profile.no_transfer_bias
    return value


def _validate_model_inputs(
    state: OpponentObservedState,
    candidates: tuple[OpponentActionCandidate, ...],
    profile: OpponentBehaviourProfile,
) -> None:
    if not state.rights_status.permitted:
        raise RankStrategyError(
            "RANK_OPPONENT_RIGHTS_INVALID",
            "opponent action modelling requires synthetic, repository-approved or authorised data",
            manager_id=state.manager_id,
            rights_status=state.rights_status.value,
        )
    if profile.manager_id != state.manager_id:
        raise RankStrategyError(
            "RANK_OPPONENT_PROFILE_MANAGER_MISMATCH",
            "opponent behaviour profile manager does not match observed state",
        )
    if profile.information_cutoff != state.information_cutoff:
        raise RankStrategyError(
            "RANK_OPPONENT_PROFILE_CUTOFF_MISMATCH",
            "opponent profile and observed state must use the same information cutoff",
        )
    if len(candidates) < 2:
        raise RankStrategyError(
            "RANK_OPPONENT_ACTION_SET_TOO_SMALL",
            "probabilistic opponent modelling requires at least two plausible actions",
        )
    action_ids = tuple(item.action_id for item in candidates)
    if len(action_ids) != len(set(action_ids)):
        raise RankStrategyError(
            "RANK_OPPONENT_ACTION_DUPLICATE",
            "opponent action IDs must be unique",
        )
    if profile.probability_floor * len(candidates) >= 1.0:
        raise RankStrategyError(
            "RANK_OPPONENT_PROBABILITY_FLOOR_INVALID",
            "probability floor leaves no mass for random utility",
            action_count=len(candidates),
            probability_floor=profile.probability_floor,
        )
    if not any(item.transfer_count == 0 for item in candidates):
        raise RankStrategyError(
            "RANK_OPPONENT_NO_TRANSFER_MISSING",
            "baseline opponent action set must include at least one no-transfer action",
        )
    if not any(item.transfer_count > 0 for item in candidates):
        raise RankStrategyError(
            "RANK_OPPONENT_TRANSFER_ACTION_MISSING",
            "baseline opponent action set must include at least one transfer action",
        )

    base_plan = state.observed_plan
    plan_ids: set[str] = set()
    plan_semantic_hashes: set[str] = set()
    for candidate in candidates:
        plan = candidate.manager_plan
        if plan.manager_id != state.manager_id:
            raise RankStrategyError(
                "RANK_OPPONENT_ACTION_MANAGER_MISMATCH",
                "opponent action plan manager does not match observed state",
                action_id=candidate.action_id,
            )
        if plan.cumulative_points != base_plan.cumulative_points:
            raise RankStrategyError(
                "RANK_OPPONENT_CUMULATIVE_POINTS_MUTATION",
                "future opponent action cannot mutate predeadline cumulative points",
                action_id=candidate.action_id,
            )
        expected_counted = base_plan.counted_transfers + candidate.counted_transfer_delta
        if plan.counted_transfers != expected_counted:
            raise RankStrategyError(
                "RANK_OPPONENT_COUNTED_TRANSFER_MISMATCH",
                "future opponent action counted-transfer state does not reconcile",
                action_id=candidate.action_id,
                expected=expected_counted,
                actual=plan.counted_transfers,
            )
        if candidate.generated_at > state.information_cutoff:
            raise RankStrategyError(
                "RANK_OPPONENT_FUTURE_ACTION_LEAKAGE",
                "opponent action candidate was generated after the information cutoff",
                action_id=candidate.action_id,
            )
        if candidate.features.observed_at > state.information_cutoff:
            raise RankStrategyError(
                "RANK_OPPONENT_FUTURE_FEATURE_LEAKAGE",
                "opponent action feature was unavailable at the information cutoff",
                action_id=candidate.action_id,
            )
        if candidate.features.observed_at > candidate.generated_at:
            raise RankStrategyError(
                "RANK_OPPONENT_FEATURE_GENERATION_ORDER_INVALID",
                "opponent action features cannot postdate candidate generation",
                action_id=candidate.action_id,
            )
        if candidate.features.contains_postdeadline_action_label:
            raise RankStrategyError(
                "RANK_OPPONENT_POSTDEADLINE_LABEL_LEAKAGE",
                "postdeadline rival action labels cannot enter a predeadline model",
                action_id=candidate.action_id,
            )
        if candidate.transfer_count == 0 and plan.permanent_squad != base_plan.permanent_squad:
            raise RankStrategyError(
                "RANK_OPPONENT_NO_TRANSFER_SQUAD_MUTATION",
                "no-transfer action cannot change the permanent squad",
                action_id=candidate.action_id,
            )
        if (
            candidate.transfer_count > 0
            and candidate.chip_action is not OpponentChipAction.FREE_HIT
            and plan.permanent_squad == base_plan.permanent_squad
        ):
            raise RankStrategyError(
                "RANK_OPPONENT_TRANSFER_SQUAD_UNCHANGED",
                "a transfer action must change the permanent squad outside Free Hit",
                action_id=candidate.action_id,
            )
        if (
            candidate.chip_action is OpponentChipAction.FREE_HIT
            and plan.permanent_squad != base_plan.permanent_squad
        ):
            raise RankStrategyError(
                "RANK_OPPONENT_FREE_HIT_PERMANENT_MUTATION",
                "Free Hit action cannot mutate the permanent squad",
                action_id=candidate.action_id,
            )

        plan_semantic_hash = semantic_sha256(plan.model_dump(mode="json", exclude={"plan_id"}))
        if plan.plan_id in plan_ids or plan_semantic_hash in plan_semantic_hashes:
            raise RankStrategyError(
                "RANK_OPPONENT_PLAN_DUPLICATE",
                "opponent action plans must be semantically distinct",
                action_id=candidate.action_id,
                plan_id=plan.plan_id,
            )
        plan_ids.add(plan.plan_id)
        plan_semantic_hashes.add(plan_semantic_hash)


def model_opponent_actions(
    state: OpponentObservedState,
    candidates: tuple[OpponentActionCandidate, ...],
    profile: OpponentBehaviourProfile,
) -> OpponentActionDistribution:
    """Return a transparent non-degenerate softmax distribution over rival plans."""

    _validate_model_inputs(state, candidates, profile)
    ordered = tuple(sorted(candidates, key=lambda item: item.action_id))
    utilities = tuple(_utility(item, profile) for item in ordered)
    scaled = tuple(value / profile.random_utility_temperature for value in utilities)
    maximum = max(scaled)
    exponentials = tuple(exp(value - maximum) for value in scaled)
    denominator = sum(exponentials)
    remaining = 1.0 - profile.probability_floor * len(ordered)
    probabilities = tuple(
        profile.probability_floor + remaining * value / denominator for value in exponentials
    )
    actions = tuple(
        OpponentActionProbability(
            action_id=candidate.action_id,
            manager_plan=candidate.manager_plan,
            transfer_count=candidate.transfer_count,
            counted_transfer_delta=candidate.counted_transfer_delta,
            chip_action=candidate.chip_action,
            deterministic_utility=utility,
            probability=probability,
            feature_confidence=candidate.features.confidence,
        )
        for candidate, utility, probability in zip(ordered, utilities, probabilities, strict=True)
    )
    entropy = -sum(item.probability * log(item.probability) for item in actions)
    normalised_entropy = entropy / log(len(actions))
    confidence = _worst_confidence(
        profile.confidence,
        *(item.features.confidence for item in ordered),
    )
    value = OpponentActionDistribution(
        manager_id=state.manager_id,
        state_id=state.state_id,
        profile_id=profile.profile_id,
        information_cutoff=state.information_cutoff,
        deadline=state.deadline,
        actions=actions,
        no_transfer_probability=sum(
            item.probability for item in actions if item.transfer_count == 0
        ),
        expected_transfer_count=sum(item.probability * item.transfer_count for item in actions),
        expected_hit_points=sum(
            item.probability * item.manager_plan.transfer_hit_points for item in actions
        ),
        entropy=entropy,
        normalised_entropy=normalised_entropy,
        confidence=confidence,
        distribution_hash="0" * 64,
    )
    payload = value.model_dump(mode="json", exclude={"distribution_hash"})
    return value.model_copy(update={"distribution_hash": semantic_sha256(payload)})


def combine_opponent_action_distributions(
    distributions: tuple[OpponentActionDistribution, ...],
    *,
    max_joint_scenarios: int = 10_000,
) -> JointOpponentActionDistribution:
    """Form the explicit baseline conditional-independence joint action model."""

    if not distributions:
        raise RankStrategyError(
            "RANK_OPPONENT_DISTRIBUTIONS_EMPTY",
            "at least one opponent distribution is required",
        )
    if max_joint_scenarios < 1:
        raise RankStrategyError(
            "RANK_OPPONENT_JOINT_LIMIT_INVALID",
            "joint opponent scenario limit must be positive",
        )
    ordered = tuple(sorted(distributions, key=lambda item: item.manager_id))
    manager_ids = tuple(item.manager_id for item in ordered)
    if len(manager_ids) != len(set(manager_ids)):
        raise RankStrategyError(
            "RANK_OPPONENT_DISTRIBUTION_DUPLICATE_MANAGER",
            "joint opponent model cannot contain duplicate managers",
        )
    cutoff = ordered[0].information_cutoff
    deadline = ordered[0].deadline
    if any(item.information_cutoff != cutoff or item.deadline != deadline for item in ordered[1:]):
        raise RankStrategyError(
            "RANK_OPPONENT_JOINT_TEMPORAL_MISMATCH",
            "joint opponent distributions must share cutoff and deadline",
        )
    scenario_count = 1
    for item in ordered:
        scenario_count *= len(item.actions)
    if scenario_count > max_joint_scenarios:
        raise RankStrategyError(
            "RANK_OPPONENT_JOINT_LIMIT_EXCEEDED",
            "exact joint opponent action enumeration exceeds configured limit",
            scenario_count=scenario_count,
            max_joint_scenarios=max_joint_scenarios,
        )
    scenarios: list[JointOpponentActionScenario] = []
    for combination in product(*(item.actions for item in ordered)):
        action_ids = {
            manager_id: action.action_id
            for manager_id, action in zip(manager_ids, combination, strict=True)
        }
        plans = {
            manager_id: action.manager_plan
            for manager_id, action in zip(manager_ids, combination, strict=True)
        }
        semantic_identity = semantic_sha256(action_ids)
        scenarios.append(
            JointOpponentActionScenario(
                scenario_id=f"joint-{semantic_identity[:24]}",
                probability=float(prod(action.probability for action in combination)),
                action_ids=action_ids,
                manager_plans=plans,
            )
        )
    scenarios.sort(key=lambda item: item.scenario_id)
    value = JointOpponentActionDistribution(
        manager_ids=manager_ids,
        information_cutoff=cutoff,
        deadline=deadline,
        source_distribution_hashes={item.manager_id: item.distribution_hash for item in ordered},
        scenarios=tuple(scenarios),
        joint_hash="0" * 64,
    )
    payload = value.model_dump(mode="json", exclude={"joint_hash"})
    return value.model_copy(update={"joint_hash": semantic_sha256(payload)})
