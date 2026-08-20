from __future__ import annotations

import pytest

from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.service import (
    evaluate_opponent_actions,
    evaluate_rank_plans,
    seal_rank_service_request,
    validate_installed_rank_capability,
    validate_rank_service_requests,
)
from dmf_pulse.rank_strategy.service_models import RankServiceRequest
from dmf_pulse.rank_strategy.utility_models import (
    RankActivationStatus,
    RankObjectiveMode,
    RankTargetDefinition,
)
from tests.support.rank_service_fixtures import service_request


def test_service_preserves_points_and_rank_optimal_plans_and_selects_rank() -> None:
    request = service_request()

    result = evaluate_rank_plans(request)

    assert result.activation_status is RankActivationStatus.ACTIVE
    assert result.points_optimal_plan.plan_id == "points-plan"
    assert result.rank_optimal_plan.plan_id == "rank-plan"
    assert result.selected_plan.plan_id == "rank-plan"
    assert result.expected_points_difference == pytest.approx(-0.6)
    assert result.target_probability_difference == pytest.approx(0.4)
    assert result.raw_projection_hash == request.lineage.raw_projection_hash
    assert result.scenario_set_hash == request.lineage.scenario_set_hash
    assert result.projection_invariance.unchanged is True
    assert result.projection_invariance.before_score_hashes == (
        result.projection_invariance.after_score_hashes
    )
    assert result.fail_closed_reasons == ()


def test_service_keeps_stage12_and_stage14_plan_bindings() -> None:
    result = evaluate_rank_plans(service_request())

    assert result.points_optimal_plan.source_stage.value == "STAGE_12"
    assert result.points_optimal_plan.source_plan_hash == "1" * 64
    assert result.rank_optimal_plan.source_stage.value == "STAGE_14"
    assert result.rank_optimal_plan.source_plan_hash == "3" * 64
    assert result.points_optimal_plan.binding_hash != "0" * 64
    assert result.rank_optimal_plan.binding_hash != "0" * 64


@pytest.mark.parametrize(
    ("service_input", "reason"),
    (
        (service_request(rights_valid=False), "RANK_SAMPLE_RIGHTS_INVALID"),
        (service_request(cohort_valid=False), "RANK_COHORT_INVALID"),
        (service_request(opponent_valid=False), "RANK_OPPONENT_DATA_INVALID"),
        (service_request(rules_verified=False), "RANK_RULES_UNVERIFIED"),
        (service_request(explicit_target=False), "RANK_TARGET_NOT_USER_SELECTED"),
        (service_request(include_cohort=False), "RANK_COHORT_INVALID"),
        (service_request(include_opponent=False), "RANK_OPPONENT_DATA_INVALID"),
    ),
)
def test_required_gate_failure_falls_back_to_pure_points(
    service_input: RankServiceRequest,
    reason: str,
) -> None:
    result = evaluate_rank_plans(service_input)

    assert result.activation_status is not RankActivationStatus.ACTIVE
    assert result.effective_objective is RankObjectiveMode.PURE_POINTS
    assert result.selected_plan.plan_id == "points-plan"
    assert reason in result.fail_closed_reasons
    assert result.diagnostic_output_available is True
    assert result.rank_decision is not None


def test_rights_lineage_cannot_be_overridden_by_true_context_boolean() -> None:
    request = service_request(rights_status="INVALID", rights_valid=True)

    result = evaluate_rank_plans(request)

    assert result.selected_plan.plan_id == "points-plan"
    assert "RANK_SAMPLE_RIGHTS_INVALID" in result.fail_closed_reasons


def test_low_confidence_rank_plan_is_diagnostic_only() -> None:
    result = evaluate_rank_plans(service_request(rank_plan_confidence="E", minimum_confidence="C"))

    assert result.activation_status is RankActivationStatus.DIAGNOSTIC_ONLY
    assert result.selected_plan.plan_id == "points-plan"
    assert result.rank_optimal_plan.plan_id == "rank-plan"
    assert "RANK_PLAN_CONFIDENCE_TOO_LOW" in result.fail_closed_reasons
    assert "RANK_CONFIDENCE_TOO_LOW" in result.fail_closed_reasons


def test_early_season_material_points_sacrifice_is_blocked() -> None:
    result = evaluate_rank_plans(service_request(gameweek=4, rank_expected_points=99.4))

    assert result.activation_status is RankActivationStatus.DIAGNOSTIC_ONLY
    assert result.selected_plan.plan_id == "points-plan"
    assert "EARLY_SEASON_MATERIAL_POINTS_GATE" in result.fail_closed_reasons


def test_points_floor_excludes_ineligible_rank_candidate_without_false_gate_failure() -> None:
    result = evaluate_rank_plans(service_request(points_epsilon=0.25, rank_expected_points=99.4))

    assert result.selected_plan.plan_id == "points-plan"
    assert result.rank_optimal_plan.plan_id == "points-plan"
    assert result.activation_status is RankActivationStatus.ACTIVE
    assert result.fail_closed_reasons == ()
    excluded = next(
        item for item in result.rank_decision.evaluations if item.plan_id == "rank-plan"
    )
    assert excluded.exclusion_reasons == ("POINTS_FLOOR_VIOLATION",)


def test_projection_lineage_mismatch_disables_rank_diagnostics() -> None:
    result = evaluate_rank_plans(service_request(rank_raw_hash="9" * 64))

    assert result.activation_status is RankActivationStatus.DIAGNOSTIC_ONLY
    assert result.selected_plan.plan_id == "points-plan"
    assert result.rank_optimal_plan.plan_id == "points-plan"
    assert result.rank_decision is None
    assert result.diagnostic_output_available is False
    assert result.projection_invariance.unchanged is True
    assert result.projection_invariance.common_raw_projection_lineage is False
    assert "RANK_RAW_PROJECTION_LINEAGE_MISMATCH" in result.fail_closed_reasons


def test_scenario_lineage_mismatch_disables_rank_diagnostics() -> None:
    result = evaluate_rank_plans(service_request(rank_scenario_hash="8" * 64))

    assert result.selected_plan.plan_id == "points-plan"
    assert result.rank_decision is None
    assert result.projection_invariance.common_scenario_lineage is False
    assert "RANK_SCENARIO_LINEAGE_MISMATCH" in result.fail_closed_reasons


def test_pure_points_does_not_require_rank_models() -> None:
    result = evaluate_rank_plans(
        service_request(
            objective=RankObjectiveMode.PURE_POINTS,
            rights_valid=False,
            cohort_valid=False,
            opponent_valid=False,
            include_cohort=False,
            include_opponent=False,
            explicit_target=False,
        )
    )

    assert result.activation_status is RankActivationStatus.ACTIVE
    assert result.effective_objective is RankObjectiveMode.PURE_POINTS
    assert result.selected_plan.plan_id == "points-plan"
    assert result.fail_closed_reasons == ()


def test_service_requires_sealed_request() -> None:
    request = service_request()
    unsealed = RankServiceRequest.model_validate(
        request.model_copy(update={"service_request_hash": "0" * 64}).model_dump(mode="python")
    )

    with pytest.raises(RankStrategyError) as exc_info:
        evaluate_rank_plans(unsealed)

    assert exc_info.value.code == "RANK_SERVICE_REQUEST_UNSEALED"


def test_tampered_request_hash_fails_before_numerical_use() -> None:
    request = service_request()
    tampered = request.model_copy(
        update={"policy": request.policy.model_copy(update={"points_epsilon": 0.2})}
    )

    with pytest.raises(RankStrategyError) as exc_info:
        evaluate_rank_plans(tampered)

    assert exc_info.value.code == "RANK_SERVICE_REQUEST_INVALID"


def test_sealing_is_deterministic_and_batch_validation_returns_result_hashes() -> None:
    request = service_request()

    assert seal_rank_service_request(request) == request
    expected = evaluate_rank_plans(request).result_hash
    assert validate_rank_service_requests((request, request)) == (expected, expected)


def test_installed_capability_is_explicitly_fail_closed() -> None:
    report = validate_installed_rank_capability()

    assert report.status == "IMPLEMENTED_PENDING_INDEPENDENT_REVIEW"
    assert report.fail_closed_to_pure_points is True
    assert report.raw_projection_mutation_permitted is False
    assert report.mass_manager_scraping_permitted is False
    assert report.definitive_overall_win_claim_permitted is False
    assert report.cli_commands == (
        "cohort",
        "compare",
        "eo",
        "evaluate",
        "mini-league",
        "opponents",
        "validate",
    )


def _reseal_with_target(
    request: RankServiceRequest,
    *,
    objective: RankObjectiveMode,
    target: RankTargetDefinition | None,
) -> RankServiceRequest:
    return seal_rank_service_request(
        request.model_copy(
            update={
                "objective": objective,
                "target": target,
                "service_request_hash": "0" * 64,
            }
        )
    )


@pytest.mark.parametrize(
    ("objective", "target", "reason"),
    (
        (
            RankObjectiveMode.MINI_LEAGUE_WIN,
            RankTargetDefinition(target_rank=2),
            "TARGET_DEFINITION_INVALID",
        ),
        (RankObjectiveMode.TARGET_RANK, None, "TARGET_RANK_UNDEFINED"),
        (RankObjectiveMode.RANK_BAND, None, "RANK_BAND_UNDEFINED"),
        (
            RankObjectiveMode.PRIZE_BAND,
            RankTargetDefinition(band_best_rank=1, band_worst_rank=2),
            "PRIZE_BAND_UNDEFINED",
        ),
        (
            RankObjectiveMode.RANK_BAND,
            RankTargetDefinition(
                band_best_rank=1,
                band_worst_rank=2,
                prize_band_id="cash-zone",
            ),
            "TARGET_DEFINITION_INVALID",
        ),
    ),
)
def test_objective_specific_target_contracts_fail_closed(
    objective: RankObjectiveMode,
    target: RankTargetDefinition | None,
    reason: str,
) -> None:
    request = _reseal_with_target(service_request(), objective=objective, target=target)

    result = evaluate_rank_plans(request)

    assert result.activation_status is RankActivationStatus.DIAGNOSTIC_ONLY
    assert result.selected_plan.plan_id == result.points_optimal_plan.plan_id
    assert reason in result.fail_closed_reasons


def test_inactive_target_rules_and_measured_leverage_paths_are_explicit() -> None:
    inactive = evaluate_rank_plans(service_request(target_rules_active=False))
    assert "TARGET_RULES_INACTIVE" in inactive.fail_closed_reasons

    leverage = evaluate_rank_plans(service_request(objective=RankObjectiveMode.MEASURED_LEVERAGE))
    assert leverage.activation_status is RankActivationStatus.ACTIVE
    assert leverage.fail_closed_reasons == ()


def test_opponent_service_forms_joint_distribution_when_additional_rivals_exist() -> None:
    from dmf_pulse.rank_strategy.opponent_models import JointOpponentActionDistribution
    from tests.support.opponent_action_fixtures import (
        baseline_candidates,
        behaviour_profile,
        observed_state,
    )

    second = evaluate_opponent_actions(
        observed_state("rival-b"),
        baseline_candidates("rival-b"),
        behaviour_profile("rival-b"),
    )
    assert not isinstance(second, JointOpponentActionDistribution)

    joint = evaluate_opponent_actions(
        observed_state("rival-a"),
        baseline_candidates("rival-a"),
        behaviour_profile("rival-a"),
        additional_distributions=(second,),
        max_joint_scenarios=100,
    )

    assert isinstance(joint, JointOpponentActionDistribution)
    assert joint.manager_ids == ("rival-a", "rival-b")
