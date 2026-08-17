"""Immutable manager state and ownership-cohort semantics for Stage 11."""

from __future__ import annotations

from collections import Counter
from itertools import pairwise
from typing import TYPE_CHECKING, Literal

from pydantic import Field, StrictStr, model_validator

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import PlayerPosition
from dmf_pulse.optimisation.models import NonNegativeInt, OptimisationModel, PositiveInt, Sha256

if TYPE_CHECKING:
    from dmf_pulse.optimisation.multi_gameweek_models import (
        PlayerCatalogEntry,
        SellingPriceRule,
        TransferRules,
    )


class OwnershipSpell(OptimisationModel):
    """One append-only purchase cohort for one player."""

    spell_id: StrictStr = Field(min_length=1, max_length=200)
    player_id: StrictStr = Field(min_length=1, max_length=100)
    club_id: StrictStr = Field(min_length=1, max_length=100)
    position: PlayerPosition
    purchase_price_tenths: NonNegativeInt
    current_price_tenths: NonNegativeInt
    started_gameweek: PositiveInt
    started_at_node_id: StrictStr = Field(min_length=1, max_length=100)
    ended_gameweek: PositiveInt | None = None
    ended_at_node_id: StrictStr | None = None
    realised_selling_price_tenths: NonNegativeInt | None = None

    @model_validator(mode="after")
    def closure_is_coherent(self) -> OwnershipSpell:
        closed = self.ended_gameweek is not None
        if closed != (self.ended_at_node_id is not None):
            raise ValueError("ownership-spell end node and Gameweek must be populated together")
        if closed != (self.realised_selling_price_tenths is not None):
            raise ValueError("closed ownership spell requires its realised selling price")
        if self.ended_gameweek is not None and self.ended_gameweek < self.started_gameweek:
            raise ValueError("ownership spell cannot end before it starts")
        return self

    @property
    def active(self) -> bool:
        return self.ended_gameweek is None


class ManagerState(OptimisationModel):
    """Replayable state immediately before one transfer decision."""

    schema_version: Literal["multi-gameweek-manager-state-v1"] = "multi-gameweek-manager-state-v1"
    state_id: StrictStr = Field(min_length=1, max_length=200)
    parent_state_id: StrictStr | None = None
    current_gameweek: PositiveInt
    observed_node_id: StrictStr = Field(min_length=1, max_length=100)
    bank_tenths: NonNegativeInt
    free_transfers: NonNegativeInt
    ownership_spells: tuple[OwnershipSpell, ...] = Field(min_length=1)
    ruleset_id: StrictStr = Field(min_length=1, max_length=100)
    ruleset_version: StrictStr = Field(min_length=1, max_length=100)
    ruleset_hash: Sha256
    transition_id: StrictStr | None = None
    state_sha256: Sha256

    @model_validator(mode="after")
    def canonical_state(self) -> ManagerState:
        keys = tuple(
            (spell.player_id, spell.started_gameweek, spell.spell_id)
            for spell in self.ownership_spells
        )
        if keys != tuple(sorted(keys)):
            raise ValueError("ownership spells must be canonically sorted")
        spell_ids = tuple(item.spell_id for item in self.ownership_spells)
        if len(spell_ids) != len(set(spell_ids)):
            raise ValueError("ownership spell IDs must be unique")
        active = tuple(item.player_id for item in self.ownership_spells if item.active)
        if not active or len(active) != len(set(active)):
            raise ValueError("active ownership spells must form a non-empty unique squad")
        by_player: dict[str, list[OwnershipSpell]] = {}
        for spell in self.ownership_spells:
            by_player.setdefault(spell.player_id, []).append(spell)
        for spells in by_player.values():
            for previous, current in pairwise(spells):
                if previous.active:
                    raise ValueError("an active ownership spell must be the player's latest spell")
                if (
                    previous.ended_gameweek is not None
                    and previous.ended_gameweek > current.started_gameweek
                ):
                    raise ValueError("ownership spells for one player cannot overlap")
        return self

    @property
    def active_spells(self) -> tuple[OwnershipSpell, ...]:
        return tuple(item for item in self.ownership_spells if item.active)

    @property
    def active_by_player(self) -> dict[str, OwnershipSpell]:
        return {item.player_id: item for item in self.active_spells}

    @property
    def squad_ids(self) -> tuple[str, ...]:
        return tuple(sorted(item.player_id for item in self.active_spells))


def _payload(value: ManagerState) -> dict[str, object]:
    payload = value.model_dump(mode="json")
    payload["state_sha256"] = None
    return payload


def seal_manager_state(value: ManagerState) -> ManagerState:
    return value.model_copy(update={"state_sha256": semantic_sha256(_payload(value))})


def verify_manager_state_hash(value: ManagerState) -> None:
    if value.state_sha256 != semantic_sha256(_payload(value)):
        raise ValueError("manager-state semantic hash does not match")


def state_fingerprint(value: ManagerState) -> str:
    return semantic_sha256(
        {
            "current_gameweek": value.current_gameweek,
            "observed_node_id": value.observed_node_id,
            "bank_tenths": value.bank_tenths,
            "free_transfers": value.free_transfers,
            "ruleset_hash": value.ruleset_hash,
            "ownership_spells": [item.model_dump(mode="json") for item in value.ownership_spells],
        }
    )


def selling_price_tenths(
    *,
    purchase_price_tenths: int,
    current_price_tenths: int,
    rule: SellingPriceRule,
) -> int:
    """Apply configured retained-profit/full-loss semantics in integer price units."""

    if purchase_price_tenths < 0 or current_price_tenths < 0:
        raise ValueError("prices must be non-negative integer tenths")
    if current_price_tenths <= purchase_price_tenths:
        return current_price_tenths
    profit = current_price_tenths - purchase_price_tenths
    retained = profit * rule.retained_profit_numerator // rule.retained_profit_denominator
    return purchase_price_tenths + retained


def validate_manager_state(
    value: ManagerState,
    *,
    candidate_pool: tuple[PlayerCatalogEntry, ...],
    rules: TransferRules,
) -> None:
    """Validate exact squad legality, FT range and ownership-spell integrity."""

    verify_manager_state_hash(value)
    if (
        value.ruleset_id != rules.ruleset_id
        or value.ruleset_version != rules.ruleset_version
        or value.ruleset_hash != rules.ruleset_hash
    ):
        raise ValueError("manager state and transfer rules lineage differ")
    if value.free_transfers > rules.maximum_free_transfers:
        raise ValueError("free-transfer state exceeds configured maximum")
    catalog = {item.player_id: item for item in candidate_pool}
    if len(catalog) != len(candidate_pool):
        raise ValueError("candidate pool contains duplicate player IDs")
    if len(value.active_spells) != rules.squad_size:
        raise ValueError("active permanent squad has the wrong size")
    if not set(value.squad_ids) <= set(catalog):
        raise ValueError("active squad contains an unknown player")
    for spell in value.ownership_spells:
        entry = catalog.get(spell.player_id)
        if entry is None:
            raise ValueError("ownership history contains an unknown player")
        if entry.club_id != spell.club_id or entry.position is not spell.position:
            raise ValueError("ownership spell metadata differs from the player catalog")
        if not spell.active and spell.realised_selling_price_tenths != selling_price_tenths(
            purchase_price_tenths=spell.purchase_price_tenths,
            current_price_tenths=spell.current_price_tenths,
            rule=rules.selling_price_rule,
        ):
            raise ValueError("closed ownership spell has an invalid realised selling price")
    if Counter(item.position for item in value.active_spells) != Counter(
        rules.position_squad_quota
    ):
        raise ValueError("active squad violates configured position quotas")
    clubs = Counter(item.club_id for item in value.active_spells)
    if clubs and max(clubs.values()) > rules.max_players_per_club:
        raise ValueError("active squad violates configured club maximum")
