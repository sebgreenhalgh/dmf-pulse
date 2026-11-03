"""Diagnostic-only typed chip-schema adaptation; original HTTP inputs stay intact.

Only a proven past ``played`` observation is translated to the accepted compiler's
used-history spelling. Explicit inactive copies can be omitted from its argument
only after a unique governed assignment proves the compiler's existing default.
No chip availability, use event, rule, numeric model or provider body is invented.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, cast

from pydantic import Field

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.chips.definitions import CompiledChipBundle
from dmf_pulse.chips.inventory import ChipInventoryToken, build_chip_inventory
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.manager_provider import ProviderCurrentChip, ProviderCurrentTeam
from dmf_pulse.operation.models import Metadata, Sha

_CHIPS = {
    "wildcard": "WILDCARD",
    "freehit": "FREE_HIT",
    "bboost": "BENCH_BOOST",
    "3xc": "TRIPLE_CAPTAIN",
}
_STATUSES = frozenset({"available", "unavailable", "active", "pending", "played"})


class ChipSchemaProof(Metadata):
    """Closed derived evidence; hashes refer to typed objects, never a new HTTP response."""

    schema_version: Literal["opr003-chip-source-adapter-v1"] = "opr003-chip-source-adapter-v1"
    source_manager_sha256: Sha
    compiler_argument_sha256: Sha
    governed_chip_bundle_sha256: Sha
    assignment_sha256: Sha
    translated_played_records: int = Field(ge=0, strict=True)
    omitted_inactive_records: int = Field(ge=0, strict=True)


@dataclass(frozen=True, slots=True, repr=False)
class AdaptedChipSource:
    compiler_source: ProviderCurrentTeam
    proof: ChipSchemaProof


def _refuse(code: str) -> IngestionError:
    return IngestionError(code, "Diagnostic manager chip source failed its fixed contract")


def _bound_record(
    record: ProviderCurrentChip,
    tokens: tuple[ChipInventoryToken, ...],
    *,
    target_gameweek: int,
) -> ChipInventoryToken | None:
    status = record.status_for_entry.casefold()
    played = record.played_by_entry
    if len(played) > 1 or len(set(played)) != len(played):
        raise _refuse("DIAGNOSTIC_MANAGER_CHIP_HISTORY_INVALID")
    if status == "played" and (len(played) != 1 or played[0] >= target_gameweek):
        raise _refuse("DIAGNOSTIC_MANAGER_CHIP_HISTORY_INVALID")
    if played and status not in {"played", "unavailable"}:
        raise _refuse("DIAGNOSTIC_MANAGER_CHIP_HISTORY_INVALID")
    if status == "unavailable" and not played:
        return None
    event = played[0] if played else target_gameweek
    candidates = tuple(
        token
        for token in tokens
        if token.activation_start_gameweek <= event <= token.activation_end_gameweek
    )
    if len(candidates) != 1:
        raise _refuse("DIAGNOSTIC_MANAGER_CHIP_MAPPING_AMBIGUOUS")
    return candidates[0]


def adapt_chip_source(
    source: ProviderCurrentTeam,
    bundle: CompiledChipBundle,
    *,
    target_gameweek: int,
) -> AdaptedChipSource:
    """Derive a compiler argument from unique source/rule constraints, never numbers alone.

    A number is an opaque source identity: the existing supported number27 case
    remains valid. Repeated identities, two unresolved unavailable copies and
    window contradictions cannot be repaired by guessing an ordinal.
    """
    try:
        source = ProviderCurrentTeam.model_validate(
            source.model_dump(mode="python", warnings="error")
        )
    except (ValueError, TypeError):
        raise _refuse("DIAGNOSTIC_MANAGER_CHIP_SCHEMA_INVALID") from None
    inventory = build_chip_inventory(bundle, current_gameweek=target_gameweek)
    tokens_by_key: dict[str, list[ChipInventoryToken]] = defaultdict(list)
    records_by_key: dict[str, list[tuple[int, ProviderCurrentChip]]] = defaultdict(list)
    for token in inventory.tokens:
        tokens_by_key[token.chip_key].append(token)
    for index, record in enumerate(source.chips):
        key = _CHIPS.get(record.name.casefold())
        if key is None:
            raise _refuse("CURRENT_MANAGER_CHIP_IDENTITY_UNSUPPORTED")
        if record.status_for_entry.casefold() not in _STATUSES:
            raise _refuse("CURRENT_MANAGER_CHIP_STATUS_UNSUPPORTED")
        records_by_key[key].append((index, record))
    if set(tokens_by_key) != set(records_by_key):
        raise _refuse("DIAGNOSTIC_MANAGER_CHIP_MAPPING_AMBIGUOUS")
    adapted: dict[int, ProviderCurrentChip] = {}
    assignments: list[dict[str, object]] = []
    translated = omitted = 0
    for key, indexed in records_by_key.items():
        tokens = tuple(tokens_by_key[key])
        if len(indexed) > len(tokens) or len({r.number for _, r in indexed}) != len(indexed):
            raise _refuse("DIAGNOSTIC_MANAGER_CHIP_MAPPING_AMBIGUOUS")
        occupied: set[str] = set()
        unresolved: list[tuple[int, ProviderCurrentChip]] = []
        bindings: list[tuple[int, ProviderCurrentChip, ChipInventoryToken]] = []
        for index, record in indexed:
            bound_token = _bound_record(record, tokens, target_gameweek=target_gameweek)
            if bound_token is None:
                unresolved.append((index, record))
            else:
                if bound_token.token_id in occupied:
                    raise _refuse("DIAGNOSTIC_MANAGER_CHIP_MAPPING_AMBIGUOUS")
                occupied.add(bound_token.token_id)
                bindings.append((index, record, bound_token))
        if unresolved:
            # Preserve the accepted single-record current-window contract.
            candidates = tuple(
                token
                for token in tokens
                if token.token_id not in occupied
                and (
                    len(indexed) > 1
                    or token.activation_start_gameweek
                    <= target_gameweek
                    <= token.activation_end_gameweek
                )
            )
            if len(unresolved) != 1 or len(candidates) != 1:
                raise _refuse("DIAGNOSTIC_MANAGER_CHIP_MAPPING_AMBIGUOUS")
            index, record = unresolved[0]
            bindings.append((index, record, candidates[0]))
        for index, record, token in bindings:
            status = record.status_for_entry.casefold()
            inactive_copy = (
                status == "unavailable"
                and not record.played_by_entry
                and not token.activation_start_gameweek
                <= target_gameweek
                <= token.activation_end_gameweek
            )
            if inactive_copy:
                if token.status.value not in {"UNAVAILABLE", "EXPIRED"}:
                    raise _refuse("DIAGNOSTIC_MANAGER_CHIP_MAPPING_AMBIGUOUS")
                omitted += 1
            else:
                adapted[index] = (
                    record.model_copy(update={"status_for_entry": "unavailable"})
                    if status == "played"
                    else record
                )
                translated += int(status == "played")
            assignments.append(
                {
                    "source_index": index,
                    "source_number": record.number,
                    "token_id": token.token_id,
                    "translation": status == "played",
                    "omitted_inactive_copy": inactive_copy,
                }
            )
    compiler_source = source.model_copy(
        update={"chips": tuple(adapted[i] for i in sorted(adapted))}
    )
    return AdaptedChipSource(
        compiler_source,
        ChipSchemaProof(
            source_manager_sha256=canonical_sha256(source.model_dump(mode="json")),
            compiler_argument_sha256=canonical_sha256(compiler_source.model_dump(mode="json")),
            governed_chip_bundle_sha256=canonical_sha256(bundle.model_dump(mode="json")),
            assignment_sha256=canonical_sha256(
                sorted(assignments, key=lambda item: cast(int, item["source_index"]))
            ),
            translated_played_records=translated,
            omitted_inactive_records=omitted,
        ),
    )
