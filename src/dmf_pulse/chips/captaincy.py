"""Joint captain/vice and Triple Captain evaluation on common Stage-9 scenarios."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from math import fsum, isfinite
from typing import Any, Protocol, TypeVar, cast

from dmf_pulse.chips.definitions import (
    ActivationStatus,
    CompiledChipBundle,
    CompiledChipDefinition,
    semantic_sha256,
)
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import ChipInventory, TokenStatus, activate_token
from dmf_pulse.chips.policy_models import (
    CaptainResolution,
    CaptainScenarioScore,
    CaptainViceDecision,
    ScenarioPolicyValue,
    TripleCaptainEvaluation,
)


class ScenarioLike(Protocol):
    scenario_id: str
    outcome_draw_id: str
    weight: float
    player_points: Mapping[str, int]


class ScoreLike(Protocol):
    manager_points: int
    effective_captain_id: str | None
    captain_resolution: Any


ScenarioT = TypeVar("ScenarioT", bound=ScenarioLike)
Evaluator = Callable[[ScenarioT, Any, dict[str, Any], Any], tuple[ScoreLike, Any]]


def _copy_with(value: Any, **updates: object) -> Any:
    copier = getattr(value, "model_copy", None)
    if callable(copier):
        return copier(update=updates)
    try:
        return replace(value, **updates)
    except (TypeError, ValueError) as exc:
        raise ChipError(
            "CHIP_ADAPTER_COPY_UNSUPPORTED",
            "tactical/rules adapter must support Pydantic model_copy or dataclass replace",
            type=type(value).__name__,
        ) from exc


def _resolution_token(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _normalised_scenarios(scenarios: Iterable[ScenarioT]) -> tuple[ScenarioT, ...]:
    items = tuple(scenarios)
    if not items:
        raise ChipError("CHIP_SCENARIOS_EMPTY", "captain evaluation requires common scenarios")
    identities = tuple((item.scenario_id, item.outcome_draw_id) for item in items)
    scenario_ids = tuple(item.scenario_id for item in items)
    if any(not scenario_id or not outcome_id for scenario_id, outcome_id in identities):
        raise ChipError("CHIP_SCENARIO_ID_INVALID", "scenario identities must be non-empty")
    if len(identities) != len(set(identities)) or len(scenario_ids) != len(set(scenario_ids)):
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


def _default_evaluator() -> Evaluator[Any]:
    from dmf_pulse.optimisation.autosub_evaluator import evaluate_scenario

    return cast(Evaluator[Any], evaluate_scenario)


def _starting_xi(base_tactic: Any) -> tuple[str, ...]:
    raw = getattr(base_tactic, "starting_xi", None)
    if not isinstance(raw, tuple) or not raw:
        raise ChipError(
            "CHIP_TACTIC_INVALID",
            "accepted tactical configuration must expose a non-empty starting_xi tuple",
        )
    starting_xi = tuple(str(item) for item in raw)
    if len(starting_xi) != len(set(starting_xi)):
        raise ChipError("CHIP_TACTIC_INVALID", "starting XI player IDs must be unique")
    return starting_xi


def _captain_multiplier(rules: Any) -> int:
    raw = getattr(rules, "captain_multiplier", None)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        raise ChipError(
            "CHIP_CAPTAIN_MULTIPLIER_INVALID",
            "captain multiplier must be a positive integer",
            multiplier=raw,
        )
    return raw


def _assert_rules_lineage(rules: Any, bundle: CompiledChipBundle) -> None:
    lineage = (
        getattr(rules, "ruleset_id", None),
        getattr(rules, "ruleset_version", None),
        getattr(rules, "ruleset_hash", None),
    )
    expected = (bundle.ruleset_id, bundle.ruleset_version, bundle.ruleset_hash)
    if all(item is None for item in lineage):
        return
    if lineage != expected:
        raise ChipError(
            "CHIP_RULESET_LINEAGE_MISMATCH",
            "tactical rules and compiled chip rules have different lineage",
            observed=lineage,
            expected=expected,
        )


def _scenario_hash(common: tuple[ScenarioT, ...]) -> str:
    payload: list[dict[str, object]] = []
    for item in common:
        scenario: dict[str, object] = {
            "scenario_id": item.scenario_id,
            "outcome_draw_id": item.outcome_draw_id,
            "weight": float(item.weight),
            "player_points": dict(sorted(item.player_points.items())),
        }
        appearances = getattr(item, "player_appeared", None)
        if isinstance(appearances, Mapping):
            scenario["player_appeared"] = dict(sorted(appearances.items()))
        for name in ("gameweek_id", "assembly_mode"):
            value = getattr(item, name, None)
            if value is not None:
                scenario[name] = str(getattr(value, "value", value))
        fixture_ids = getattr(item, "fixture_ids", None)
        if fixture_ids is not None:
            scenario["fixture_ids"] = tuple(str(value) for value in fixture_ids)
        payload.append(scenario)
    return semantic_sha256(payload)


def optimise_captain_vice(
    *,
    scenarios: Iterable[ScenarioT],
    base_tactic: Any,
    players: dict[str, Any],
    rules: Any,
    candidate_ids: Sequence[str] | None = None,
    captain_multiplier: int | None = None,
    evaluator: Evaluator[ScenarioT] | None = None,
) -> CaptainViceDecision:
    """Enumerate ordered captain/vice pairs using the accepted exact evaluator.

    Vice is valued only through conditional fallback in each common scenario;
    it is never selected as the second-highest independent mean.
    """

    common = _normalised_scenarios(scenarios)
    starting_xi = _starting_xi(base_tactic)
    declared_candidates = starting_xi if candidate_ids is None else candidate_ids
    candidates = tuple(sorted(str(item) for item in declared_candidates))
    if (
        len(candidates) < 2
        or len(candidates) != len(set(candidates))
        or not set(candidates) <= set(starting_xi)
    ):
        raise ChipError(
            "CHIP_CAPTAIN_CANDIDATES_INVALID",
            "captain candidates must contain at least two unique starting-XI players",
        )
    missing = tuple(
        (scenario.scenario_id, candidate)
        for scenario in common
        for candidate in candidates
        if candidate not in scenario.player_points
    )
    if missing:
        raise ChipError(
            "CHIP_CAPTAIN_SCENARIO_UNIVERSE",
            "captain candidates must exist in every common Stage-9 scenario",
            missing=missing,
        )

    active_rules = (
        _copy_with(rules, captain_multiplier=captain_multiplier)
        if captain_multiplier is not None
        else rules
    )
    multiplier = _captain_multiplier(active_rules)
    score_scenario = evaluator or _default_evaluator()

    best_key: tuple[float, str, str] | None = None
    best: tuple[
        str,
        str,
        tuple[CaptainScenarioScore, ...],
        float,
        float,
        float,
        float,
        float,
    ] | None = None
    evaluated_pairs = 0
    for captain in candidates:
        for vice in candidates:
            if captain == vice:
                continue
            evaluated_pairs += 1
            tactic = _copy_with(base_tactic, captain=captain, vice_captain=vice)
            scores: list[CaptainScenarioScore] = []
            weighted_manager: list[float] = []
            weighted_effective_raw: list[float] = []
            vice_weight: list[float] = []
            vice_incremental: list[float] = []
            neither_weight: list[float] = []
            for scenario in common:
                score, _ = score_scenario(scenario, tactic, players, active_rules)
                resolution = _resolution_token(score.captain_resolution)
                if resolution not in {"CAPTAIN", "VICE_CAPTAIN", "NEITHER"}:
                    raise ChipError(
                        "CHIP_CAPTAIN_RESOLUTION_INVALID",
                        "accepted tactical evaluator returned an unknown captain resolution",
                        resolution=resolution,
                    )
                effective = score.effective_captain_id
                if effective is not None and effective not in scenario.player_points:
                    raise ChipError(
                        "CHIP_EFFECTIVE_CAPTAIN_UNKNOWN",
                        "effective captain is absent from the common Stage-9 scenario",
                        player_id=effective,
                    )
                raw = 0.0 if effective is None else float(scenario.player_points[effective])
                weight = float(scenario.weight)
                manager_points = float(score.manager_points)
                if not isfinite(manager_points) or not isfinite(raw):
                    raise ChipError(
                        "CHIP_CAPTAIN_SCORE_INVALID",
                        "captain evaluator returned a non-finite score",
                    )
                weighted_manager.append(weight * manager_points)
                weighted_effective_raw.append(weight * raw)
                if resolution == "VICE_CAPTAIN":
                    vice_weight.append(weight)
                    vice_incremental.append(weight * (multiplier - 1) * raw)
                if resolution == "NEITHER":
                    neither_weight.append(weight)
                scores.append(
                    CaptainScenarioScore(
                        scenario_id=scenario.scenario_id,
                        outcome_draw_id=scenario.outcome_draw_id,
                        weight=weight,
                        manager_points=manager_points,
                        effective_captain_id=effective,
                        effective_captain_raw_points=raw,
                        captain_resolution=cast(CaptainResolution, resolution),
                    )
                )
            expected = fsum(weighted_manager)
            expected_raw = fsum(weighted_effective_raw)
            vice_probability = fsum(vice_weight)
            vice_value = fsum(vice_incremental)
            neither_probability = fsum(neither_weight)
            key = (-expected, captain, vice)
            if best_key is None or key < best_key:
                best_key = key
                best = (
                    captain,
                    vice,
                    tuple(scores),
                    expected,
                    expected_raw,
                    vice_probability,
                    vice_value,
                    neither_probability,
                )
    if best is None:  # pragma: no cover - guarded by the candidate contract above
        raise ChipError("CHIP_CAPTAIN_SEARCH_EMPTY", "no legal captain/vice pair was evaluated")
    (
        captain,
        vice,
        scores,
        expected,
        expected_raw,
        vice_probability,
        vice_value,
        neither_probability,
    ) = best
    payload = {
        "captain": captain,
        "vice_captain": vice,
        "captain_multiplier": multiplier,
        "expected_manager_points": expected,
        "expected_effective_captain_raw_points": expected_raw,
        "vice_fallback_probability": vice_probability,
        "vice_fallback_incremental_points": vice_value,
        "captain_and_vice_failure_probability": neither_probability,
        "evaluated_pairs": evaluated_pairs,
        "scenario_scores": [item.model_dump(mode="json") for item in scores],
    }
    return CaptainViceDecision(
        captain=captain,
        vice_captain=vice,
        captain_multiplier=multiplier,
        expected_manager_points=expected,
        expected_effective_captain_raw_points=expected_raw,
        vice_fallback_probability=vice_probability,
        vice_fallback_incremental_points=vice_value,
        captain_and_vice_failure_probability=neither_probability,
        evaluated_pairs=evaluated_pairs,
        scenario_scores=tuple(scores),
        decision_hash=semantic_sha256(payload),
    )


def _tc_definition(compiled: object) -> CompiledChipDefinition:
    if isinstance(compiled, CompiledChipBundle):
        try:
            return compiled.definition_for("TRIPLE_CAPTAIN")
        except KeyError as exc:
            raise ChipError(
                "CHIP_TC_DEFINITION_MISSING",
                "compiled chip bundle does not contain Triple Captain",
            ) from exc
    raise ChipError(
        "CHIP_RULESET_LINEAGE_REQUIRED",
        "Triple Captain evaluation requires the rules-bound compiled chip bundle",
    )


def evaluate_triple_captain(
    *,
    scenarios: Iterable[ScenarioT],
    base_tactic: Any,
    players: dict[str, Any],
    rules: Any,
    chip_bundle: CompiledChipBundle,
    inventory: ChipInventory,
    token_id: str,
    candidate_ids: Sequence[str] | None = None,
    evaluator: Evaluator[ScenarioT] | None = None,
) -> TripleCaptainEvaluation:
    """Compare the best TC captain/vice pair with the best ordinary pair."""

    common = _normalised_scenarios(scenarios)
    definition = _tc_definition(chip_bundle)
    _assert_rules_lineage(rules, chip_bundle)
    if definition.activation_status is not ActivationStatus.READY:
        raise ChipError(
            "CHIP_EFFECT_BLOCKED",
            "Triple Captain definition is blocked",
            blockers=definition.blockers,
        )
    effects = tuple(
        effect
        for effect in definition.definition.effects
        if effect.surface == "CAPTAIN" and effect.operation == "SET_MULTIPLIER"
    )
    if len(effects) != 1:
        raise ChipError(
            "CHIP_TC_EFFECT_MISSING",
            "compiled Triple Captain must expose exactly one captain multiplier effect",
        )
    multiplier_value = effects[0].parameters.get("multiplier")
    if (
        not isinstance(multiplier_value, int) or isinstance(multiplier_value, bool)
    ):  # pragma: no cover - known invalid semantics are blocked by the compiler
        raise ChipError(
            "CHIP_TC_MULTIPLIER_INVALID",
            "Triple Captain multiplier is not an integer",
        )
    multiplier = multiplier_value
    ordinary_multiplier = _captain_multiplier(rules)
    if multiplier <= ordinary_multiplier:
        raise ChipError(
            "CHIP_TC_MULTIPLIER_INVALID",
            "Triple Captain multiplier must exceed the ordinary captain multiplier",
            ordinary_multiplier=ordinary_multiplier,
            chip_multiplier=multiplier,
        )
    vice_fallback = effects[0].parameters.get("vice_fallback")
    accepted_fallback = getattr(rules, "vice_captain_fallback", None)
    if not isinstance(vice_fallback, bool) or vice_fallback != accepted_fallback:
        raise ChipError(
            "CHIP_TC_FALLBACK_MISMATCH",
            "Triple Captain vice fallback differs from the accepted tactical rules view",
        )
    token = inventory.token(token_id)
    if token.chip_key != "TRIPLE_CAPTAIN":
        raise ChipError(
            "CHIP_TC_TOKEN_MISMATCH",
            "Triple Captain evaluation requires a Triple Captain inventory token",
            token_id=token_id,
            chip_key=token.chip_key,
        )
    if token.status not in {TokenStatus.AVAILABLE, TokenStatus.PENDING_CANCELLABLE}:
        raise ChipError(
            "CHIP_TC_TOKEN_UNAVAILABLE",
            "Triple Captain token is not available for projected activation",
            token_id=token_id,
            status=token.status,
        )
    projected_inventory = activate_token(inventory, chip_bundle, token_id=token_id)
    ordinary = optimise_captain_vice(
        scenarios=common,
        base_tactic=base_tactic,
        players=players,
        rules=rules,
        candidate_ids=candidate_ids,
        evaluator=evaluator,
    )
    triple = optimise_captain_vice(
        scenarios=common,
        base_tactic=base_tactic,
        players=players,
        rules=rules,
        candidate_ids=candidate_ids,
        captain_multiplier=multiplier,
        evaluator=evaluator,
    )
    ordinary_scores = {
        (item.scenario_id, item.outcome_draw_id): item for item in ordinary.scenario_scores
    }
    scenario_values: list[ScenarioPolicyValue] = []
    for item in triple.scenario_scores:
        baseline = ordinary_scores[(item.scenario_id, item.outcome_draw_id)]
        increment = item.manager_points - baseline.manager_points
        scenario_values.append(
            ScenarioPolicyValue(
                scenario_id=item.scenario_id,
                outcome_draw_id=item.outcome_draw_id,
                weight=item.weight,
                no_chip_points=baseline.manager_points,
                chip_points=item.manager_points,
                gross_increment=increment,
                policy_increment=increment,
            )
        )
    gross = triple.expected_manager_points - ordinary.expected_manager_points
    scenario_set_hash = _scenario_hash(common)
    payload = {
        "chip_key": "TRIPLE_CAPTAIN",
        "rule_multiplier": multiplier,
        "ordinary": ordinary.model_dump(mode="json"),
        "triple_captain": triple.model_dump(mode="json"),
        "scenario_values": [item.model_dump(mode="json") for item in scenario_values],
        "gross_current_gain": gross,
        "chip_consumed": True,
        "zero_extra_score": abs(gross) <= 1e-12,
        "token_id": token_id,
        "inventory_before_hash": inventory.inventory_hash,
        "inventory_after_activation_hash": projected_inventory.inventory_hash,
        "scenario_set_hash": scenario_set_hash,
        "ruleset_id": chip_bundle.ruleset_id,
        "ruleset_version": chip_bundle.ruleset_version,
        "ruleset_hash": chip_bundle.ruleset_hash,
        "chip_definition_hash": definition.definition_hash,
    }
    return TripleCaptainEvaluation(
        chip_key="TRIPLE_CAPTAIN",
        rule_multiplier=multiplier,
        ordinary=ordinary,
        triple_captain=triple,
        scenario_values=tuple(scenario_values),
        gross_current_gain=gross,
        chip_consumed=True,
        zero_extra_score=abs(gross) <= 1e-12,
        token_id=token_id,
        inventory_before_hash=inventory.inventory_hash,
        inventory_after_activation_hash=projected_inventory.inventory_hash,
        scenario_set_hash=scenario_set_hash,
        ruleset_id=chip_bundle.ruleset_id,
        ruleset_version=chip_bundle.ruleset_version,
        ruleset_hash=chip_bundle.ruleset_hash,
        chip_definition_hash=definition.definition_hash,
        evaluation_hash=semantic_sha256(payload),
    )
