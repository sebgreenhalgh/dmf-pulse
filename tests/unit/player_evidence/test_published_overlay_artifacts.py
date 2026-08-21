"""Validate the public, derived-only GW1-PLY-004 overlay artifacts."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from dmf_pulse.player_evidence.models import (
    HistorySensitivityWorld,
    PlayerAllocationCandidateArtifact,
    PriceWorld,
)
from dmf_pulse.player_evidence.overlays import (
    AllocationSensitivitySummary,
    PenaltyOverlayReceipt,
)

ROOT = Path("evidence/tickets/GW1-PLY-004")
BASELINE_PATH = Path("evidence/tickets/GW1-PLY-003/GW1_CURRENT_PLAYER_ALLOCATION_CANDIDATE.json")
ALLOCATION_PATHS = {
    HistorySensitivityWorld.CENTRAL_TEMPORARY: ROOT
    / "GW1_CURRENT_PLAYER_ALLOCATION_CENTRAL_OVERLAY.json",
    HistorySensitivityWorld.LOW_SHRINKAGE: ROOT / "GW1_CURRENT_PLAYER_ALLOCATION_LOW_OVERLAY.json",
    HistorySensitivityWorld.HIGH_SHRINKAGE: ROOT
    / "GW1_CURRENT_PLAYER_ALLOCATION_HIGH_OVERLAY.json",
}
EXPECTED_ALLOCATION_HASHES = {
    HistorySensitivityWorld.CENTRAL_TEMPORARY: (
        "629d6c288f9faa7aa7763f5c578e662511c03d514169f683cbeb6ee81af695be"
    ),
    HistorySensitivityWorld.LOW_SHRINKAGE: (
        "6a3184e809d4cc11c4d34327c6b5b7fec320201784614f3601f1285e92ea5bb8"
    ),
    HistorySensitivityWorld.HIGH_SHRINKAGE: (
        "be28135f96276ccd59a57c38369ee4fe423d7b504400faca34a33a847482c0db"
    ),
}


def _load_allocation(path: Path) -> PlayerAllocationCandidateArtifact:
    return PlayerAllocationCandidateArtifact.model_validate_json(path.read_text(encoding="utf-8"))


def _all_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for child in value.values():
            keys.update(_all_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_all_keys(child))
    return keys


def test_published_overlay_artifacts_are_bound_complete_and_derived_only() -> None:
    receipt = PenaltyOverlayReceipt.model_validate_json(
        (ROOT / "GW1_CURRENT_PENALTY_ROLE_OVERLAY_RECEIPT.json").read_text(encoding="utf-8")
    )
    sensitivity = AllocationSensitivitySummary.model_validate_json(
        (ROOT / "GW1_PLAYER_ALLOCATION_SENSITIVITY_SUMMARY.json").read_text(encoding="utf-8")
    )
    allocations = {world: _load_allocation(path) for world, path in ALLOCATION_PATHS.items()}
    baseline = _load_allocation(BASELINE_PATH)

    assert receipt.receipt_sha256 == (
        "cb325409752286beb4dff2366c34bca0fafb33bff2426951e9e760e928c5c9bb"
    )
    assert receipt.penalty_assignment_artifact_sha256 == (
        "0f5aa416babdb0db6166b2126448dd2c2ce3c58732e6d69837cf182ee9b60efb"
    )
    assert sensitivity.artifact_sha256 == receipt.sensitivity_artifact_sha256
    assert receipt.classification_counts == {
        "CLEAR_PRIMARY": 3,
        "PRIMARY_WITH_BACKUP": 9,
        "MULTIPLE_CANDIDATES": 8,
        "UNKNOWN": 0,
    }
    assert receipt.penalty_assignment_count == 50
    assert receipt.penalty_assignment_status == "REVIEWED_CANDIDATE_NOT_HUMAN_ACCEPTED"
    assert receipt.role_override_count == 0
    assert receipt.unknown_team_identity_sha256s == ()
    assert receipt.history_network_request_count == 0
    assert receipt.exact_stage7_player_identity_equality is True
    assert receipt.exact_stage7_team_identity_equality is True
    assert receipt.stage7_expected_minutes_separate is True
    assert receipt.penalty_assignments_affect_penalty_share_only is True
    assert receipt.defensive_contribution_model_completeness == "PARTIAL"
    assert receipt.raw_fpl_history_persisted is False
    assert receipt.current_fpl_catalogue_persisted is False
    assert receipt.player_allocation_human_accepted is False

    baseline_by_id = {profile.player_id: profile for profile in baseline.profiles}
    expected_player_ids = set(baseline_by_id)
    expected_team_by_player = {profile.player_id: profile.team_id for profile in baseline.profiles}
    for world, allocation in allocations.items():
        assert allocation.artifact_sha256 == EXPECTED_ALLOCATION_HASHES[world]
        assert allocation.price_policy.world is PriceWorld.PRICE_OFF
        assert len(allocation.profiles) == 599
        assert {profile.player_id for profile in allocation.profiles} == expected_player_ids
        assert {
            profile.player_id: profile.team_id for profile in allocation.profiles
        } == expected_team_by_player
        assert "STAGE7_MINUTES_NOT_EMBEDDED_IN_PERSISTENT_SHARES" in allocation.limitations
        assert "ZERO_EXPOSURE_DISCIPLINE_ONLY_EXCLUDED_FROM_RATE_MODEL" in allocation.limitations
        profiles_by_team: dict[str, list[float]] = defaultdict(list)
        goal_by_team: dict[str, float] = defaultdict(float)
        assist_by_team: dict[str, float] = defaultdict(float)
        for profile in allocation.profiles:
            profiles_by_team[profile.team_id].append(profile.penalty_taker_share)
            goal_by_team[profile.team_id] += profile.goal_share
            assist_by_team[profile.team_id] += profile.assist_share
        assert len(profiles_by_team) == 20
        assert all(math.isclose(value, 1.0, abs_tol=1e-12) for value in goal_by_team.values())
        assert all(math.isclose(value, 1.0, abs_tol=1e-12) for value in assist_by_team.values())
        assert all(
            math.isclose(sum(values), 1.0, abs_tol=1e-12) for values in profiles_by_team.values()
        )
        assert all(
            sum(value > 0.0 for value in values) < len(values)
            for values in profiles_by_team.values()
        )

    central_by_id = {
        profile.player_id: profile
        for profile in allocations[HistorySensitivityWorld.CENTRAL_TEMPORARY].profiles
    }
    for player_id, profile in central_by_id.items():
        assert profile.model_dump(mode="json", exclude={"penalty_taker_share"}) == baseline_by_id[
            player_id
        ].model_dump(mode="json", exclude={"penalty_taker_share"})

    assert sensitivity.player_count == 599
    assert sensitivity.team_count == 20
    assert sensitivity.penalty_profiles_invariant_across_worlds == 599
    assert sensitivity.penalty_clubs_invariant_across_worlds == 20
    assert sensitivity.players_materially_unstable_on_either_metric == 21
    assert sensitivity.goal_share.players_at_or_above_material_threshold == 7
    assert sensitivity.assist_share.players_at_or_above_material_threshold == 14

    forbidden = {
        "display_name",
        "history_past",
        "season_name",
        "expected_minutes",
        "p_start",
        "p_appearance",
        "current_price_tenths",
    }
    for path in (*ALLOCATION_PATHS.values(), *ROOT.glob("*.json")):
        assert _all_keys(json.loads(path.read_text(encoding="utf-8"))).isdisjoint(forbidden)
