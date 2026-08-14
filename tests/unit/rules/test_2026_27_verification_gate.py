"""Explicit fail-closed regressions for the 2026/27 launch verification gate."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.rules.authoring import (
    AssistsFile,
    BpsRules,
    LineupFile,
    PricesFile,
    TransfersFile,
)
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.models import RulesetStatus
from dmf_pulse.rules.yaml_loader import load_rules_yaml


@pytest.mark.unit
def test_2026_27_checked_claims_and_sources_are_current(repository_root: Path) -> None:
    target = repository_root / "fixtures/rules/RUL-002/target_2026_27_partial"
    claims = load_rules_yaml(target / "target_2026_27_claims.yaml")
    checked = claims["checked_claims"]
    assert checked["bps.being_tackled"]["operation"] == "REMOVE"
    assert checked["bps.cbi_group_size"]["value"] == 3
    assert checked["bps.any_save"]["value"] == 2
    assert checked["bps.inside_box_save_extra"]["value"] == 1
    assert checked["bps.big_chance_save_extra"]["value"] == 1
    assert checked["bps.penalty_save"]["value"] == 7
    assert checked["free_transfer_cap"]["value"] == 5
    assert checked["gameweek_finality"]["local_time"] == "09:00"
    assert checked["gw1_deadline"]["value"] == "2026-08-21T17:30:00Z"

    source_manifest = load_rules_yaml(target / "source_manifest.yaml")
    sources = {source["source_id"]: source for source in source_manifest["sources"]}
    assert set(sources) == {
        "SRC-FPL-2026-BPS-001",
        "SRC-FPL-2026-BOOTSTRAP-001",
        "SRC-FPL-2026-CHANGES-001",
        "SRC-FPL-2026-CHIPS-001",
        "SRC-FPL-2026-DC-001",
        "SRC-FPL-2026-PRICE-001",
        "SRC-FPL-2026-RULES-001",
    }
    assert {source["accessed_on"] for source in sources.values()} == {"2026-08-14"}


@pytest.mark.unit
def test_2026_27_target_stays_globally_blocked_on_manager_state_gaps(
    repository_root: Path,
) -> None:
    target = repository_root / "fixtures/rules/RUL-002/target_2026_27_partial"
    compiled = compile_ruleset(target)
    assert compiled.status is RulesetStatus.CAPTURED_UNVERIFIED
    assert compiled.production_eligible is False
    assert set(compiled.unknown_blockers) >= {
        "target:automatic_substitution_rules_not_yet_promoted",
        "target:gameweek_finality_not_yet_promoted",
        "target:official_source_selling_price_loss_branch",
        "target:selling_price_rules_not_yet_promoted",
        "target:split_chip_inventory_windows_and_effects_not_yet_promoted",
        "target:transfer_state_transitions_not_yet_promoted",
    }


@pytest.mark.unit
def test_verified_2026_27_rules_cannot_be_silently_forced_into_v1_schema(
    repository_root: Path,
) -> None:
    reference = repository_root / "fixtures/rules/RUL-002/reference_2025_26"

    bps = copy.deepcopy(load_rules_yaml(reference / "bonus.yaml")["bps"])
    bps["big_chance_save"] = 1
    with pytest.raises(ValidationError, match="Extra inputs"):
        BpsRules.model_validate(bps)

    assists = copy.deepcopy(load_rules_yaml(reference / "assists.yaml"))
    assists["eligibility_policy"] = {"max_defensive_touches": 1}
    with pytest.raises(ValidationError, match="Extra inputs"):
        AssistsFile.model_validate(assists)

    lineup = copy.deepcopy(load_rules_yaml(reference / "lineup.yaml"))
    lineup["automatic_substitutions"] = {"preserve_formation": True}
    with pytest.raises(ValidationError, match="Extra inputs"):
        LineupFile.model_validate(lineup)

    with pytest.raises(ValidationError):
        TransfersFile.model_validate(
            {"free_transfer_cap": 5, "hit_points": -4, "state": "VERIFIED"}
        )

    prices = copy.deepcopy(load_rules_yaml(reference / "prices.yaml"))
    prices["transfers_sell_on_fee"] = "0.5"
    with pytest.raises(ValidationError, match="Extra inputs"):
        PricesFile.model_validate(prices)
