from __future__ import annotations

from dmf_pulse.optimisation.multi_gameweek_models import HorizonTransferCountFrontier
from dmf_pulse.private_v1.rolling import PrivateV1RollingRecommendationService
from dmf_pulse.private_v1.rolling_models import PrivateV1RollingDecision

from .e2e_test_support import build_execution_input, build_rolling_execution_input


def test_basic_three_gameweek_private_policy_is_legal_structured_and_replayable(
    repository_root, tmp_path
) -> None:
    execution = build_rolling_execution_input(repository_root, tmp_path / "rolling")

    result = PrivateV1RollingRecommendationService().run(execution)

    decision = result.decision
    assert decision.horizon_gameweeks == (1, 2, 3)
    assert decision.do_now.actionability == "DO_NOW"
    assert tuple(item.actionability for item in decision.future_plan) == (
        "PROVISIONAL_REOPTIMISE_AT_DEADLINE",
        "PROVISIONAL_REOPTIMISE_AT_DEADLINE",
    )
    assert tuple(item.gameweek for item in decision.by_gameweek) == (1, 2, 3)
    assert all(item.fixture_coverage.blocked_fixtures == 0 for item in decision.by_gameweek)
    assert decision.by_gameweek[1].fixture_coverage.score_prior_only_fixtures == 3
    assert decision.by_gameweek[2].fixture_coverage.score_prior_only_fixtures == 3
    assert decision.terminal_value_mode == "THREE_GAMEWEEK_ZERO_TERMINAL_VALUE_AFTER_HORIZON"
    assert decision.future_price_mode == "FUTURE_PRICE_CHANGES_NOT_MODELLED_IN_PRIVATE_3GW_V1"
    assert decision.transfer_count_scope_source == (
        "CURRENT_FT_COMPILED_RULES_AND_TICKET_BOUNDED_SEARCH_POLICY"
    )
    assert decision.maximum_transfers_per_deadline == (
        execution.current_execution.candidate_action_policy.maximum_transfers
    )
    assert isinstance(result.optimiser_result.transfer_count_frontier, HorizonTransferCountFrontier)
    assert result.optimiser_result.recommended_plan is not None
    assert result.optimiser_result.recommended_plan.terminal_value.total == 0
    assert all(
        not node.revealed_information for node in result.optimiser_request.scenario_tree.nodes
    )
    assert tuple(node.gameweek for node in result.optimiser_request.scenario_tree.nodes) == (
        1,
        2,
        3,
    )
    assert set(decision.lineage.stage7_input_sha256_by_gameweek) == {1, 2, 3}
    assert set(decision.lineage.stage8_distribution_sha256_by_gameweek) == {1, 2, 3}
    assert set(decision.lineage.player_prior_binding_sha256_by_gameweek) == {1, 2, 3}
    assert PrivateV1RollingDecision.model_validate_json(decision.model_dump_json()) == decision
    assert "DO NOW" in result.report
    assert result.report.count("PROVISIONAL - REOPTIMISE AT THAT DEADLINE") == 2
    assert "Squad after:" in result.report
    assert "XI:" in result.report
    assert "Bench:" in result.report
    assert "immediate uplift=" in result.report
    assert "gain p10/median/p90=" in result.report
    assert "future=[GW2" in result.report
    assert "One-GW moves:" in result.report
    assert "Three-GW moves:" in result.report
    assert "FT entering next-GW difference:" in result.report


def test_three_gameweek_nodes_hold_current_prices_constant_and_preserve_squad_continuity(
    repository_root, tmp_path
) -> None:
    execution = build_rolling_execution_input(repository_root, tmp_path / "rolling")

    result = PrivateV1RollingRecommendationService().run(execution)

    plan = result.optimiser_result.recommended_plan
    assert plan is not None
    decisions = (plan.current_action, *plan.future_policy)
    assert all(decision.state_after.squad_ids == decision.squad_after for decision in decisions)
    assert tuple(item.squad_after for item in result.decision.by_gameweek) == tuple(
        squad for _node, squad in plan.squad_path
    )
    node_prices = tuple(
        {player_id: state.current_price_tenths for player_id, state in node.prices.items()}
        for node in result.optimiser_request.scenario_tree.nodes
    )
    assert node_prices[1:] == (node_prices[0], node_prices[0])
    assert "FUTURE_PRICE_CHANGES_NOT_MODELLED_IN_PRIVATE_3GW_V1" in result.decision.warnings


def test_rolling_instrumentation_names_every_required_expensive_stage(
    repository_root, tmp_path
) -> None:
    execution = build_rolling_execution_input(repository_root, tmp_path / "rolling")

    result = PrivateV1RollingRecommendationService().run(execution)

    stages = {item.stage for item in result.stage_timings}
    assert {
        "stage8_9_gameweek_1",
        "stage8_9_gameweek_2",
        "stage8_9_gameweek_3",
        "joint_scenario_assembly_gameweek_1",
        "joint_scenario_assembly_gameweek_2",
        "joint_scenario_assembly_gameweek_3",
        "action_generation",
        "tactical_batch_evaluation",
        "stage11_policy_solving",
        "report_and_comparator",
    } <= stages
    assert all(item.elapsed_ms >= 0 for item in result.stage_timings)


def test_one_gameweek_execution_contract_remains_exactly_unchanged(
    repository_root, tmp_path
) -> None:
    first = build_execution_input(repository_root, tmp_path / "one")
    second = build_execution_input(repository_root, tmp_path / "two")

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert first.semantic_sha256 == second.semantic_sha256
