"""Nested and source-bound semantic tamper tests for CURRENT-FPL-STATE-001C."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.inventory import TokenStatus
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.manager_current import (
    CurrentManagerStateBundle,
    CurrentManagerStateService,
    current_manager_state_semantic_sha256,
)
from tests.unit.ingestion.current_manager_test_support import (
    CurrentManagerTestContext,
    build_context,
    compile_manager,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def context(repository_root: Path, tmp_path: Path) -> CurrentManagerTestContext:
    return build_context(repository_root, tmp_path)


def _reseal(value: CurrentManagerStateBundle) -> CurrentManagerStateBundle:
    return value.model_copy(
        update={"semantic_sha256": current_manager_state_semantic_sha256(value)}
    )


def _changed_member(
    bundle: CurrentManagerStateBundle, field: str, value: object
) -> CurrentManagerStateBundle:
    member = bundle.squad[0].model_copy(update={field: value})
    return bundle.model_copy(update={"squad": (member, *bundle.squad[1:])})


def _changed_lineup(
    bundle: CurrentManagerStateBundle, field: str, value: object
) -> CurrentManagerStateBundle:
    return bundle.model_copy(update={"lineup": bundle.lineup.model_copy(update={field: value})})


def _changed_declaration_player(bundle: CurrentManagerStateBundle) -> CurrentManagerStateBundle:
    member = bundle.declaration.squad[0].model_copy(
        update={"purchase_price_tenths": bundle.declaration.squad[0].purchase_price_tenths + 1}
    )
    declaration = bundle.declaration.model_copy(
        update={"squad": (member, *bundle.declaration.squad[1:])}
    )
    return bundle.model_copy(update={"declaration": declaration})


def _changed_declaration_chip(bundle: CurrentManagerStateBundle) -> CurrentManagerStateBundle:
    token = bundle.declaration.chip_tokens[0].model_copy(update={"status": "UNAVAILABLE"})
    declaration = bundle.declaration.model_copy(
        update={"chip_tokens": (token, *bundle.declaration.chip_tokens[1:])}
    )
    return bundle.model_copy(update={"declaration": declaration})


def _changed_inventory(bundle: CurrentManagerStateBundle) -> CurrentManagerStateBundle:
    token = bundle.chip_inventory.tokens[0].model_copy(
        update={"status": TokenStatus.USED, "used_at_gameweek": 1}
    )
    inventory = bundle.chip_inventory.model_copy(
        update={"tokens": (token, *bundle.chip_inventory.tokens[1:])}
    )
    return bundle.model_copy(update={"chip_inventory": inventory})


def _changed_lineage(bundle: CurrentManagerStateBundle, field: str) -> CurrentManagerStateBundle:
    lineage = bundle.lineage.model_copy(update={field: "0" * 64})
    return bundle.model_copy(update={"lineage": lineage})


def test_outer_hash_and_every_private_nested_authority_resist_tamper(
    context: CurrentManagerTestContext,
) -> None:
    bundle = compile_manager(context)
    mutations: tuple[Callable[[CurrentManagerStateBundle], CurrentManagerStateBundle], ...] = (
        lambda value: _changed_member(
            value, "official_fpl_element_id", value.squad[0].official_fpl_element_id + 1000
        ),
        lambda value: _changed_member(
            value, "purchase_price_tenths", value.squad[0].purchase_price_tenths + 1
        ),
        _changed_declaration_player,
        lambda value: value.model_copy(update={"bank_tenths": value.bank_tenths + 1}),
        lambda value: value.model_copy(update={"free_transfers": value.free_transfers + 1}),
        lambda value: _changed_lineup(
            value, "captain_element_id", value.lineup.vice_captain_element_id
        ),
        lambda value: _changed_lineup(
            value, "vice_captain_element_id", value.lineup.captain_element_id
        ),
        lambda value: _changed_lineup(
            value,
            "bench_outfield_element_ids",
            tuple(reversed(value.lineup.bench_outfield_element_ids)),
        ),
        _changed_declaration_chip,
        _changed_inventory,
        lambda value: value.model_copy(
            update={"information_cutoff": value.information_cutoff.replace(microsecond=1)}
        ),
        lambda value: _changed_lineage(value, "ruleset_sha256"),
        lambda value: _changed_lineage(value, "fpl_input_semantic_sha256"),
        lambda value: _changed_lineage(value, "selling_price_rule_semantic_sha256"),
    )
    verifier = CurrentManagerStateService()
    for mutate in mutations:
        tampered = _reseal(mutate(bundle))
        with pytest.raises(IngestionError) as caught:
            verifier.verify(
                tampered,
                fpl_input=context.fpl_input,
                ruleset=context.ruleset,
                capability=context.capability,
            )
        assert caught.value.code == "MAPPING_CONFLICT"


def test_outer_semantic_hash_tamper_is_rejected_before_source_comparison(
    context: CurrentManagerTestContext,
) -> None:
    bundle = compile_manager(context)
    tampered = bundle.model_copy(update={"semantic_sha256": "0" * 64})
    with pytest.raises(IngestionError) as caught:
        CurrentManagerStateService().verify(
            tampered,
            fpl_input=context.fpl_input,
            ruleset=context.ruleset,
            capability=context.capability,
        )
    assert caught.value.code == "MAPPING_CONFLICT"


def test_output_contracts_are_immutable(
    context: CurrentManagerTestContext,
) -> None:
    bundle = compile_manager(context)
    with pytest.raises(ValidationError):
        bundle.bank_tenths = 99  # type: ignore[misc]
    with pytest.raises(ValidationError):
        bundle.runtime.network_called = True  # type: ignore[misc]
