"""Synthetic-only paired shadow substitution, with unchanged ordinary Stage-9 code."""

from decimal import Decimal

import pytest

from tests.support.factories import reference_engine
from tests.unit.fpl_points.current_shadow_support import (
    load_r9b_script,
    synthetic_shadow,
    synthetic_stage9_request,
)

_comparison = load_r9b_script("compare_r9b_stage9")
ablation_requests = _comparison.ablation_requests
compare_stage9 = _comparison.compare_stage9

pytestmark = pytest.mark.unit


def test_offline_stage9_ablations_keep_upstream_and_pair_draws(repository_root):
    shadow = synthetic_shadow(repository_root, count=120)
    request = synthetic_stage9_request(shadow, scenario_count=32)
    variants = dict(ablation_requests(request, shadow.worlds[0]))
    assert len(variants) == 5
    for variant in variants.values():
        assert variant.score_distribution == request.score_distribution
        assert variant.participation_scenarios == request.participation_scenarios
        assert variant.root_seed == request.root_seed
        assert variant.player_prior_identity is None
    result = compare_stage9(
        request,
        shadow.worlds[0],
        reference_engine(),
        frozen_squad=tuple(p.player_id for p in request.allocation_profiles[:15]),
    )
    assert result["paired_stage7_stage8_equal"]
    assert result["variants"]["STALE"]["squad_expected_points_delta"] == 0
    assert result["variants"]["ALL_SUPPORTED"]["stage9_mean_absolute_player_xp_change"] > 0


def test_offline_harness_rejects_identity_mutation_and_invalid_squad(repository_root):
    shadow = synthetic_shadow(repository_root, count=120)
    request = synthetic_stage9_request(shadow, scenario_count=4)
    profile = request.allocation_profiles[0].model_copy(update={"assist_share": 999.0})
    changed = request.model_copy(
        update={"allocation_profiles": (profile, *request.allocation_profiles[1:])}
    )
    with pytest.raises(ValueError, match="exact bound"):
        tuple(ablation_requests(changed, shadow.worlds[0]))
    with pytest.raises(ValueError, match="frozen squad"):
        compare_stage9(request, shadow.worlds[0], reference_engine(), frozen_squad=("unknown",))


def test_future_stage7_minutes_do_not_reweight_shadow_posteriors_or_assists(repository_root):
    shadow = synthetic_shadow(repository_root, count=120)
    before_hash = shadow.semantic_sha256
    full = synthetic_stage9_request(shadow, scenario_count=4, future_minutes=90)
    reduced = synthetic_stage9_request(shadow, scenario_count=4, future_minutes=60)
    assert full.participation_scenarios != reduced.participation_scenarios
    assert (
        full.participation_scenarios[0].stage7_minutes_context
        != reduced.participation_scenarios[0].stage7_minutes_context
    )
    for world in shadow.worlds:
        first = dict(ablation_requests(full, world))
        second = dict(ablation_requests(reduced, world))
        assert (
            first["ALL_SUPPORTED"].allocation_profiles
            == second["ALL_SUPPORTED"].allocation_profiles
        )
        assert first["ASSIST_ONLY"].allocation_profiles == second["ASSIST_ONLY"].allocation_profiles
        assert first["ALL_SUPPORTED"].participation_scenarios == full.participation_scenarios
        assert second["ALL_SUPPORTED"].participation_scenarios == reduced.participation_scenarios
    assert shadow.semantic_sha256 == before_hash
    assert shadow == synthetic_shadow(repository_root, count=120)


def test_offline_exact_stage10_provided_squad_sensitivity(repository_root):
    from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter
    from dmf_pulse.rules.compiler import compile_ruleset
    from tests.unit.fpl_points.current_shadow_support import synthetic_decision_inputs

    shadow = synthetic_shadow(repository_root, count=120)
    requests, squads = synthetic_decision_inputs(shadow, scenario_count=8)
    harness = load_r9b_script("compare_r9b_decisions")
    rules = compile_ruleset(repository_root / "config/rules/fpl-2026-27")
    result = harness.compare_decisions(
        requests,
        shadow.worlds[0],
        AcceptedRulesAdapter(rules),
        rules,
        squads,
    )
    assert result["provided_squad_count"] == 2
    assert result["stage11_not_executed"] is True
    assert result["rolling_action_changed"] is None
    assert Decimal(result["expected_manager_utility_delta"]) == Decimal(
        result["paired_manager_gain_mean"]
    )
