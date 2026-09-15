"""Offline R9A evidence-only current-player-history proofs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current_player_history import (
    CurrentPlayerHistoryQuality,
    build_current_player_history_evidence,
)
from dmf_pulse.ingestion.fpl.direct_payloads import (
    DirectEntry,
    DirectEntryHistory,
    DirectFplSnapshot,
    parse_direct_event_live,
)
from dmf_pulse.ingestion.fpl.manager_provider import parse_provider_current_team
from tests.unit.ingestion.current_manager_test_support import CUTOFF
from tests.unit.ingestion.test_fpl_manager_provider import _context

pytestmark = pytest.mark.unit


def _snapshot(repository_root: Path, *, second_goal_missing: bool = False) -> DirectFplSnapshot:
    fpl, _, _, manager_body = _context(repository_root)
    first = fpl.players[0]
    players = (
        first.model_copy(update={"season_minutes": 90, "season_starts": 1}),
        *fpl.players[1:],
    )
    events = (
        fpl.events[0].model_copy(update={"finished": True, "data_checked": True}),
        *fpl.events[1:],
    )
    body_one = {
        "elements": [
            {
                "id": first.provider_element_id,
                "stats": {
                    "minutes": 90,
                    "starts": 1,
                    "goals_scored": 0,
                    "assists": 1,
                    "own_goals": 0,
                    "penalties_saved": 0,
                    "penalties_missed": 0,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "saves": 0,
                    "clearances_blocks_interceptions": 3,
                    "tackles": 2,
                    "recoveries": 4,
                    "defensive_contribution": 5,
                    "bonus": 0,
                    "bps": -2,
                },
            }
        ]
    }
    if second_goal_missing:
        del body_one["elements"][0]["stats"]["goals_scored"]
    return DirectFplSnapshot(
        captured_at=CUTOFF,
        target_gameweek=2,
        fpl_input=fpl.model_copy(update={"players": players, "events": events}),
        entry=DirectEntry(id=42, started_event=1),
        history=DirectEntryHistory(current=()),
        transfers=(),
        latest_public_picks=None,
        current_team=parse_provider_current_team(json.dumps(manager_body).encode()),
        live_by_gameweek={
            1: parse_direct_event_live(json.dumps(body_one).encode()),
        },
        request_count=8,
        endpoint_classes=("BOOTSTRAP", "FIXTURES", "EVENT_LIVE"),
    )


def test_event_live_allowlist_preserves_zero_missing_and_signed_bps() -> None:
    live = parse_direct_event_live(
        b'{"elements":[{"id":1,"stats":{"goals_scored":0,"bps":-4,"saves":2}}]}'
    )
    stats = live.elements[0].stats
    assert stats.goals_scored == 0  # observed zero, never a missing-value surrogate
    assert stats.assists is None
    assert stats.bps == -4
    assert len(live.source_body_sha256) == len(live.semantic_sha256) == 64
    with pytest.raises(IngestionError):
        parse_direct_event_live(b'{"elements":[{"id":1,"stats":{"goals_scored":-1}}]}')
    with pytest.raises(IngestionError):
        parse_direct_event_live(b'{"elements":[{"id":1,"stats":{"saves":true}}]}')


def test_evidence_is_pure_missingness_preserving_and_reconciles_complete_window(
    repository_root: Path,
) -> None:
    snapshot = _snapshot(repository_root)
    evidence = build_current_player_history_evidence(snapshot)
    first = evidence.entries[0]
    assert evidence.model_input_status == "EVIDENCE_ONLY_NOT_MODEL_INPUT"
    assert evidence.new_network_requests == 0
    assert evidence.persistence_performed is False
    assert evidence.coverage.observed_gameweeks == (1,)
    assert first.reconciliation_minutes == first.reconciliation_starts == "MATCH"
    assert first.observations[0].goals_scored == 0
    assert first.observations[0].combined_cbi == 3
    assert first.observations[0].source_granularity == "OFFICIAL_FPL_GAMEWEEK_PLAYER_AGGREGATE"
    assert first.canonical_player_id is None
    assert evidence.entries[1].quality == (CurrentPlayerHistoryQuality.PLAYER_HISTORY_UNAVAILABLE,)
    summary = evidence.safe_summary()
    assert "players" not in summary
    assert summary["model_input_status"] == "EVIDENCE_ONLY_NOT_MODEL_INPUT"
    assert (
        build_current_player_history_evidence(snapshot).semantic_sha256 == evidence.semantic_sha256
    )


def test_missing_field_is_partial_not_zero_and_tampering_fails(repository_root: Path) -> None:
    evidence = build_current_player_history_evidence(
        _snapshot(repository_root, second_goal_missing=True)
    )
    first = evidence.entries[0]
    assert first.observations[0].goals_scored is None
    assert CurrentPlayerHistoryQuality.PARTIAL_FIELD_COVERAGE in first.quality
    tampered = evidence.model_dump(mode="python")
    tampered["entries"][0]["observations"][0]["goals_scored"] = 9
    with pytest.raises(ValueError, match="semantic hash"):
        type(evidence).model_validate(tampered)


def test_partial_window_does_not_compare_to_full_season_total(repository_root: Path) -> None:
    snapshot = _snapshot(repository_root)
    snapshot = snapshot.model_copy(update={"live_by_gameweek": {}})
    evidence = build_current_player_history_evidence(snapshot)
    first = evidence.entries[0]
    assert first.reconciliation_minutes == first.reconciliation_starts == "NOT_APPLICABLE"
    assert first.quality == (CurrentPlayerHistoryQuality.PLAYER_HISTORY_UNAVAILABLE,)
