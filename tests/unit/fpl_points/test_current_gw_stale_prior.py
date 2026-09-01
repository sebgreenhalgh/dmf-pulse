from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.player_prior import (
    CurrentGwPriorFallbackAssignment,
    CurrentGwStalePriorCarryForwardPolicy,
    build_current_gw_player_prior_binding,
    build_player_prior_identity_binding,
    load_packaged_player_prior,
    seal_current_gw_stale_prior_policy,
)
from dmf_pulse.ingestion.fpl.current import CurrentFplInputBundle
from tests.unit.ingestion.current_manager_test_support import ATTESTED, build_context

_PLAYER_UUID = "10000000-0000-4000-8000-000000000114"
_TEAM_UUID = "20000000-0000-4000-8000-000000000004"


def _policy(
    fpl_input: CurrentFplInputBundle,
    *,
    assignment: CurrentGwPriorFallbackAssignment | None,
) -> CurrentGwStalePriorCarryForwardPolicy:
    prior = load_packaged_player_prior()
    provisional = CurrentGwStalePriorCarryForwardPolicy.model_construct(
        target_gameweek=fpl_input.target_gameweek,
        current_fpl_bundle_sha256=fpl_input.semantic_sha256,
        prior_artifact_sha256=prior.artifact.artifact_sha256,
        historical_acceptance_sha256=prior.historical_acceptance.acceptance_sha256,
        original_evidence_cutoff=prior.artifact.information_cutoff,
        declared_at=ATTESTED,
        fallback_assignments=() if assignment is None else (assignment,),
        semantic_sha256="0" * 64,
    )
    return seal_current_gw_stale_prior_policy(provisional)


def test_packaged_gw1_resources_remain_byte_exact(repository_root: Path) -> None:
    resource = repository_root / "src/dmf_pulse/fpl_points/resources"
    assert (
        hashlib.sha256(
            (resource / "gw1_private_player_allocation_prior_v1.json").read_bytes()
        ).hexdigest()
        == "995d0166c7d5cdd86f18948f6d374044da116881758622fc98f1ca3718c5fae0"
    )
    assert (
        hashlib.sha256(
            (resource / "gw1_private_player_allocation_acceptance_v1.json").read_bytes()
        ).hexdigest()
        == "67b69a2c04171ceacd8bcc3667d058e4b2d1864442dc95f3e1c9371f9cd58224"
    )


def test_original_binding_remains_gw1_only(repository_root: Path, tmp_path: Path) -> None:
    context = build_context(repository_root, tmp_path)
    with pytest.raises(FplPointsError, match="restricted to 2026/27 GW1"):
        build_player_prior_identity_binding(
            load_packaged_player_prior(),
            context.fpl_input,
            canonical_player_ids_by_source_id={114: _PLAYER_UUID},
            canonical_team_ids_by_source_id={4: _TEAM_UUID},
        )


def test_invalid_individual_team_relation_requires_explicit_position_fallback(
    repository_root: Path, tmp_path: Path
) -> None:
    context = build_context(repository_root, tmp_path)
    prior = load_packaged_player_prior()
    with pytest.raises(FplPointsError, match="explicit governed position fallback"):
        build_current_gw_player_prior_binding(
            prior,
            context.fpl_input,
            _policy(context.fpl_input, assignment=None),
            canonical_player_ids_by_source_id={114: _PLAYER_UUID},
            canonical_team_ids_by_source_id={4: _TEAM_UUID},
        )

    assignment = CurrentGwPriorFallbackAssignment(
        current_official_fpl_element_id=114,
        fallback_official_fpl_element_id=119,
        operator_reason="GW1 individual/team relationship differs; use governed FWD fallback",
    )
    policy = _policy(context.fpl_input, assignment=assignment)
    first = build_current_gw_player_prior_binding(
        prior,
        context.fpl_input,
        policy,
        canonical_player_ids_by_source_id={114: _PLAYER_UUID},
        canonical_team_ids_by_source_id={4: _TEAM_UUID},
    )
    second = build_current_gw_player_prior_binding(
        prior,
        context.fpl_input,
        policy,
        canonical_player_ids_by_source_id={114: _PLAYER_UUID},
        canonical_team_ids_by_source_id={4: _TEAM_UUID},
    )
    assert first == second
    assert first.schema_version == "current-gw-player-prior-carry-forward-binding-v1"
    assert first.entries[0].assignment_level == "FPL_POSITION_FALLBACK"
    assert first.entries[0].donor_source_player_id == 119
    assert policy.current_player_history_created is False
    assert policy.current_use_acceptance_coverage == "NOT_COVERED_BY_HISTORICAL_ACCEPTANCE"


def test_valid_same_team_individual_profile_is_carried_explicitly(
    repository_root: Path, tmp_path: Path
) -> None:
    context = build_context(repository_root, tmp_path)
    binding = build_current_gw_player_prior_binding(
        load_packaged_player_prior(),
        context.fpl_input,
        _policy(context.fpl_input, assignment=None),
        canonical_player_ids_by_source_id={115: "10000000-0000-4000-8000-000000000115"},
        canonical_team_ids_by_source_id={5: "20000000-0000-4000-8000-000000000005"},
    )
    assert binding.entries[0].assignment_level == "INDIVIDUAL_SAME_TEAM"
    assert binding.entries[0].donor_source_player_id == 115


def test_wrong_position_fallback_fails_closed(repository_root: Path, tmp_path: Path) -> None:
    context = build_context(repository_root, tmp_path)
    assignment = CurrentGwPriorFallbackAssignment(
        current_official_fpl_element_id=114,
        fallback_official_fpl_element_id=110,
        operator_reason="hostile wrong-position mapping",
    )
    with pytest.raises(FplPointsError, match="same FPL position"):
        build_current_gw_player_prior_binding(
            load_packaged_player_prior(),
            context.fpl_input,
            _policy(context.fpl_input, assignment=assignment),
            canonical_player_ids_by_source_id={114: _PLAYER_UUID},
            canonical_team_ids_by_source_id={4: _TEAM_UUID},
        )
