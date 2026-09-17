"""Offline synthetic inputs for the R9C-A1.03 four-world rolling comparison.

The rolling execution and the pure R9B compiler share one sealed GW5 target
and finalized GW1--4 window. It performs no provider acquisition.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from dmf_pulse.fpl_points.current_player_posterior import load_historical_rate_resource
from dmf_pulse.fpl_points.current_player_shadow import compile_current_player_shadow
from dmf_pulse.fpl_points.player_prior import (
    build_automatic_current_gw_stale_prior_policy,
    build_current_gw_player_prior_binding,
    load_packaged_player_prior,
)
from dmf_pulse.ingestion.fpl.current_player_history import build_current_player_history_evidence
from dmf_pulse.ingestion.fpl.direct_payloads import DirectFplSnapshot, parse_direct_event_live
from dmf_pulse.private_v1.rolling_models import PrivateV1RollingExecutionInput
from tests.unit.private_v1.e2e_test_support import (
    _CUTOFF,
    build_rolling_execution_input,
)


def build_a1_03_inputs(
    repository_root: Path,
    working: Path,
    *,
    candidate_saves_per_gameweek: int = 3,
    force_candidate_low_current_minutes: bool = False,
) -> tuple[PrivateV1RollingExecutionInput, object]:
    """Return a sealed rolling input and a matching three-world shadow.

    This is deliberately test-only construction. Its rolling and history
    contracts share exactly one target Gameweek and source window.
    """

    execution = build_rolling_execution_input(
        repository_root,
        working / "rolling",
        target_gameweek=5,
        historical_gameweeks=4,
        force_candidate_low_current_minutes=force_candidate_low_current_minutes,
    )
    shadow_fpl = execution.current_execution.current_state.fpl_input
    candidate_id = (
        execution.current_execution.candidate_action_policy.allowed_transfer_in_element_ids[0]
    )
    canonical_players = {
        item.official_fpl_element_id: str(item.canonical_player_id)
        for item in execution.current_execution.player_identity_map.players
    }
    canonical_teams = {
        item.official_fpl_team_id: str(item.canonical_team_id)
        for item in execution.current_execution.player_identity_map.teams
    }
    rows_by_gameweek = {}
    for gameweek in range(1, 5):
        rows = []
        for player in shadow_fpl.players:
            rows.append(
                {
                    "id": player.provider_element_id,
                    "stats": {
                        "minutes": 90,
                        "starts": 1,
                        "goals_scored": int(player.provider_element_id % 17 == 0),
                        "assists": int((player.provider_element_id + gameweek) % 5 == 0),
                        "own_goals": 0,
                        "penalties_saved": 0,
                        "penalties_missed": 0,
                        "yellow_cards": int(player.provider_element_id % 13 == 0),
                        "red_cards": 0,
                        "saves": (
                            candidate_saves_per_gameweek
                            if player.provider_element_id == candidate_id
                            else 0
                        ),
                        "clearances_blocks_interceptions": 4,
                        "tackles": 2,
                        "recoveries": 5,
                        "defensive_contribution": 8,
                        "bonus": 0,
                        "bps": 14,
                    },
                }
            )
        rows_by_gameweek[gameweek] = parse_direct_event_live(
            json.dumps({"elements": rows}, sort_keys=True).encode()
        )
    snapshot = DirectFplSnapshot.model_construct(
        captured_at=_CUTOFF,
        target_gameweek=5,
        fpl_input=shadow_fpl,
        live_by_gameweek=rows_by_gameweek,
        request_count=11,
        endpoint_classes=("BOOTSTRAP", "FIXTURES", "EVENT_LIVE"),
    )
    history = build_current_player_history_evidence(
        snapshot,
        canonical_player_ids={
            element_id: UUID(value) for element_id, value in canonical_players.items()
        },
    )
    prior = load_packaged_player_prior()
    policy = build_automatic_current_gw_stale_prior_policy(
        prior,
        shadow_fpl,
        current_official_fpl_element_ids=tuple(sorted(canonical_players)),
        declared_at=_CUTOFF,
    )
    binding = build_current_gw_player_prior_binding(
        prior,
        shadow_fpl,
        policy,
        canonical_player_ids_by_source_id=canonical_players,
        canonical_team_ids_by_source_id=canonical_teams,
    )
    shadow = compile_current_player_shadow(
        history=history,
        current_fpl=shadow_fpl,
        binding=binding,
        policy=policy,
        prior=prior,
        historical=load_historical_rate_resource(),
    )
    return execution, shadow


__all__ = ["build_a1_03_inputs"]
