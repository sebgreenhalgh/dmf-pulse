"""Compile accepted rules declarations into generic Stage-14 chip definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dmf_pulse.chips.definitions import (
    ActivationRoute,
    ActivationStatus,
    ChipDefinition,
    ChipEffect,
    CompiledChipBundle,
    CompiledChipDefinition,
    EffectCapability,
    InventoryGrant,
    ParameterValue,
    semantic_sha256,
)

COMPILER_VERSION = "CHIP-014-COMPILER-V1"


@dataclass(frozen=True, slots=True)
class EffectContract:
    required_parameters: frozenset[str]
    optional_parameters: frozenset[str]
    capabilities: frozenset[EffectCapability]


_EFFECTS: dict[tuple[str, str], EffectContract] = {
    ("SCORING", "ADD_POINTS"): EffectContract(
        frozenset({"points"}), frozenset(), frozenset({EffectCapability.SCORING_TRANSFORM})
    ),
    ("SCORING", "MULTIPLY_POINTS"): EffectContract(
        frozenset({"multiplier"}),
        frozenset(),
        frozenset({EffectCapability.SCORING_TRANSFORM}),
    ),
    ("CAPTAIN", "SET_MULTIPLIER"): EffectContract(
        frozenset({"multiplier", "vice_fallback"}),
        frozenset(),
        frozenset({EffectCapability.CAPTAIN_TRANSFORM}),
    ),
    ("LINEUP", "INCLUDE_BENCH_POINTS"): EffectContract(
        frozenset(), frozenset(), frozenset({EffectCapability.BENCH_TRANSFORM})
    ),
    ("LINEUP", "ADD_BENCH_SLOTS"): EffectContract(
        frozenset({"count"}), frozenset(), frozenset({EffectCapability.BENCH_TRANSFORM})
    ),
    ("TRANSFERS", "UNLIMITED_FREE"): EffectContract(
        frozenset(), frozenset(), frozenset({EffectCapability.TRANSFER_TRANSFORM})
    ),
    ("TRANSFERS", "REMOVE_CURRENT_GAMEWEEK_HITS"): EffectContract(
        frozenset(), frozenset(), frozenset({EffectCapability.TRANSFER_TRANSFORM})
    ),
    ("TRANSFERS", "PRESERVE_SAVED_FREE_TRANSFERS"): EffectContract(
        frozenset(),
        frozenset(),
        frozenset(
            {EffectCapability.TRANSFER_TRANSFORM, EffectCapability.FREE_TRANSFER_TRANSFORM}
        ),
    ),
    ("TRANSFERS", "SET_HIT_COST"): EffectContract(
        frozenset({"points_per_paid_transfer"}),
        frozenset(),
        frozenset({EffectCapability.TRANSFER_TRANSFORM}),
    ),
    ("TRANSFERS", "LOCK"): EffectContract(
        frozenset(), frozenset(), frozenset({EffectCapability.TRANSFER_TRANSFORM})
    ),
    ("FREE_TRANSFERS", "SET"): EffectContract(
        frozenset({"value"}),
        frozenset(),
        frozenset({EffectCapability.FREE_TRANSFER_TRANSFORM}),
    ),
    ("FREE_TRANSFERS", "PRESERVE"): EffectContract(
        frozenset(), frozenset(), frozenset({EffectCapability.FREE_TRANSFER_TRANSFORM})
    ),
    ("SQUAD", "TEMPORARY"): EffectContract(
        frozenset(), frozenset(), frozenset({EffectCapability.TEMPORARY_SQUAD})
    ),
    ("SQUAD", "PERMANENT"): EffectContract(
        frozenset(), frozenset(), frozenset({EffectCapability.PERMANENT_SQUAD})
    ),
    ("SQUAD", "RESTORE_NEXT_DEADLINE"): EffectContract(
        frozenset(), frozenset(), frozenset({EffectCapability.RESTORATION})
    ),
    ("BANK", "RESTORE_NEXT_DEADLINE"): EffectContract(
        frozenset(), frozenset(), frozenset({EffectCapability.RESTORATION})
    ),
    ("PURCHASE_PRICES", "RESTORE_NEXT_DEADLINE"): EffectContract(
        frozenset(), frozenset(), frozenset({EffectCapability.RESTORATION})
    ),
    ("BUDGET", "ADD_TEMPORARY"): EffectContract(
        frozenset({"amount_tenths"}),
        frozenset(),
        frozenset({EffectCapability.BUDGET_TRANSFORM}),
    ),
    ("BUDGET", "ADD_PERMANENT"): EffectContract(
        frozenset({"amount_tenths"}),
        frozenset(),
        frozenset({EffectCapability.BUDGET_TRANSFORM}),
    ),
    ("CLUB_LIMIT", "SET"): EffectContract(
        frozenset({"limit"}), frozenset(), frozenset({EffectCapability.CLUB_TRANSFORM})
    ),
    ("POSITION_LIMIT", "SET"): EffectContract(
        frozenset({"position", "minimum", "maximum"}),
        frozenset(),
        frozenset({EffectCapability.POSITION_TRANSFORM}),
    ),
}


def _is_int(value: ParameterValue) -> bool:
    return type(value) is int


def _semantic_blockers(effect: ChipEffect) -> tuple[str, ...]:
    key = (effect.surface, effect.operation)
    contract = _EFFECTS.get(key)
    if contract is None:
        return (f"UNKNOWN_EFFECT:{effect.surface}:{effect.operation}",)
    actual = frozenset(effect.parameters)
    allowed = contract.required_parameters | contract.optional_parameters
    blockers: list[str] = []
    if not contract.required_parameters <= actual or not actual <= allowed:
        blockers.append(f"INVALID_PARAMETERS:{effect.surface}:{effect.operation}")
        return tuple(blockers)

    params = effect.parameters
    if key == ("CAPTAIN", "SET_MULTIPLIER"):
        if (
            not _is_int(params["multiplier"])
            or int(params["multiplier"]) <= 1
            or params["vice_fallback"] is not True
        ):
            blockers.append("INVALID_CAPTAIN_MULTIPLIER")
    elif key == ("SCORING", "MULTIPLY_POINTS"):
        if not _is_int(params["multiplier"]) or int(params["multiplier"]) <= 0:
            blockers.append("INVALID_SCORING_MULTIPLIER")
    elif key in {
        ("LINEUP", "ADD_BENCH_SLOTS"),
        ("FREE_TRANSFERS", "SET"),
        ("CLUB_LIMIT", "SET"),
    }:
        parameter = next(iter(contract.required_parameters))
        if not _is_int(params[parameter]) or int(params[parameter]) < 0:
            blockers.append(f"INVALID_NONNEGATIVE_PARAMETER:{parameter}")
    elif key == ("POSITION_LIMIT", "SET"):
        minimum = params["minimum"]
        maximum = params["maximum"]
        if (
            not isinstance(params["position"], str)
            or not _is_int(minimum)
            or not _is_int(maximum)
            or int(minimum) < 0
            or int(maximum) < int(minimum)
        ):
            blockers.append("INVALID_POSITION_LIMIT")
    elif key == ("TRANSFERS", "SET_HIT_COST"):
        value = params["points_per_paid_transfer"]
        if not _is_int(value) or int(value) > 0:
            blockers.append("INVALID_TRANSFER_HIT_COST")
    elif key in {
        ("BUDGET", "ADD_TEMPORARY"),
        ("BUDGET", "ADD_PERMANENT"),
        ("SCORING", "ADD_POINTS"),
    }:
        parameter = next(iter(contract.required_parameters))
        if not _is_int(params[parameter]):
            blockers.append(f"INVALID_INTEGER_PARAMETER:{parameter}")
    return tuple(blockers)


def compile_chip_definition(definition: ChipDefinition) -> CompiledChipDefinition:
    """Validate one generic definition without assuming a chip name."""

    blockers: list[str] = []
    capabilities: set[EffectCapability] = {EffectCapability.CONFLICT_OCCUPANCY}
    unknown = False
    for effect in definition.effects:
        effect_blockers = _semantic_blockers(effect)
        blockers.extend(effect_blockers)
        contract = _EFFECTS.get((effect.surface, effect.operation))
        if contract is None:
            unknown = True
        else:
            capabilities.update(contract.capabilities)

    if blockers:
        status = (
            ActivationStatus.BLOCKED_UNKNOWN_EFFECT
            if unknown
            else ActivationStatus.BLOCKED_INVALID_SEMANTICS
        )
    else:
        status = ActivationStatus.READY
    return CompiledChipDefinition(
        definition=definition,
        definition_hash=semantic_sha256(definition),
        compiler_version=COMPILER_VERSION,
        activation_status=status,
        capabilities=frozenset(capabilities),
        blockers=tuple(sorted(set(blockers))),
    )


def _field(value: object, name: str) -> Any:
    if isinstance(value, Mapping):
        return value[name]
    return getattr(value, name)


def _optional_field(value: object, name: str, default: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def definition_from_rules_runtime(
    runtime_rule: object,
    *,
    ruleset_version: str,
) -> ChipDefinition:
    """Adapt a rules-layer RuntimeChipRule using its public fields only."""

    key = str(_field(runtime_rule, "key"))
    copies = int(_field(runtime_rule, "copies_per_window"))
    windows = tuple(_field(runtime_rule, "windows"))
    grants = tuple(
        InventoryGrant(
            grant_id=f"window-{index + 1}",
            copies=copies,
            acquired_gameweek=int(_field(window, "start_gameweek")),
            activation_start_gameweek=int(_field(window, "start_gameweek")),
            activation_end_gameweek=int(_field(window, "end_gameweek")),
            expires_after_gameweek=int(_field(window, "end_gameweek")),
        )
        for index, window in enumerate(windows)
    )
    effects = tuple(
        ChipEffect(
            surface=str(_field(effect, "surface")),
            operation=str(_field(effect, "operation")),
            parameters=dict(_field(effect, "parameters")),
        )
        for effect in tuple(_field(runtime_rule, "effects"))
    )
    route = ActivationRoute(str(_field(runtime_rule, "activation_route")))
    return ChipDefinition(
        chip_key=key,
        definition_version=f"{ruleset_version}:{key}",
        grants=grants,
        duration_gameweeks=int(_field(runtime_rule, "duration_gameweeks")),
        concurrency_group=str(_field(runtime_rule, "concurrency_group")),
        activation_route=route,
        cancellable_before_lock=bool(_field(runtime_rule, "cancellable_before_deadline")),
        lock_after_confirmed_transfer_count=_optional_field(
            runtime_rule, "lock_after_confirmed_transfer_count", None
        ),
        excluded_gameweeks=tuple(int(item) for item in _field(runtime_rule, "excluded_gameweeks")),
        minimum_gap_gameweeks=int(_field(runtime_rule, "minimum_gap_gameweeks")),
        effects=effects,
    )


def compile_optimisation_chip_rules(rules_view: object) -> CompiledChipBundle:
    """Compile an accepted rules-layer ChipRulesView into Stage-14 contracts."""

    definitions = tuple(
        compile_chip_definition(
            definition_from_rules_runtime(
                item,
                ruleset_version=str(_field(rules_view, "ruleset_version")),
            )
        )
        for item in tuple(_field(rules_view, "chips"))
    )
    ruleset_id = str(_field(rules_view, "ruleset_id"))
    ruleset_version = str(_field(rules_view, "ruleset_version"))
    ruleset_hash = str(_field(rules_view, "ruleset_hash"))
    concurrency_limit = int(_field(rules_view, "concurrency_limit"))
    provisional = {
        "ruleset_id": ruleset_id,
        "ruleset_version": ruleset_version,
        "ruleset_hash": ruleset_hash,
        "compiler_version": COMPILER_VERSION,
        "concurrency_limit": concurrency_limit,
        "definitions": [item.model_dump(mode="json") for item in definitions],
    }
    return CompiledChipBundle(
        ruleset_id=ruleset_id,
        ruleset_version=ruleset_version,
        ruleset_hash=ruleset_hash,
        compiler_version=COMPILER_VERSION,
        concurrency_limit=concurrency_limit,
        definitions=definitions,
        bundle_hash=semantic_sha256(provisional),
    )


def compile_synthetic_bundle(
    *,
    ruleset_id: str,
    ruleset_version: str,
    ruleset_hash: str,
    concurrency_limit: int,
    definitions: tuple[ChipDefinition, ...],
) -> CompiledChipBundle:
    """Compile explicit future-chip fixtures without claiming target-season authority."""

    compiled = tuple(compile_chip_definition(item) for item in definitions)
    provisional = {
        "ruleset_id": ruleset_id,
        "ruleset_version": ruleset_version,
        "ruleset_hash": ruleset_hash,
        "compiler_version": COMPILER_VERSION,
        "concurrency_limit": concurrency_limit,
        "definitions": [item.model_dump(mode="json") for item in compiled],
    }
    return CompiledChipBundle(
        ruleset_id=ruleset_id,
        ruleset_version=ruleset_version,
        ruleset_hash=ruleset_hash,
        compiler_version=COMPILER_VERSION,
        concurrency_limit=concurrency_limit,
        definitions=compiled,
        bundle_hash=semantic_sha256(provisional),
    )
