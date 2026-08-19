"""Bench Boost incremental policy valuation on common coherent scenarios."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from math import fsum, isfinite
from typing import Any, Protocol, cast

from dmf_pulse.chips.definitions import (
    ActivationStatus,
    CompiledChipBundle,
    CompiledChipDefinition,
    semantic_sha256,
)
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import ChipInventory, TokenStatus, activate_token
from dmf_pulse.chips.policy_models import (
    BenchBoostCostProfile,
    BenchBoostEvaluation,
    BenchBoostRouteEvaluation,
    BenchBoostScenarioValue,
    WildcardBenchBoostSynergy,
)


class ScenarioLike(Protocol):
    scenario_id: str
    outcome_draw_id: str
    weight: float
    player_points: Mapping[str, int]
    player_appeared: Mapping[str, bool]


class ScoreLike(Protocol):
    manager_points: int
    counted_player_ids: Sequence[str]


type Evaluator[ScenarioT: ScenarioLike] = Callable[
    [ScenarioT, Any, dict[str, Any], Any], tuple[ScoreLike, Any]
]


def _default_evaluator() -> Evaluator[Any]:
    from dmf_pulse.optimisation.autosub_evaluator import evaluate_scenario

    return cast(Evaluator[Any], evaluate_scenario)


def _normalised_scenarios[ScenarioT: ScenarioLike](
    scenarios: Iterable[ScenarioT],
) -> tuple[ScenarioT, ...]:
    items = tuple(scenarios)
    if not items:
        raise ChipError("CHIP_SCENARIOS_EMPTY", "Bench Boost evaluation requires scenarios")
    identities = tuple((item.scenario_id, item.outcome_draw_id) for item in items)
    if any(not scenario_id or not draw_id for scenario_id, draw_id in identities):
        raise ChipError("CHIP_SCENARIO_ID_INVALID", "scenario identities must be non-empty")
    if len(identities) != len(set(identities)):
        raise ChipError("CHIP_SCENARIOS_DUPLICATE", "scenario identities must be unique")
    weights = tuple(float(item.weight) for item in items)
    if any(not isfinite(weight) or weight <= 0.0 or weight > 1.0 for weight in weights):
        raise ChipError("CHIP_SCENARIO_WEIGHT_INVALID", "scenario weights must be probabilities")
    total = fsum(weights)
    if abs(total - 1.0) > 1e-9:
        raise ChipError(
            "CHIP_SCENARIO_WEIGHT_SUM",
            "scenario weights must sum to one",
            observed=total,
        )
    return tuple(sorted(items, key=lambda item: (item.scenario_id, item.outcome_draw_id)))


def _scenario_set_hash[ScenarioT: ScenarioLike](
    scenarios: tuple[ScenarioT, ...],
) -> str:
    payload: list[dict[str, object]] = []
    for scenario in scenarios:
        item: dict[str, object] = {
            "scenario_id": scenario.scenario_id,
            "outcome_draw_id": scenario.outcome_draw_id,
            "weight": float(scenario.weight),
            "player_points": dict(sorted(scenario.player_points.items())),
            "player_appeared": dict(sorted(scenario.player_appeared.items())),
        }
        fixture_ids = getattr(scenario, "fixture_ids", None)
        if fixture_ids is not None:
            item["fixture_ids"] = tuple(str(value) for value in fixture_ids)
        gameweek_id = getattr(scenario, "gameweek_id", None)
        if gameweek_id is not None:
            item["gameweek_id"] = str(gameweek_id)
        payload.append(item)
    return semantic_sha256(payload)


def _bench_ids(tactic: Any) -> tuple[str, str, str, str]:
    goalkeeper = getattr(tactic, "bench_goalkeeper", None)
    order = getattr(tactic, "bench_order", None)
    if order is None:
        order = getattr(tactic, "outfield_bench_order", None)
    if not isinstance(goalkeeper, str) or not goalkeeper:
        raise ChipError("CHIP_BB_TACTIC_INVALID", "Bench Boost tactic requires a bench goalkeeper")
    if not isinstance(order, tuple) or len(order) != 3:
        raise ChipError(
            "CHIP_BB_TACTIC_INVALID", "Bench Boost tactic requires three outfield bench slots"
        )
    bench = (goalkeeper, *(str(item) for item in order))
    if any(not player_id for player_id in bench) or len(bench) != len(set(bench)):
        raise ChipError(
            "CHIP_BB_TACTIC_INVALID", "Bench Boost bench IDs must be non-empty and unique"
        )
    return cast(tuple[str, str, str, str], bench)


def _tactic_signature(tactic: Any) -> str:
    starting_xi = getattr(tactic, "starting_xi", None)
    if not isinstance(starting_xi, tuple) or not starting_xi:
        raise ChipError("CHIP_BB_TACTIC_INVALID", "Bench Boost tactic requires a starting XI")
    bench = _bench_ids(tactic)
    payload = {
        "starting_xi": tuple(str(item) for item in starting_xi),
        "bench": bench,
        "captain": str(getattr(tactic, "captain", "")),
        "vice_captain": str(getattr(tactic, "vice_captain", "")),
    }
    return semantic_sha256(payload)


def _assert_rules_lineage(rules: Any, bundle: CompiledChipBundle) -> None:
    observed = (
        getattr(rules, "ruleset_id", None),
        getattr(rules, "ruleset_version", None),
        getattr(rules, "ruleset_hash", None),
    )
    expected = (bundle.ruleset_id, bundle.ruleset_version, bundle.ruleset_hash)
    if all(value is None for value in observed):
        return
    if observed != expected:
        raise ChipError(
            "CHIP_RULESET_LINEAGE_MISMATCH",
            "tactical rules and compiled chip rules have different lineage",
            observed=observed,
            expected=expected,
        )


def _bb_definition(bundle: CompiledChipBundle) -> CompiledChipDefinition:
    try:
        definition = bundle.definition_for("BENCH_BOOST")
    except KeyError as exc:
        raise ChipError(
            "CHIP_BB_DEFINITION_MISSING",
            "compiled chip bundle does not contain Bench Boost",
        ) from exc
    if definition.activation_status is not ActivationStatus.READY:
        raise ChipError(
            "CHIP_EFFECT_BLOCKED",
            "Bench Boost definition is blocked",
            blockers=definition.blockers,
        )
    effects = tuple(
        effect
        for effect in definition.definition.effects
        if effect.surface == "LINEUP" and effect.operation == "INCLUDE_BENCH_POINTS"
    )
    if len(effects) != 1:
        raise ChipError(
            "CHIP_BB_EFFECT_MISSING",
            "compiled Bench Boost must expose exactly one include-bench-points effect",
        )
    return definition


def _evaluate_candidate[ScenarioT: ScenarioLike](
    *,
    scenarios: tuple[ScenarioT, ...],
    tactic: Any,
    players: dict[str, Any],
    rules: Any,
    evaluator: Evaluator[ScenarioT],
) -> tuple[str, tuple[BenchBoostScenarioValue, ...], float, float]:
    signature = _tactic_signature(tactic)
    bench = _bench_ids(tactic)
    values: list[BenchBoostScenarioValue] = []
    weighted_normal: list[float] = []
    weighted_bb: list[float] = []
    for scenario in scenarios:
        missing = tuple(player_id for player_id in bench if player_id not in scenario.player_points)
        if missing:
            raise ChipError(
                "CHIP_BB_SCENARIO_UNIVERSE",
                "every bench player must exist in every common scenario",
                scenario_id=scenario.scenario_id,
                missing=missing,
            )
        score, _ = evaluator(scenario, tactic, players, rules)
        normal_points = float(score.manager_points)
        if not isfinite(normal_points):
            raise ChipError("CHIP_BB_SCORE_INVALID", "normal tactical score is not finite")
        counted = tuple(str(item) for item in score.counted_player_ids)
        if len(counted) != len(set(counted)):
            raise ChipError("CHIP_BB_COUNTED_INVALID", "normal counted-player IDs must be unique")
        appeared = scenario.player_appeared
        bench_appeared = tuple(player_id for player_id in bench if appeared.get(player_id, False))
        bench_points = float(
            fsum(float(scenario.player_points[player_id]) for player_id in bench_appeared)
        )
        overlap_players = tuple(player_id for player_id in bench_appeared if player_id in counted)
        overlap_points = float(
            fsum(float(scenario.player_points[player_id]) for player_id in overlap_players)
        )
        incremental = bench_points - overlap_points
        bb_points = normal_points + incremental
        if not all(
            isfinite(value) for value in (bench_points, overlap_points, incremental, bb_points)
        ):
            raise ChipError("CHIP_BB_SCORE_INVALID", "Bench Boost score is not finite")
        weight = float(scenario.weight)
        weighted_normal.append(weight * normal_points)
        weighted_bb.append(weight * bb_points)
        values.append(
            BenchBoostScenarioValue(
                scenario_id=scenario.scenario_id,
                outcome_draw_id=scenario.outcome_draw_id,
                weight=weight,
                normal_points=normal_points,
                bench_boost_points=bb_points,
                gross_increment=incremental,
                bench_appeared_ids=bench_appeared,
                normal_autosub_overlap_ids=overlap_players,
                bench_raw_points=bench_points,
                autosub_overlap_points=overlap_points,
            )
        )
    return signature, tuple(values), fsum(weighted_normal), fsum(weighted_bb)


def _evaluate_route[ScenarioT: ScenarioLike](
    *,
    plan_id: str,
    scenarios: tuple[ScenarioT, ...],
    tactical_candidates: Sequence[Any],
    players: dict[str, Any],
    rules: Any,
    costs: BenchBoostCostProfile,
    evaluator: Evaluator[ScenarioT],
) -> BenchBoostRouteEvaluation:
    candidates = tuple(tactical_candidates)
    if not candidates:
        raise ChipError(
            "CHIP_BB_CANDIDATES_EMPTY", "Bench Boost route requires tactical candidates"
        )
    evaluated = tuple(
        _evaluate_candidate(
            scenarios=scenarios,
            tactic=tactic,
            players=players,
            rules=rules,
            evaluator=evaluator,
        )
        for tactic in candidates
    )
    signatures = tuple(item[0] for item in evaluated)
    if len(signatures) != len(set(signatures)):
        raise ChipError(
            "CHIP_BB_CANDIDATES_DUPLICATE", "Bench Boost tactic candidates must be unique"
        )
    normal = min(evaluated, key=lambda item: (-item[2], item[0]))
    boosted = min(evaluated, key=lambda item: (-item[3], item[0]))
    normal_values = {(item.scenario_id, item.outcome_draw_id): item for item in normal[1]}
    comparative: list[BenchBoostScenarioValue] = []
    for item in boosted[1]:
        baseline = normal_values[(item.scenario_id, item.outcome_draw_id)]
        gross = item.bench_boost_points - baseline.normal_points
        comparative.append(
            item.model_copy(
                update={
                    "normal_points": baseline.normal_points,
                    "gross_increment": gross,
                }
            )
        )
    gross_current_gain = boosted[3] - normal[2]
    net_value = gross_current_gain - costs.total_cost_points
    payload = {
        "plan_id": plan_id,
        "is_natural": costs.is_natural,
        "normal_tactic_signature": normal[0],
        "bench_boost_tactic_signature": boosted[0],
        "expected_normal_points": normal[2],
        "expected_bench_boost_points": boosted[3],
        "gross_current_gain": gross_current_gain,
        "costs": costs.model_dump(mode="json"),
        "net_pre_continuation_value": net_value,
        "evaluated_tactics": len(evaluated),
        "scenario_values": [item.model_dump(mode="json") for item in comparative],
    }
    return BenchBoostRouteEvaluation(
        plan_id=plan_id,
        is_natural=costs.is_natural,
        normal_tactic_signature=normal[0],
        bench_boost_tactic_signature=boosted[0],
        expected_normal_points=normal[2],
        expected_bench_boost_points=boosted[3],
        gross_current_gain=gross_current_gain,
        costs=costs,
        net_pre_continuation_value=net_value,
        evaluated_tactics=len(evaluated),
        scenario_values=tuple(comparative),
        route_hash=semantic_sha256(payload),
    )


def evaluate_bench_boost[ScenarioT: ScenarioLike](
    *,
    scenarios: Iterable[ScenarioT],
    tactical_candidates: Sequence[Any],
    players: dict[str, Any],
    rules: Any,
    chip_bundle: CompiledChipBundle,
    inventory: ChipInventory,
    token_id: str,
    costs: BenchBoostCostProfile,
    wildcard_tactical_candidates: Sequence[Any] | None = None,
    wildcard_costs: BenchBoostCostProfile | None = None,
    evaluator: Evaluator[ScenarioT] | None = None,
) -> BenchBoostEvaluation:
    """Value Bench Boost against the optimised same-state normal tactical policy."""

    common = _normalised_scenarios(scenarios)
    definition = _bb_definition(chip_bundle)
    _assert_rules_lineage(rules, chip_bundle)
    token = inventory.token(token_id)
    if token.chip_key != "BENCH_BOOST":
        raise ChipError(
            "CHIP_BB_TOKEN_MISMATCH",
            "Bench Boost evaluation requires a Bench Boost inventory token",
            token_id=token_id,
            chip_key=token.chip_key,
        )
    if token.status not in {TokenStatus.AVAILABLE, TokenStatus.PENDING_CANCELLABLE}:
        raise ChipError(
            "CHIP_BB_TOKEN_UNAVAILABLE",
            "Bench Boost token is not available for projected activation",
            token_id=token_id,
            status=token.status,
        )
    projected_inventory = activate_token(inventory, chip_bundle, token_id=token_id)
    score_scenario = evaluator or _default_evaluator()
    standalone = _evaluate_route(
        plan_id=costs.plan_id,
        scenarios=common,
        tactical_candidates=tactical_candidates,
        players=players,
        rules=rules,
        costs=costs,
        evaluator=score_scenario,
    )
    wildcard_route: BenchBoostRouteEvaluation | None = None
    synergy: WildcardBenchBoostSynergy | None = None
    if (wildcard_tactical_candidates is None) != (wildcard_costs is None):
        raise ChipError(
            "CHIP_BB_WILDCARD_ROUTE_INCOMPLETE",
            "Wildcard-Bench Boost measurement requires both candidates and costs",
        )
    if wildcard_tactical_candidates is not None and wildcard_costs is not None:
        wildcard_route = _evaluate_route(
            plan_id=wildcard_costs.plan_id,
            scenarios=common,
            tactical_candidates=wildcard_tactical_candidates,
            players=players,
            rules=rules,
            costs=wildcard_costs,
            evaluator=score_scenario,
        )
        measured = wildcard_route.net_pre_continuation_value - standalone.net_pre_continuation_value
        synergy_payload = {
            "standalone_route_hash": standalone.route_hash,
            "wildcard_prepared_route_hash": wildcard_route.route_hash,
            "measured_synergy": measured,
            "positive": measured > 0.0,
        }
        synergy = WildcardBenchBoostSynergy(
            standalone_route_hash=standalone.route_hash,
            wildcard_prepared_route_hash=wildcard_route.route_hash,
            measured_synergy=measured,
            positive=measured > 0.0,
            synergy_hash=semantic_sha256(synergy_payload),
        )
    scenario_hash = _scenario_set_hash(common)
    payload = {
        "chip_key": "BENCH_BOOST",
        "standalone_route": standalone.model_dump(mode="json"),
        "wildcard_prepared_route": (
            wildcard_route.model_dump(mode="json") if wildcard_route is not None else None
        ),
        "wildcard_synergy": synergy.model_dump(mode="json") if synergy is not None else None,
        "chip_consumed": True,
        "continuation_value_included": False,
        "token_id": token_id,
        "inventory_before_hash": inventory.inventory_hash,
        "inventory_after_activation_hash": projected_inventory.inventory_hash,
        "scenario_set_hash": scenario_hash,
        "ruleset_id": chip_bundle.ruleset_id,
        "ruleset_version": chip_bundle.ruleset_version,
        "ruleset_hash": chip_bundle.ruleset_hash,
        "chip_definition_hash": definition.definition_hash,
    }
    return BenchBoostEvaluation(
        chip_key="BENCH_BOOST",
        standalone_route=standalone,
        wildcard_prepared_route=wildcard_route,
        wildcard_synergy=synergy,
        chip_consumed=True,
        continuation_value_included=False,
        token_id=token_id,
        inventory_before_hash=inventory.inventory_hash,
        inventory_after_activation_hash=projected_inventory.inventory_hash,
        scenario_set_hash=scenario_hash,
        ruleset_id=chip_bundle.ruleset_id,
        ruleset_version=chip_bundle.ruleset_version,
        ruleset_hash=chip_bundle.ruleset_hash,
        chip_definition_hash=definition.definition_hash,
        evaluation_hash=semantic_sha256(payload),
    )
