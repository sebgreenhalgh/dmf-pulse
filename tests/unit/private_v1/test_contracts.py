from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from dmf_pulse.private_v1.models import (
    PrivateCandidateActionPolicy,
    PrivateCurrentOwnership,
    PrivateCurrentOwnershipMember,
    PrivateGainMass,
    PrivatePairedComparison,
    PrivateReplayFile,
    PrivateReplayManifest,
    seal_candidate_action_policy,
    seal_current_ownership,
    seal_replay_manifest,
)

_CUTOFF = datetime(2026, 8, 28, 17, 30, tzinfo=UTC)


def _ownership() -> PrivateCurrentOwnership:
    provisional = PrivateCurrentOwnership.model_construct(
        source_class="OPERATOR_DECLARED_PRIVATE_TRANSIENT",
        attestation_status="HUMAN_ATTESTED",
        provider_verification="NOT_PROVIDER_VERIFIED",
        target_gameweek=2,
        declared_at=datetime(2026, 8, 28, 16, 0, tzinfo=UTC),
        attested_at=datetime(2026, 8, 28, 16, 5, tzinfo=UTC),
        information_cutoff=_CUTOFF,
        members=tuple(
            PrivateCurrentOwnershipMember(
                official_fpl_element_id=index,
                acquired_gameweek=1,
            )
            for index in range(1, 16)
        ),
        semantic_sha256="0" * 64,
    )
    return seal_current_ownership(provisional)


def test_ownership_is_hash_bound_and_requires_truthful_chronology() -> None:
    value = _ownership()
    assert value == PrivateCurrentOwnership.model_validate_json(value.model_dump_json())

    payload = value.model_dump(mode="python")
    payload["members"] = (
        *payload["members"][:-1],
        PrivateCurrentOwnershipMember(
            official_fpl_element_id=15,
            acquired_gameweek=3,
        ),
    )
    with pytest.raises(ValidationError, match="acquisition cannot be after"):
        PrivateCurrentOwnership.model_validate(payload)

    payload = value.model_dump(mode="python")
    payload["members"] = tuple(reversed(payload["members"]))
    with pytest.raises(ValidationError, match="unique and ordered"):
        PrivateCurrentOwnership.model_validate(payload)


def test_candidate_action_scope_is_explicit_sorted_and_hash_bound() -> None:
    provisional = PrivateCandidateActionPolicy.model_construct(
        allowed_transfer_in_element_ids=(16, 17),
        maximum_transfers=1,
        rationale="Two current same-scenario candidates declared by the operator.",
        semantic_sha256="0" * 64,
    )
    value = seal_candidate_action_policy(provisional)
    assert value.allowed_transfer_in_element_ids == (16, 17)

    with pytest.raises(ValidationError, match="unique and sorted"):
        PrivateCandidateActionPolicy.model_validate(
            {**value.model_dump(mode="python"), "allowed_transfer_in_element_ids": (17, 16)}
        )
    with pytest.raises(ValidationError, match="nonzero transfer scope"):
        PrivateCandidateActionPolicy.model_validate(
            {
                **value.model_dump(mode="python"),
                "allowed_transfer_in_element_ids": (),
                "maximum_transfers": 1,
            }
        )


def test_paired_comparison_reconciles_hit_adjusted_common_scenario_values() -> None:
    provisional = PrivatePairedComparison.model_construct(
        scenario_count=2,
        recommended_expected_points_before_hit=Decimal("52"),
        no_transfer_expected_points=Decimal("49"),
        transfer_hit_points=0,
        recommended_expected_points_after_hit=Decimal("52"),
        net_expected_uplift=Decimal("3"),
        gain_p10=-2,
        gain_median=-2,
        gain_p90=8,
        probability_recommended_beats_baseline=Decimal("0.5"),
        probability_gain_at_least_four=Decimal("0.5"),
        probability_loss_at_least_four=Decimal("0"),
        gain_pmf=(
            PrivateGainMass(points=-2, probability=Decimal("0.5")),
            PrivateGainMass(points=8, probability=Decimal("0.5")),
        ),
        semantic_sha256="0" * 64,
    )
    from dmf_pulse.assurance.canonical import canonical_sha256

    value = PrivatePairedComparison.model_validate(
        {
            **provisional.model_dump(mode="python"),
            "semantic_sha256": canonical_sha256(
                provisional.model_dump(mode="json", exclude={"semantic_sha256"})
            ),
        }
    )
    assert value.net_expected_uplift == Decimal("3")
    with pytest.raises(ValidationError, match="does not reconcile"):
        value.model_copy(update={"transfer_hit_points": 4})


def test_replay_manifest_is_relative_stable_and_content_bound() -> None:
    provisional = PrivateReplayManifest.model_construct(
        run_id="SYNTHETIC-E2E-01",
        code_sha="1" * 40,
        execution_input_semantic_sha256="2" * 64,
        decision_semantic_sha256="3" * 64,
        files=(
            PrivateReplayFile(relative_path="decision.json", sha256="4" * 64, byte_count=10),
            PrivateReplayFile(relative_path="input.json", sha256="5" * 64, byte_count=20),
            PrivateReplayFile(relative_path="report.txt", sha256="6" * 64, byte_count=30),
        ),
        manifest_sha256="0" * 64,
    )
    value = seal_replay_manifest(provisional)
    assert value.absolute_paths_embedded is False
    assert value.network_required is False
    assert value == seal_replay_manifest(provisional)

    with pytest.raises(ValidationError):
        PrivateReplayFile(
            relative_path="C:\\private\\input.json",
            sha256="4" * 64,
            byte_count=10,
        )
