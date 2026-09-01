"""Provider-observed current manager assembly remains transient and exact."""

from __future__ import annotations

import json
from copy import deepcopy
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
from dmf_pulse.ingestion.fpl.manager_provider import (
    _chip_declarations,
    parse_provider_current_team,
)
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
    chip_names = {
        "WILDCARD": "wildcard",
        "FREE_HIT": "freehit",
        "BENCH_BOOST": "bboost",
        "TRIPLE_CAPTAIN": "3xc",
    }
    chips = [
        {
            "name": name,
            "number": 1,
            "status_for_entry": "available",
            "played_by_entry": [],
        }
        for name in chip_names.values()
    ]
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


def _chip_payloads() -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "number": 1,
            "status_for_entry": "available",
            "played_by_entry": [],
        }
        for name in ("wildcard", "freehit", "bboost", "3xc")
    ]


def _provider_with_chips(body: dict[str, object], chips: list[dict[str, object]]):
    candidate = deepcopy(body)
    candidate["chips"] = chips
    return parse_provider_current_team(json.dumps(candidate).encode())


@pytest.mark.parametrize("target_gameweek", [3, 20])
def test_current_provider_chip_records_map_by_governed_activation_window(
    repository_root: Path, target_gameweek: int
) -> None:
    _, ruleset, _, body = _context(repository_root)
    bundle = compile_optimisation_chip_rules(build_chip_rules_view(ruleset))
    source = _provider_with_chips(body, _chip_payloads())

    declarations = {
        item.token_id: item
        for item in _chip_declarations(source, bundle, target_gameweek=target_gameweek)
    }
    inventory = build_chip_inventory(bundle, current_gameweek=target_gameweek)

    assert len(declarations) == 8
    for token in inventory.tokens:
        expected = (
            "AVAILABLE"
            if token.activation_start_gameweek <= target_gameweek <= token.activation_end_gameweek
            else token.status.value
        )
        assert declarations[token.token_id].status == expected


def test_played_and_current_provider_records_map_to_distinct_governed_windows(
    repository_root: Path,
) -> None:
    _, ruleset, _, body = _context(repository_root)
    bundle = compile_optimisation_chip_rules(build_chip_rules_view(ruleset))
    chips = _chip_payloads()
    chips[0] = {
        "name": "wildcard",
        "number": 1,
        "status_for_entry": "unavailable",
        "played_by_entry": [3],
    }
    chips.append(
        {
            "name": "wildcard",
            "number": 2,
            "status_for_entry": "available",
            "played_by_entry": [],
        }
    )
    source = _provider_with_chips(body, chips)

    declarations = {
        item.token_id: item for item in _chip_declarations(source, bundle, target_gameweek=20)
    }
    wildcard_tokens = sorted(
        (
            item
            for item in build_chip_inventory(bundle, current_gameweek=20).tokens
            if item.chip_key == "WILDCARD"
        ),
        key=lambda item: item.activation_start_gameweek,
    )

    assert declarations[wildcard_tokens[0].token_id].status == "USED"
    assert declarations[wildcard_tokens[0].token_id].used_at_gameweek == 3
    assert declarations[wildcard_tokens[1].token_id].status == "AVAILABLE"


@pytest.mark.parametrize(
    ("provider_status", "expected_status"),
    [
        ("available", "AVAILABLE"),
        ("unavailable", "UNAVAILABLE"),
        ("pending", "PENDING_CANCELLABLE"),
        ("active", "PENDING_CANCELLABLE"),
    ],
)
def test_current_chip_declaration_incorporates_known_provider_status(
    repository_root: Path, provider_status: str, expected_status: str
) -> None:
    _, ruleset, _, body = _context(repository_root)
    bundle = compile_optimisation_chip_rules(build_chip_rules_view(ruleset))
    chips = _chip_payloads()
    chips[0]["number"] = 27
    chips[0]["status_for_entry"] = provider_status
    source = _provider_with_chips(body, chips)

    declarations = {
        item.token_id: item for item in _chip_declarations(source, bundle, target_gameweek=3)
    }
    current_wildcard = next(
        item
        for item in build_chip_inventory(bundle, current_gameweek=3).tokens
        if item.chip_key == "WILDCARD"
        and item.activation_start_gameweek <= 3 <= item.activation_end_gameweek
    )

    assert declarations[current_wildcard.token_id].status == expected_status


@pytest.mark.parametrize(
    ("chips", "target_gameweek", "code"),
    [
        (
            [
                {
                    "name": "wildcard",
                    "number": 1,
                    "status_for_entry": "mystery",
                    "played_by_entry": [],
                },
                *_chip_payloads()[1:],
            ],
            3,
            "SCHEMA_DRIFT",
        ),
        (
            [
                {
                    "name": "wildcard",
                    "number": 1,
                    "status_for_entry": "available",
                    "played_by_entry": [3],
                },
                *_chip_payloads()[1:],
            ],
            3,
            "VALIDATION_FAILED",
        ),
        (
            [
                {
                    "name": "wildcard",
                    "number": 1,
                    "status_for_entry": "unavailable",
                    "played_by_entry": [3, 3],
                },
                *_chip_payloads()[1:],
            ],
            3,
            "VALIDATION_FAILED",
        ),
        (
            [
                {
                    "name": "wildcard",
                    "number": 1,
                    "status_for_entry": "unavailable",
                    "played_by_entry": [2, 3],
                },
                *_chip_payloads()[1:],
            ],
            3,
            "VALIDATION_FAILED",
        ),
        (
            [
                {
                    "name": "wildcard",
                    "number": 1,
                    "status_for_entry": "unavailable",
                    "played_by_entry": [39],
                },
                *_chip_payloads()[1:],
            ],
            3,
            "MAPPING_CONFLICT",
        ),
        ([*_chip_payloads(), _chip_payloads()[0]], 3, "MAPPING_CONFLICT"),
        (_chip_payloads(), 39, "MAPPING_CONFLICT"),
        (_chip_payloads()[1:], 3, "MAPPING_CONFLICT"),
    ],
)
def test_provider_chip_mapping_fails_closed_on_unreconcilable_evidence(
    repository_root: Path,
    chips: list[dict[str, object]],
    target_gameweek: int,
    code: str,
) -> None:
    _, ruleset, _, body = _context(repository_root)
    bundle = compile_optimisation_chip_rules(build_chip_rules_view(ruleset))
    source = _provider_with_chips(body, chips)

    with pytest.raises(IngestionError) as caught:
        _chip_declarations(source, bundle, target_gameweek=target_gameweek)

    assert caught.value.code == code


@pytest.mark.parametrize("played_by_entry", [[], [3]])
def test_chip_fails_closed_when_governed_windows_overlap(
    repository_root: Path, played_by_entry: list[int]
) -> None:
    _, ruleset, _, body = _context(repository_root)
    bundle = compile_optimisation_chip_rules(build_chip_rules_view(ruleset))
    wildcard = bundle.definition_for("WILDCARD")
    first, second = wildcard.definition.grants
    overlapping_second = second.model_copy(
        update={"acquired_gameweek": 2, "activation_start_gameweek": 2}
    )
    overlapping_definition = wildcard.definition.model_copy(
        update={"grants": (first, overlapping_second)}
    )
    overlapping_wildcard = wildcard.model_copy(update={"definition": overlapping_definition})
    overlapping_bundle = bundle.model_copy(
        update={
            "definitions": tuple(
                overlapping_wildcard if item.chip_key == "WILDCARD" else item
                for item in bundle.definitions
            )
        }
    )
    chips = _chip_payloads()
    chips[0] = {
        "name": "wildcard",
        "number": 1,
        "status_for_entry": "unavailable" if played_by_entry else "available",
        "played_by_entry": played_by_entry,
    }
    source = _provider_with_chips(body, chips)

    with pytest.raises(IngestionError) as caught:
        _chip_declarations(source, overlapping_bundle, target_gameweek=3)

    assert caught.value.code == "MAPPING_CONFLICT"


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
