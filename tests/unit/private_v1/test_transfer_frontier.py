"""Private 001M transfer-frontier structure, comparison, and report contracts."""

from __future__ import annotations

import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.optimisation.models import OneGameweekPlan
from dmf_pulse.optimisation.multi_gameweek_solver import (
    make_transfer_action,
    resolve_free_transfer_arc,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import PrivateTransferFrontierDelta, PrivateV1Decision
from dmf_pulse.private_v1.reporting import _delta, render_transfer_frontier
from dmf_pulse.private_v1.service import (
    PrivateV1RecommendationService,
    _frontier_comparison,
    _frontier_relationship,
    _paired_comparison,
    _private_free_transfer_state,
    _quantile,
)
from tests.support.multi_gameweek_factories import player_catalog, transfer_rules

from .e2e_test_support import build_execution_input

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("free_transfers", "transfer_count", "used", "remaining", "next_deadline", "hit"),
    (
        (2, 0, 0, 2, 3, 0),
        (2, 1, 1, 1, 2, 0),
        (2, 2, 2, 0, 1, 0),
        (0, 1, 0, 0, 1, 4),
    ),
)
def test_frontier_ft_disclosure_uses_the_compiled_transition_arc(
    free_transfers: int,
    transfer_count: int,
    used: int,
    remaining: int,
    next_deadline: int,
    hit: int,
) -> None:
    arc = resolve_free_transfer_arc(
        transfer_rules(),
        event="NORMAL",
        ft_before=free_transfers,
        transfer_count=transfer_count,
    )

    state = _private_free_transfer_state(arc, manager_state_before=free_transfers)

    assert state.used_by_action == used
    assert state.remaining_immediately_after_action == remaining
    assert state.next_decision_deadline == next_deadline
    assert state.paid_transfers == (transfer_count - used)
    assert state.hit_points == hit


def test_frontier_delta_distinguishes_nested_and_non_nested_plans() -> None:
    catalog = player_catalog(include_second_mid=True)
    one = make_transfer_action(transfers_out=("p07",), transfers_in=("p15",), event="NORMAL")
    nested_two = make_transfer_action(
        transfers_out=("p07", "p08"),
        transfers_in=("p15", "p19"),
        event="NORMAL",
    )
    non_nested_two = make_transfer_action(
        transfers_out=("p08", "p09"),
        transfers_in=("p15", "p19"),
        event="NORMAL",
    )

    nested, incremental = _frontier_relationship(one, nested_two, candidate_pool=catalog)
    non_nested, unsupported = _frontier_relationship(one, non_nested_two, candidate_pool=catalog)

    assert nested == "STRICT_EXTENSION"
    assert tuple((item.player_out, item.player_in) for item in incremental) == (("p08", "p19"),)
    assert non_nested == "NON_NESTED"
    assert unsupported == ()

    rendered = _delta(
        PrivateTransferFrontierDelta(
            lower_transfer_count=1,
            higher_transfer_count=2,
            immediate_expected_points_delta=Decimal("1.25"),
            plan_relationship="NON_NESTED",
        ),
        label=str,
    )
    assert "FRONTIER DELTA VS BEST 1-TRANSFER PLAN: +1.25" in rendered
    assert "PLANS ARE NON-NESTED" in rendered
    assert "value of the second transfer" not in rendered.casefold()


def test_private_frontier_is_exact_paired_hash_bound_and_recommendation_compatible(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    execution = build_execution_input(repository_root, tmp_path / "frontier")
    run = PrivateV1RecommendationService().run(execution)
    decision = run.decision
    frontier = decision.transfer_frontier

    assert frontier is not None
    assert tuple(item.transfer_count for item in frontier.points) == (0, 1)
    assert frontier.objective == "ONE_GAMEWEEK_ZERO_TERMINAL_VALUE_OBJECTIVE"
    assert frontier.future_free_transfer_value_included is False
    assert frontier.action_space_disclosure == decision.action_space_disclosure
    assert frontier.stage9_projection_sha256 == decision.lineage.stage9_result_sha256
    assert frontier.stage9_joint_scenario_sha256 == decision.lineage.stage9_joint_matrix_sha256
    assert frontier.optimiser_request_sha256 == decision.lineage.optimiser_request_sha256
    assert frontier.optimiser_result_sha256 == decision.lineage.optimiser_result_sha256

    optimiser_frontier = run.optimiser_result.transfer_count_frontier
    assert optimiser_frontier is not None
    by_count = {item.transfer_count: item for item in optimiser_frontier.points}
    for point in frontier.points:
        evaluated = by_count[point.transfer_count]
        action = evaluated.plan.current_action
        comparison = point.comparison_vs_hold
        assert point.action_id == action.action.action_id
        assert point.action_signature == action.action.signature
        assert point.resulting_squad == action.squad_after
        assert point.tactical_plan_sha256 == action.tactical_evaluation.tactical_plan_sha256
        assert point.stage11_plan_sha256 == evaluated.plan.plan_sha256
        assert point.bank_after_tenths == action.bank_after_tenths
        assert comparison.scenario_count == len(run.gameweek_projection.scenario_set.scenarios)
        assert comparison.plan_expected_points_after_hit - comparison.baseline_expected_points == (
            comparison.expected_uplift
        )
        assert comparison.gain_p10 <= comparison.gain_median <= comparison.gain_p90
        assert sum((item.probability for item in comparison.gain_pmf), Decimal(0)) == Decimal(1)
        assert point.free_transfer_state.manager_state_before == action.free_transfers_before
        assert point.free_transfer_state.next_decision_deadline == action.free_transfers_after

    hold = frontier.points[0]
    assert hold.comparison_vs_hold.expected_uplift == Decimal(0)
    assert hold.comparison_vs_hold.gain_p10 == 0
    assert hold.comparison_vs_hold.gain_median == 0
    assert hold.comparison_vs_hold.gain_p90 == 0
    assert hold.comparison_vs_hold.probability_plan_beats_hold == Decimal(0)

    recommended_count = len(decision.transfers)
    recommended_point = next(
        item for item in frontier.points if item.transfer_count == recommended_count
    )
    assert recommended_point.transfers == decision.transfers
    assert recommended_point.resulting_squad == decision.resulting_squad
    assert recommended_point.tactics == decision.tactics
    assert recommended_point.comparison_vs_hold.plan_expected_points_after_hit == (
        decision.paired_comparison.recommended_expected_points_after_hit
    )
    assert recommended_point.comparison_vs_hold.expected_uplift == (
        decision.paired_comparison.net_expected_uplift
    )

    plan = OneGameweekPlan.model_validate(
        by_count[recommended_count].plan.current_action.tactical_evaluation.tactical_plan
    )
    baseline = OneGameweekPlan.model_validate(
        by_count[0].plan.current_action.tactical_evaluation.tactical_plan
    )
    scenario_template = run.gameweek_projection.scenario_set.scenarios[0]
    plan_score_template = plan.scenario_scores[0]
    baseline_score_template = baseline.scenario_scores[0]
    weighted = (("a", 0.1, 5), ("b", 0.4, 9), ("c", 0.4, 12), ("d", 0.1, 20))
    weighted_plan = plan.model_copy(
        update={
            "scenario_scores": tuple(
                plan_score_template.model_copy(
                    update={
                        "scenario_id": scenario_id,
                        "outcome_draw_id": f"draw-{scenario_id}",
                        "manager_points": points,
                    }
                )
                for scenario_id, _weight, points in weighted
            )
        }
    )
    weighted_baseline = baseline.model_copy(
        update={
            "scenario_scores": tuple(
                baseline_score_template.model_copy(
                    update={
                        "scenario_id": scenario_id,
                        "outcome_draw_id": f"draw-{scenario_id}",
                        "manager_points": 10,
                    }
                )
                for scenario_id, _weight, _points in weighted
            )
        }
    )
    weighted_scenarios = run.gameweek_projection.scenario_set.model_copy(
        update={
            "scenarios": tuple(
                scenario_template.model_copy(
                    update={
                        "scenario_id": scenario_id,
                        "outcome_draw_id": f"draw-{scenario_id}",
                        "weight": weight,
                    }
                )
                for scenario_id, weight, _points in weighted
            )
        }
    )
    comparison = _frontier_comparison(
        weighted_plan,
        weighted_baseline,
        scenarios=weighted_scenarios,
        hit_points=0,
    )
    assert (comparison.gain_p10, comparison.gain_median, comparison.gain_p90) == (-5, -1, 2)
    assert comparison.probability_plan_beats_hold == Decimal("0.5")
    assert comparison.expected_uplift == Decimal("0.9")
    legacy_comparison = _paired_comparison(
        weighted_plan,
        weighted_baseline,
        scenarios=weighted_scenarios,
        hit_points=0,
    )
    assert legacy_comparison.gain_p10 == comparison.gain_p10
    assert legacy_comparison.probability_recommended_beats_baseline == Decimal("0.5")

    mismatched_plan = weighted_plan.model_copy(
        update={
            "scenario_scores": weighted_plan.scenario_scores[:-1],
        }
    )
    with pytest.raises(PrivateV1Error, match="recommendation and baseline scenarios differ"):
        _frontier_comparison(
            mismatched_plan,
            weighted_baseline,
            scenarios=weighted_scenarios,
            hit_points=0,
        )
    zero_weight_scenarios = weighted_scenarios.model_copy(
        update={
            "scenarios": tuple(
                item.model_copy(update={"weight": 0.0}) for item in weighted_scenarios.scenarios
            )
        }
    )
    with pytest.raises(PrivateV1Error, match="scenario weights are invalid"):
        _frontier_comparison(
            weighted_plan,
            weighted_baseline,
            scenarios=zero_weight_scenarios,
            hit_points=0,
        )
    with pytest.raises(PrivateV1Error, match="paired comparison has no quantile"):
        _quantile({}, Fraction(1, 2))

    assert PrivateV1Decision.model_validate_json(decision.model_dump_json()) == decision
    legacy_payload = decision.model_dump(mode="json")
    legacy_payload.pop("transfer_frontier")
    legacy_payload.pop("semantic_sha256")
    legacy_payload["semantic_sha256"] = canonical_sha256(legacy_payload)
    legacy = PrivateV1Decision.model_validate_json(json.dumps(legacy_payload))
    assert legacy.transfer_frontier is None
    assert "TRANSFER FRONTIER" in run.report
    assert "FRONTIER DELTA" in run.report
    assert "FUTURE FREE-TRANSFER VALUE IS NOT INCLUDED." in run.report
    assert "CURRENT OBJECTIVE REMAINS ONE_GAMEWEEK_ZERO_TERMINAL_VALUE_OBJECTIVE." in run.report
    assert "value of the second transfer" not in run.report.casefold()


def test_frontier_contract_rejects_empty_reordered_and_malformed_state(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    decision = (
        PrivateV1RecommendationService()
        .run(build_execution_input(repository_root, tmp_path / "invalid-frontier"))
        .decision
    )
    frontier = decision.transfer_frontier
    assert frontier is not None

    empty = frontier.model_dump(mode="python")
    empty["points"] = ()
    empty["deltas"] = ()
    empty["semantic_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="frontier requires at least the hold plan"):
        type(frontier).model_validate(empty)

    reordered = frontier.model_dump(mode="python")
    reordered["points"] = tuple(reversed(reordered["points"]))
    reordered["semantic_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="canonically ordered"):
        type(frontier).model_validate(reordered)

    point = frontier.points[0]
    malformed = point.free_transfer_state.model_dump(mode="python")
    malformed["remaining_immediately_after_action"] += 1
    malformed["semantic_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="free-transfer transition does not reconcile"):
        type(point.free_transfer_state).model_validate(malformed)

    changed_action = point.model_dump(mode="python")
    changed_action["action_id"] = "transfer-" + "f" * 32
    changed_action["semantic_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="point does not reconcile"):
        type(point).model_validate(changed_action)

    tampered_hash = point.model_dump(mode="python")
    tampered_hash["semantic_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="point does not reconcile"):
        type(point).model_validate(tampered_hash)

    transfer = frontier.points[1].transfers[0]
    with pytest.raises(ValidationError, match="transfer counts must increase"):
        PrivateTransferFrontierDelta(
            lower_transfer_count=1,
            higher_transfer_count=1,
            immediate_expected_points_delta=Decimal(0),
            plan_relationship="NON_NESTED",
        )
    with pytest.raises(ValidationError, match="cannot claim an incremental move"):
        PrivateTransferFrontierDelta(
            lower_transfer_count=0,
            higher_transfer_count=1,
            immediate_expected_points_delta=Decimal(0),
            plan_relationship="NON_NESTED",
            nested_incremental_transfers=(transfer,),
        )
    with pytest.raises(ValidationError, match="must expose its incremental move"):
        PrivateTransferFrontierDelta(
            lower_transfer_count=0,
            higher_transfer_count=1,
            immediate_expected_points_delta=Decimal(0),
            plan_relationship="STRICT_EXTENSION",
        )

    bad_delta = frontier.model_dump(mode="python")
    bad_delta["deltas"][0]["immediate_expected_points_delta"] += Decimal(1)
    bad_delta["semantic_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="frontier does not reconcile"):
        type(frontier).model_validate(bad_delta)

    assert render_transfer_frontier(None, label=str) == ""
