"""Generic optimisation-facing chip definitions and effect grammar.

Deterministic chip mechanics remain owned by the accepted rules layer.  These
models compile that layer into a finite-inventory representation suitable for
Stage-14 policy evaluation, and also support explicit synthetic future chips.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
ParameterValue = StrictBool | StrictInt | StrictStr


class FrozenModel(BaseModel):
    """Strict immutable base for reproducible decision inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ActivationStatus(StrEnum):
    """Whether a compiled definition may be used by policy code."""

    READY = "READY"
    BLOCKED_UNKNOWN_EFFECT = "BLOCKED_UNKNOWN_EFFECT"
    BLOCKED_INVALID_SEMANTICS = "BLOCKED_INVALID_SEMANTICS"


class ActivationRoute(StrEnum):
    """Generic route used by the deterministic rules state machine."""

    PICK_TEAM_SAVE = "PICK_TEAM_SAVE"
    CONFIRMED_TRANSFERS = "CONFIRMED_TRANSFERS"
    EXPLICIT_CONFIRMATION = "EXPLICIT_CONFIRMATION"


class EffectCapability(StrEnum):
    """Closed optimisation capabilities derived from declarative effects."""

    SCORING_TRANSFORM = "SCORING_TRANSFORM"
    CAPTAIN_TRANSFORM = "CAPTAIN_TRANSFORM"
    BENCH_TRANSFORM = "BENCH_TRANSFORM"
    TRANSFER_TRANSFORM = "TRANSFER_TRANSFORM"
    TEMPORARY_SQUAD = "TEMPORARY_SQUAD"
    PERMANENT_SQUAD = "PERMANENT_SQUAD"
    RESTORATION = "RESTORATION"
    BUDGET_TRANSFORM = "BUDGET_TRANSFORM"
    CLUB_TRANSFORM = "CLUB_TRANSFORM"
    POSITION_TRANSFORM = "POSITION_TRANSFORM"
    FREE_TRANSFER_TRANSFORM = "FREE_TRANSFER_TRANSFORM"
    CONFLICT_OCCUPANCY = "CONFLICT_OCCUPANCY"


class InventoryGrant(FrozenModel):
    """One acquisition/window declaration that can mint several token copies."""

    grant_id: StrictStr = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    copies: PositiveInt
    acquired_gameweek: PositiveInt
    activation_start_gameweek: PositiveInt
    activation_end_gameweek: PositiveInt
    expires_after_gameweek: PositiveInt

    @model_validator(mode="after")
    def chronology_is_valid(self) -> InventoryGrant:
        if self.acquired_gameweek > self.activation_start_gameweek:
            raise ValueError("chip grant cannot be acquired after its activation starts")
        if self.activation_start_gameweek > self.activation_end_gameweek:
            raise ValueError("chip activation window is inverted")
        if self.activation_end_gameweek > self.expires_after_gameweek:
            raise ValueError("chip cannot expire before the activation window ends")
        return self


class ChipEffect(FrozenModel):
    """One declarative effect; unknown pairs survive parsing but block compilation."""

    surface: StrictStr = Field(min_length=1, pattern=r"^[A-Z][A-Z0-9_]*$")
    operation: StrictStr = Field(min_length=1, pattern=r"^[A-Z][A-Z0-9_]*$")
    parameters: dict[StrictStr, ParameterValue] = Field(default_factory=dict)


class ChipDefinition(FrozenModel):
    """Generic chip definition independent of FPL chip names."""

    chip_key: StrictStr = Field(min_length=1, pattern=r"^[A-Z][A-Z0-9_]*$")
    definition_version: StrictStr = Field(min_length=1)
    grants: tuple[InventoryGrant, ...]
    duration_gameweeks: PositiveInt
    concurrency_group: StrictStr = Field(min_length=1)
    activation_route: ActivationRoute
    cancellable_before_lock: StrictBool
    lock_after_confirmed_transfer_count: PositiveInt | None = None
    excluded_gameweeks: tuple[PositiveInt, ...] = ()
    minimum_gap_gameweeks: NonNegativeInt = 0
    effects: tuple[ChipEffect, ...]

    @model_validator(mode="after")
    def definition_is_coherent(self) -> ChipDefinition:
        if not self.grants:
            raise ValueError("chip definition requires at least one inventory grant")
        grant_ids = tuple(grant.grant_id for grant in self.grants)
        if len(grant_ids) != len(set(grant_ids)):
            raise ValueError("chip inventory grant IDs must be unique")
        effects = tuple((effect.surface, effect.operation) for effect in self.effects)
        if not effects or len(effects) != len(set(effects)):
            raise ValueError("chip effects must be non-empty and unique by surface/operation")
        if len(self.excluded_gameweeks) != len(set(self.excluded_gameweeks)):
            raise ValueError("excluded Gameweeks must be unique")
        if (
            self.activation_route == ActivationRoute.CONFIRMED_TRANSFERS
            and self.lock_after_confirmed_transfer_count is None
        ):
            raise ValueError("confirmed-transfer activation requires a lock threshold")
        if (
            self.activation_route != ActivationRoute.CONFIRMED_TRANSFERS
            and self.lock_after_confirmed_transfer_count is not None
        ):
            raise ValueError("only confirmed-transfer activation may define a lock threshold")
        return self


class CompiledChipDefinition(FrozenModel):
    """Validated definition with derived capabilities and fail-closed blockers."""

    definition: ChipDefinition
    definition_hash: Sha256
    compiler_version: StrictStr
    activation_status: ActivationStatus
    capabilities: frozenset[EffectCapability]
    blockers: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def status_matches_blockers(self) -> CompiledChipDefinition:
        if self.activation_status == ActivationStatus.READY and self.blockers:
            raise ValueError("ready chip definition cannot contain blockers")
        if self.activation_status != ActivationStatus.READY and not self.blockers:
            raise ValueError("blocked chip definition must identify blockers")
        if EffectCapability.CONFLICT_OCCUPANCY not in self.capabilities:
            raise ValueError("every compiled chip must expose conflict occupancy")
        return self

    @property
    def chip_key(self) -> str:
        """Expose the generic key without duplicating it in the compiled payload."""

        return self.definition.chip_key


class CompiledChipBundle(FrozenModel):
    """Rules-bound optimisation chip bundle."""

    ruleset_id: StrictStr
    ruleset_version: StrictStr
    ruleset_hash: Sha256
    compiler_version: StrictStr
    concurrency_limit: PositiveInt
    definitions: tuple[CompiledChipDefinition, ...]
    bundle_hash: Sha256

    @model_validator(mode="after")
    def keys_are_unique(self) -> CompiledChipBundle:
        keys = tuple(item.chip_key for item in self.definitions)
        if not keys or len(keys) != len(set(keys)):
            raise ValueError("compiled chip keys must be non-empty and unique")
        return self

    def definition_for(self, chip_key: str) -> CompiledChipDefinition:
        """Resolve one chip definition or fail with an explicit key error."""

        for definition in self.definitions:
            if definition.chip_key == chip_key:
                return definition
        raise KeyError(chip_key)


def canonical_payload(value: BaseModel | dict[str, Any] | tuple[Any, ...] | list[Any]) -> bytes:
    """Serialize semantic input deterministically for hashing and artifacts."""

    if isinstance(value, BaseModel):
        payload: Any = value.model_dump(mode="json", exclude_none=False)
    else:
        payload = value
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def semantic_sha256(value: BaseModel | dict[str, Any] | tuple[Any, ...] | list[Any]) -> str:
    """Return the lowercase SHA-256 of canonical semantic JSON."""

    return hashlib.sha256(canonical_payload(value)).hexdigest()
