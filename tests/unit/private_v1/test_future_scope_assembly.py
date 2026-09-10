"""R4 automatic private scope is assembled separately from its root declaration."""

import pytest

from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import seal_candidate_action_policy, seal_execution_input
from dmf_pulse.private_v1.rolling import PrivateV1RollingRecommendationService
from dmf_pulse.private_v1.service import (
    PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1,
    _stage11_request,
)
from tests.unit.private_v1.e2e_test_support import build_rolling_execution_input


def test_automatic_root_cap_and_shortlist_remain_unchanged_when_future_scope_is_added(
    repository_root, tmp_path
):
    execution = build_rolling_execution_input(repository_root, tmp_path / "rolling")
    run = PrivateV1RollingRecommendationService().run(execution)
    current = execution.current_execution
    policy = type(current.candidate_action_policy).model_construct(
        **{
            **current.candidate_action_policy.model_dump(mode="python"),
            "maximum_transfers": 1,
            "rationale": PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1,
        }
    )
    current = seal_execution_input(
        type(current).model_construct(
            **{
                **{name: getattr(current, name) for name in type(current).model_fields},
                "candidate_action_policy": seal_candidate_action_policy(policy),
            }
        )
    )
    one, _, _, one_scope = _stage11_request(current, run.gameweek_projections[0])
    with pytest.raises(PrivateV1Error, match="HORIZON_COMPARATOR_ACTION_REQUIRED"):
        _stage11_request(
            current, run.gameweek_projections[0], future_gameweeks=run.gameweek_projections[1:]
        )
    rolling, _, _, rolling_scope = _stage11_request(
        current,
        run.gameweek_projections[0],
        future_gameweeks=run.gameweek_projections[1:],
        protected_incoming_ids=(),
    )
    assert one.search_policy.max_transfers_per_node == 1
    assert one.search_policy.transfer_action_scope is None
    # The synthetic fixture intentionally retains only one incoming candidate.
    assert rolling.search_policy.max_transfers_per_node == min(
        2, len(one.scenario_tree.root.allowed_transfer_in_ids)
    )
    assert rolling.search_policy.transfer_action_scope.root_maximum_transfers == 1
    assert rolling.search_policy.transfer_action_scope.continuation_mode == "FREE_TRANSFERS_ONLY"
    from dataclasses import replace

    assert rolling_scope.pruning_policy == "PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V3"
    assert rolling_scope.bounded_screen is not None
    assert one_scope == replace(
        rolling_scope, pruning_policy=one_scope.pruning_policy, bounded_screen=None
    )
    assert rolling_scope.bounded_screen.nodes[0].horizon_gameweeks == (1, 2, 3)
    assert any("HORIZON_CANDIDATE_SCREEN_SHA256:" in item for item in rolling.assumptions)
    assert all(
        node.allowed_transfer_in_ids == one.scenario_tree.root.allowed_transfer_in_ids
        for node in rolling.scenario_tree.nodes
    )
    assert run.decision.one_gameweek_comparison.counterfactual_action_matches_one_gameweek_action
    assert "Root maximum transfers:" in run.report
    assert "Maximum future transfers allowed by search/rules:" in run.report
    assert "One-GW action counterfactual three-GW utility:" in run.report
    from dmf_pulse.private_v1.rolling import render_rolling_report
    from dmf_pulse.private_v1.rolling_models import seal_rolling_decision

    ft_decision = seal_rolling_decision(
        type(run.decision).model_construct(
            **{
                **{name: getattr(run.decision, name) for name in type(run.decision).model_fields},
                "continuation_transfer_mode": "FREE_TRANSFERS_ONLY",
            }
        )
    )
    type(ft_decision).model_validate_json(ft_decision.model_dump_json())
    assert "Future transfer scope: FREE_TRANSFERS_ONLY" in render_rolling_report(ft_decision)
    from dmf_pulse.private_v1.rolling_models import seal_rolling_execution_input

    automatic = seal_rolling_execution_input(
        type(execution).model_construct(
            **{
                **{name: getattr(execution, name) for name in type(execution).model_fields},
                "current_execution": current,
            }
        )
    )
    automatic_run = PrivateV1RollingRecommendationService().run(automatic)
    assert "PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V3" in automatic_run.report
    assert "Screening: HORIZON_AWARE" in automatic_run.report
    assert "Certified horizon-dominated: 0" in automatic_run.report
    assert "Candidate horizon: GW1,GW2,GW3" in automatic_run.report
    assert "Retention categories (overlapping):" in automatic_run.report
    assert "PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1" not in automatic_run.report
    assert automatic_run.optimiser_result.root_action_counterfactual_plan is not None


@pytest.mark.parametrize("has_plan", [False, True])
def test_failed_actual_comparator_cannot_construct_horizon_scope(
    repository_root, tmp_path, monkeypatch, has_plan
):
    from types import SimpleNamespace

    from dmf_pulse.optimisation.multi_gameweek_models import MultiGameweekResultStatus
    from dmf_pulse.private_v1 import rolling
    from dmf_pulse.private_v1.service import _MemoizedStage10Evaluator

    execution = build_rolling_execution_input(repository_root, tmp_path / "failed-comparator")
    original_request = rolling._stage11_request
    calls = []

    def observed_request(*args, **kwargs):
        assert not kwargs.get("future_gameweeks")
        calls.append("ONE_GW")
        return original_request(*args, **kwargs)

    monkeypatch.setattr(rolling, "_stage11_request", observed_request)
    monkeypatch.setattr(_MemoizedStage10Evaluator, "precompute", lambda self: None)
    monkeypatch.setattr(
        rolling,
        "optimise_multi_gameweek",
        lambda *args, **kwargs: SimpleNamespace(
            recommended_plan=object() if has_plan else None,
            status=MultiGameweekResultStatus.ERROR,
            error_code=None if has_plan else "SYNTHETIC_COMPARATOR_FAILURE",
        ),
    )
    expected = "ONE_GAMEWEEK_COMPARATOR_BLOCKED" if has_plan else "SYNTHETIC_COMPARATOR_FAILURE"
    with pytest.raises(PrivateV1Error, match=expected):
        PrivateV1RollingRecommendationService().run(execution)
    assert calls == ["ONE_GW"]
