"""Governed penalty-overlay and three-world sensitivity tests."""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.player_evidence.empirical_bayes import compile_posterior_artifact
from dmf_pulse.player_evidence.models import (
    HistoryPastSeason,
    HistorySensitivityWorld,
    PenaltyDesignation,
    PlayerHistoryEvidence,
    PriceWorld,
    candidate_eb_parameters,
    candidate_price_policy,
)
from dmf_pulse.player_evidence.overlays import (
    PenaltyResponsibilityClassification,
    PrivateAllocationOverlayReview,
    PrivatePenaltyCandidateReview,
    PrivateTeamPenaltyReview,
    ReviewConfidence,
    compile_current_allocation_overlay,
)
from tests.support.factories import (
    A_FWD,
    A_MID,
    AWAY_TEAM_ID,
    H_FWD,
    H_MID,
    HOME_TEAM_ID,
)
from tests.unit.player_evidence.support import NOW, SHA, catalogue, generic_prior

SOURCE = "https://example.test/current-penalty-review"


def _catalogue_player(player_id: str):
    return next(player for player in catalogue().players if player.player_id == UUID(player_id))


def _history(player_id: str, *, goals: int, assists: int) -> PlayerHistoryEvidence:
    player = _catalogue_player(player_id)
    return PlayerHistoryEvidence(
        player_id=player.player_id,
        source_player_id=player.source_player_id,
        seasons=(
            HistoryPastSeason(
                season="2025/26",
                minutes=1_800,
                goals=goals,
                assists=assists,
                yellow_cards=2,
                red_cards=0,
                saves=0,
            ),
        ),
    )


def _posteriors():
    histories = (
        _history(H_MID, goals=20, assists=10),
        _history(H_FWD, goals=2, assists=1),
    )
    return {
        world: compile_posterior_artifact(
            catalogue=catalogue(),
            histories=histories,
            role_priors=(generic_prior(),),
            tactical_roles={},
            parameters=candidate_eb_parameters(world),
            information_cutoff=NOW,
            source_observed_at=NOW - timedelta(hours=3),
            usable_at=NOW - timedelta(hours=2),
            produced_at=NOW - timedelta(hours=1),
            source_locator="synthetic://GW1-PLY-004/posterior",
            schema_fingerprint=SHA,
            rights_profile_id="SYNTHETIC_REPLAY_ONLY",
        )
        for world in HistorySensitivityWorld
    }


def _candidate(
    player_id: str,
    *,
    designation: PenaltyDesignation,
    weight: float,
) -> PrivatePenaltyCandidateReview:
    player = _catalogue_player(player_id)
    return PrivatePenaltyCandidateReview(
        source_player_id=player.source_player_id,
        player_id=player.player_id,
        team_id=player.team_id,
        display_name=f"private-{player.source_player_id}",
        designation=designation,
        allocation_weight=weight,
        source_reference=SOURCE,
    )


def _team_review(
    *,
    provider_team_id: int,
    team_id: str,
    classification: PenaltyResponsibilityClassification,
    candidates: tuple[PrivatePenaltyCandidateReview, ...],
) -> PrivateTeamPenaltyReview:
    return PrivateTeamPenaltyReview(
        provider_team_id=provider_team_id,
        team_id=UUID(team_id),
        display_name=f"private-team-{provider_team_id}",
        classification=classification,
        confidence=(
            ReviewConfidence.LOW
            if classification is PenaltyResponsibilityClassification.UNKNOWN
            else ReviewConfidence.HIGH
        ),
        uncertainty_flag=classification is not PenaltyResponsibilityClassification.CLEAR_PRIMARY,
        reason="Synthetic current review for offline contract tests.",
        evidence_source_references=(SOURCE,),
        observed_at=NOW - timedelta(hours=3),
        usable_at=NOW - timedelta(hours=2),
        expires_at=NOW + timedelta(days=1),
        candidates=candidates,
    )


def _review(*, away_unknown: bool = False) -> PrivateAllocationOverlayReview:
    home = _team_review(
        provider_team_id=1,
        team_id=HOME_TEAM_ID,
        classification=PenaltyResponsibilityClassification.CLEAR_PRIMARY,
        candidates=(_candidate(H_MID, designation=PenaltyDesignation.PRIMARY, weight=1.0),),
    )
    away = _team_review(
        provider_team_id=2,
        team_id=AWAY_TEAM_ID,
        classification=(
            PenaltyResponsibilityClassification.UNKNOWN
            if away_unknown
            else PenaltyResponsibilityClassification.PRIMARY_WITH_BACKUP
        ),
        candidates=(
            ()
            if away_unknown
            else (
                _candidate(A_MID, designation=PenaltyDesignation.PRIMARY, weight=0.8),
                _candidate(A_FWD, designation=PenaltyDesignation.BACKUP, weight=0.2),
            )
        ),
    )
    values = {
        "schema_version": "gw1-player-allocation-overlay-private-review-v1",
        "status": "PRIVATE_OPERATOR_REVIEW_NOT_FOR_PUBLICATION",
        "scope": "PRIVATE_2026_27_GW1_ONLY",
        "catalogue_semantic_sha256": SHA,
        "expected_player_count": len(catalogue().players),
        "expected_team_count": 2,
        "information_cutoff": NOW,
        "reviewer": "synthetic-test-only",
        "role_review_rationale": "No synthetic role case clears the materiality threshold.",
        "teams": (home, away),
        "role_overrides": (),
    }
    provisional = PrivateAllocationOverlayReview.model_construct(**values, review_sha256="0" * 64)
    return PrivateAllocationOverlayReview(
        **values,
        review_sha256=canonical_sha256(
            provisional.model_dump(mode="json", exclude={"review_sha256"})
        ),
    )


def _compile(*, review: PrivateAllocationOverlayReview | None = None):
    return compile_current_allocation_overlay(
        review=review or _review(),
        catalogue=catalogue(),
        team_ids_by_provider={1: UUID(HOME_TEAM_ID), 2: UUID(AWAY_TEAM_ID)},
        posteriors=_posteriors(),
        role_priors=(generic_prior(),),
        price_policy=candidate_price_policy(PriceWorld.PRICE_OFF),
        produced_at=NOW - timedelta(minutes=30),
    )


def test_reviewed_assignments_compile_three_hash_bound_worlds() -> None:
    compiled = _compile()
    assert len(compiled.assignments) == 3
    assert {assignment.status for assignment in compiled.assignments} == {
        "REVIEWED_CANDIDATE_NOT_HUMAN_ACCEPTED"
    }
    assert all(
        assignment.assignment_sha256
        == canonical_sha256(assignment.model_dump(mode="json", exclude={"assignment_sha256"}))
        for assignment in compiled.assignments
    )
    assert set(compiled.allocations) == set(HistorySensitivityWorld)
    for allocation in compiled.allocations.values():
        assert len(allocation.profiles) == len(catalogue().players)
        profiles = {profile.player_id: profile for profile in allocation.profiles}
        assert profiles[H_MID].penalty_taker_share == pytest.approx(1.0)
        assert profiles[A_MID].penalty_taker_share == pytest.approx(0.8)
        assert profiles[A_FWD].penalty_taker_share == pytest.approx(0.2)
        assert "STAGE7_MINUTES_NOT_EMBEDDED_IN_PERSISTENT_SHARES" in allocation.limitations
    assert compiled.receipt.classification_counts == {
        "CLEAR_PRIMARY": 1,
        "PRIMARY_WITH_BACKUP": 1,
        "MULTIPLE_CANDIDATES": 0,
        "UNKNOWN": 0,
    }
    assert compiled.receipt.penalty_assignments_affect_penalty_share_only is True
    assert compiled.receipt.penalty_assignment_status == "REVIEWED_CANDIDATE_NOT_HUMAN_ACCEPTED"
    assert compiled.receipt.history_network_request_count == 0
    assert compiled.receipt.raw_fpl_history_persisted is False
    assert compiled.receipt.current_fpl_catalogue_persisted is False
    assert compiled.sensitivity_summary.penalty_profiles_invariant_across_worlds == len(
        catalogue().players
    )
    assert compiled.sensitivity_summary.penalty_clubs_invariant_across_worlds == 2


def test_penalty_overlay_does_not_change_goal_or_assist_world_sensitivity() -> None:
    compiled = _compile()
    rows = {str(row.player_id): row for row in compiled.sensitivity_rows}
    assert rows[H_MID].maximum_absolute_goal_share_movement > 0.0
    assert rows[H_MID].maximum_absolute_assist_share_movement > 0.0
    assert compiled.sensitivity_summary.goal_share.maximum_absolute_movement > 0.0
    assert compiled.sensitivity_summary.assist_share.maximum_absolute_movement > 0.0
    for allocation in compiled.allocations.values():
        profiles = {profile.player_id: profile for profile in allocation.profiles}
        assert profiles[H_MID].penalty_taker_share == 1.0


def test_explicit_unknown_preserves_visible_whole_roster_fallback() -> None:
    compiled = _compile(review=_review(away_unknown=True))
    assert compiled.receipt.classification_counts["UNKNOWN"] == 1
    assert len(compiled.receipt.unknown_team_identity_sha256s) == 1
    for allocation in compiled.allocations.values():
        away = [profile for profile in allocation.profiles if profile.team_id == AWAY_TEAM_ID]
        assert all(profile.penalty_taker_share > 0.0 for profile in away)
        assert sum(profile.penalty_taker_share for profile in away) == pytest.approx(1.0)


def test_review_rejects_incoherent_weights_and_unbound_urls() -> None:
    candidate = _candidate(H_MID, designation=PenaltyDesignation.PRIMARY, weight=0.8)
    with pytest.raises(ValidationError, match="weights must sum to one"):
        _team_review(
            provider_team_id=1,
            team_id=HOME_TEAM_ID,
            classification=PenaltyResponsibilityClassification.CLEAR_PRIMARY,
            candidates=(candidate,),
        )
    payload = _review().model_dump(mode="json")
    payload["teams"][0]["evidence_source_references"] = ["http://example.test/insecure"]
    payload["teams"][0]["candidates"][0]["source_reference"] = "http://example.test/insecure"
    with pytest.raises(ValidationError, match="HTTPS URLs"):
        PrivateAllocationOverlayReview.model_validate_json(json.dumps(payload))


def test_compile_rejects_identity_conflicts_and_hash_mutation() -> None:
    review = _review()
    payload = review.model_dump(mode="json")
    payload["teams"][0]["candidates"][0]["player_id"] = str(uuid4())
    payload["review_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "review_sha256"}
    )
    conflicting = PrivateAllocationOverlayReview.model_validate_json(json.dumps(payload))
    with pytest.raises(IngestionError, match="exact current identity"):
        _compile(review=conflicting)

    mutated = review.model_copy(update={"review_sha256": "f" * 64})
    with pytest.raises(ValidationError, match="review hash is invalid"):
        PrivateAllocationOverlayReview.model_validate_json(mutated.model_dump_json())


def test_compile_rejects_post_cutoff_production_and_wrong_team_bridge() -> None:
    with pytest.raises(IngestionError, match="produced_at exceeds"):
        compile_current_allocation_overlay(
            review=_review(),
            catalogue=catalogue(),
            team_ids_by_provider={1: UUID(HOME_TEAM_ID), 2: UUID(AWAY_TEAM_ID)},
            posteriors=_posteriors(),
            role_priors=(generic_prior(),),
            price_policy=candidate_price_policy(PriceWorld.PRICE_OFF),
            produced_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(IngestionError, match="team identities do not match"):
        compile_current_allocation_overlay(
            review=_review(),
            catalogue=catalogue(),
            team_ids_by_provider={1: UUID(AWAY_TEAM_ID), 2: UUID(HOME_TEAM_ID)},
            posteriors=_posteriors(),
            role_priors=(generic_prior(),),
            price_policy=candidate_price_policy(PriceWorld.PRICE_OFF),
            produced_at=NOW - timedelta(minutes=30),
        )
