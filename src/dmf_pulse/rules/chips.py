"""Pure execution of schema-1.1 chip declarations.

The target-season policy remains in compiled rules data.  This module provides
the closed operation registry and generic state transitions that make those
declarations executable rather than treating YAML as documentary metadata.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import CompiledRuleset, RulesetStatus

PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
ChipKey = Literal["WILDCARD", "FREE_HIT", "TRIPLE_CAPTAIN", "BENCH_BOOST"]


class ChipModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeWindow(ChipModel):
    start_gameweek: PositiveInt
    end_gameweek: PositiveInt


class RuntimeEffect(ChipModel):
    surface: StrictStr
    operation: StrictStr
    parameters: dict[StrictStr, StrictInt | StrictBool | StrictStr]


class RuntimeChipRule(ChipModel):
    key: ChipKey
    copies_per_window: PositiveInt
    windows: tuple[RuntimeWindow, ...]
    duration_gameweeks: Literal[1]
    concurrency_group: StrictStr
    activation_route: Literal["PICK_TEAM_SAVE", "CONFIRMED_TRANSFERS"]
    lock_after_confirmed_transfer_count: PositiveInt | None
    cancellable_before_deadline: StrictBool
    excluded_gameweeks: tuple[PositiveInt, ...]
    minimum_gap_gameweeks: NonNegativeInt
    effects: tuple[RuntimeEffect, ...]


class ChipRulesView(ChipModel):
    ruleset_id: StrictStr
    ruleset_version: StrictStr
    ruleset_hash: Sha256
    concurrency_limit: Literal[1]
    maximum_transfers_per_deadline: PositiveInt
    hit_points_per_paid_transfer: StrictInt
    chips: tuple[RuntimeChipRule, ...]

    @model_validator(mode="after")
    def keys_are_complete(self) -> ChipRulesView:
        keys = tuple(chip.key for chip in self.chips)
        if len(keys) != len(set(keys)) or set(keys) != {
            "WILDCARD",
            "FREE_HIT",
            "TRIPLE_CAPTAIN",
            "BENCH_BOOST",
        }:
            raise ValueError("runtime chip rules must define each supported chip exactly once")
        if self.hit_points_per_paid_transfer >= 0:
            raise ValueError("transfer hit points must be a negative scoring adjustment")
        return self


class ChipUse(ChipModel):
    chip_key: ChipKey
    gameweek: PositiveInt
    window_index: NonNegativeInt


class FreeHitSnapshot(ChipModel):
    permanent_squad: tuple[StrictStr, ...]
    bank_tenths: NonNegativeInt
    purchase_prices_tenths: dict[StrictStr, NonNegativeInt]


class ChipManagerState(ChipModel):
    ruleset_id: StrictStr
    ruleset_version: StrictStr
    ruleset_hash: Sha256
    gameweek: PositiveInt
    saved_free_transfers: NonNegativeInt
    permanent_squad: tuple[StrictStr, ...]
    active_squad: tuple[StrictStr, ...]
    bank_tenths: NonNegativeInt
    purchase_prices_tenths: dict[StrictStr, NonNegativeInt]
    use_history: tuple[ChipUse, ...] = ()
    pending_chip: ChipKey | None = None
    active_chip: ChipKey | None = None
    confirmed_transfer_count: NonNegativeInt = 0
    free_hit_snapshot: FreeHitSnapshot | None = None

    @model_validator(mode="after")
    def state_is_coherent(self) -> ChipManagerState:
        if not self.permanent_squad or len(self.permanent_squad) != len(set(self.permanent_squad)):
            raise ValueError("permanent squad must be non-empty and unique")
        if len(self.active_squad) != len(self.permanent_squad) or len(self.active_squad) != len(
            set(self.active_squad)
        ):
            raise ValueError("active squad must be unique and preserve squad size")
        if set(self.purchase_prices_tenths) != set(self.active_squad):
            raise ValueError("purchase prices must cover the active squad exactly")
        if self.pending_chip is not None and self.active_chip is not None:
            raise ValueError("a chip cannot be pending and active simultaneously")
        if self.free_hit_snapshot is not None and self.active_chip is None:
            raise ValueError("a Free Hit snapshot requires an active chip")
        return self


class ChipScoreResult(ChipModel):
    total_points: StrictInt
    counted_players: tuple[StrictStr, ...]
    bench_included: StrictBool
    effective_captain: StrictStr | None
    captain_multiplier: PositiveInt


_EXPECTED_EFFECTS: dict[ChipKey, dict[tuple[str, str], frozenset[str]]] = {
    "WILDCARD": {
        ("TRANSFERS", "UNLIMITED_FREE"): frozenset(),
        ("TRANSFERS", "REMOVE_CURRENT_GAMEWEEK_HITS"): frozenset(),
        ("TRANSFERS", "PRESERVE_SAVED_FREE_TRANSFERS"): frozenset(),
        ("SQUAD", "PERMANENT"): frozenset(),
    },
    "FREE_HIT": {
        ("TRANSFERS", "UNLIMITED_FREE"): frozenset(),
        ("TRANSFERS", "PRESERVE_SAVED_FREE_TRANSFERS"): frozenset(),
        ("SQUAD", "RESTORE_NEXT_DEADLINE"): frozenset(),
        ("BANK", "RESTORE_NEXT_DEADLINE"): frozenset(),
        ("PURCHASE_PRICES", "RESTORE_NEXT_DEADLINE"): frozenset(),
    },
    "TRIPLE_CAPTAIN": {
        ("CAPTAIN", "SET_MULTIPLIER"): frozenset({"multiplier", "vice_fallback"}),
    },
    "BENCH_BOOST": {("LINEUP", "INCLUDE_BENCH_POINTS"): frozenset()},
}


def declarative_chip_blockers(chips: object) -> tuple[str, ...]:
    """Return stable blockers for missing, extra, or unsupported chip effects."""

    if not isinstance(chips, dict) or chips.get("verification_status") in {
        "UNKNOWN",
        "CONFLICTED",
    }:
        return ()
    raw_chips = chips.get("chips")
    if not isinstance(raw_chips, list):
        return ("unimplemented:chips.invalid",)
    blockers: list[str] = []
    seen: set[str] = set()
    for chip_index, raw_chip in enumerate(raw_chips):
        if not isinstance(raw_chip, dict) or raw_chip.get("key") not in _EXPECTED_EFFECTS:
            blockers.append(f"unimplemented:chips[{chip_index}].key")
            continue
        key = raw_chip["key"]
        seen.add(key)
        actual: dict[tuple[str, str], object] = {}
        effects = raw_chip.get("effects")
        if not isinstance(effects, list):
            blockers.append(f"unimplemented:chips[{chip_index}].effects")
            continue
        for effect_index, effect in enumerate(effects):
            if not isinstance(effect, dict):
                blockers.append(f"unimplemented:chips[{chip_index}].effects[{effect_index}]")
                continue
            surface = effect.get("surface")
            operation = effect.get("operation")
            if not isinstance(surface, str) or not isinstance(operation, str):
                blockers.append(f"unimplemented:chips[{chip_index}].effects[{effect_index}]")
                continue
            actual[(surface, operation)] = effect.get("parameters")
        expected = _EXPECTED_EFFECTS[key]
        contract_mismatch = set(actual) != set(expected)
        if not contract_mismatch:
            for operation, parameter_names in expected.items():
                parameters = actual[operation]
                if not isinstance(parameters, dict) or set(parameters) != parameter_names:
                    contract_mismatch = True
                    break
        if contract_mismatch:
            blockers.append(f"unimplemented:chips[{chip_index}].effect_contract")
            continue
        if key == "TRIPLE_CAPTAIN":
            parameters = actual[("CAPTAIN", "SET_MULTIPLIER")]
            assert isinstance(parameters, dict)
            multiplier = parameters["multiplier"]
            if (
                type(multiplier) is not int
                or multiplier <= 1
                or parameters["vice_fallback"] is not True
            ):
                blockers.append(f"unimplemented:chips[{chip_index}].effect_contract")
    for missing in sorted(set(_EXPECTED_EFFECTS) - seen):
        blockers.append(f"unimplemented:chips.missing.{missing}")
    return tuple(sorted(set(blockers)))


def _effect(chip: RuntimeChipRule, surface: str, operation: str) -> RuntimeEffect | None:
    return next(
        (
            effect
            for effect in chip.effects
            if effect.surface == surface and effect.operation == operation
        ),
        None,
    )


def build_chip_rules_view(compiled: CompiledRuleset) -> ChipRulesView:
    """Resolve executable chip state from one integrity-checked compiled ruleset."""

    from dmf_pulse.rules.compiler import ensure_compiled_ruleset_integrity

    ensure_compiled_ruleset_integrity(compiled)
    if compiled.schema_version != "1.1" or compiled.status not in {
        RulesetStatus.REFERENCE_ONLY,
        RulesetStatus.VERIFIED,
        RulesetStatus.ACTIVE,
    }:
        raise RulesValidationError(
            "CHIP_STATE_CAPABILITY_UNAVAILABLE",
            "chip execution requires complete schema-1.1 reference, verified, or active rules",
        )
    chips = compiled.rules.get("chips")
    blockers = declarative_chip_blockers(chips)
    if blockers:
        raise RulesValidationError(
            "CHIP_EFFECT_UNSUPPORTED",
            "compiled chip declarations are not fully executable",
            blockers=blockers,
        )
    assert isinstance(chips, dict)
    runtime: list[RuntimeChipRule] = []
    for raw_chip in chips["chips"]:
        inventory = raw_chip["inventory"]
        activation = raw_chip["activation"]
        runtime.append(
            RuntimeChipRule(
                key=raw_chip["key"],
                copies_per_window=inventory["copies_per_window"],
                windows=tuple(RuntimeWindow.model_validate(item) for item in inventory["windows"]),
                duration_gameweeks=raw_chip["duration_gameweeks"],
                concurrency_group=raw_chip["concurrency_group"],
                activation_route=activation["route"],
                lock_after_confirmed_transfer_count=activation[
                    "lock_after_confirmed_transfer_count"
                ],
                cancellable_before_deadline=activation["cancellable_before_deadline"],
                excluded_gameweeks=tuple(raw_chip["excluded_gameweeks"]),
                minimum_gap_gameweeks=raw_chip["minimum_gap_gameweeks"],
                effects=tuple(RuntimeEffect.model_validate(item) for item in raw_chip["effects"]),
            )
        )
    transition = compiled.rules["transfers"]["transition"]
    return ChipRulesView(
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
        concurrency_limit=chips["concurrency_limit"],
        maximum_transfers_per_deadline=transition["max_transfers_per_deadline"],
        hit_points_per_paid_transfer=transition["hit_points"],
        chips=tuple(runtime),
    )


def _rule(rules: ChipRulesView, key: ChipKey) -> RuntimeChipRule:
    return next(chip for chip in rules.chips if chip.key == key)


def _window(chip: RuntimeChipRule, gameweek: int) -> int:
    for index, window in enumerate(chip.windows):
        if window.start_gameweek <= gameweek <= window.end_gameweek:
            return index
    raise ValueError(f"{chip.key} is outside its configured inventory window")


def _assert_lineage(state: ChipManagerState, rules: ChipRulesView) -> None:
    if (state.ruleset_id, state.ruleset_version, state.ruleset_hash) != (
        rules.ruleset_id,
        rules.ruleset_version,
        rules.ruleset_hash,
    ):
        raise ValueError("chip state and ruleset lineage differ")


def _activate(
    state: ChipManagerState,
    chip: RuntimeChipRule,
    window_index: int,
) -> ChipManagerState:
    snapshot = state.free_hit_snapshot
    if _effect(chip, "SQUAD", "RESTORE_NEXT_DEADLINE") is not None:
        snapshot = FreeHitSnapshot(
            permanent_squad=state.permanent_squad,
            bank_tenths=state.bank_tenths,
            purchase_prices_tenths=state.purchase_prices_tenths,
        )
    return state.model_copy(
        update={
            "pending_chip": None,
            "active_chip": chip.key,
            "use_history": (
                *state.use_history,
                ChipUse(chip_key=chip.key, gameweek=state.gameweek, window_index=window_index),
            ),
            "free_hit_snapshot": snapshot,
        }
    )


def play_chip(
    state: ChipManagerState,
    rules: ChipRulesView,
    chip_key: ChipKey,
    *,
    confirmed_transfer_count: int = 0,
) -> ChipManagerState:
    """Select a chip, locking it only when its configured activation route does."""

    _assert_lineage(state, rules)
    if state.pending_chip is not None or state.active_chip is not None:
        raise ValueError("only one chip may be selected or active in a Gameweek")
    chip = _rule(rules, chip_key)
    window_index = _window(chip, state.gameweek)
    if state.gameweek in chip.excluded_gameweeks:
        raise ValueError(f"{chip.key} is excluded in this Gameweek")
    used_in_window = sum(
        use.chip_key == chip.key and use.window_index == window_index for use in state.use_history
    )
    if used_in_window >= chip.copies_per_window:
        raise ValueError(f"{chip.key} inventory for this window is exhausted")
    prior = [use.gameweek for use in state.use_history if use.chip_key == chip.key]
    if prior and state.gameweek - max(prior) <= chip.minimum_gap_gameweeks:
        raise ValueError(f"{chip.key} cannot be used within its configured Gameweek gap")
    pending = state.model_copy(
        update={
            "pending_chip": chip.key,
            "confirmed_transfer_count": confirmed_transfer_count,
        }
    )
    threshold = chip.lock_after_confirmed_transfer_count
    if (
        chip.activation_route == "CONFIRMED_TRANSFERS"
        and threshold is not None
        and confirmed_transfer_count >= threshold
    ):
        return _activate(pending, chip, window_index)
    return pending


def confirm_chip_transfers(
    state: ChipManagerState,
    rules: ChipRulesView,
    *,
    confirmed_transfer_count: int,
) -> ChipManagerState:
    """Advance a pending transfer chip to its configured irreversible threshold."""

    _assert_lineage(state, rules)
    if state.pending_chip is None:
        raise ValueError("no transfer chip is pending")
    chip = _rule(rules, state.pending_chip)
    if chip.activation_route != "CONFIRMED_TRANSFERS":
        raise ValueError("Pick Team chips do not activate through transfers")
    if confirmed_transfer_count < state.confirmed_transfer_count:
        raise ValueError("confirmed transfers are irreversible")
    pending = state.model_copy(update={"confirmed_transfer_count": confirmed_transfer_count})
    threshold = chip.lock_after_confirmed_transfer_count
    assert threshold is not None
    if confirmed_transfer_count < threshold:
        return pending
    return _activate(pending, chip, _window(chip, state.gameweek))


def cancel_pending_chip(state: ChipManagerState, rules: ChipRulesView) -> ChipManagerState:
    """Cancel only a still-pending chip before its configured lock point."""

    _assert_lineage(state, rules)
    if state.pending_chip is None:
        raise ValueError("no chip is pending")
    chip = _rule(rules, state.pending_chip)
    if not chip.cancellable_before_deadline:
        raise ValueError(f"{chip.key} cannot be cancelled")
    return state.model_copy(update={"pending_chip": None, "confirmed_transfer_count": 0})


def finalise_chip_deadline(state: ChipManagerState, rules: ChipRulesView) -> ChipManagerState:
    """Activate a saved Pick Team chip; discard an unlocked transfer-chip selection."""

    _assert_lineage(state, rules)
    if state.pending_chip is None:
        return state
    chip = _rule(rules, state.pending_chip)
    if chip.activation_route == "CONFIRMED_TRANSFERS":
        return state.model_copy(update={"pending_chip": None, "confirmed_transfer_count": 0})
    return _activate(state, chip, _window(chip, state.gameweek))


def replace_chip_squad(
    state: ChipManagerState,
    rules: ChipRulesView,
    *,
    squad: tuple[str, ...],
    bank_tenths: int,
    purchase_prices_tenths: dict[str, int],
) -> ChipManagerState:
    """Apply Wildcard/Free-Hit moves with permanent or temporary state semantics."""

    _assert_lineage(state, rules)
    if state.active_chip is None:
        raise ValueError("squad replacement requires an active transfer chip")
    chip = _rule(rules, state.active_chip)
    if _effect(chip, "TRANSFERS", "UNLIMITED_FREE") is None:
        raise ValueError("active chip does not authorise squad replacement")
    if len(squad) != len(state.active_squad) or len(squad) != len(set(squad)):
        raise ValueError("chip squad replacement must preserve unique squad size")
    if set(purchase_prices_tenths) != set(squad) or bank_tenths < 0:
        raise ValueError("chip squad finances are incomplete or negative")
    updates: dict[str, object] = {
        "active_squad": squad,
        "bank_tenths": bank_tenths,
        "purchase_prices_tenths": purchase_prices_tenths,
    }
    if _effect(chip, "SQUAD", "PERMANENT") is not None:
        updates["permanent_squad"] = squad
    return state.model_copy(update=updates)


def transfer_hit_points(
    state: ChipManagerState,
    rules: ChipRulesView,
    *,
    transfer_count: int,
    available_free_transfers: int,
) -> int:
    """Calculate configured hits, including chip unlimited-transfer overrides."""

    _assert_lineage(state, rules)
    if transfer_count < 0 or available_free_transfers < 0:
        raise ValueError("transfer counts cannot be negative")
    active = _rule(rules, state.active_chip) if state.active_chip is not None else None
    if active is not None and _effect(active, "TRANSFERS", "UNLIMITED_FREE") is not None:
        return 0
    if transfer_count > rules.maximum_transfers_per_deadline:
        raise ValueError("transfer count exceeds the configured deadline maximum")
    return max(transfer_count - available_free_transfers, 0) * rules.hit_points_per_paid_transfer


def score_chip_gameweek(
    state: ChipManagerState,
    rules: ChipRulesView,
    *,
    player_points: dict[str, int],
    starter_ids: tuple[str, ...],
    bench_ids: tuple[str, ...],
    captain_id: str,
    vice_captain_id: str,
    appeared_player_ids: frozenset[str],
    normal_captain_multiplier: int,
) -> ChipScoreResult:
    """Apply Bench Boost and Triple Captain to an already resolved legal lineup."""

    _assert_lineage(state, rules)
    if normal_captain_multiplier < 1:
        raise ValueError("captain multiplier must be positive")
    if set(starter_ids) & set(bench_ids) or not set(starter_ids + bench_ids) <= set(player_points):
        raise ValueError("lineup and player points are inconsistent")
    chip = _rule(rules, state.active_chip) if state.active_chip is not None else None
    bench_included = (
        chip is not None and _effect(chip, "LINEUP", "INCLUDE_BENCH_POINTS") is not None
    )
    counted = (*starter_ids, *bench_ids) if bench_included else starter_ids
    effective_captain = (
        captain_id
        if captain_id in appeared_player_ids
        else vice_captain_id
        if vice_captain_id in appeared_player_ids
        else None
    )
    multiplier = normal_captain_multiplier
    if chip is not None:
        triple = _effect(chip, "CAPTAIN", "SET_MULTIPLIER")
        if triple is not None:
            multiplier = int(triple.parameters["multiplier"])
    total = sum(player_points[player_id] for player_id in counted)
    if effective_captain is not None:
        total += player_points[effective_captain] * (multiplier - 1)
    return ChipScoreResult(
        total_points=total,
        counted_players=tuple(counted),
        bench_included=bench_included,
        effective_captain=effective_captain,
        captain_multiplier=multiplier,
    )


def complete_chip_gameweek(
    state: ChipManagerState,
    rules: ChipRulesView,
    *,
    next_gameweek: int,
) -> ChipManagerState:
    """Clear a one-Gameweek chip and restore the pre-Free-Hit ownership state."""

    _assert_lineage(state, rules)
    if next_gameweek != state.gameweek + 1:
        raise ValueError("chip completion must advance exactly one Gameweek")
    updates: dict[str, object] = {
        "gameweek": next_gameweek,
        "active_chip": None,
        "pending_chip": None,
        "confirmed_transfer_count": 0,
        "free_hit_snapshot": None,
    }
    if state.free_hit_snapshot is not None:
        snapshot = state.free_hit_snapshot
        updates.update(
            active_squad=snapshot.permanent_squad,
            permanent_squad=snapshot.permanent_squad,
            bank_tenths=snapshot.bank_tenths,
            purchase_prices_tenths=snapshot.purchase_prices_tenths,
        )
    return state.model_copy(update=updates)
