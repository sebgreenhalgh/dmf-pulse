"""Synthetic-only construction helpers for CURRENT-FPL-STATE-001C tests."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dmf_pulse.chips.compiler import compile_optimisation_chip_rules
from dmf_pulse.chips.inventory import build_chip_inventory
from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplInputBundle,
    CurrentFplInputRequest,
    CurrentFplInputService,
)
from dmf_pulse.ingestion.fpl.manager_current import (
    CurrentManagerStateBundle,
    CurrentManagerStateService,
    bind_current_manager_state_request,
)
from dmf_pulse.optimisation.manager_state import selling_price_tenths
from dmf_pulse.rules.canonical import self_hash
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.chips import build_chip_rules_view
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.models import (
    CapabilityArtifact,
    CompiledRuleset,
    RuleCapability,
)
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules

FPL_CAPTURED = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
FPL_RECEIVED = datetime(2026, 8, 24, 10, 5, tzinfo=UTC)
FPL_USABLE = datetime(2026, 8, 24, 10, 6, tzinfo=UTC)
DECLARED = datetime(2026, 8, 24, 11, 0, tzinfo=UTC)
ATTESTED = datetime(2026, 8, 24, 11, 1, tzinfo=UTC)
MANAGER_RECEIVED = datetime(2026, 8, 24, 11, 2, tzinfo=UTC)
MANAGER_USABLE = datetime(2026, 8, 24, 11, 3, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class CurrentManagerTestContext:
    repository_root: Path
    working: Path
    fpl_input: CurrentFplInputBundle
    ruleset: CompiledRuleset
    capability: CapabilityArtifact
    declaration: dict[str, Any]


def active_target_rules(repository_root: Path) -> tuple[CompiledRuleset, CapabilityArtifact]:
    """Build an integrity-valid ACTIVE test input without publishing an active registry entry."""

    verified = compile_ruleset(repository_root / "config/rules/fpl-2026-27")
    payload = verified.model_dump(mode="json")
    payload["status"] = "ACTIVE"
    payload["production_eligible"] = True
    payload["ruleset_hash"] = self_hash(payload)
    active = CompiledRuleset.model_validate(payload)
    capability = compile_capability_artifact(active, RuleCapability.FULL_SEASON)
    return active, capability


def _source(repository_root: Path, name: str) -> object:
    return json.loads(
        (repository_root / "fixtures/fpl/FPL-004/happy_path" / name).read_text(encoding="utf-8")
    )


def _synthetic_bootstrap(repository_root: Path) -> dict[str, Any]:
    bootstrap = _source(repository_root, "bootstrap.json")
    assert isinstance(bootstrap, dict)
    original_teams = bootstrap["teams"]
    original_players = bootstrap["elements"]
    assert isinstance(original_teams, list)
    assert isinstance(original_players, list)

    teams: list[dict[str, Any]] = []
    for team_id in range(1, 6):
        source = deepcopy(original_teams[(team_id - 1) % len(original_teams)])
        source.update(
            {
                "id": team_id,
                "code": 3000 + team_id,
                "name": f"Synthetic Club {team_id}",
                "short_name": f"S{team_id}",
            }
        )
        teams.append(source)

    templates = {int(item["element_type"]): item for item in original_players}
    position_types = (
        1,
        1,
        2,
        2,
        2,
        2,
        2,
        3,
        3,
        3,
        3,
        3,
        4,
        4,
        4,
        1,
        2,
        3,
        4,
    )
    players: list[dict[str, Any]] = []
    for offset, element_type in enumerate(position_types):
        element_id = 101 + offset
        source = deepcopy(templates[element_type])
        source.update(
            {
                "id": element_id,
                "code": 40000 + element_id,
                "element_type": element_type,
                "team": 1 if element_id >= 116 else (offset % 5) + 1,
                "now_cost": 50 + offset,
                "first_name": f"Synthetic{element_id}",
                "second_name": f"Player{element_id}",
                "web_name": f"P{element_id}",
                "status": "a",
                "chance_of_playing_this_round": None,
                "chance_of_playing_next_round": None,
                "news": "",
                "news_added": None,
            }
        )
        players.append(source)
    bootstrap["teams"] = teams
    bootstrap["elements"] = players
    return bootstrap


def _synthetic_fixtures(repository_root: Path) -> list[dict[str, Any]]:
    fixtures = _source(repository_root, "fixtures.json")
    assert isinstance(fixtures, list)
    gw2 = deepcopy(fixtures[0])
    gw2.update(
        {
            "id": 102,
            "code": 900102,
            "event": 2,
            "kickoff_time": "2026-08-29T14:00:00Z",
            "team_h": 2,
            "team_a": 1,
        }
    )
    fixtures.append(gw2)
    return fixtures


def build_fpl_input(repository_root: Path, working: Path) -> CurrentFplInputBundle:
    working.mkdir(parents=True, exist_ok=True)
    bootstrap_path = working / "synthetic-bootstrap.json"
    fixtures_path = working / "synthetic-fixtures.json"
    bootstrap_path.write_text(
        json.dumps(_synthetic_bootstrap(repository_root), sort_keys=True), encoding="utf-8"
    )
    fixtures_path.write_text(
        json.dumps(_synthetic_fixtures(repository_root), sort_keys=True), encoding="utf-8"
    )
    times = iter((FPL_RECEIVED, FPL_USABLE))
    return CurrentFplInputService(clock=lambda: next(times)).compile(
        CurrentFplInputRequest(
            bootstrap_path=bootstrap_path,
            fixtures_path=fixtures_path,
            competition_key="PL",
            season_code="2026/27",
            target_gameweek=2,
            captured_at=FPL_CAPTURED,
            information_cutoff=CUTOFF,
            rights_profile_id="fpl_official_private_manual_v1",
        )
    )


def declaration_for(
    fpl_input: CurrentFplInputBundle,
    ruleset: CompiledRuleset,
    *,
    declaration_order: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    transfer_rules = build_multi_gameweek_transfer_rules(
        ruleset,
        projection_mode=ProjectionMode.PRODUCTION,
        capability=compile_capability_artifact(ruleset, RuleCapability.FULL_SEASON),
    )
    chip_bundle = compile_optimisation_chip_rules(build_chip_rules_view(ruleset))
    players = {item.provider_element_id: item for item in fpl_input.players}
    element_ids = tuple(sorted(players)[:15])
    ordered_ids = declaration_order or element_ids
    squad = []
    for element_id in ordered_ids:
        player = players[element_id]
        purchase = player.current_price_tenths
        selling = selling_price_tenths(
            purchase_price_tenths=purchase,
            current_price_tenths=player.current_price_tenths,
            rule=transfer_rules.selling_price_rule,
        )
        squad.append(
            {
                "official_fpl_element_id": element_id,
                "purchase_price_tenths": purchase,
                "observed_selling_price_tenths": selling,
            }
        )
    inventory = build_chip_inventory(chip_bundle, current_gameweek=fpl_input.target_gameweek)
    return {
        "schema_version": "1.0.0",
        "source_class": "OPERATOR_DECLARED",
        "season_code": "2026/27",
        "target_gameweek": fpl_input.target_gameweek,
        "information_cutoff": CUTOFF.isoformat().replace("+00:00", "Z"),
        "attestation": {
            "declaration_method": "OPERATOR_DECLARED",
            "attestation_status": "HUMAN_ATTESTED",
            "provider_verification": "NOT_PROVIDER_VERIFIED",
            "declared_at": DECLARED.isoformat().replace("+00:00", "Z"),
            "attested_at": ATTESTED.isoformat().replace("+00:00", "Z"),
            "operator_reference": "synthetic-operator",
        },
        "squad": squad,
        "bank_tenths": 15,
        "free_transfers": 2,
        "lineup": {
            "starting_xi_element_ids": [101, 103, 104, 105, 106, 108, 109, 110, 111, 113, 114],
            "bench_goalkeeper_element_id": 102,
            "bench_outfield_element_ids": [107, 112, 115],
            "captain_element_id": 108,
            "vice_captain_element_id": 113,
        },
        "chip_tokens": [
            {
                "token_id": token.token_id,
                "status": token.status.value,
                "selected_at_gameweek": None,
                "active_from_gameweek": None,
                "used_at_gameweek": None,
            }
            for token in inventory.tokens
        ],
        "overall_points": None,
        "overall_rank": None,
    }


def build_context(repository_root: Path, tmp_path: Path) -> CurrentManagerTestContext:
    working = tmp_path / "current-manager"
    fpl_input = build_fpl_input(repository_root, working)
    ruleset, capability = active_target_rules(repository_root)
    return CurrentManagerTestContext(
        repository_root=repository_root,
        working=working,
        fpl_input=fpl_input,
        ruleset=ruleset,
        capability=capability,
        declaration=declaration_for(fpl_input, ruleset),
    )


def write_declaration(
    context: CurrentManagerTestContext,
    value: object,
    *,
    name: str = "manager-declaration.json",
) -> Path:
    path = context.working / name
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8")
    return path


def compile_manager(
    context: CurrentManagerTestContext,
    declaration: object | None = None,
    *,
    times: tuple[datetime, datetime] = (MANAGER_RECEIVED, MANAGER_USABLE),
    name: str = "manager-declaration.json",
) -> CurrentManagerStateBundle:
    value = context.declaration if declaration is None else declaration
    path = write_declaration(context, value, name=name)
    request = bind_current_manager_state_request(
        path,
        context.fpl_input,
        context.ruleset,
        context.capability,
    )
    clock = iter(times)
    return CurrentManagerStateService(clock=lambda: next(clock)).compile(
        request,
        fpl_input=context.fpl_input,
        ruleset=context.ruleset,
        capability=context.capability,
    )


__all__ = [
    "ATTESTED",
    "CUTOFF",
    "DECLARED",
    "FPL_USABLE",
    "MANAGER_RECEIVED",
    "MANAGER_USABLE",
    "CurrentManagerTestContext",
    "active_target_rules",
    "build_context",
    "build_fpl_input",
    "compile_manager",
    "declaration_for",
    "write_declaration",
]
