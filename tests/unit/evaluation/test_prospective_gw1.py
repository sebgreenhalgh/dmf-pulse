"""Stage-12 hash-only prospective receipt acceptance."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dmf_pulse.evaluation.prospective import (
    ProspectiveDecisionReceipt,
    build_prospective_receipt,
    persist_prospective_receipt,
)

pytestmark = pytest.mark.unit


def _receipt() -> ProspectiveDecisionReceipt:
    return build_prospective_receipt(
        recorded_at=datetime(2026, 8, 20, 12, 5, tzinfo=UTC),
        information_cutoff=datetime(2026, 8, 20, 12, 4, tzinfo=UTC),
        code_commit="a" * 40,
        ruleset_hash="1" * 64,
        manager_capability_hash="2" * 64,
        session1_semantic_sha256="3" * 64,
        market_semantic_sha256="4" * 64,
        availability_semantic_sha256="5" * 64,
        event_semantic_sha256="6" * 64,
        projection_config_sha256="7" * 64,
        projection_semantic_sha256="8" * 64,
        gameweek_result_sha256="9" * 64,
        scenario_set_sha256="b" * 64,
        decision_sha256="c" * 64,
    )


def test_receipt_is_predeadline_hash_only_and_content_addressed(tmp_path) -> None:
    receipt = _receipt()
    destination = persist_prospective_receipt(receipt, artifact_root=tmp_path)

    assert destination == tmp_path / "gw1" / receipt.receipt_sha256 / "receipt.json"
    assert persist_prospective_receipt(receipt, artifact_root=tmp_path) == destination
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["dataset_mode"] == "LIVE_OBSERVED"
    assert payload["observation_role"] == "METADATA"
    assert payload["detailed_fpl_content_persisted"] is False
    assert payload["raw_provider_content_persisted"] is False
    assert not {
        "players",
        "squad",
        "starting_xi",
        "captain",
        "provider_payload",
    } & set(payload)


def test_receipt_rejects_post_cutoff_or_naive_recording() -> None:
    with pytest.raises(ValidationError, match="time or identity"):
        ProspectiveDecisionReceipt.model_validate_json(
            _receipt()
            .model_copy(update={"information_cutoff": datetime(2026, 8, 20, 12, 6, tzinfo=UTC)})
            .model_dump_json()
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        build_prospective_receipt(
            recorded_at=datetime(2026, 8, 20, 12),
            information_cutoff=datetime(2026, 8, 20, 12, 4, tzinfo=UTC),
            code_commit="a" * 40,
            ruleset_hash="1" * 64,
            manager_capability_hash="2" * 64,
            session1_semantic_sha256="3" * 64,
            market_semantic_sha256="4" * 64,
            availability_semantic_sha256="5" * 64,
            event_semantic_sha256="6" * 64,
            projection_config_sha256="7" * 64,
            projection_semantic_sha256="8" * 64,
            gameweek_result_sha256="9" * 64,
            scenario_set_sha256="b" * 64,
            decision_sha256="c" * 64,
        )


def test_receipt_refuses_different_existing_bytes(tmp_path) -> None:
    receipt = _receipt()
    destination = persist_prospective_receipt(receipt, artifact_root=tmp_path)
    destination.write_text("{}\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="different bytes"):
        persist_prospective_receipt(receipt, artifact_root=tmp_path)
