"""Synthetic confounding cases and disclosure-safe exact screen arithmetic."""

from decimal import Decimal

import pytest

from dmf_pulse.ingestion.openfootball.team_strength_data import seal
from dmf_pulse.private_v1.team_strength_comparison_models import MaterialityComparison
from dmf_pulse.private_v1.team_strength_screen_metrics import (
    ScreenComparisonMetrics,
    screen_metrics,
)


@pytest.mark.parametrize(
    "left,right,projection_changed,root_changed,expected",
    [
        ({"a", "b"}, {"a", "b"}, True, False, "PLAYER_PROJECTION_MATERIAL_BUT_DECISION_ROBUST"),
        ({"a", "b"}, {"a", "c"}, False, False, "EXACT_DECISION_ROBUST"),
        ({"a", "b"}, {"a", "c"}, True, True, "CANDIDATE_SCREEN_CONFOUNDED"),
        (
            {"a", "b"},
            {"a", "b", "c"},
            True,
            False,
            "PLAYER_PROJECTION_MATERIAL_BUT_DECISION_ROBUST",
        ),
        ({"a", "b"}, {"a", "b", "c"}, False, True, "CANDIDATE_SCREEN_CONFOUNDED"),
    ],
)
def test_confounded_and_robust_screen_cases(
    left, right, projection_changed, root_changed, expected
):
    metrics = screen_metrics(frozenset(left), frozenset(right), protected=frozenset({"a", "b"}))
    assert metrics.baseline_screen_count == len(left)
    assert metrics.shadow_screen_count == len(right)
    assert metrics.intersection_count == len(left & right)
    assert metrics.union_count == len(left | right)
    assert metrics.added_count == len(right - left)
    assert metrics.removed_count == len(left - right)
    assert metrics.protected_candidate_retained_count == len({"a", "b"} & left & right)
    material = seal(
        MaterialityComparison,
        root_action_changed=root_changed,
        continuation_changed=False,
        tactics_changed=False,
        starting_xi_changed=False,
        captain_changed=False,
        vice_captain_changed=False,
        candidate_screen_equal=left == right,
        utility_delta=Decimal(0),
        hold_utility_delta=Decimal(0),
        uplift_delta=Decimal(0),
        utility_material=False,
        decision_material=root_changed,
        player_projection_material=projection_changed,
        classification=expected,
    )
    assert material.classification == expected
    payload = metrics.model_dump_json()
    assert '"a"' not in payload and '"b"' not in payload and '"c"' not in payload
    assert metrics.exact_cross_screen_solving == "OFF_BY_DEFAULT_NOT_IMPLEMENTED"


def test_empty_sets_and_protected_retention_and_node_differences():
    empty = screen_metrics(frozenset(), frozenset(), protected=frozenset())
    assert empty.jaccard_similarity == 1
    result = screen_metrics(
        frozenset({"private-a"}),
        frozenset({"private-b"}),
        protected=frozenset({"private-a", "private-b"}),
        baseline_node_eligibility=frozenset({("root", 5, "private-a")}),
        shadow_node_eligibility=frozenset({("root", 5, "private-b")}),
    )
    assert result.protected_candidate_count == 2 and result.protected_candidate_retained_count == 0
    assert result.baseline_protected_retained_count == result.shadow_protected_retained_count == 1
    assert result.node_eligibility_added_count == result.node_eligibility_removed_count == 1
    assert "private-" not in result.model_dump_json()
    assert ScreenComparisonMetrics.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    "update",
    [
        {"intersection_count": 3},
        {"union_count": 0},
        {"added_count": 4},
        {"jaccard_similarity": Decimal("0.1")},
        {"protected_candidate_retained_count": 4},
        {"baseline_protected_retained_count": 4},
        {"shadow_protected_retained_count": 4},
    ],
)
def test_forged_screen_arithmetic_rejected(update):
    value = screen_metrics(frozenset({"a", "b"}), frozenset({"b", "c"}), protected=frozenset({"b"}))
    with pytest.raises(ValueError):
        value.model_copy(update=update)


def test_integrated_metrics_use_screened_nodes_even_when_catalog_is_identical():
    from types import SimpleNamespace as NS

    from dmf_pulse.private_v1.team_strength_comparison import _run_screen_metrics

    catalog = (NS(player_id="a"), NS(player_id="b"), NS(player_id="c"))

    def run(allowed):
        return NS(
            optimiser_request=NS(
                candidate_pool=catalog,
                scenario_tree=NS(
                    nodes=(NS(node_id="root", gameweek=5, allowed_transfer_in_ids=allowed),)
                ),
            ),
            one_gameweek_optimiser_result=NS(
                recommended_plan=NS(current_action=NS(action=NS(transfers_in=("a",))))
            ),
        )

    result = _run_screen_metrics(run(("a", "b")), run(("a", "c")))
    assert result.baseline_screen_count == result.shadow_screen_count == 2
    assert result.intersection_count == 1 and result.union_count == 3
    assert result.added_count == result.removed_count == 1
    assert result.jaccard_similarity < 1
    assert result.protected_candidate_count == result.protected_candidate_retained_count == 1
