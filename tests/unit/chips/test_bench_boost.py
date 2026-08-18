from __future__ import annotations

from dataclasses import dataclass, replace
from math import nan
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.bench_boost import evaluate_bench_boost
from dmf_pulse.chips.compiler import compile_synthetic_bundle
from dmf_pulse.chips.definitions import (
    ActivationRoute,
    ChipDefinition,
    ChipEffect,
    CompiledChipBundle,
    InventoryGrant,
    semantic_sha256,
)
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import build_chip_inventory
from dmf_pulse.chips.policy_models import BenchBoostCostProfile

RULESET_ID = "FPL-2026-27"
RULESET_VERSION = "2026.27.1"
RULESET_HASH = "a" * 64


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    outcome_draw_id: str
    weight: float
    player_points: dict[str, int]
    player_appeared: dict[str, bool]
    fixture_ids: tuple[str, ...] = ("fixture-1",)


@dataclass(frozen=True)
class Rules:
    captain_multiplier: int = 2
    vice_captain_fallback: bool = True
    ruleset_id: str = RULESET_ID
    ruleset_version: str = RULESET_VERSION
    ruleset_hash: str = RULESET_HASH


@dataclass(frozen=True)
class Tactic:
    starting_xi: tuple[str, ...]
    bench_goalkeeper: str
    bench_order: tuple[str, str, str]
    captain: str
    vice_captain: str


@dataclass(frozen=True)
class Score:
    manager_points: int | float
    counted_player_ids: tuple[str, ...]


def normal_evaluator(scenario, tactic, players, rules):
    del players
    appeared = {player for player, value in scenario.player_appeared.items() if value}
    counted = [player for player in tactic.starting_xi if player in appeared]
    absent = sum(player not in appeared for player in tactic.starting_xi)
    for player in (*tactic.bench_order, tactic.bench_goalkeeper):
        if absent <= 0:
            break
        if player in appeared and player not in counted:
            counted.append(player)
            absent -= 1
    effective = (
        tactic.captain
        if tactic.captain in appeared
        else tactic.vice_captain if tactic.vice_captain in appeared else None
    )
    points = sum(scenario.player_points[player] for player in counted)
    if effective is not None:
        points += (rules.captain_multiplier - 1) * scenario.player_points[effective]
    return Score(points, tuple(counted)), None


def tactic_a() -> Tactic:
    return Tactic(
        starting_xi=("A", "B", "C", "D"),
        bench_goalkeeper="G",
        bench_order=("E", "F", "H"),
        captain="A",
        vice_captain="B",
    )


def tactic_b() -> Tactic:
    return Tactic(
        starting_xi=("A", "B", "E", "F"),
        bench_goalkeeper="G",
        bench_order=("C", "D", "H"),
        captain="A",
        vice_captain="B",
    )


def bb_definition(
    *,
    key: str = "BENCH_BOOST",
    effects: tuple[ChipEffect, ...] | None = None,
) -> ChipDefinition:
    return ChipDefinition(
        chip_key=key,
        definition_version=f"{RULESET_VERSION}:{key}",
        grants=(
            InventoryGrant(
                grant_id="window-1",
                copies=1,
                acquired_gameweek=1,
                activation_start_gameweek=1,
                activation_end_gameweek=19,
                expires_after_gameweek=19,
            ),
        ),
        duration_gameweeks=1,
        concurrency_group="SQUAD_CHIP",
        activation_route=ActivationRoute.PICK_TEAM_SAVE,
        cancellable_before_lock=True,
        effects=effects
        or (ChipEffect(surface="LINEUP", operation="INCLUDE_BENCH_POINTS", parameters={}),),
    )


def bundle_for(*definitions: ChipDefinition) -> CompiledChipBundle:
    return compile_synthetic_bundle(
        ruleset_id=RULESET_ID,
        ruleset_version=RULESET_VERSION,
        ruleset_hash=RULESET_HASH,
        concurrency_limit=1,
        definitions=definitions or (bb_definition(),),
    )


def costs(
    plan_id: str = "natural",
    *,
    natural: bool = True,
    hit: float = 0.0,
    budget: float = 0.0,
    future: float = 0.0,
    unwind: float = 0.0,
    price: float = 0.0,
) -> BenchBoostCostProfile:
    return BenchBoostCostProfile(
        plan_id=plan_id,
        is_natural=natural,
        preparation_transfer_count=0 if natural else 3,
        preparation_hit_cost_points=hit,
        budget_shift_cost_points=budget,
        future_starting_xi_cost_points=future,
        post_boost_unwind_cost_points=unwind,
        price_route_cost_points=price,
    )


def full_scenario(
    *,
    scenario_id: str = "s1",
    draw_id: str = "d1",
    weight: float = 1.0,
    points: dict[str, int] | None = None,
    appeared: dict[str, bool] | None = None,
) -> Scenario:
    values = points or {"A": 10, "B": 8, "C": 6, "D": 5, "E": 4, "F": 3, "G": 2, "H": 1}
    appearances = appeared or {player: True for player in values}
    return Scenario(scenario_id, draw_id, weight, values, appearances)


def evaluate(
    scenarios: tuple[Scenario, ...],
    *,
    tactical_candidates=(None,),
    cost_profile: BenchBoostCostProfile | None = None,
    bundle: CompiledChipBundle | None = None,
    rules: Rules | None = None,
    wildcard_candidates=None,
    wildcard_cost_profile=None,
    evaluator=normal_evaluator,
):
    active_bundle = bundle or bundle_for()
    inventory = build_chip_inventory(active_bundle, current_gameweek=1)
    token = next(item for item in inventory.tokens if item.chip_key == "BENCH_BOOST")
    candidates = (tactic_a(),) if tactical_candidates == (None,) else tactical_candidates
    return evaluate_bench_boost(
        scenarios=scenarios,
        tactical_candidates=candidates,
        players={},
        rules=rules or Rules(),
        chip_bundle=active_bundle,
        inventory=inventory,
        token_id=token.token_id,
        costs=cost_profile or costs(),
        wildcard_tactical_candidates=wildcard_candidates,
        wildcard_costs=wildcard_cost_profile,
        evaluator=evaluator,
    )


def test_four_player_bench_including_goalkeeper_scores_incrementally() -> None:
    result = evaluate((full_scenario(),))
    scenario = result.standalone_route.scenario_values[0]
    assert scenario.bench_appeared_ids == ("G", "E", "F", "H")
    assert scenario.bench_raw_points == 10.0
    assert scenario.autosub_overlap_points == 0.0
    assert scenario.gross_increment == 10.0
    assert result.standalone_route.gross_current_gain == 10.0


def test_autosub_overlap_is_subtracted_from_bench_sum() -> None:
    scenario = full_scenario(appeared={"A": True, "B": True, "C": False, "D": True, "E": True, "F": True, "G": True, "H": True})
    result = evaluate((scenario,))
    value = result.standalone_route.scenario_values[0]
    assert "E" in value.normal_autosub_overlap_ids
    assert value.bench_raw_points == 10.0
    assert value.autosub_overlap_points == 4.0
    assert value.gross_increment == 6.0


def test_zero_bench_appearances_have_zero_increment_but_consume_chip() -> None:
    appearances = {"A": True, "B": True, "C": True, "D": True, "E": False, "F": False, "G": False, "H": False}
    result = evaluate((full_scenario(appeared=appearances),))
    assert result.standalone_route.gross_current_gain == 0.0
    assert result.chip_consumed is True
    assert result.inventory_before_hash != result.inventory_after_activation_hash


def test_negative_bench_points_can_reduce_current_score() -> None:
    points = {"A": 10, "B": 8, "C": 6, "D": 5, "E": -2, "F": -1, "G": 0, "H": 0}
    result = evaluate((full_scenario(points=points),))
    assert result.standalone_route.gross_current_gain == -3.0


def test_best_normal_comparator_is_not_a_frozen_current_xi() -> None:
    scenario = full_scenario()
    result = evaluate((scenario,), tactical_candidates=(tactic_a(), tactic_b()))
    route = result.standalone_route
    assert route.evaluated_tactics == 2
    assert route.expected_normal_points == 39.0
    assert route.expected_bench_boost_points == 49.0
    assert route.gross_current_gain == 10.0


def test_natural_route_preserves_gross_as_net_before_continuation() -> None:
    result = evaluate((full_scenario(),), cost_profile=costs("natural", natural=True))
    route = result.standalone_route
    assert route.is_natural is True
    assert route.net_pre_continuation_value == route.gross_current_gain
    assert result.continuation_value_included is False


def test_engineered_route_can_have_worse_net_value() -> None:
    engineered = costs("engineered", natural=False, hit=8.0, budget=2.0, future=3.0, unwind=2.0)
    result = evaluate((full_scenario(),), cost_profile=engineered)
    route = result.standalone_route
    assert route.gross_current_gain == 10.0
    assert route.costs.total_cost_points == 15.0
    assert route.net_pre_continuation_value == -5.0


def test_wc_bb_positive_synergy_is_measured() -> None:
    standalone = costs("standalone", natural=False, hit=8.0, budget=2.0, future=2.0)
    wildcard = costs("wc-linked", natural=False, hit=0.0, budget=1.0, future=1.0)
    result = evaluate(
        (full_scenario(),),
        cost_profile=standalone,
        wildcard_candidates=(tactic_a(),),
        wildcard_cost_profile=wildcard,
    )
    assert result.wildcard_synergy is not None
    assert result.wildcard_synergy.measured_synergy == 10.0
    assert result.wildcard_synergy.positive is True


def test_wc_bb_negative_synergy_is_measured_not_assumed() -> None:
    standalone = costs("standalone", natural=True)
    wildcard = costs("wc-linked", natural=False, budget=4.0, future=3.0, unwind=2.0)
    result = evaluate(
        (full_scenario(),),
        cost_profile=standalone,
        wildcard_candidates=(tactic_a(),),
        wildcard_cost_profile=wildcard,
    )
    assert result.wildcard_synergy is not None
    assert result.wildcard_synergy.measured_synergy == -9.0
    assert result.wildcard_synergy.positive is False


def test_wildcard_route_requires_candidates_and_costs_together() -> None:
    with pytest.raises(ChipError) as exc:
        evaluate((full_scenario(),), wildcard_candidates=(tactic_a(),))
    assert exc.value.code == "CHIP_BB_WILDCARD_ROUTE_INCOMPLETE"


@pytest.mark.parametrize(
    ("scenarios", "code"),
    [
        ((), "CHIP_SCENARIOS_EMPTY"),
        ((replace(full_scenario(), scenario_id=""),), "CHIP_SCENARIO_ID_INVALID"),
        ((replace(full_scenario(), weight=nan),), "CHIP_SCENARIO_WEIGHT_INVALID"),
        ((replace(full_scenario(), weight=0.4),), "CHIP_SCENARIO_WEIGHT_SUM"),
    ],
)
def test_scenario_contracts_fail_closed(scenarios, code) -> None:
    with pytest.raises(ChipError) as exc:
        evaluate(scenarios)
    assert exc.value.code == code


def test_duplicate_scenario_identity_fails() -> None:
    scenario = replace(full_scenario(), weight=0.5)
    with pytest.raises(ChipError) as exc:
        evaluate((scenario, scenario))
    assert exc.value.code == "CHIP_SCENARIOS_DUPLICATE"


@pytest.mark.parametrize(
    "candidate",
    [
        (),
        (SimpleNamespace(starting_xi=("A",)),),
        (replace(tactic_a(), bench_order=("E", "E", "H")),),
    ],
)
def test_invalid_tactical_candidates_fail(candidate) -> None:
    expected = "CHIP_BB_CANDIDATES_EMPTY" if not candidate else "CHIP_BB_TACTIC_INVALID"
    with pytest.raises(ChipError) as exc:
        evaluate((full_scenario(),), tactical_candidates=candidate)
    assert exc.value.code == expected


def test_duplicate_tactical_candidates_fail() -> None:
    with pytest.raises(ChipError) as exc:
        evaluate((full_scenario(),), tactical_candidates=(tactic_a(), tactic_a()))
    assert exc.value.code == "CHIP_BB_CANDIDATES_DUPLICATE"


def test_missing_bench_player_in_scenario_fails() -> None:
    scenario = full_scenario(points={"A": 1, "B": 1, "C": 1, "D": 1, "E": 1, "F": 1, "G": 1})
    with pytest.raises(ChipError) as exc:
        evaluate((scenario,))
    assert exc.value.code == "CHIP_BB_SCENARIO_UNIVERSE"


def test_invalid_counted_players_and_nonfinite_score_fail() -> None:
    scenario = full_scenario()

    def duplicate_counted(*args):
        return Score(10, ("A", "A")), None

    with pytest.raises(ChipError) as exc:
        evaluate((scenario,), evaluator=duplicate_counted)
    assert exc.value.code == "CHIP_BB_COUNTED_INVALID"

    def nonfinite(*args):
        return Score(float("inf"), ("A",)), None

    with pytest.raises(ChipError) as exc:
        evaluate((scenario,), evaluator=nonfinite)
    assert exc.value.code == "CHIP_BB_SCORE_INVALID"


def test_rules_lineage_definition_effect_and_token_fail_closed() -> None:
    scenario = full_scenario()
    with pytest.raises(ChipError) as exc:
        evaluate((scenario,), rules=replace(Rules(), ruleset_hash="b" * 64))
    assert exc.value.code == "CHIP_RULESET_LINEAGE_MISMATCH"

    missing = bundle_for(bb_definition(key="OTHER"))
    inventory = build_chip_inventory(missing, current_gameweek=1)
    with pytest.raises(ChipError) as exc:
        evaluate_bench_boost(
            scenarios=(scenario,), tactical_candidates=(tactic_a(),), players={}, rules=Rules(),
            chip_bundle=missing, inventory=inventory, token_id=inventory.tokens[0].token_id,
            costs=costs(), evaluator=normal_evaluator,
        )
    assert exc.value.code == "CHIP_BB_DEFINITION_MISSING"

    wrong_effect = bundle_for(
        bb_definition(effects=(ChipEffect(surface="SCORING", operation="ADD_POINTS", parameters={"points": 1}),))
    )
    with pytest.raises(ChipError) as exc:
        evaluate((scenario,), bundle=wrong_effect)
    assert exc.value.code == "CHIP_BB_EFFECT_MISSING"

    bundle = bundle_for(bb_definition(), bb_definition(key="OTHER"))
    inventory = build_chip_inventory(bundle, current_gameweek=1)
    other = next(token for token in inventory.tokens if token.chip_key == "OTHER")
    with pytest.raises(ChipError) as exc:
        evaluate_bench_boost(
            scenarios=(scenario,), tactical_candidates=(tactic_a(),), players={}, rules=Rules(),
            chip_bundle=bundle, inventory=inventory, token_id=other.token_id,
            costs=costs(), evaluator=normal_evaluator,
        )
    assert exc.value.code == "CHIP_BB_TOKEN_MISMATCH"


def test_blocked_and_expired_token_fail_closed() -> None:
    blocked = bundle_for(
        bb_definition(effects=(ChipEffect(surface="UNKNOWN", operation="UNKNOWN", parameters={}),))
    )
    with pytest.raises(ChipError) as exc:
        evaluate((full_scenario(),), bundle=blocked)
    assert exc.value.code == "CHIP_EFFECT_BLOCKED"

    bundle = bundle_for()
    inventory = build_chip_inventory(bundle, current_gameweek=20)
    with pytest.raises(ChipError) as exc:
        evaluate_bench_boost(
            scenarios=(full_scenario(),), tactical_candidates=(tactic_a(),), players={}, rules=Rules(),
            chip_bundle=bundle, inventory=inventory, token_id=inventory.tokens[0].token_id,
            costs=costs(), evaluator=normal_evaluator,
        )
    assert exc.value.code == "CHIP_BB_TOKEN_UNAVAILABLE"


def test_default_evaluator_adapter(monkeypatch) -> None:
    import dmf_pulse.optimisation.autosub_evaluator as adapter

    monkeypatch.setattr(adapter, "evaluate_scenario", normal_evaluator)
    result = evaluate((full_scenario(),), evaluator=None)
    assert result.standalone_route.gross_current_gain == 10.0


def test_hashes_are_reproducible_and_tamper_evident() -> None:
    first = evaluate((full_scenario(),))
    second = evaluate((full_scenario(),))
    assert first == second
    assert first.evaluation_hash == second.evaluation_hash
    assert semantic_sha256(first.model_dump(mode="json", exclude={"evaluation_hash"})) == first.evaluation_hash

    payload = first.model_dump(mode="python")
    payload["evaluation_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="evaluation hash mismatch"):
        type(first).model_validate(payload)

    route_payload = first.standalone_route.model_dump(mode="python")
    route_payload["net_pre_continuation_value"] += 1.0
    with pytest.raises(ValidationError, match="net pre-continuation"):
        type(first.standalone_route).model_validate(route_payload)


def test_synergy_contract_rejects_sign_tampering() -> None:
    result = evaluate(
        (full_scenario(),),
        wildcard_candidates=(tactic_a(),),
        wildcard_cost_profile=costs("wc", natural=False, hit=1.0),
    )
    assert result.wildcard_synergy is not None
    payload = result.wildcard_synergy.model_dump(mode="python")
    payload["positive"] = not payload["positive"]
    with pytest.raises(ValidationError, match="sign"):
        type(result.wildcard_synergy).model_validate(payload)
