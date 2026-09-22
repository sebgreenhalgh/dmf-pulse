"""Fixed materiality and authenticated numerical-summary boundary tests."""

from decimal import Decimal

import pytest

from dmf_pulse.ingestion.openfootball.team_strength_data import seal
from dmf_pulse.private_v1.team_strength_comparison_models import (
    CONTROL_NAMES,
    GameweekMarketCoverage,
    MaterialityComparison,
    PlayerMovement,
    PriorWorldResult,
    TeamStrengthDecisionComparison,
    summarise_movements,
)


@pytest.mark.parametrize(
    "root,continuation,tactics,player,screen,delta,expected",
    [
        (True, True, True, True, False, "0.01", "CANDIDATE_SCREEN_CONFOUNDED"),
        (True, False, False, False, True, "0", "TEAM_STRENGTH_ROOT_ACTION_MATERIAL"),
        (False, True, True, True, True, "0", "ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE"),
        (False, False, True, True, True, "0", "ROOT_ACTION_ROBUST_TACTICS_SENSITIVE"),
        (False, False, False, True, True, "0", "PLAYER_PROJECTION_MATERIAL_BUT_DECISION_ROBUST"),
        (False, False, False, False, True, "0.49", "UTILITY_ONLY_MOVEMENT"),
        (False, False, False, False, True, "0.50", "UTILITY_ONLY_MOVEMENT"),
        (False, False, False, False, True, "-0.50", "UTILITY_ONLY_MOVEMENT"),
        (False, False, False, False, True, "0", "EXACT_DECISION_ROBUST"),
    ],
)
def test_locked_thresholds_and_precedence(
    root, continuation, tactics, player, screen, delta, expected
):
    values = dict(
        root_action_changed=root,
        continuation_changed=continuation,
        tactics_changed=tactics,
        starting_xi_changed=False,
        captain_changed=tactics,
        vice_captain_changed=False,
        candidate_screen_equal=screen,
        utility_delta=Decimal(delta),
        hold_utility_delta=Decimal(0),
        uplift_delta=Decimal(delta),
        utility_material=abs(Decimal(delta)) >= Decimal("0.50"),
        decision_material=root or abs(Decimal(delta)) >= Decimal("0.50"),
        player_projection_material=player,
        classification=expected,
    )
    outcome = seal(MaterialityComparison, **values)
    assert outcome.decision_material == (root or abs(Decimal(delta)) >= Decimal("0.50"))
    with pytest.raises(ValueError, match="threshold"):
        seal(
            MaterialityComparison, **(values | {"decision_material": not outcome.decision_material})
        )
    wrong = (
        "UTILITY_ONLY_MOVEMENT" if expected != "UTILITY_ONLY_MOVEMENT" else "EXACT_DECISION_ROBUST"
    )
    with pytest.raises(ValueError, match="precedence"):
        seal(MaterialityComparison, **(values | {"classification": wrong}))


def row(delta="0.15", **updates):
    return PlayerMovement(
        **(
            dict(
                gameweek=5,
                player_id="player",
                team_id="team",
                in_current_squad=True,
                baseline_xp=Decimal(2),
                shadow_xp=Decimal(2) + Decimal(delta),
                delta=Decimal(delta),
                baseline_rank=1,
                shadow_rank=2,
            )
            | updates
        )
    )


def test_projection_boundary_quantiles_and_rank_movement():
    rows = (row("0.149999"), row("0.15", player_id="b"), row("-0.15", gameweek=6))
    summary = summarise_movements(rows)
    assert summary.player_count == 2 and summary.player_gameweek_count == 3
    assert summary.material_player_gameweek_count == 2
    assert summary.materially_moved_player_count == 2
    assert summary.material_rank_movement_count == 2
    assert summary.median_absolute_xp == summary.maximum_absolute_xp == Decimal("0.15")
    assert summary.current_squad_delta_by_gameweek == (
        (5, Decimal("0.299999")),
        (6, Decimal("-0.15")),
    )
    with pytest.raises(ValueError, match="empty"):
        summarise_movements(())
    with pytest.raises(ValueError, match="delta"):
        row(delta="0.15", shadow_xp=Decimal(3))
    with pytest.raises(ValueError):
        row(delta="Infinity")


def test_market_coverage_reconciles():
    with pytest.raises(ValueError, match="reconcile"):
        GameweekMarketCoverage(gameweek=5, total=3, market_backed=1, partial_market=1, prior_only=0)


def test_nonfinite_internal_values_fail_even_if_parser_is_bypassed():
    bad = PlayerMovement.model_construct(
        baseline_xp=Decimal("Infinity"), shadow_xp=Decimal(2), delta=Decimal(1)
    )
    with pytest.raises(ValueError, match="nonfinite"):
        bad.reconcile()
    bad_result = MaterialityComparison.model_construct(
        utility_delta=Decimal("Infinity"), hold_utility_delta=Decimal(0), uplift_delta=Decimal(0)
    )
    with pytest.raises(ValueError, match="nonfinite"):
        bad_result.classification_is_fixed()


def test_control_inventory_and_execution_binding_are_required():
    controls = tuple((name, "a" * 64) for name in sorted(CONTROL_NAMES))
    world = PriorWorldResult.model_construct(world="LEAGUE_BASELINE", controls=controls)
    assert world.complete_controls() is world
    incomplete = PriorWorldResult.model_construct(controls=controls[:-1])
    with pytest.raises(ValueError, match="inventory"):
        incomplete.complete_controls()
    shadow = PriorWorldResult.model_construct(world="TEAM_STRENGTH_SHADOW", controls=controls)
    wrong = TeamStrengthDecisionComparison.model_construct(
        worlds=(world, shadow), baseline_execution_sha256="b" * 64
    )
    with pytest.raises(ValueError, match="frozen execution identity"):
        wrong.controls_and_coverage()
