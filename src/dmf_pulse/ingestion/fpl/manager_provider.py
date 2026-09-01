"""Authenticated official-FPL current-team parsing and manager-state adaptation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError

from dmf_pulse.chips.definitions import CompiledChipBundle
from dmf_pulse.chips.inventory import ChipInventoryToken, build_chip_inventory
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplInputBundle
from dmf_pulse.ingestion.fpl.manager_current import (
    CurrentManagerAttestation,
    CurrentManagerChipDeclaration,
    CurrentManagerDeclaration,
    CurrentManagerLineupDeclaration,
    CurrentManagerPlayerDeclaration,
)
from dmf_pulse.rules.models import FPLPosition

PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class ProviderCurrentPick(_ProviderModel):
    element: PositiveInt
    position: PositiveInt
    selling_price: PositiveInt
    purchase_price: PositiveInt
    multiplier: NonNegativeInt
    is_captain: StrictBool
    is_vice_captain: StrictBool


class ProviderCurrentChip(_ProviderModel):
    name: StrictStr = Field(min_length=1, max_length=40)
    number: PositiveInt
    status_for_entry: StrictStr = Field(min_length=1, max_length=40)
    played_by_entry: tuple[PositiveInt, ...]


class ProviderCurrentTransfers(_ProviderModel):
    cost: NonNegativeInt
    status: StrictStr = Field(min_length=1, max_length=40)
    limit: NonNegativeInt | None
    made: NonNegativeInt
    bank: NonNegativeInt
    value: PositiveInt


class ProviderCurrentTeam(_ProviderModel):
    picks: tuple[ProviderCurrentPick, ...] = Field(min_length=1)
    chips: tuple[ProviderCurrentChip, ...] = Field(min_length=1)
    transfers: ProviderCurrentTransfers


_CHIP_KEYS = {
    "wildcard": "WILDCARD",
    "freehit": "FREE_HIT",
    "bboost": "BENCH_BOOST",
    "3xc": "TRIPLE_CAPTAIN",
}


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate provider key")
        value[key] = item
    return value


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite provider constant is forbidden: {value}")


def parse_provider_current_team(body: bytes) -> ProviderCurrentTeam:
    """Parse one bounded response without retaining the source bytes."""

    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
        if not isinstance(value, dict):
            raise ValueError("provider current team must be an object")
        return ProviderCurrentTeam.model_validate_json(body)
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise IngestionError(
            "VALIDATION_FAILED", "authenticated current FPL team failed schema validation"
        ) from None


def _chip_declarations(
    source: ProviderCurrentTeam,
    bundle: CompiledChipBundle,
    *,
    target_gameweek: int,
) -> tuple[CurrentManagerChipDeclaration, ...]:
    base = build_chip_inventory(bundle, current_gameweek=target_gameweek)
    records: dict[str, list[ProviderCurrentChip]] = {}
    for item in source.chips:
        chip_key = _CHIP_KEYS.get(item.name.casefold())
        if chip_key is None:
            raise IngestionError("SCHEMA_DRIFT", "FPL published an unknown chip identity")
        records.setdefault(chip_key, []).append(item)
    tokens: dict[str, list[ChipInventoryToken]] = {}
    for token in base.tokens:
        tokens.setdefault(token.chip_key, []).append(token)
    if set(records) != set(tokens):
        raise IngestionError("MAPPING_CONFLICT", "FPL chip inventory is incomplete")

    declarations = {
        token.token_id: CurrentManagerChipDeclaration(
            token_id=token.token_id,
            status=token.status.value,
        )
        for token in base.tokens
    }
    mapped_tokens: set[str] = set()
    for chip_key, key_tokens in sorted(tokens.items()):
        key_tokens.sort(key=lambda item: (item.activation_start_gameweek, item.token_id))
        for record in sorted(records[chip_key], key=lambda item: item.number):
            played = tuple(sorted(set(record.played_by_entry)))
            if len(played) != len(record.played_by_entry) or len(played) > 1:
                raise IngestionError("VALIDATION_FAILED", "FPL chip use history is ambiguous")
            status = record.status_for_entry.casefold()
            if status not in {"active", "pending", "available", "unavailable"}:
                raise IngestionError("SCHEMA_DRIFT", "FPL published an unknown chip status")
            if played:
                if status != "unavailable":
                    raise IngestionError(
                        "VALIDATION_FAILED", "FPL chip status contradicts its use history"
                    )
                event = played[0]
                candidates = tuple(
                    token
                    for token in key_tokens
                    if token.activation_start_gameweek <= event <= token.activation_end_gameweek
                )
                if not candidates:
                    raise IngestionError("MAPPING_CONFLICT", "FPL chip use is outside its window")
                if len(candidates) != 1:
                    raise IngestionError("MAPPING_CONFLICT", "FPL chip copies are ambiguous")
                mapped_chip = candidates[0]
                declaration = CurrentManagerChipDeclaration(
                    token_id=mapped_chip.token_id, status="USED", used_at_gameweek=event
                )
            else:
                candidates = tuple(
                    token
                    for token in key_tokens
                    if token.activation_start_gameweek
                    <= target_gameweek
                    <= token.activation_end_gameweek
                )
                if len(candidates) != 1:
                    raise IngestionError("MAPPING_CONFLICT", "FPL current chip copy is ambiguous")
                mapped_chip = candidates[0]
                if status in {"active", "pending"}:
                    declaration = CurrentManagerChipDeclaration(
                        token_id=mapped_chip.token_id,
                        status="PENDING_CANCELLABLE",
                        selected_at_gameweek=target_gameweek,
                    )
                else:
                    declaration = CurrentManagerChipDeclaration(
                        token_id=mapped_chip.token_id,
                        status="AVAILABLE" if status == "available" else "UNAVAILABLE",
                    )
            if mapped_chip.token_id in mapped_tokens:
                raise IngestionError("MAPPING_CONFLICT", "FPL chip records are ambiguous")
            mapped_tokens.add(mapped_chip.token_id)
            declarations[mapped_chip.token_id] = declaration
    return tuple(sorted(declarations.values(), key=lambda item: item.token_id))


def provider_current_manager_declaration(
    source: ProviderCurrentTeam,
    fpl_input: CurrentFplInputBundle,
    chip_bundle: CompiledChipBundle,
    *,
    observed_at: datetime,
    overall_points: int | None = None,
    overall_rank: int | None = None,
) -> CurrentManagerDeclaration:
    """Map authoritative current-team facts to the accepted manager contract."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise IngestionError("VALIDATION_FAILED", "provider observation time must be aware")
    observed_at = observed_at.astimezone(UTC)
    if observed_at > fpl_input.provenance.information_cutoff:
        raise IngestionError("POST_CUTOFF", "provider manager observation is post-cutoff")
    catalogue = {item.provider_element_id: item for item in fpl_input.players}
    picks = tuple(sorted(source.picks, key=lambda item: item.position))
    if len(picks) != 15 or tuple(item.position for item in picks) != tuple(range(1, 16)):
        raise IngestionError("VALIDATION_FAILED", "current FPL picks do not form a 15-player squad")
    if len({item.element for item in picks}) != 15 or any(
        item.element not in catalogue for item in picks
    ):
        raise IngestionError("MAPPING_CONFLICT", "current FPL picks contain an unknown player")
    starters = tuple(item.element for item in picks if item.position <= 11)
    bench = tuple(item for item in picks if item.position > 11)
    bench_goalkeepers = tuple(
        item.element for item in bench if catalogue[item.element].position is FPLPosition.GK
    )
    bench_outfield = tuple(
        item.element for item in bench if catalogue[item.element].position is not FPLPosition.GK
    )
    captains = tuple(item.element for item in picks if item.is_captain)
    vice_captains = tuple(item.element for item in picks if item.is_vice_captain)
    if len(bench_goalkeepers) != 1 or len(bench_outfield) != 3:
        raise IngestionError("VALIDATION_FAILED", "current FPL bench roles are invalid")
    if len(captains) != 1 or len(vice_captains) != 1:
        raise IngestionError("VALIDATION_FAILED", "current FPL captaincy is ambiguous")
    if source.transfers.limit is None:
        raise IngestionError(
            "CURRENT_MANAGER_TRANSFER_LIMIT_UNRESOLVED",
            "FPL current-team response does not expose a finite free-transfer limit",
        )
    return CurrentManagerDeclaration(
        source_class="PROVIDER_OBSERVED",
        target_gameweek=fpl_input.target_gameweek,
        information_cutoff=fpl_input.provenance.information_cutoff,
        attestation=CurrentManagerAttestation(
            declaration_method="PROVIDER_OBSERVED",
            attestation_status="PROVIDER_OBSERVED",
            provider_verification="PROVIDER_VERIFIED",
            declared_at=observed_at,
            attested_at=observed_at,
            operator_reference="official-fpl-current-team",
        ),
        squad=tuple(
            sorted(
                (
                    CurrentManagerPlayerDeclaration(
                        official_fpl_element_id=item.element,
                        purchase_price_tenths=item.purchase_price,
                        observed_selling_price_tenths=item.selling_price,
                    )
                    for item in picks
                ),
                key=lambda item: item.official_fpl_element_id,
            )
        ),
        bank_tenths=source.transfers.bank,
        free_transfers=max(source.transfers.limit - source.transfers.made, 0),
        lineup=CurrentManagerLineupDeclaration(
            starting_xi_element_ids=tuple(sorted(starters)),
            bench_goalkeeper_element_id=bench_goalkeepers[0],
            bench_outfield_element_ids=bench_outfield,
            captain_element_id=captains[0],
            vice_captain_element_id=vice_captains[0],
        ),
        chip_tokens=_chip_declarations(
            source, chip_bundle, target_gameweek=fpl_input.target_gameweek
        ),
        overall_points=overall_points,
        overall_rank=overall_rank,
    )


__all__ = [
    "ProviderCurrentChip",
    "ProviderCurrentPick",
    "ProviderCurrentTeam",
    "ProviderCurrentTransfers",
    "parse_provider_current_team",
    "provider_current_manager_declaration",
]
