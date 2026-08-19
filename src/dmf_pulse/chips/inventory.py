"""Deterministic finite chip-inventory state transitions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, StrictStr, model_validator

from dmf_pulse.chips.definitions import (
    ActivationStatus,
    CompiledChipBundle,
    CompiledChipDefinition,
    FrozenModel,
    NonNegativeInt,
    PositiveInt,
    Sha256,
    semantic_sha256,
)
from dmf_pulse.chips.errors import ChipError


class TokenStatus(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    AVAILABLE = "AVAILABLE"
    PENDING_CANCELLABLE = "PENDING_CANCELLABLE"
    ACTIVE = "ACTIVE"
    USED = "USED"
    EXPIRED = "EXPIRED"


class TokenEventKind(StrEnum):
    ACQUIRED = "ACQUIRED"
    SELECTED = "SELECTED"
    CANCELLED = "CANCELLED"
    ACTIVATED = "ACTIVATED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class TokenEvent(FrozenModel):
    event: TokenEventKind
    gameweek: PositiveInt


class ChipInventoryToken(FrozenModel):
    """One finite exercise right derived from one compiled inventory grant."""

    token_id: StrictStr = Field(min_length=1)
    chip_key: StrictStr
    definition_hash: Sha256
    grant_id: StrictStr
    copy_index: PositiveInt
    acquired_gameweek: PositiveInt
    activation_start_gameweek: PositiveInt
    activation_end_gameweek: PositiveInt
    expires_after_gameweek: PositiveInt
    duration_gameweeks: PositiveInt
    concurrency_group: StrictStr
    minimum_gap_gameweeks: NonNegativeInt
    excluded_gameweeks: tuple[PositiveInt, ...]
    status: TokenStatus
    selected_at_gameweek: PositiveInt | None = None
    active_from_gameweek: PositiveInt | None = None
    active_until_gameweek: PositiveInt | None = None
    used_at_gameweek: PositiveInt | None = None
    history: tuple[TokenEvent, ...] = ()

    @model_validator(mode="after")
    def state_is_coherent(self) -> ChipInventoryToken:
        if self.activation_start_gameweek > self.activation_end_gameweek:
            raise ValueError("token activation window is inverted")
        if self.activation_end_gameweek > self.expires_after_gameweek:
            raise ValueError("token expiry precedes activation end")
        if self.status == TokenStatus.PENDING_CANCELLABLE and self.selected_at_gameweek is None:
            raise ValueError("pending token requires selection time")
        if self.status == TokenStatus.ACTIVE and (
            self.active_from_gameweek is None or self.active_until_gameweek is None
        ):
            raise ValueError("active token requires an occupied interval")
        if self.status == TokenStatus.USED and self.used_at_gameweek is None:
            raise ValueError("used token requires completion time")
        return self


class ChipInventory(FrozenModel):
    """Rules-bound token inventory at one decision Gameweek."""

    ruleset_id: StrictStr
    ruleset_version: StrictStr
    ruleset_hash: Sha256
    bundle_hash: Sha256
    current_gameweek: PositiveInt
    concurrency_limit: PositiveInt
    tokens: tuple[ChipInventoryToken, ...]
    inventory_hash: Sha256

    @model_validator(mode="after")
    def token_ids_are_unique(self) -> ChipInventory:
        token_ids = tuple(token.token_id for token in self.tokens)
        if len(token_ids) != len(set(token_ids)):
            raise ValueError("chip inventory token IDs must be unique")
        return self

    def token(self, token_id: str) -> ChipInventoryToken:
        for token in self.tokens:
            if token.token_id == token_id:
                return token
        raise ChipError(
            "CHIP_TOKEN_UNKNOWN",
            "chip inventory token does not exist",
            token_id=token_id,
        )


def _inventory_payload(
    *,
    ruleset_id: str,
    ruleset_version: str,
    ruleset_hash: str,
    bundle_hash: str,
    current_gameweek: int,
    concurrency_limit: int,
    tokens: tuple[ChipInventoryToken, ...],
) -> dict[str, object]:
    return {
        "ruleset_id": ruleset_id,
        "ruleset_version": ruleset_version,
        "ruleset_hash": ruleset_hash,
        "bundle_hash": bundle_hash,
        "current_gameweek": current_gameweek,
        "concurrency_limit": concurrency_limit,
        "tokens": [token.model_dump(mode="json") for token in tokens],
    }


def _make_inventory(
    inventory: ChipInventory | None,
    *,
    bundle: CompiledChipBundle | None = None,
    current_gameweek: int,
    tokens: tuple[ChipInventoryToken, ...],
) -> ChipInventory:
    if inventory is None:
        if bundle is None:
            raise ValueError("a compiled bundle is required to mint chip inventory")
        ruleset_id = bundle.ruleset_id
        ruleset_version = bundle.ruleset_version
        ruleset_hash = bundle.ruleset_hash
        bundle_hash = bundle.bundle_hash
        concurrency_limit = bundle.concurrency_limit
    else:
        ruleset_id = inventory.ruleset_id
        ruleset_version = inventory.ruleset_version
        ruleset_hash = inventory.ruleset_hash
        bundle_hash = inventory.bundle_hash
        concurrency_limit = inventory.concurrency_limit
    ordered = tuple(sorted(tokens, key=lambda item: item.token_id))
    payload = _inventory_payload(
        ruleset_id=ruleset_id,
        ruleset_version=ruleset_version,
        ruleset_hash=ruleset_hash,
        bundle_hash=bundle_hash,
        current_gameweek=current_gameweek,
        concurrency_limit=concurrency_limit,
        tokens=ordered,
    )
    return ChipInventory(
        ruleset_id=ruleset_id,
        ruleset_version=ruleset_version,
        ruleset_hash=ruleset_hash,
        bundle_hash=bundle_hash,
        current_gameweek=current_gameweek,
        concurrency_limit=concurrency_limit,
        tokens=ordered,
        inventory_hash=semantic_sha256(payload),
    )


def build_chip_inventory(bundle: CompiledChipBundle, *, current_gameweek: int) -> ChipInventory:
    """Mint deterministic tokens for every current and future inventory grant."""

    tokens: list[ChipInventoryToken] = []
    for compiled in sorted(bundle.definitions, key=lambda item: item.chip_key):
        definition = compiled.definition
        for grant in sorted(definition.grants, key=lambda item: item.grant_id):
            for copy_index in range(1, grant.copies + 1):
                acquired = current_gameweek >= grant.acquired_gameweek
                if current_gameweek > grant.expires_after_gameweek:
                    status = TokenStatus.EXPIRED
                elif (
                    acquired
                    and grant.activation_start_gameweek
                    <= current_gameweek
                    <= grant.activation_end_gameweek
                ):
                    status = TokenStatus.AVAILABLE
                else:
                    status = TokenStatus.UNAVAILABLE
                history_items: list[TokenEvent] = []
                if acquired:
                    history_items.append(
                        TokenEvent(event=TokenEventKind.ACQUIRED, gameweek=grant.acquired_gameweek)
                    )
                if status == TokenStatus.EXPIRED:
                    history_items.append(
                        TokenEvent(
                            event=TokenEventKind.EXPIRED,
                            gameweek=grant.expires_after_gameweek,
                        )
                    )
                history = tuple(history_items)
                tokens.append(
                    ChipInventoryToken(
                        token_id=f"{definition.chip_key}:{grant.grant_id}:{copy_index}",
                        chip_key=definition.chip_key,
                        definition_hash=compiled.definition_hash,
                        grant_id=grant.grant_id,
                        copy_index=copy_index,
                        acquired_gameweek=grant.acquired_gameweek,
                        activation_start_gameweek=grant.activation_start_gameweek,
                        activation_end_gameweek=grant.activation_end_gameweek,
                        expires_after_gameweek=grant.expires_after_gameweek,
                        duration_gameweeks=definition.duration_gameweeks,
                        concurrency_group=definition.concurrency_group,
                        minimum_gap_gameweeks=definition.minimum_gap_gameweeks,
                        excluded_gameweeks=definition.excluded_gameweeks,
                        status=status,
                        history=history,
                    )
                )
    return _make_inventory(
        None,
        bundle=bundle,
        current_gameweek=current_gameweek,
        tokens=tuple(tokens),
    )


def _replace_token(
    inventory: ChipInventory,
    replacement: ChipInventoryToken,
) -> ChipInventory:
    tokens = tuple(
        replacement if token.token_id == replacement.token_id else token
        for token in inventory.tokens
    )
    return _make_inventory(inventory, current_gameweek=inventory.current_gameweek, tokens=tokens)


def _compiled_for(
    bundle: CompiledChipBundle,
    inventory: ChipInventory,
    token: ChipInventoryToken,
) -> CompiledChipDefinition:
    if (
        inventory.ruleset_id,
        inventory.ruleset_version,
        inventory.ruleset_hash,
        inventory.bundle_hash,
    ) != (
        bundle.ruleset_id,
        bundle.ruleset_version,
        bundle.ruleset_hash,
        bundle.bundle_hash,
    ):
        raise ChipError("CHIP_LINEAGE_MISMATCH", "chip inventory and compiled bundle differ")
    compiled = bundle.definition_for(token.chip_key)
    if compiled.definition_hash != token.definition_hash:
        raise ChipError("CHIP_DEFINITION_MISMATCH", "chip token definition hash differs")
    return compiled


def _assert_available(
    inventory: ChipInventory,
    token: ChipInventoryToken,
    compiled: CompiledChipDefinition,
) -> None:
    gameweek = inventory.current_gameweek
    if compiled.activation_status != ActivationStatus.READY:
        raise ChipError(
            "CHIP_EFFECT_BLOCKED",
            "chip has unknown or invalid effect semantics",
            chip_key=token.chip_key,
            blockers=compiled.blockers,
        )
    if token.status != TokenStatus.AVAILABLE:
        raise ChipError(
            "CHIP_TOKEN_UNAVAILABLE",
            "chip token is not available",
            token_id=token.token_id,
            status=token.status,
        )
    if not token.activation_start_gameweek <= gameweek <= token.activation_end_gameweek:
        raise ChipError("CHIP_WINDOW_CLOSED", "chip token is outside its activation window")
    if gameweek in token.excluded_gameweeks:
        raise ChipError("CHIP_GAMEWEEK_EXCLUDED", "chip is excluded in the current Gameweek")


def select_token(
    inventory: ChipInventory,
    bundle: CompiledChipBundle,
    *,
    token_id: str,
) -> ChipInventory:
    """Place a cancellable token selection without consuming it."""

    token = inventory.token(token_id)
    compiled = _compiled_for(bundle, inventory, token)
    _assert_available(inventory, token, compiled)
    if not compiled.definition.cancellable_before_lock:
        raise ChipError("CHIP_NOT_CANCELLABLE", "chip selection is immediately irreversible")
    if any(item.status == TokenStatus.PENDING_CANCELLABLE for item in inventory.tokens):
        raise ChipError("CHIP_SELECTION_CONFLICT", "another chip token is already pending")
    replacement = token.model_copy(
        update={
            "status": TokenStatus.PENDING_CANCELLABLE,
            "selected_at_gameweek": inventory.current_gameweek,
            "history": (
                *token.history,
                TokenEvent(event=TokenEventKind.SELECTED, gameweek=inventory.current_gameweek),
            ),
        }
    )
    return _replace_token(inventory, replacement)


def cancel_token(
    inventory: ChipInventory,
    *,
    token_id: str,
) -> ChipInventory:
    """Cancel a pending selection without consuming its exercise right."""

    token = inventory.token(token_id)
    if token.status != TokenStatus.PENDING_CANCELLABLE:
        raise ChipError("CHIP_NOT_PENDING", "only a pending chip selection may be cancelled")
    replacement = token.model_copy(
        update={
            "status": TokenStatus.AVAILABLE,
            "selected_at_gameweek": None,
            "history": (
                *token.history,
                TokenEvent(event=TokenEventKind.CANCELLED, gameweek=inventory.current_gameweek),
            ),
        }
    )
    return _replace_token(inventory, replacement)


def _overlaps(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a <= end_b and start_b <= end_a


def activate_token(
    inventory: ChipInventory,
    bundle: CompiledChipBundle,
    *,
    token_id: str,
) -> ChipInventory:
    """Consume the current exercise decision and occupy its configured interval."""

    token = inventory.token(token_id)
    compiled = _compiled_for(bundle, inventory, token)
    if token.status == TokenStatus.AVAILABLE:
        _assert_available(inventory, token, compiled)
    elif token.status != TokenStatus.PENDING_CANCELLABLE:
        raise ChipError(
            "CHIP_TOKEN_UNAVAILABLE",
            "chip token is not available for activation",
            status=token.status,
        )
    else:
        if compiled.activation_status != ActivationStatus.READY:
            raise ChipError(
                "CHIP_EFFECT_BLOCKED",
                "chip has unknown or invalid effect semantics",
                chip_key=token.chip_key,
                blockers=compiled.blockers,
            )
        if not compiled.definition.cancellable_before_lock:
            raise ChipError(
                "CHIP_PENDING_STATE_INVALID",
                "only a cancellable chip can have a pending selection",
            )
        if token.selected_at_gameweek != inventory.current_gameweek:
            raise ChipError(
                "CHIP_PENDING_STATE_INVALID",
                "pending chip selection must belong to the current Gameweek",
            )
        if not (
            token.activation_start_gameweek
            <= inventory.current_gameweek
            <= token.activation_end_gameweek
        ):
            raise ChipError("CHIP_WINDOW_CLOSED", "chip token is outside its activation window")
        if inventory.current_gameweek in token.excluded_gameweeks:
            raise ChipError("CHIP_GAMEWEEK_EXCLUDED", "chip is excluded in the current Gameweek")

    current = inventory.current_gameweek
    active_until = current + token.duration_gameweeks - 1
    active = tuple(item for item in inventory.tokens if item.status == TokenStatus.ACTIVE)
    overlaps = tuple(
        item
        for item in active
        if item.active_from_gameweek is not None
        and item.active_until_gameweek is not None
        and _overlaps(current, active_until, item.active_from_gameweek, item.active_until_gameweek)
    )
    if len(overlaps) >= inventory.concurrency_limit:
        raise ChipError("CHIP_CONCURRENCY_LIMIT", "chip activation exceeds concurrency limit")
    if any(item.concurrency_group == token.concurrency_group for item in overlaps):
        raise ChipError("CHIP_CONCURRENCY_GROUP", "chip activation conflicts with occupied group")

    prior = tuple(
        item.used_at_gameweek
        for item in inventory.tokens
        if item.chip_key == token.chip_key and item.used_at_gameweek is not None
    )
    if prior and current - max(prior) <= token.minimum_gap_gameweeks:
        raise ChipError("CHIP_MINIMUM_GAP", "chip activation violates its minimum Gameweek gap")

    replacement = token.model_copy(
        update={
            "status": TokenStatus.ACTIVE,
            "selected_at_gameweek": token.selected_at_gameweek or current,
            "active_from_gameweek": current,
            "active_until_gameweek": active_until,
            "history": (
                *token.history,
                TokenEvent(event=TokenEventKind.ACTIVATED, gameweek=current),
            ),
        }
    )
    return _replace_token(inventory, replacement)


def advance_inventory(
    inventory: ChipInventory,
    *,
    to_gameweek: int,
) -> ChipInventory:
    """Advance acquisition, activation windows, completion and expiry deterministically."""

    if to_gameweek < inventory.current_gameweek:
        raise ChipError("CHIP_TIME_REVERSED", "chip inventory cannot move backwards")
    if to_gameweek == inventory.current_gameweek:
        return inventory

    advanced: list[ChipInventoryToken] = []
    for token in inventory.tokens:
        status = token.status
        history = token.history
        updates: dict[str, object] = {}

        if status == TokenStatus.PENDING_CANCELLABLE:
            status = TokenStatus.AVAILABLE
            updates["selected_at_gameweek"] = None
            history = (
                *history,
                TokenEvent(event=TokenEventKind.CANCELLED, gameweek=inventory.current_gameweek),
            )

        if status == TokenStatus.ACTIVE:
            assert token.active_until_gameweek is not None
            if to_gameweek > token.active_until_gameweek:
                status = TokenStatus.USED
                updates["used_at_gameweek"] = token.active_until_gameweek
                history = (
                    *history,
                    TokenEvent(
                        event=TokenEventKind.COMPLETED,
                        gameweek=token.active_until_gameweek,
                    ),
                )
        elif status not in {TokenStatus.USED, TokenStatus.EXPIRED}:
            acquired_already = any(event.event == TokenEventKind.ACQUIRED for event in history)
            if to_gameweek >= token.acquired_gameweek and not acquired_already:
                history = (
                    *history,
                    TokenEvent(event=TokenEventKind.ACQUIRED, gameweek=token.acquired_gameweek),
                )
            if to_gameweek > token.expires_after_gameweek:
                status = TokenStatus.EXPIRED
                if not any(event.event == TokenEventKind.EXPIRED for event in history):
                    history = (
                        *history,
                        TokenEvent(
                            event=TokenEventKind.EXPIRED,
                            gameweek=token.expires_after_gameweek,
                        ),
                    )
            elif (
                to_gameweek >= token.acquired_gameweek
                and token.activation_start_gameweek <= to_gameweek <= token.activation_end_gameweek
            ):
                status = TokenStatus.AVAILABLE
            else:
                status = TokenStatus.UNAVAILABLE

        updates.update(status=status, history=history)
        advanced.append(token.model_copy(update=updates))
    return _make_inventory(
        inventory,
        current_gameweek=to_gameweek,
        tokens=tuple(advanced),
    )


def validate_chip_inventory(
    inventory: ChipInventory,
    bundle: CompiledChipBundle,
) -> ChipInventory:
    """Independently replay a rules-bound inventory and reject forged state.

    A semantic hash proves byte-level integrity, not that tokens were minted by
    the compiled rules or reached their state through legal transitions.  This
    verifier reconstructs the inventory from the bundle and replays every
    user-driven selection, cancellation and activation event before comparing
    the complete resulting state.
    """

    checked = ChipInventory.model_validate(inventory.model_dump(mode="python"))
    expected_hash = semantic_sha256(checked.model_dump(mode="json", exclude={"inventory_hash"}))
    if checked.inventory_hash != expected_hash:
        raise ChipError(
            "CHIP_INVENTORY_HASH_MISMATCH",
            "chip inventory hash does not match",
        )
    if (
        checked.ruleset_id,
        checked.ruleset_version,
        checked.ruleset_hash,
        checked.bundle_hash,
        checked.concurrency_limit,
    ) != (
        bundle.ruleset_id,
        bundle.ruleset_version,
        bundle.ruleset_hash,
        bundle.bundle_hash,
        bundle.concurrency_limit,
    ):
        raise ChipError(
            "CHIP_INVENTORY_BUNDLE_MISMATCH",
            "chip inventory does not match the compiled rules bundle",
        )

    replayed = build_chip_inventory(bundle, current_gameweek=1)
    commands = tuple(
        sorted(
            (
                event.gameweek,
                token.token_id,
                index,
                event.event,
            )
            for token in checked.tokens
            for index, event in enumerate(token.history)
            if event.event
            in {
                TokenEventKind.SELECTED,
                TokenEventKind.CANCELLED,
                TokenEventKind.ACTIVATED,
            }
        )
    )
    for gameweek, token_id, _, event in commands:
        if gameweek > checked.current_gameweek:
            raise ChipError(
                "CHIP_INVENTORY_FUTURE_EVENT",
                "chip inventory history contains a future event",
                token_id=token_id,
                gameweek=gameweek,
            )
        replayed = advance_inventory(replayed, to_gameweek=gameweek)
        if event is TokenEventKind.SELECTED:
            replayed = select_token(replayed, bundle, token_id=token_id)
        elif event is TokenEventKind.CANCELLED:
            replayed = cancel_token(replayed, token_id=token_id)
        else:
            replayed = activate_token(replayed, bundle, token_id=token_id)
    replayed = advance_inventory(replayed, to_gameweek=checked.current_gameweek)
    if replayed != checked:
        raise ChipError(
            "CHIP_INVENTORY_STATE_INVALID",
            "chip inventory was not produced by legal compiled-rules transitions",
        )
    return checked


def available_token_ids(inventory: ChipInventory) -> tuple[str, ...]:
    """Return stable available-token IDs for policy generation."""

    return tuple(
        token.token_id for token in inventory.tokens if token.status == TokenStatus.AVAILABLE
    )
