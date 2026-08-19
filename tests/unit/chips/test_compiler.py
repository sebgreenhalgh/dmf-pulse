from __future__ import annotations

from dataclasses import dataclass

from dmf_pulse.chips.compiler import (
    compile_chip_definition,
    compile_optimisation_chip_rules,
)
from dmf_pulse.chips.definitions import (
    ActivationRoute,
    ActivationStatus,
    ChipDefinition,
    ChipEffect,
    EffectCapability,
    InventoryGrant,
)


@dataclass(frozen=True)
class Window:
    start_gameweek: int
    end_gameweek: int


@dataclass(frozen=True)
class Effect:
    surface: str
    operation: str
    parameters: dict[str, int | bool | str]


@dataclass(frozen=True)
class RuntimeRule:
    key: str
    copies_per_window: int
    windows: tuple[Window, ...]
    duration_gameweeks: int
    concurrency_group: str
    activation_route: str
    lock_after_confirmed_transfer_count: int | None
    cancellable_before_deadline: bool
    excluded_gameweeks: tuple[int, ...]
    minimum_gap_gameweeks: int
    effects: tuple[Effect, ...]


@dataclass(frozen=True)
class RulesView:
    ruleset_id: str
    ruleset_version: str
    ruleset_hash: str
    concurrency_limit: int
    chips: tuple[RuntimeRule, ...]


def _definition(surface: str, operation: str, parameters: dict[str, int | bool | str]):
    return ChipDefinition(
        chip_key="FUTURE_CHIP",
        definition_version="SYNTHETIC-V1",
        grants=(
            InventoryGrant(
                grant_id="g1",
                copies=1,
                acquired_gameweek=4,
                activation_start_gameweek=4,
                activation_end_gameweek=8,
                expires_after_gameweek=8,
            ),
        ),
        duration_gameweeks=2,
        concurrency_group="FUTURE",
        activation_route=ActivationRoute.EXPLICIT_CONFIRMATION,
        cancellable_before_lock=False,
        effects=(ChipEffect(surface=surface, operation=operation, parameters=parameters),),
    )


def test_multiweek_scoring_chip_compiles_without_name_branch() -> None:
    compiled = compile_chip_definition(_definition("SCORING", "ADD_POINTS", {"points": 3}))
    assert compiled.activation_status == ActivationStatus.READY
    assert EffectCapability.SCORING_TRANSFORM in compiled.capabilities
    assert EffectCapability.CONFLICT_OCCUPANCY in compiled.capabilities


def test_transfer_cost_modifying_chip_compiles() -> None:
    compiled = compile_chip_definition(
        _definition("TRANSFERS", "SET_HIT_COST", {"points_per_paid_transfer": 0})
    )
    assert compiled.activation_status == ActivationStatus.READY
    assert EffectCapability.TRANSFER_TRANSFORM in compiled.capabilities


def test_budget_modifying_chip_compiles() -> None:
    compiled = compile_chip_definition(
        _definition("BUDGET", "ADD_TEMPORARY", {"amount_tenths": 20})
    )
    assert compiled.activation_status == ActivationStatus.READY
    assert EffectCapability.BUDGET_TRANSFORM in compiled.capabilities


def test_unknown_effect_is_parsed_but_blocks_activation() -> None:
    compiled = compile_chip_definition(_definition("FIXTURE", "CLONE", {}))
    assert compiled.activation_status == ActivationStatus.BLOCKED_UNKNOWN_EFFECT
    assert compiled.blockers == ("UNKNOWN_EFFECT:FIXTURE:CLONE",)


def test_invalid_known_semantics_fail_closed() -> None:
    compiled = compile_chip_definition(
        _definition("CAPTAIN", "SET_MULTIPLIER", {"multiplier": 1, "vice_fallback": True})
    )
    assert compiled.activation_status == ActivationStatus.BLOCKED_INVALID_SEMANTICS
    assert "INVALID_CAPTAIN_MULTIPLIER" in compiled.blockers


def test_generic_captain_effect_accepts_boolean_fallback_for_rules_reconciliation() -> None:
    compiled = compile_chip_definition(
        _definition("CAPTAIN", "SET_MULTIPLIER", {"multiplier": 3, "vice_fallback": False})
    )
    assert compiled.activation_status == ActivationStatus.READY


def test_rules_view_is_adapted_without_copying_target_constants() -> None:
    view = RulesView(
        ruleset_id="FPL-2026-27",
        ruleset_version="2026.27.1",
        ruleset_hash="a" * 64,
        concurrency_limit=1,
        chips=(
            RuntimeRule(
                key="TRIPLE_CAPTAIN",
                copies_per_window=1,
                windows=(Window(1, 19), Window(20, 38)),
                duration_gameweeks=1,
                concurrency_group="SQUAD_CHIP",
                activation_route="PICK_TEAM_SAVE",
                lock_after_confirmed_transfer_count=None,
                cancellable_before_deadline=True,
                excluded_gameweeks=(),
                minimum_gap_gameweeks=0,
                effects=(
                    Effect(
                        "CAPTAIN",
                        "SET_MULTIPLIER",
                        {"multiplier": 3, "vice_fallback": True},
                    ),
                ),
            ),
        ),
    )
    bundle = compile_optimisation_chip_rules(view)
    compiled = bundle.definition_for("TRIPLE_CAPTAIN")
    assert compiled.activation_status == ActivationStatus.READY
    assert tuple(grant.activation_start_gameweek for grant in compiled.definition.grants) == (1, 20)
    assert tuple(grant.activation_end_gameweek for grant in compiled.definition.grants) == (19, 38)
    assert bundle.ruleset_hash == "a" * 64


def test_semantically_identical_compile_is_hash_stable() -> None:
    definition = _definition("SCORING", "ADD_POINTS", {"points": 3})
    first = compile_chip_definition(definition)
    second = compile_chip_definition(definition.model_copy(deep=True))
    assert first == second
    assert first.definition_hash == second.definition_hash
