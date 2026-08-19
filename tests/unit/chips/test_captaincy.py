from __future__ import annotations

from dataclasses import dataclass, replace
from math import nan
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from dmf_pulse.chips.captaincy import evaluate_triple_captain, optimise_captain_vice
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
from dmf_pulse.chips.inventory import TokenStatus, build_chip_inventory

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
    effective_captain_id: str | None
    captain_resolution: str


class PydanticTactic(BaseModel):
    model_config = ConfigDict(frozen=True)
    starting_xi: tuple[str, ...]
    captain: str
    vice_captain: str


def evaluator(scenario, tactic, players, rules):
    del players
    appeared = {key for key, value in scenario.player_appeared.items() if value}
    base = sum(
        scenario.player_points[player] for player in tactic.starting_xi if player in appeared
    )
    if tactic.captain in appeared:
        effective = tactic.captain
        resolution = "CAPTAIN"
    elif rules.vice_captain_fallback and tactic.vice_captain in appeared:
        effective = tactic.vice_captain
        resolution = "VICE_CAPTAIN"
    else:
        effective = None
        resolution = "NEITHER"
    bonus = (
        0
        if effective is None
        else (rules.captain_multiplier - 1) * scenario.player_points[effective]
    )
    return Score(base + bonus, effective, resolution), None


def tactic() -> Tactic:
    return Tactic(
        starting_xi=("A", "B", "C"),
        bench_goalkeeper="G",
        bench_order=("D", "E", "F"),
        captain="A",
        vice_captain="B",
    )


def tc_definition(
    *,
    multiplier: int = 3,
    vice_fallback: bool = True,
    key: str = "TRIPLE_CAPTAIN",
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
        or (
            ChipEffect(
                surface="CAPTAIN",
                operation="SET_MULTIPLIER",
                parameters={"multiplier": multiplier, "vice_fallback": vice_fallback},
            ),
        ),
    )


def bundle_for(*definitions: ChipDefinition) -> CompiledChipBundle:
    return compile_synthetic_bundle(
        ruleset_id=RULESET_ID,
        ruleset_version=RULESET_VERSION,
        ruleset_hash=RULESET_HASH,
        concurrency_limit=1,
        definitions=definitions or (tc_definition(),),
    )


def inventory_for(bundle: CompiledChipBundle, *, gameweek: int = 1):
    inventory = build_chip_inventory(bundle, current_gameweek=gameweek)
    token = next(item for item in inventory.tokens if item.chip_key == "TRIPLE_CAPTAIN")
    return inventory, token.token_id


def evaluate(
    scenarios: tuple[Scenario, ...],
    *,
    bundle: CompiledChipBundle | None = None,
    rules: Rules | None = None,
    candidate_ids: tuple[str, ...] | None = None,
):
    active_bundle = bundle or bundle_for()
    inventory, token_id = inventory_for(active_bundle)
    return evaluate_triple_captain(
        scenarios=scenarios,
        base_tactic=tactic(),
        players={},
        rules=rules or Rules(),
        chip_bundle=active_bundle,
        inventory=inventory,
        token_id=token_id,
        candidate_ids=candidate_ids,
        evaluator=evaluator,
    )


def test_captain_appears_and_vice_is_conditional_fallback() -> None:
    scenarios = (
        Scenario("s1", "d1", 0.6, {"A": 10, "B": 9, "C": 1}, {"A": True, "B": True, "C": True}),
        Scenario("s2", "d2", 0.4, {"A": 0, "B": 1, "C": 8}, {"A": False, "B": True, "C": True}),
    )
    decision = optimise_captain_vice(
        scenarios=scenarios,
        base_tactic=tactic(),
        players={},
        rules=Rules(),
        evaluator=evaluator,
    )
    assert (decision.captain, decision.vice_captain) == ("A", "C")
    assert decision.vice_fallback_probability == pytest.approx(0.4)
    assert decision.vice_fallback_incremental_points == pytest.approx(3.2)
    assert decision.captain_and_vice_failure_probability == 0.0
    assert decision.evaluated_pairs == 6


def test_captain_absent_vice_appears() -> None:
    scenario = Scenario("fallback", "d1", 1.0, {"A": 12, "B": 7}, {"A": False, "B": True})
    decision = optimise_captain_vice(
        scenarios=(scenario,),
        base_tactic=replace(tactic(), starting_xi=("A", "B")),
        players={},
        rules=Rules(),
        evaluator=evaluator,
    )
    assert decision.scenario_scores[0].effective_captain_id == "B"
    assert decision.scenario_scores[0].captain_resolution == "VICE_CAPTAIN"
    assert decision.expected_effective_captain_raw_points == 7.0


def test_both_absent_scores_no_captain_copy() -> None:
    scenario = Scenario("neither", "d1", 1.0, {"A": 9, "B": 8}, {"A": False, "B": False})
    decision = optimise_captain_vice(
        scenarios=(scenario,),
        base_tactic=replace(tactic(), starting_xi=("A", "B")),
        players={},
        rules=Rules(),
        evaluator=evaluator,
    )
    assert decision.scenario_scores[0].effective_captain_id is None
    assert decision.expected_effective_captain_raw_points == 0.0
    assert decision.captain_and_vice_failure_probability == 1.0


def test_dgw_uses_aggregate_gameweek_score_and_single_fixture_can_outscore_weak_dgw() -> None:
    dgw = Scenario(
        "dgw-player-one-appearance",
        "draw-1",
        0.5,
        {"A": 10, "B": 6, "C": 2},
        {"A": True, "B": True, "C": True},
        ("double-1", "double-2"),
    )
    single = Scenario(
        "single-fixture-haul",
        "draw-2",
        0.5,
        {"A": 18, "B": 6, "C": 2},
        {"A": True, "B": True, "C": True},
        ("single-1",),
    )
    result = evaluate((dgw, single))
    assert result.triple_captain.captain == "A"
    assert result.gross_current_gain == 14.0
    assert tuple(item.gross_increment for item in result.scenario_values) == (10.0, 18.0)


def test_correlated_postponement_preserves_joint_failure() -> None:
    scenarios = (
        Scenario("played", "d1", 0.7, {"A": 8, "B": 7}, {"A": True, "B": True}),
        Scenario("postponed", "d2", 0.3, {"A": 0, "B": 0}, {"A": False, "B": False}),
    )
    decision = optimise_captain_vice(
        scenarios=scenarios,
        base_tactic=replace(tactic(), starting_xi=("A", "B")),
        players={},
        rules=Rules(),
        evaluator=evaluator,
    )
    assert decision.captain_and_vice_failure_probability == pytest.approx(0.3)
    assert decision.vice_fallback_probability == 0.0


def test_tc_jointly_enumerates_an_alternative_pair() -> None:
    scenarios = (
        Scenario("a", "d1", 0.5, {"A": 12, "B": 4, "C": 9}, {"A": True, "B": True, "C": True}),
        Scenario("b", "d2", 0.5, {"A": 0, "B": 2, "C": 8}, {"A": False, "B": True, "C": True}),
    )
    result = evaluate(scenarios)
    assert result.triple_captain.evaluated_pairs == 6
    assert (result.triple_captain.captain, result.triple_captain.vice_captain) == ("A", "C")
    assert result.gross_current_gain == pytest.approx(10.0)


def test_tc_is_consumed_when_extra_score_is_zero() -> None:
    scenario = Scenario("all-absent", "d1", 1.0, {"A": 0, "B": 0}, {"A": False, "B": False})
    result = evaluate((scenario,), candidate_ids=("A", "B"))
    assert result.zero_extra_score is True
    assert result.gross_current_gain == 0.0
    assert result.chip_consumed is True
    assert result.inventory_before_hash != result.inventory_after_activation_hash


def test_pydantic_copy_path_and_default_evaluator(monkeypatch) -> None:
    import dmf_pulse.optimisation.autosub_evaluator as adapter

    monkeypatch.setattr(adapter, "evaluate_scenario", evaluator)
    decision = optimise_captain_vice(
        scenarios=(Scenario("s", "d", 1.0, {"A": 4, "B": 3}, {"A": True, "B": True}),),
        base_tactic=PydanticTactic(starting_xi=("A", "B"), captain="A", vice_captain="B"),
        players={},
        rules=Rules(),
    )
    assert decision.captain == "A"


def test_scenario_hash_includes_correlated_appearance_state() -> None:
    points = {"A": 5, "B": 4}
    played = evaluate(
        (Scenario("s", "d", 1.0, points, {"A": True, "B": True}),), candidate_ids=("A", "B")
    )
    absent = evaluate(
        (Scenario("s", "d", 1.0, points, {"A": False, "B": False}),), candidate_ids=("A", "B")
    )
    assert played.scenario_set_hash != absent.scenario_set_hash


@pytest.mark.parametrize(
    ("scenarios", "code"),
    [
        ((), "CHIP_SCENARIOS_EMPTY"),
        (
            (Scenario("", "d", 1.0, {"A": 1, "B": 1}, {"A": True, "B": True}),),
            "CHIP_SCENARIO_ID_INVALID",
        ),
        (
            (Scenario("s", "d", nan, {"A": 1, "B": 1}, {"A": True, "B": True}),),
            "CHIP_SCENARIO_WEIGHT_INVALID",
        ),
        (
            (Scenario("s", "d", 0.7, {"A": 1, "B": 1}, {"A": True, "B": True}),),
            "CHIP_SCENARIO_WEIGHT_SUM",
        ),
    ],
)
def test_scenario_contracts_fail_closed(scenarios, code) -> None:
    with pytest.raises(ChipError) as exc:
        optimise_captain_vice(
            scenarios=scenarios,
            base_tactic=replace(tactic(), starting_xi=("A", "B")),
            players={},
            rules=Rules(),
            evaluator=evaluator,
        )
    assert exc.value.code == code


def test_duplicate_scenarios_fail_closed() -> None:
    scenario = Scenario("s", "d", 0.5, {"A": 1, "B": 1}, {"A": True, "B": True})
    with pytest.raises(ChipError) as exc:
        optimise_captain_vice(
            scenarios=(scenario, scenario),
            base_tactic=replace(tactic(), starting_xi=("A", "B")),
            players={},
            rules=Rules(),
            evaluator=evaluator,
        )
    assert exc.value.code == "CHIP_SCENARIOS_DUPLICATE"


@pytest.mark.parametrize(
    "candidate_ids",
    [("A",), ("A", "A"), ("A", "D")],
)
def test_invalid_candidate_sets_fail(candidate_ids) -> None:
    with pytest.raises(ChipError) as exc:
        optimise_captain_vice(
            scenarios=(
                Scenario(
                    "s", "d", 1.0, {"A": 1, "B": 1, "C": 1}, {"A": True, "B": True, "C": True}
                ),
            ),
            base_tactic=tactic(),
            players={},
            rules=Rules(),
            candidate_ids=candidate_ids,
            evaluator=evaluator,
        )
    assert exc.value.code == "CHIP_CAPTAIN_CANDIDATES_INVALID"


def test_missing_candidate_in_scenario_universe_fails() -> None:
    with pytest.raises(ChipError) as exc:
        optimise_captain_vice(
            scenarios=(Scenario("s", "d", 1.0, {"A": 1}, {"A": True}),),
            base_tactic=replace(tactic(), starting_xi=("A", "B")),
            players={},
            rules=Rules(),
            evaluator=evaluator,
        )
    assert exc.value.code == "CHIP_CAPTAIN_SCENARIO_UNIVERSE"


@pytest.mark.parametrize(
    "base_tactic",
    [SimpleNamespace(), SimpleNamespace(starting_xi=("A", "A"))],
)
def test_invalid_tactic_contract_fails(base_tactic) -> None:
    with pytest.raises(ChipError) as exc:
        optimise_captain_vice(
            scenarios=(Scenario("s", "d", 1.0, {"A": 1, "B": 1}, {"A": True, "B": True}),),
            base_tactic=base_tactic,
            players={},
            rules=Rules(),
            evaluator=evaluator,
        )
    assert exc.value.code == "CHIP_TACTIC_INVALID"


def test_unsupported_copy_adapter_fails_explicitly() -> None:
    base = SimpleNamespace(starting_xi=("A", "B"), captain="A", vice_captain="B")
    with pytest.raises(ChipError) as exc:
        optimise_captain_vice(
            scenarios=(Scenario("s", "d", 1.0, {"A": 1, "B": 1}, {"A": True, "B": True}),),
            base_tactic=base,
            players={},
            rules=Rules(),
            evaluator=evaluator,
        )
    assert exc.value.code == "CHIP_ADAPTER_COPY_UNSUPPORTED"


def test_invalid_multiplier_resolution_effective_id_and_score_fail() -> None:
    scenario = Scenario("s", "d", 1.0, {"A": 1, "B": 1}, {"A": True, "B": True})
    for rules in (
        replace(Rules(), captain_multiplier=0),
        replace(Rules(), captain_multiplier=True),
    ):
        with pytest.raises(ChipError) as exc:
            optimise_captain_vice(
                scenarios=(scenario,),
                base_tactic=replace(tactic(), starting_xi=("A", "B")),
                players={},
                rules=rules,
                evaluator=evaluator,
            )
        assert exc.value.code == "CHIP_CAPTAIN_MULTIPLIER_INVALID"

    def invalid_resolution(*args):
        return Score(1, "A", "UNKNOWN"), None

    with pytest.raises(ChipError) as exc:
        optimise_captain_vice(
            scenarios=(scenario,),
            base_tactic=replace(tactic(), starting_xi=("A", "B")),
            players={},
            rules=Rules(),
            evaluator=invalid_resolution,
        )
    assert exc.value.code == "CHIP_CAPTAIN_RESOLUTION_INVALID"

    def invalid_player(*args):
        return Score(1, "Z", "CAPTAIN"), None

    with pytest.raises(ChipError) as exc:
        optimise_captain_vice(
            scenarios=(scenario,),
            base_tactic=replace(tactic(), starting_xi=("A", "B")),
            players={},
            rules=Rules(),
            evaluator=invalid_player,
        )
    assert exc.value.code == "CHIP_EFFECTIVE_CAPTAIN_UNKNOWN"

    def invalid_score(*args):
        return Score(float("inf"), "A", "CAPTAIN"), None

    with pytest.raises(ChipError) as exc:
        optimise_captain_vice(
            scenarios=(scenario,),
            base_tactic=replace(tactic(), starting_xi=("A", "B")),
            players={},
            rules=Rules(),
            evaluator=invalid_score,
        )
    assert exc.value.code == "CHIP_CAPTAIN_SCORE_INVALID"


def test_tc_requires_bundle_definition_and_matching_lineage() -> None:
    scenario = Scenario("s", "d", 1.0, {"A": 2, "B": 1}, {"A": True, "B": True})
    bundle = bundle_for()
    inventory, token_id = inventory_for(bundle)
    with pytest.raises(ChipError) as exc:
        evaluate_triple_captain(
            scenarios=(scenario,),
            base_tactic=replace(tactic(), starting_xi=("A", "B")),
            players={},
            rules=Rules(),
            chip_bundle=bundle.definition_for("TRIPLE_CAPTAIN"),
            inventory=inventory,
            token_id=token_id,
            evaluator=evaluator,
        )
    assert exc.value.code == "CHIP_RULESET_LINEAGE_REQUIRED"

    missing = bundle_for(tc_definition(key="OTHER"))
    with pytest.raises(ChipError) as exc:
        evaluate_triple_captain(
            scenarios=(scenario,),
            base_tactic=replace(tactic(), starting_xi=("A", "B")),
            players={},
            rules=Rules(),
            chip_bundle=missing,
            inventory=build_chip_inventory(missing, current_gameweek=1),
            token_id="missing",
            evaluator=evaluator,
        )
    assert exc.value.code == "CHIP_TC_DEFINITION_MISSING"

    with pytest.raises(ChipError) as exc:
        evaluate((scenario,), rules=replace(Rules(), ruleset_hash="b" * 64))
    assert exc.value.code == "CHIP_RULESET_LINEAGE_MISMATCH"


def test_tc_definition_semantics_fail_closed() -> None:
    scenario = Scenario("s", "d", 1.0, {"A": 2, "B": 1}, {"A": True, "B": True})
    blocked = bundle_for(
        tc_definition(effects=(ChipEffect(surface="UNKNOWN", operation="UNKNOWN", parameters={}),))
    )
    with pytest.raises(ChipError) as exc:
        evaluate((scenario,), bundle=blocked)
    assert exc.value.code == "CHIP_EFFECT_BLOCKED"

    missing_effect_bundle = bundle_for(
        tc_definition(
            effects=(
                ChipEffect(surface="SCORING", operation="ADD_POINTS", parameters={"points": 1}),
            )
        )
    )
    with pytest.raises(ChipError) as exc:
        evaluate((scenario,), bundle=missing_effect_bundle)
    assert exc.value.code == "CHIP_TC_EFFECT_MISSING"

    with pytest.raises(ChipError) as exc:
        evaluate((scenario,), bundle=bundle_for(tc_definition(multiplier=2)))
    assert exc.value.code == "CHIP_TC_MULTIPLIER_INVALID"

    with pytest.raises(ChipError) as exc:
        evaluate((scenario,), bundle=bundle_for(tc_definition(vice_fallback=False)))
    assert exc.value.code == "CHIP_TC_FALLBACK_MISMATCH"


def test_tc_token_mismatch_and_unavailable_fail_closed() -> None:
    scenario = Scenario("s", "d", 1.0, {"A": 2, "B": 1}, {"A": True, "B": True})
    bundle = bundle_for(tc_definition(), tc_definition(key="OTHER"))
    inventory = build_chip_inventory(bundle, current_gameweek=1)
    other = next(item for item in inventory.tokens if item.chip_key == "OTHER")
    with pytest.raises(ChipError) as exc:
        evaluate_triple_captain(
            scenarios=(scenario,),
            base_tactic=replace(tactic(), starting_xi=("A", "B")),
            players={},
            rules=Rules(),
            chip_bundle=bundle,
            inventory=inventory,
            token_id=other.token_id,
            evaluator=evaluator,
        )
    assert exc.value.code == "CHIP_TC_TOKEN_MISMATCH"

    expired = build_chip_inventory(bundle_for(), current_gameweek=20)
    token_id = expired.tokens[0].token_id
    assert expired.tokens[0].status is TokenStatus.EXPIRED
    with pytest.raises(ChipError) as exc:
        evaluate_triple_captain(
            scenarios=(scenario,),
            base_tactic=replace(tactic(), starting_xi=("A", "B")),
            players={},
            rules=Rules(),
            chip_bundle=bundle_for(),
            inventory=expired,
            token_id=token_id,
            evaluator=evaluator,
        )
    assert exc.value.code == "CHIP_TC_TOKEN_UNAVAILABLE"


def test_hash_and_arithmetic_models_reject_tampering() -> None:
    result = evaluate(
        (Scenario("s", "d", 1.0, {"A": 3, "B": 2}, {"A": True, "B": True}),),
        candidate_ids=("A", "B"),
    )
    ordinary_payload = result.ordinary.model_dump(mode="python")
    ordinary_payload["decision_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="decision hash mismatch"):
        type(result.ordinary).model_validate(ordinary_payload)
    payload = result.model_dump(mode="python")
    payload["evaluation_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="evaluation hash mismatch"):
        type(result).model_validate(payload)
    scenario_payload = result.scenario_values[0].model_dump(mode="python")
    scenario_payload["gross_increment"] += 1.0
    with pytest.raises(ValidationError, match="gross scenario increment"):
        type(result.scenario_values[0]).model_validate(scenario_payload)


def test_evaluation_hash_is_reproducible() -> None:
    scenario = Scenario("s", "d", 1.0, {"A": 3, "B": 2}, {"A": True, "B": True})
    first = evaluate((scenario,), candidate_ids=("A", "B"))
    second = evaluate((scenario,), candidate_ids=("A", "B"))
    assert first == second
    assert first.evaluation_hash == second.evaluation_hash
    payload = first.model_dump(mode="json", exclude={"evaluation_hash"})
    assert semantic_sha256(payload) == first.evaluation_hash


@dataclass(frozen=True)
class BareRules:
    captain_multiplier: int = 2
    vice_captain_fallback: bool = True


@dataclass(frozen=True)
class BareScenario:
    scenario_id: str
    outcome_draw_id: str
    weight: float
    player_points: dict[str, int]


def test_optional_scenario_context_and_rules_lineage_are_not_fabricated() -> None:
    scenario = BareScenario("bare", "draw", 1.0, {"A": 4, "B": 3})

    def bare_evaluator(scenario, tactic, players, rules):
        del players
        points = sum(scenario.player_points[player] for player in tactic.starting_xi)
        points += (rules.captain_multiplier - 1) * scenario.player_points[tactic.captain]
        return Score(points, tactic.captain, "CAPTAIN"), None

    bundle = bundle_for()
    inventory, token_id = inventory_for(bundle)
    result = evaluate_triple_captain(
        scenarios=(scenario,),
        base_tactic=replace(tactic(), starting_xi=("A", "B")),
        players={},
        rules=BareRules(),
        chip_bundle=bundle,
        inventory=inventory,
        token_id=token_id,
        evaluator=bare_evaluator,
    )
    assert result.gross_current_gain == 4.0


def test_empty_candidate_declaration_does_not_fall_back_to_starting_xi() -> None:
    with pytest.raises(ChipError) as exc:
        optimise_captain_vice(
            scenarios=(Scenario("s", "d", 1.0, {"A": 1, "B": 1}, {"A": True, "B": True}),),
            base_tactic=replace(tactic(), starting_xi=("A", "B")),
            players={},
            rules=Rules(),
            candidate_ids=(),
            evaluator=evaluator,
        )
    assert exc.value.code == "CHIP_CAPTAIN_CANDIDATES_INVALID"


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"captain_resolution": "NEITHER", "effective_captain_id": "A"}, "NEITHER"),
        ({"captain_resolution": "CAPTAIN", "effective_captain_id": None}, "requires"),
    ],
)
def test_captain_scenario_contract_rejects_resolution_mismatch(update, message) -> None:
    result = evaluate(
        (Scenario("s", "d", 1.0, {"A": 3, "B": 2}, {"A": True, "B": True}),),
        candidate_ids=("A", "B"),
    )
    payload = result.ordinary.scenario_scores[0].model_dump(mode="python")
    payload.update(update)
    with pytest.raises(ValidationError, match=message):
        type(result.ordinary.scenario_scores[0]).model_validate(payload)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload.update(vice_captain=payload["captain"]), "must differ"),
        (lambda payload: payload.update(scenario_scores=()), "non-empty"),
        (
            lambda payload: payload.update(
                scenario_scores=({**payload["scenario_scores"][0], "weight": 0.5},)
            ),
            "sum to one",
        ),
        (
            lambda payload: payload.update(
                expected_manager_points=payload["expected_manager_points"] + 1.0
            ),
            "expected manager points",
        ),
    ],
)
def test_captain_decision_contract_rejects_semantic_tampering(mutator, message) -> None:
    result = evaluate(
        (Scenario("s", "d", 1.0, {"A": 3, "B": 2}, {"A": True, "B": True}),),
        candidate_ids=("A", "B"),
    )
    payload = result.ordinary.model_dump(mode="python")
    mutator(payload)
    with pytest.raises(ValidationError, match=message):
        type(result.ordinary).model_validate(payload)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload.update(rule_multiplier=2), "must exceed"),
        (
            lambda payload: payload.update(rule_multiplier=4),
            "wrong multiplier",
        ),
        (
            lambda payload: payload["scenario_values"][0].update(scenario_id="other"),
            "same ordered scenario",
        ),
        (
            lambda payload: payload.update(gross_current_gain=payload["gross_current_gain"] + 1.0),
            "gross gain",
        ),
        (lambda payload: payload.update(zero_extra_score=True), "zero-extra"),
        (
            lambda payload: payload.update(
                inventory_after_activation_hash=payload["inventory_before_hash"]
            ),
            "change projected inventory",
        ),
    ],
)
def test_triple_captain_contract_rejects_semantic_tampering(mutator, message) -> None:
    result = evaluate(
        (Scenario("s", "d", 1.0, {"A": 3, "B": 2}, {"A": True, "B": True}),),
        candidate_ids=("A", "B"),
    )
    payload = result.model_dump(mode="python")
    mutator(payload)
    with pytest.raises(ValidationError, match=message):
        type(result).model_validate(payload)
