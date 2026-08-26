"""CURRENT-FPL-STATE-001C transient operator manager-state contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmf_pulse.ingestion.fpl.manager_current import CurrentManagerStateService
from tests.unit.ingestion.current_manager_test_support import (
    CurrentManagerTestContext,
    build_context,
    compile_manager,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def context(repository_root: Path, tmp_path: Path) -> CurrentManagerTestContext:
    return build_context(repository_root, tmp_path)


def test_valid_operator_declaration_compiles_private_transient_bundle(
    context: CurrentManagerTestContext,
) -> None:
    bundle = compile_manager(context)

    assert bundle.status == "VALID"
    assert bundle.source_class == "OPERATOR_DECLARED"
    assert bundle.attestation_status == "HUMAN_ATTESTED"
    assert bundle.provider_verification == "NOT_PROVIDER_VERIFIED"
    assert bundle.target_gameweek == 2
    assert len(bundle.squad) == 15
    assert {item.position.value for item in bundle.squad} == {"GK", "DEF", "MID", "FWD"}
    assert len(bundle.lineup.starting_xi_element_ids) == 11
    assert len(bundle.lineup.bench_outfield_element_ids) == 3
    assert bundle.bank_tenths == 15
    assert bundle.free_transfers == 2
    assert bundle.selected_chip_token_id is None
    assert bundle.runtime.storage_mode == "TRANSIENT_IN_MEMORY"
    assert bundle.runtime.persistence_performed is False
    assert bundle.runtime.database_accessed is False
    assert bundle.runtime.network_called is False
    assert bundle.lineage.fpl_input_semantic_sha256 == context.fpl_input.semantic_sha256
    assert bundle.lineage.ruleset_sha256 == context.ruleset.ruleset_hash
    assert bundle.lineage.chip_inventory_sha256 == bundle.chip_inventory.inventory_hash
    assert (
        CurrentManagerStateService().verify(
            bundle,
            fpl_input=context.fpl_input,
            ruleset=context.ruleset,
            capability=context.capability,
        )
        == bundle
    )

    summary = bundle.safe_summary().model_dump(mode="json")
    rendered = json.dumps(summary, sort_keys=True)
    assert summary["squad_count"] == 15
    assert summary["starter_count"] == 11
    assert summary["bench_count"] == 4
    assert summary["provider_verification"] == "NOT_PROVIDER_VERIFIED"
    assert "synthetic-operator" not in rendered
    for private_field in (
        "bank_tenths",
        "free_transfers",
        "captain_element_id",
        "official_fpl_element_id",
        "operator_reference",
        "purchase_price_tenths",
        "selling_price_tenths",
    ):
        assert private_field not in rendered
