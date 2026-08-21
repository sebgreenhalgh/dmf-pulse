"""Deterministic validation of the permitted GW1-PLY-003R4 derived evidence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.player_evidence.approvals import load_player_history_rights_approval
from dmf_pulse.player_evidence.models import (
    CaptureAccessMode,
    DeletionManifest,
    HistorySensitivityWorld,
    PlayerAllocationCandidateArtifact,
    PlayerPosteriorArtifact,
    PriceWorld,
    RetentionMode,
)
from dmf_pulse.player_evidence.role_priors import (
    load_role_prior_candidate,
    role_priors_from_candidate,
)

EVIDENCE = Path("evidence/tickets/GW1-PLY-003")
APPROVAL_SHA256 = "2a4561b3ad7fa24cbe3b40f5a56e8b58251b3d6e8ec68881ed4d78c0d8579b4b"
ROLE_PRIOR_SHA256 = "007e4d400d8f72eccc50541a9e9b385042bd3eb5d724b0b1d76e7cc69f42afb8"
RAW_HISTORY_KEYS = {
    "season_name",
    "minutes",
    "goals_scored",
    "assists",
    "yellow_cards",
    "red_cards",
    "saves",
    "history_past",
}
CURRENT_CATALOGUE_KEYS = {
    "current_price_tenths",
    "source_player_identity_sha256",
    "source_team_identity_sha256",
}
STAGE7_PARTICIPATION_KEYS = {"p_start", "p_appearance", "expected_minutes"}


def _read(relative_path: str) -> str:
    return Path(relative_path).read_text(encoding="utf-8")


def _file_sha256(relative_path: str) -> str:
    return hashlib.sha256(Path(relative_path).read_bytes()).hexdigest()


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


def test_published_capture_receipt_and_artifacts_are_hash_bound_and_safe() -> None:
    receipt_path = EVIDENCE / "GW1_POST_DIAGNOSTIC_FULL_CAPTURE_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["receipt_sha256"] == canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    assert receipt["approval"]["approval_sha256"] == APPROVAL_SHA256
    assert receipt["approval"]["consumed"] is True
    assert receipt["capture"]["actual_request_count"] == 599
    assert receipt["capture"]["successful_response_count"] == 599
    assert receipt["capture"]["retry_occurred"] is False
    assert receipt["state"]["raw_fpl_history_persisted"] is False
    assert receipt["state"]["current_fpl_catalogue_persisted"] is False

    artifact_records = receipt["artifacts"]
    central = PlayerPosteriorArtifact.model_validate_json(
        _read(artifact_records["central_posterior"]["path"])
    )
    low = PlayerPosteriorArtifact.model_validate_json(
        _read(artifact_records["low_posterior"]["path"])
    )
    high = PlayerPosteriorArtifact.model_validate_json(
        _read(artifact_records["high_posterior"]["path"])
    )
    allocation = PlayerAllocationCandidateArtifact.model_validate_json(
        _read(artifact_records["allocation_candidate"]["path"])
    )
    deletion = DeletionManifest.model_validate_json(
        _read(artifact_records["deletion_manifest"]["path"])
    )
    for record in artifact_records.values():
        assert _file_sha256(record["path"]) == record["file_sha256"]
    assert central.artifact_sha256 == artifact_records["central_posterior"]["artifact_sha256"]
    assert low.artifact_sha256 == artifact_records["low_posterior"]["artifact_sha256"]
    assert high.artifact_sha256 == artifact_records["high_posterior"]["artifact_sha256"]
    assert allocation.artifact_sha256 == artifact_records["allocation_candidate"]["artifact_sha256"]
    assert (
        canonical_sha256(deletion.model_dump(mode="json"))
        == artifact_records["deletion_manifest"]["artifact_sha256"]
    )

    assert central.parameters.sensitivity_world is HistorySensitivityWorld.CENTRAL_TEMPORARY
    assert low.parameters.sensitivity_world is HistorySensitivityWorld.LOW_SHRINKAGE
    assert high.parameters.sensitivity_world is HistorySensitivityWorld.HIGH_SHRINKAGE
    assert len({central.artifact_sha256, low.artifact_sha256, high.artifact_sha256}) == 3
    assert allocation.posterior_artifact_sha256 == central.artifact_sha256
    assert allocation.price_policy.world is PriceWorld.PRICE_OFF
    assert allocation.degraded_player_allocation is False
    assert deletion.deletion_outcome == "SUCCESS"
    assert deletion.posterior_artifact_sha256 == central.artifact_sha256
    assert deletion.raw_history_persisted is False
    assert deletion.current_catalogue_persisted is False
    assert len(deletion.temporary_object_identifiers) == 600

    player_ids = {str(player.player_id) for player in central.players}
    assert len(player_ids) == 599
    assert {str(player.player_id) for player in low.players} == player_ids
    assert {str(player.player_id) for player in high.players} == player_ids
    assert {profile.player_id for profile in allocation.profiles} == player_ids
    assert {str(lineage.player_id) for lineage in allocation.lineage} == player_ids
    assert len({profile.team_id for profile in allocation.profiles}) == 20

    no_history = [player for player in central.players if not player.history_seasons_included]
    assert len(no_history) == 93
    assert all(player.posterior_effective_minutes == 0.0 for player in no_history)
    assert all(
        player.goal_rate.mean_per90 > 0.0 and player.assist_rate.mean_per90 > 0.0
        for player in no_history
    )
    lineage_by_id = {str(lineage.player_id): lineage for lineage in allocation.lineage}
    assert all(
        lineage_by_id[str(player.player_id)].goal_source_level.value != "INDIVIDUAL"
        for player in no_history
    )

    affected = [
        player
        for player in central.players
        if player.zero_exposure_discipline_rows_excluded_count > 0
    ]
    assert central.zero_exposure_discipline_rows_excluded_count == 1
    assert low.zero_exposure_discipline_rows_excluded_count == 1
    assert high.zero_exposure_discipline_rows_excluded_count == 1
    assert len(affected) == 1
    assert all(
        "ZERO_EXPOSURE_DISCIPLINE_ONLY_EXCLUDED_FROM_RATE_MODEL"
        in lineage_by_id[str(player.player_id)].limitations
        for player in affected
    )
    assert all(
        "STAGE7_PARTICIPATION_OWNS_MINUTES_AND_ON_PITCH_ELIGIBILITY" in lineage.limitations
        for lineage in allocation.lineage
    )

    profiles_by_team: dict[str, list[object]] = defaultdict(list)
    for profile in allocation.profiles:
        profiles_by_team[profile.team_id].append(profile)
    for profiles in profiles_by_team.values():
        assert sum(profile.goal_share for profile in profiles) == pytest.approx(1.0)
        assert sum(profile.assist_share for profile in profiles) == pytest.approx(1.0)
        assert sum(profile.penalty_taker_share for profile in profiles) == pytest.approx(1.0)
    assert "PENALTY_SHARE_SEPARATE_FROM_OPEN_PLAY_GOAL_SHARE" in allocation.limitations
    assert "STAGE7_MINUTES_NOT_EMBEDDED_IN_PERSISTENT_SHARES" in allocation.limitations
    assert "BPS_DEFENSIVE_AUXILIARY_ROLE_POOLED" in allocation.limitations

    approval = load_player_history_rights_approval(
        EVIDENCE / "GW1_PLAYER_HISTORY_POST_DIAGNOSTIC_FULL_CAPTURE_APPROVAL.json",
        expected_approval_sha256=APPROVAL_SHA256,
    )
    assert (
        approval.access_mode is CaptureAccessMode.HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT
    )
    assert approval.derived_retention is RetentionMode.POSTERIOR_ONLY
    for artifact in (central, low, high):
        assert {player.rights_profile_id for player in artifact.players} == {
            approval.rights_profile_id
        }
        assert {player.access_mode for player in artifact.players} == {approval.access_mode}
        assert {player.retention_mode for player in artifact.players} == {
            RetentionMode.POSTERIOR_ONLY
        }

    role_prior = load_role_prior_candidate(
        Path("evidence/tickets/GW1-PLY-002/GW1_PLAYER_ROLE_PRIOR_CANDIDATE.json")
    )
    assert role_prior.artifact_sha256 == ROLE_PRIOR_SHA256
    prior_versions = {prior.prior_version for prior in role_priors_from_candidate(role_prior)}
    assert {player.prior_version for player in central.players} <= prior_versions
    assert {lineage.prior_version for lineage in allocation.lineage} <= prior_versions

    for record in artifact_records.values():
        keys = _all_keys(json.loads(_read(record["path"])))
        assert keys.isdisjoint(RAW_HISTORY_KEYS)
        assert keys.isdisjoint(CURRENT_CATALOGUE_KEYS)
        assert keys.isdisjoint(STAGE7_PARTICIPATION_KEYS)
