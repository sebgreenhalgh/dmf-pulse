"""Repository-owned synthetic support for R9C-A2; no provider access."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from dmf_pulse.ingestion.fpl.current_player_history import build_current_player_history_evidence
from dmf_pulse.ingestion.fpl.direct_payloads import DirectFplSnapshot, parse_direct_event_live
from dmf_pulse.private_v1.live_shadow_observation import _compile_shadow
from dmf_pulse.private_v1.one_command import _PrivateV1PreparedRollingContext
from tests.unit.private_v1.a1_03_support import build_a1_03_inputs
from tests.unit.private_v1.e2e_test_support import _CUTOFF


def build_a2_comparison_inputs(
    repository_root: Path,
    working: Path,
    *,
    candidate_saves_per_gameweek: int = 1000,
    force_candidate_low_current_minutes: bool = False,
):
    execution, expected_shadow = build_a1_03_inputs(
        repository_root,
        working,
        candidate_saves_per_gameweek=candidate_saves_per_gameweek,
        force_candidate_low_current_minutes=force_candidate_low_current_minutes,
    )
    fpl = execution.current_execution.current_state.fpl_input
    candidate_id = (
        execution.current_execution.candidate_action_policy.allowed_transfer_in_element_ids[0]
    )
    live_by_gameweek = {}
    for gameweek in range(1, 5):
        rows = []
        for player in fpl.players:
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
        live_by_gameweek[gameweek] = parse_direct_event_live(
            json.dumps({"elements": rows}, sort_keys=True).encode()
        )
    snapshot = DirectFplSnapshot.model_construct(
        captured_at=_CUTOFF,
        target_gameweek=5,
        fpl_input=fpl,
        live_by_gameweek=live_by_gameweek,
        request_count=11,
        endpoint_classes=("BOOTSTRAP", "FIXTURES", "EVENT_LIVE"),
    )
    identity_map = execution.current_execution.player_identity_map
    prepared = _PrivateV1PreparedRollingContext(
        snapshot=snapshot,
        rolling_execution=execution,
        player_identity_map=identity_map,
        fpl_request_count=11,
        fpl_endpoint_classes=("BOOTSTRAP", "FIXTURES", "EVENT_LIVE"),
        odds_request_count=1,
        odds_endpoint_classes=("THE_ODDS_API_EPL_H2H_TOTALS_HORIZON",),
        score_prior_acquisition_count=1,
        fpl_rights_profile_id="fpl_official_private_operator_initiated_read_v1",
        odds_rights_profile_id="the_odds_api_private_analytics_v1",
        information_cutoff=_CUTOFF,
    )
    history = build_current_player_history_evidence(
        snapshot,
        canonical_player_ids={
            item.official_fpl_element_id: UUID(str(item.canonical_player_id))
            for item in identity_map.players
        },
    )
    compiled_history, shadow = _compile_shadow(prepared)
    assert compiled_history == history
    assert shadow == expected_shadow
    return prepared, history, shadow


__all__ = ["build_a2_comparison_inputs"]
