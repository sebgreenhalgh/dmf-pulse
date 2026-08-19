from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.compiler import (
    COMPILER_VERSION,
    compile_chip_definition,
    compile_optimisation_chip_rules,
)
from dmf_pulse.chips.definitions import (
    ActivationRoute,
    ActivationStatus,
    ChipDefinition,
    ChipEffect,
    CompiledChipBundle,
    CompiledChipDefinition,
    EffectCapability,
    InventoryGrant,
    canonical_payload,
    semantic_sha256,
)
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import (
    ChipInventory,
    ChipInventoryToken,
    TokenStatus,
    activate_token,
    advance_inventory,
    build_chip_inventory,
    cancel_token,
    select_token,
)


def _grant(**updates: int | str) -> InventoryGrant:
    values: dict[str, int | str] = {
        "grant_id": "g1",
        "copies": 1,
        "acquired_gameweek": 2,
        "activation_start_gameweek": 2,
        "activation_end_gameweek": 6,
        "expires_after_gameweek": 6,
    }
    values.update(updates)
    return InventoryGrant.model_validate(values)


def _definition(**updates: object) -> ChipDefinition:
    values: dict[str, object] = {
        "chip_key": "VALIDATION_CHIP",
        "definition_version": "SYNTHETIC-V1",
        "grants": (_grant(),),
        "duration_gameweeks": 1,
        "concurrency_group": "SQUAD_CHIP",
        "activation_route": ActivationRoute.PICK_TEAM_SAVE,
        "cancellable_before_lock": True,
        "lock_after_confirmed_transfer_count": None,
        "excluded_gameweeks": (),
        "minimum_gap_gameweeks": 0,
        "effects": (
            ChipEffect(surface="SCORING", operation="ADD_POINTS", parameters={"points": 1}),
        ),
    }
    values.update(updates)
    return ChipDefinition.model_validate(values)


@pytest.mark.parametrize(
    "updates",
    [
        {"acquired_gameweek": 3, "activation_start_gameweek": 2},
        {"activation_start_gameweek": 5, "activation_end_gameweek": 4},
        {"activation_end_gameweek": 7, "expires_after_gameweek": 6},
    ],
)
def test_inventory_grant_rejects_invalid_chronology(updates: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        _grant(**updates)


@pytest.mark.parametrize(
    "updates",
    [
        {"grants": ()},
        {"grants": (_grant(), _grant())},
        {"effects": ()},
        {
            "effects": (
                ChipEffect(surface="SCORING", operation="ADD_POINTS", parameters={"points": 1}),
                ChipEffect(surface="SCORING", operation="ADD_POINTS", parameters={"points": 2}),
            )
        },
        {"excluded_gameweeks": (2, 2)},
        {
            "activation_route": ActivationRoute.CONFIRMED_TRANSFERS,
            "lock_after_confirmed_transfer_count": None,
        },
        {
            "activation_route": ActivationRoute.PICK_TEAM_SAVE,
            "lock_after_confirmed_transfer_count": 1,
        },
    ],
)
def test_definition_rejects_incoherent_contract(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _definition(**updates)


def test_compiled_definition_status_and_occupancy_are_validated() -> None:
    definition = _definition()
    definition_hash = semantic_sha256(definition)
    with pytest.raises(ValidationError):
        CompiledChipDefinition(
            definition=definition,
            definition_hash=definition_hash,
            compiler_version=COMPILER_VERSION,
            activation_status=ActivationStatus.READY,
            capabilities=frozenset({EffectCapability.CONFLICT_OCCUPANCY}),
            blockers=("unexpected",),
        )
    with pytest.raises(ValidationError):
        CompiledChipDefinition(
            definition=definition,
            definition_hash=definition_hash,
            compiler_version=COMPILER_VERSION,
            activation_status=ActivationStatus.BLOCKED_INVALID_SEMANTICS,
            capabilities=frozenset({EffectCapability.CONFLICT_OCCUPANCY}),
            blockers=(),
        )
    with pytest.raises(ValidationError):
        CompiledChipDefinition(
            definition=definition,
            definition_hash=definition_hash,
            compiler_version=COMPILER_VERSION,
            activation_status=ActivationStatus.READY,
            capabilities=frozenset({EffectCapability.SCORING_TRANSFORM}),
            blockers=(),
        )


def test_bundle_rejects_empty_or_duplicate_keys_and_unknown_lookup() -> None:
    compiled = compile_chip_definition(_definition())
    provisional = {
        "ruleset_id": "SYNTHETIC",
        "ruleset_version": "1",
        "ruleset_hash": "a" * 64,
        "compiler_version": COMPILER_VERSION,
        "concurrency_limit": 1,
        "definitions": (),
    }
    with pytest.raises(ValidationError):
        CompiledChipBundle(**provisional, bundle_hash=semantic_sha256(provisional))

    duplicate = {**provisional, "definitions": (compiled, compiled)}
    with pytest.raises(ValidationError):
        CompiledChipBundle(**duplicate, bundle_hash="b" * 64)

    valid = {**provisional, "definitions": (compiled,)}
    bundle = CompiledChipBundle(**valid, bundle_hash="c" * 64)
    with pytest.raises(KeyError, match="MISSING"):
        bundle.definition_for("MISSING")


def test_canonical_payload_supports_plain_semantic_collections() -> None:
    first = canonical_payload({"b": [2, 1], "a": (True, "x")})
    second = canonical_payload({"a": (True, "x"), "b": [2, 1]})
    assert first == second
    assert semantic_sha256({"b": [2, 1], "a": (True, "x")}) == semantic_sha256(
        {"a": (True, "x"), "b": [2, 1]}
    )


@pytest.mark.parametrize(
    ("surface", "operation", "parameters", "blocker"),
    [
        ("CAPTAIN", "SET_MULTIPLIER", {"multiplier": 3}, "INVALID_PARAMETERS"),
        (
            "CAPTAIN",
            "SET_MULTIPLIER",
            {"multiplier": 3, "vice_fallback": True, "extra": 1},
            "INVALID_PARAMETERS",
        ),
        ("SCORING", "MULTIPLY_POINTS", {"multiplier": 0}, "INVALID_SCORING_MULTIPLIER"),
        ("LINEUP", "ADD_BENCH_SLOTS", {"count": -1}, "INVALID_NONNEGATIVE_PARAMETER"),
        ("FREE_TRANSFERS", "SET", {"value": True}, "INVALID_NONNEGATIVE_PARAMETER"),
        ("CLUB_LIMIT", "SET", {"limit": -1}, "INVALID_NONNEGATIVE_PARAMETER"),
        (
            "POSITION_LIMIT",
            "SET",
            {"position": "DEF", "minimum": 5, "maximum": 4},
            "INVALID_POSITION_LIMIT",
        ),
        (
            "POSITION_LIMIT",
            "SET",
            {"position": 1, "minimum": 0, "maximum": 4},
            "INVALID_POSITION_LIMIT",
        ),
        (
            "TRANSFERS",
            "SET_HIT_COST",
            {"points_per_paid_transfer": 1},
            "INVALID_TRANSFER_HIT_COST",
        ),
        ("BUDGET", "ADD_PERMANENT", {"amount_tenths": True}, "INVALID_INTEGER_PARAMETER"),
    ],
)
def test_compiler_blocks_every_invalid_effect_family(
    surface: str,
    operation: str,
    parameters: dict[str, int | bool | str],
    blocker: str,
) -> None:
    definition = _definition(
        effects=(ChipEffect(surface=surface, operation=operation, parameters=parameters),)
    )
    compiled = compile_chip_definition(definition)
    assert compiled.activation_status == ActivationStatus.BLOCKED_INVALID_SEMANTICS
    assert any(item.startswith(blocker) for item in compiled.blockers)


def test_mapping_rules_view_is_supported_and_optional_lock_defaults() -> None:
    rules_view = {
        "ruleset_id": "SYNTHETIC-MAPPING",
        "ruleset_version": "1",
        "ruleset_hash": "b" * 64,
        "concurrency_limit": 1,
        "chips": (
            {
                "key": "MAPPING_CHIP",
                "copies_per_window": 1,
                "windows": ({"start_gameweek": 1, "end_gameweek": 5},),
                "duration_gameweeks": 1,
                "concurrency_group": "SQUAD_CHIP",
                "activation_route": "PICK_TEAM_SAVE",
                "cancellable_before_deadline": True,
                "excluded_gameweeks": (),
                "minimum_gap_gameweeks": 0,
                "effects": (
                    {
                        "surface": "LINEUP",
                        "operation": "INCLUDE_BENCH_POINTS",
                        "parameters": {},
                    },
                ),
            },
        ),
    }
    bundle = compile_optimisation_chip_rules(rules_view)
    definition = bundle.definition_for("MAPPING_CHIP").definition
    assert definition.lock_after_confirmed_transfer_count is None
    assert EffectCapability.BENCH_TRANSFORM in bundle.definition_for("MAPPING_CHIP").capabilities


def _token_payload(token: ChipInventoryToken) -> dict[str, object]:
    return deepcopy(token.model_dump(mode="python"))


@pytest.mark.parametrize(
    "update",
    [
        {"activation_start_gameweek": 5, "activation_end_gameweek": 4},
        {"activation_end_gameweek": 7, "expires_after_gameweek": 6},
        {"status": TokenStatus.PENDING_CANCELLABLE, "selected_at_gameweek": None},
        {
            "status": TokenStatus.ACTIVE,
            "active_from_gameweek": None,
            "active_until_gameweek": None,
        },
        {"status": TokenStatus.USED, "used_at_gameweek": None},
    ],
)
def test_token_rejects_incoherent_state(
    make_definition, make_bundle, update: dict[str, object]
) -> None:
    inventory = build_chip_inventory(make_bundle(make_definition("TOKEN")), current_gameweek=2)
    payload = _token_payload(inventory.tokens[0])
    payload.update(update)
    with pytest.raises(ValidationError):
        ChipInventoryToken.model_validate(payload)


def test_inventory_rejects_duplicate_tokens_and_unknown_lookup(
    make_definition, make_bundle
) -> None:
    inventory = build_chip_inventory(make_bundle(make_definition("DUP")), current_gameweek=2)
    payload = inventory.model_dump(mode="python")
    payload["tokens"] = (inventory.tokens[0], inventory.tokens[0])
    with pytest.raises(ValidationError):
        ChipInventory.model_validate(payload)
    with pytest.raises(ChipError) as exc:
        inventory.token("missing")
    assert exc.value.code == "CHIP_TOKEN_UNKNOWN"


def test_error_payload_is_stable_and_sorted() -> None:
    error = ChipError("CODE", "message", z=1, a=2)
    assert error.as_error_object() == {
        "error": {"code": "CODE", "message": "message", "details": {"a": 2, "z": 1}}
    }


def test_inventory_lineage_and_definition_hash_fail_closed(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("LINEAGE"))
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    mismatched_lineage = inventory.model_copy(update={"ruleset_hash": "f" * 64})
    with pytest.raises(ChipError) as exc:
        activate_token(mismatched_lineage, bundle, token_id="LINEAGE:window-1:1")
    assert exc.value.code == "CHIP_LINEAGE_MISMATCH"

    token = inventory.tokens[0].model_copy(update={"definition_hash": "e" * 64})
    mismatched_token = inventory.model_copy(update={"tokens": (token,)})
    with pytest.raises(ChipError) as exc:
        activate_token(mismatched_token, bundle, token_id=token.token_id)
    assert exc.value.code == "CHIP_DEFINITION_MISMATCH"


def test_directly_expired_inventory_records_both_events(make_definition, make_bundle) -> None:
    inventory = build_chip_inventory(
        make_bundle(make_definition("PAST", start=1, end=2)),
        current_gameweek=4,
    )
    token = inventory.tokens[0]
    assert token.status == TokenStatus.EXPIRED
    assert [event.event.value for event in token.history] == ["ACQUIRED", "EXPIRED"]


def test_window_check_catches_tampered_available_status(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("WINDOW", start=3, end=5, acquired=3))
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    token = inventory.tokens[0].model_copy(update={"status": TokenStatus.AVAILABLE})
    tampered = inventory.model_copy(update={"tokens": (token,)})
    with pytest.raises(ChipError) as exc:
        activate_token(tampered, bundle, token_id=token.token_id)
    assert exc.value.code == "CHIP_WINDOW_CLOSED"


def test_forged_pending_state_cannot_bypass_activation_rules(make_definition, make_bundle) -> None:
    blocked_bundle = make_bundle(
        make_definition("BLOCKED_PENDING", effect=("UNKNOWN", "TRANSFORM", {}))
    )
    inventory = build_chip_inventory(blocked_bundle, current_gameweek=2)
    token = inventory.tokens[0].model_copy(
        update={
            "status": TokenStatus.PENDING_CANCELLABLE,
            "selected_at_gameweek": 2,
        }
    )
    forged = inventory.model_copy(update={"tokens": (token,)})

    with pytest.raises(ChipError) as exc_info:
        activate_token(forged, blocked_bundle, token_id=token.token_id)

    assert exc_info.value.code == "CHIP_EFFECT_BLOCKED"


def test_selection_conflicts_and_irreversible_selection(make_definition, make_bundle) -> None:
    irreversible = make_bundle(make_definition("NOW", cancellable=False))
    inventory = build_chip_inventory(irreversible, current_gameweek=2)
    with pytest.raises(ChipError) as exc:
        select_token(inventory, irreversible, token_id="NOW:window-1:1")
    assert exc.value.code == "CHIP_NOT_CANCELLABLE"

    bundle = make_bundle(make_definition("A"), make_definition("B"))
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    selected = select_token(inventory, bundle, token_id="A:window-1:1")
    with pytest.raises(ChipError) as exc:
        select_token(selected, bundle, token_id="B:window-1:1")
    assert exc.value.code == "CHIP_SELECTION_CONFLICT"
    with pytest.raises(ChipError) as exc:
        cancel_token(inventory, token_id="A:window-1:1")
    assert exc.value.code == "CHIP_NOT_PENDING"


def test_same_group_blocks_even_when_global_limit_allows_two(make_definition, make_bundle) -> None:
    bundle = make_bundle(
        make_definition("A", group="SAME"),
        make_definition("B", group="SAME"),
        concurrency_limit=2,
    )
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    active = activate_token(inventory, bundle, token_id="A:window-1:1")
    with pytest.raises(ChipError) as exc:
        activate_token(active, bundle, token_id="B:window-1:1")
    assert exc.value.code == "CHIP_CONCURRENCY_GROUP"


def test_minimum_gap_is_enforced_across_copies(make_definition, make_bundle) -> None:
    bundle = make_bundle(make_definition("GAP", copies=2, minimum_gap=1))
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    active = activate_token(inventory, bundle, token_id="GAP:window-1:1")
    completed = advance_inventory(active, to_gameweek=3)
    with pytest.raises(ChipError) as exc:
        activate_token(completed, bundle, token_id="GAP:window-1:2")
    assert exc.value.code == "CHIP_MINIMUM_GAP"


def test_advance_rejects_reverse_time_and_auto_cancels_pending(
    make_definition, make_bundle
) -> None:
    bundle = make_bundle(make_definition("PENDING"))
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    with pytest.raises(ChipError) as exc:
        advance_inventory(inventory, to_gameweek=1)
    assert exc.value.code == "CHIP_TIME_REVERSED"

    pending = select_token(inventory, bundle, token_id="PENDING:window-1:1")
    advanced = advance_inventory(pending, to_gameweek=3)
    token = advanced.token("PENDING:window-1:1")
    assert token.status == TokenStatus.AVAILABLE
    assert token.selected_at_gameweek is None
    assert token.history[-1].event.value == "CANCELLED"


def test_future_token_can_expire_when_advancement_skips_window(
    make_definition, make_bundle
) -> None:
    bundle = make_bundle(make_definition("SKIP", start=5, end=6, acquired=5))
    inventory = build_chip_inventory(bundle, current_gameweek=2)
    expired = advance_inventory(inventory, to_gameweek=8)
    assert expired.token("SKIP:window-1:1").status == TokenStatus.EXPIRED
