from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from dmf_pulse.availability.manual_override import ManualFixtureMinutesInput

FIXTURE_ID = "10000000-0000-7000-8000-000000000801"
HOME_TEAM_ID = "20000000-0000-7000-8000-000000000001"
AWAY_TEAM_ID = "20000000-0000-7000-8000-000000000002"


def _player_id(side: int, index: int) -> str:
    return str(UUID(int=(side << 112) + index + 1))


def _team(side: int, team_id: str) -> dict[str, Any]:
    positions = ("GK",) * 3 + ("DEF",) * 8 + ("MID",) * 8 + ("FWD",) * 4
    players = tuple((_player_id(side, index), position) for index, position in enumerate(positions))
    goalkeeper_ids = tuple(player_id for player_id, position in players if position == "GK")
    outfield_ids = tuple(player_id for player_id, position in players if position != "GK")
    scenarios: list[dict[str, Any]] = []
    for scenario_index in range(4):
        starting_gk = goalkeeper_ids[scenario_index % len(goalkeeper_ids)]
        bench_gk = goalkeeper_ids[(scenario_index + 1) % len(goalkeeper_ids)]
        start_outfield = {
            outfield_ids[(scenario_index * 5 + offset) % len(outfield_ids)] for offset in range(10)
        }
        remaining_outfield = tuple(
            player_id for player_id in outfield_ids if player_id not in start_outfield
        )
        bench_outfield = set(remaining_outfield[:8])
        rows: list[dict[str, Any]] = []
        for player_index, (player_id, position) in enumerate(players):
            if player_id == starting_gk or player_id in start_outfield:
                role = "START"
                minutes = 90 - 10 * ((player_index + scenario_index) % 4)
            elif player_id == bench_gk or player_id in bench_outfield:
                role = "BENCH"
                minutes = 0 if (player_index + scenario_index) % 2 == 0 else 20
            else:
                role = "OUT"
                minutes = 0
            rows.append(
                {
                    "official_minutes": minutes,
                    "player_id": player_id,
                    "position": position,
                    "role": role,
                }
            )
        scenarios.append(
            {
                "count": 64,
                "players": rows,
                "scenario_id": f"SCENARIO_{scenario_index + 1:02d}",
            }
        )
    return {
        "bench_goalkeeper_slots": 1,
        "bench_size": 9,
        "hard_overrides": [],
        "scenarios": scenarios,
        "team_id": team_id,
    }


def valid_manual_input_dict() -> dict[str, Any]:
    return {
        "as_of": "2026-08-20T11:50:00Z",
        "away": _team(4, AWAY_TEAM_ID),
        "away_team_id": AWAY_TEAM_ID,
        "fixture_id": FIXTURE_ID,
        "home": _team(3, HOME_TEAM_ID),
        "home_team_id": HOME_TEAM_ID,
        "information_cutoff": "2026-08-20T12:00:00Z",
        "provenance": {
            "adjustment_type": "SOFT_SCENARIO_MIXTURE",
            "classification": "PRIVATE_TRANSIENT",
            "entered_at": "2026-08-20T11:30:00Z",
            "evidence_type": "ANALYST_SCENARIO_JUDGEMENT",
            "expires_at": "2026-08-20T18:00:00Z",
            "fixture_scope_id": FIXTURE_ID,
            "model_derived": False,
            "operator_ref": "PRIVATE_OPERATOR",
            "persistence_class": "TRANSIENT_PRIVATE",
            "production_suitable": False,
            "reason": "Synthetic scenario mixture for contract testing.",
            "source_ref": "SYNTHETIC_TEST_SOURCE",
            "source_timestamp": "2026-08-20T11:00:00Z",
            "supplier_type": "PRIVATE_OPERATOR",
            "usable_at": "2026-08-20T11:40:00Z",
        },
        "schema_version": "private-manual-transient-minutes-v1",
    }


def valid_manual_input() -> ManualFixtureMinutesInput:
    return ManualFixtureMinutesInput.model_validate(valid_manual_input_dict())


def with_always_out_player(*, include_hard_override: bool) -> dict[str, Any]:
    body = deepcopy(valid_manual_input_dict())
    player_id = _player_id(3, 23)
    home = body["home"]
    assert isinstance(home, dict)
    scenarios = home["scenarios"]
    assert isinstance(scenarios, list)
    for scenario in scenarios:
        players = scenario["players"]
        assert isinstance(players, list)
        players.append(
            {
                "official_minutes": 0,
                "player_id": player_id,
                "position": "DEF",
                "role": "OUT",
            }
        )
    if include_hard_override:
        home["hard_overrides"] = [
            {
                "asserted_role": "OUT",
                "classification": "PRIVATE_TRANSIENT",
                "entered_at": "2026-08-20T11:30:00Z",
                "expires_at": "2026-08-20T18:00:00Z",
                "fixture_id": FIXTURE_ID,
                "model_derived": False,
                "operator_ref": "PRIVATE_OPERATOR",
                "override_type": "FORMAL_INELIGIBILITY",
                "persistence_class": "TRANSIENT_PRIVATE",
                "player_id": player_id,
                "production_suitable": False,
                "reason": "Synthetic formal ineligibility evidence.",
                "source_ref": "SYNTHETIC_OFFICIAL_NOTICE",
                "source_timestamp": "2026-08-20T11:00:00Z",
                "supplier_type": "PRIVATE_OPERATOR",
                "team_id": HOME_TEAM_ID,
                "usable_at": "2026-08-20T11:40:00Z",
            }
        ]
    return body


def with_always_start_player(*, include_hard_override: bool) -> dict[str, Any]:
    body = deepcopy(valid_manual_input_dict())
    player_id = _player_id(3, 23)
    home = body["home"]
    assert isinstance(home, dict)
    scenarios = home["scenarios"]
    assert isinstance(scenarios, list)
    for scenario in scenarios:
        players = scenario["players"]
        assert isinstance(players, list)
        demoted = next(
            player for player in players if player["role"] == "START" and player["position"] != "GK"
        )
        demoted["role"] = "OUT"
        demoted["official_minutes"] = 0
        players.append(
            {
                "official_minutes": 80,
                "player_id": player_id,
                "position": "DEF",
                "role": "START",
            }
        )
    if include_hard_override:
        home["hard_overrides"] = [
            {
                "asserted_role": "START",
                "classification": "PRIVATE_TRANSIENT",
                "entered_at": "2026-08-20T11:30:00Z",
                "expires_at": "2026-08-20T18:00:00Z",
                "fixture_id": FIXTURE_ID,
                "model_derived": False,
                "operator_ref": "PRIVATE_OPERATOR",
                "override_type": "OFFICIAL_LINEUP_NON_FPL_CUTOFF",
                "persistence_class": "TRANSIENT_PRIVATE",
                "player_id": player_id,
                "production_suitable": False,
                "reason": "Synthetic official non-FPL-cutoff lineup evidence.",
                "source_ref": "SYNTHETIC_OFFICIAL_LINEUP",
                "source_timestamp": "2026-08-20T11:00:00Z",
                "supplier_type": "PRIVATE_OPERATOR",
                "team_id": HOME_TEAM_ID,
                "usable_at": "2026-08-20T11:40:00Z",
            }
        ]
    return body


def deep_copy_input() -> dict[str, Any]:
    return deepcopy(valid_manual_input_dict())
