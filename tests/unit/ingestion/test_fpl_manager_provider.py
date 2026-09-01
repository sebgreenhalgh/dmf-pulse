"""Provider-observed current manager assembly remains transient and exact."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.chips.compiler import compile_optimisation_chip_rules
from dmf_pulse.chips.inventory import build_chip_inventory
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplDirectInputRequest,
    CurrentFplInputService,
)
from dmf_pulse.ingestion.fpl.manager_current import CurrentManagerStateService
from dmf_pulse.ingestion.fpl.manager_provider import parse_provider_current_team
from dmf_pulse.rules.chips import build_chip_rules_view
from tests.unit.ingestion.current_manager_test_support import (
    CUTOFF,
    DECLARED,
    MANAGER_RECEIVED,
    MANAGER_USABLE,
    _synthetic_bootstrap,
    _synthetic_fixtures,
    active_target_rules,
    declaration_for,
)

pytestmark = pytest.mark.unit


def _context(repository_root: Path):
    times = iter(
        (
            datetime(2026, 8, 24, 10, 5, tzinfo=UTC),
            datetime(2026, 8, 24, 10, 6, tzinfo=UTC),
        )
    )
    fpl_input = CurrentFplInputService(clock=lambda: next(times)).compile_direct(
        CurrentFplDirectInputRequest(
            competition_key="PL",
            season_code="2026/27",
            target_gameweek=2,
            captured_at=datetime(2026, 8, 24, 10, tzinfo=UTC),
            information_cutoff=CUTOFF,
        ),
        bootstrap_body=json.dumps(_synthetic_bootstrap(repository_root)).encode(),
        fixtures_body=json.dumps(_synthetic_fixtures(repository_root)).encode(),
    )
    ruleset, capability = active_target_rules(repository_root)
    operator = declaration_for(fpl_input, ruleset)
    chip_bundle = compile_optimisation_chip_rules(build_chip_rules_view(ruleset))
    inventory = build_chip_inventory(chip_bundle, current_gameweek=2)
    chip_names = {
        "WILDCARD": "wildcard",
        "FREE_HIT": "freehit",
        "BENCH_BOOST": "bboost",
        "TRIPLE_CAPTAIN": "3xc",
    }
    numbers: dict[str, int] = {}
    chips = []
    for token in inventory.tokens:
        numbers[token.chip_key] = numbers.get(token.chip_key, 0) + 1
        chips.append(
            {
                "name": chip_names[token.chip_key],
                "number": numbers[token.chip_key],
                "status_for_entry": (
                    "available" if token.status.value == "AVAILABLE" else "unavailable"
                ),
                "played_by_entry": [],
            }
        )
    players = {item.provider_element_id: item for item in fpl_input.players}
    squad = {item["official_fpl_element_id"]: item for item in operator["squad"]}
    lineup = operator["lineup"]
    ordered = [
        *lineup["starting_xi_element_ids"],
        lineup["bench_goalkeeper_element_id"],
        *lineup["bench_outfield_element_ids"],
    ]
    picks = []
    for position, element in enumerate(ordered, start=1):
        source = squad[element]
        picks.append(
            {
                "element": element,
                "position": position,
                "selling_price": source["observed_selling_price_tenths"],
                "purchase_price": source["purchase_price_tenths"],
                "multiplier": 1 if position <= 11 else 0,
                "is_captain": element == lineup["captain_element_id"],
                "is_vice_captain": element == lineup["vice_captain_element_id"],
                "ignored_provider_addition": players[element].web_name,
            }
        )
    body = {
        "picks": picks,
        "chips": chips,
        "transfers": {
            "cost": 0,
            "status": "cost",
            "limit": 2,
            "made": 0,
            "bank": 15,
            "value": 1000,
        },
    }
    return fpl_input, ruleset, capability, body


def test_authenticated_provider_snapshot_compiles_without_relabelling(
    repository_root: Path,
) -> None:
    fpl_input, ruleset, capability, body = _context(repository_root)
    provider = parse_provider_current_team(json.dumps(body).encode())
    clock = iter((MANAGER_RECEIVED, MANAGER_USABLE))

    bundle = CurrentManagerStateService(clock=lambda: next(clock)).compile_provider_snapshot(
        provider,
        fpl_input=fpl_input,
        ruleset=ruleset,
        capability=capability,
        observed_at=DECLARED,
    )

    assert fpl_input.provenance.acquisition_mode == "OPERATOR_INITIATED_DIRECT_READ"
    assert fpl_input.provenance.transport_called is True
    assert fpl_input.rights.automated_access == "ALLOW"
    assert bundle.source_class == "PROVIDER_OBSERVED"
    assert bundle.attestation_status == "PROVIDER_OBSERVED"
    assert bundle.provider_verification == "PROVIDER_VERIFIED"
    assert bundle.runtime.network_called is True
    assert bundle.runtime.automated_access == "ALLOW"
    assert bundle.runtime.manual_import == "DENY"
    assert len(bundle.squad) == 15
    assert bundle.free_transfers == 2
    assert bundle.safe_summary().source_class == "PROVIDER_OBSERVED"
    assert bundle.safe_summary().network_called is True


def test_provider_snapshot_requires_authoritative_finite_transfer_state(
    repository_root: Path,
) -> None:
    fpl_input, ruleset, capability, body = _context(repository_root)
    body["transfers"]["limit"] = None
    provider = parse_provider_current_team(json.dumps(body).encode())

    with pytest.raises(IngestionError) as caught:
        CurrentManagerStateService(clock=lambda: MANAGER_RECEIVED).compile_provider_snapshot(
            provider,
            fpl_input=fpl_input,
            ruleset=ruleset,
            capability=capability,
            observed_at=DECLARED,
        )

    assert caught.value.code == "CURRENT_MANAGER_TRANSFER_LIMIT_UNRESOLVED"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["picks"].pop(),
        lambda value: value["picks"][0].update({"element": 999999}),
        lambda value: value["chips"][0].update({"name": "unknown-chip"}),
    ],
)
def test_provider_snapshot_fails_closed_on_incomplete_or_ambiguous_facts(
    repository_root: Path, mutation: object
) -> None:
    fpl_input, ruleset, capability, body = _context(repository_root)
    assert callable(mutation)
    mutation(body)
    provider = parse_provider_current_team(json.dumps(body).encode())
    with pytest.raises(IngestionError):
        CurrentManagerStateService(clock=lambda: MANAGER_RECEIVED).compile_provider_snapshot(
            provider,
            fpl_input=fpl_input,
            ruleset=ruleset,
            capability=capability,
            observed_at=DECLARED,
        )
