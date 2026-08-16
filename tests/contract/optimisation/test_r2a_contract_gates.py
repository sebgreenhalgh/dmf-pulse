"""R2A regressions for pre-search Stage-9 and production-authority gates."""

from __future__ import annotations

import pytest

from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.models import OptimisationStatus
from dmf_pulse.optimisation.service import optimise_one_gameweek
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import (
    candidate_pool,
    projection,
    request,
    seal_request,
    synthetic_ruleset,
)


@pytest.mark.parametrize(
    "mutation",
    (
        "scenario_ids",
        "outcome_draw_ids",
        "weights",
        "player_ids",
        "points",
    ),
)
def test_stage9_joint_matrix_mutations_fail_before_search(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    rules = synthetic_ruleset()
    base = projection(rules.ruleset_hash)
    matrix = base.joint_matrix
    if mutation == "scenario_ids":
        altered = matrix.model_copy(update={"scenario_ids": ("foreign",)})
    elif mutation == "outcome_draw_ids":
        altered = matrix.model_copy(update={"outcome_draw_ids": ("foreign",)})
    elif mutation == "weights":
        altered = matrix.model_copy(update={"weights": (0.5,)})
    elif mutation == "player_ids":
        altered = matrix.model_copy(update={"player_ids": tuple(reversed(matrix.player_ids))})
    else:
        altered = matrix.model_copy(update={"points": (tuple(reversed(matrix.points[0])),)})
    tampered = base.model_construct(
        scenario_set=base.scenario_set,
        player_summaries=base.player_summaries,
        joint_matrix=altered,
        monte_carlo=base.monte_carlo,
        result_sha256=base.result_sha256,
    )
    monkeypatch.setattr(
        "dmf_pulse.optimisation.service.solve",
        lambda *args, **kwargs: pytest.fail("search must not run after a Stage-9 boundary failure"),
    )
    result = optimise_one_gameweek(request(), tampered, rules)
    assert result.status is OptimisationStatus.BLOCKED
    assert result.error_code in {"STAGE9_CONTRACT_MISMATCH", "RULESET_IDENTITY_MISMATCH"}


def test_appearance_is_not_inferred_from_zero_or_negative_points() -> None:
    rules = synthetic_ruleset()
    values = ({"p00": 0, "p01": -2},)
    appeared = ({"p00": True, "p01": True},)
    result = optimise_one_gameweek(
        request(), projection(rules.ruleset_hash, values=values, appeared_values=appeared), rules
    )
    assert result.status is OptimisationStatus.SUCCESS
    assert result.recommended_plan is not None
    score = result.recommended_plan.scenario_scores[0]
    assert "p00" in score.counted_player_ids
    assert score.base_points <= score.manager_points


def test_scenario_factory_never_derives_appearance_from_points() -> None:
    rules = synthetic_ruleset()
    defaulted = projection(rules.ruleset_hash, values=({"p00": 0, "p01": -2},))
    assert defaulted.scenario_set.scenarios[0].player_appeared["p00"] is True
    assert defaulted.scenario_set.scenarios[0].player_appeared["p01"] is True
    explicit = projection(
        rules.ruleset_hash,
        values=({"p00": 10},),
        appeared_values=({"p00": False},),
    )
    assert explicit.scenario_set.scenarios[0].player_appeared["p00"] is False


def test_declared_player_outside_stage9_universe_fails_before_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = synthetic_ruleset()
    base_request = request()
    foreign_players = tuple(
        player.model_copy(update={"player_id": "z99"}) if player.player_id == "p14" else player
        for player in base_request.candidate_pool.players
    )
    foreign_pool = candidate_pool(foreign_players)
    foreign_request = seal_request(
        base_request.model_copy(
            update={
                "candidate_pool": foreign_pool,
                "fixed_squad_ids": tuple(player.player_id for player in foreign_pool.players),
                "request_sha256": "0" * 64,
            }
        )
    )
    monkeypatch.setattr(
        "dmf_pulse.optimisation.service.solve",
        lambda *args, **kwargs: pytest.fail("search must not run with a foreign Stage-9 player"),
    )
    result = optimise_one_gameweek(
        foreign_request,
        projection(rules.ruleset_hash),
        rules,
    )
    assert result.status is OptimisationStatus.BLOCKED
    assert result.error_code == "STAGE9_CONTRACT_MISMATCH"


def test_production_cutoff_is_checked_only_after_capability_and_never_from_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = synthetic_ruleset()
    production_request = request(projection_mode=ProjectionMode.PRODUCTION).model_copy(
        update={"information_cutoff_utc": "2026-08-16T00:00:00Z"}
    )
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    monkeypatch.setattr(
        "dmf_pulse.optimisation.service.build_one_gameweek_rules_view", lambda *args, **kwargs: view
    )
    result = optimise_one_gameweek(production_request, projection(rules.ruleset_hash), rules)
    assert result.status is OptimisationStatus.BLOCKED
    assert result.error_code == "STAGE9_CUTOFF_LINEAGE_UNAVAILABLE"


def test_forged_capability_cannot_change_current_production_gate() -> None:
    rules = synthetic_ruleset()
    result = optimise_one_gameweek(
        request(projection_mode=ProjectionMode.PRODUCTION), projection(rules.ruleset_hash), rules
    )
    assert result.status is OptimisationStatus.BLOCKED
    assert result.error_code == "MANAGER_TACTICS_CAPABILITY_UNAVAILABLE"
