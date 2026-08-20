from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from dmf_pulse.evaluation.artifacts import (
    canonical_json_bytes,
    hash_without,
    semantic_sha256,
    sha256_bytes,
)
from dmf_pulse.rank_strategy.artifacts import (
    Stage15DecisionArtifact,
    artifact_identity,
    load_decision_artifact,
    persist_decision_artifact,
    seal_decision_artifact,
    verify_decision_artifact,
)
from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.service import evaluate_rank_plans
from tests.support.rank_service_fixtures import service_request


def test_artifact_binds_complete_rank_lineage_and_plan_identities() -> None:
    request = service_request()
    result = evaluate_rank_plans(request)

    artifact = seal_decision_artifact(request, result)

    assert artifact.artifact_id == artifact_identity(request)
    assert artifact.issued_at == request.forecast_origin
    assert artifact.service_request.lineage.information_cutoff == request.information_cutoff
    assert artifact.service_result.points_optimal_plan.binding_hash == (
        result.points_optimal_plan.binding_hash
    )
    assert (
        artifact.service_result.rank_optimal_plan.binding_hash
        == result.rank_optimal_plan.binding_hash
    )
    assert artifact.service_request.lineage.code_version == "rank-service-test-v1"
    assert artifact.service_request.lineage.config_version == "rank-policy-test-v1"
    assert artifact.service_request.lineage.points_floor_hash == request.lineage.points_floor_hash
    assert artifact.service_request.lineage.rights_profile_hash == "e" * 64
    assert artifact.artifact_hash != "0" * 64
    verify_decision_artifact(artifact)


def test_artifact_persists_and_loads_with_detached_hash(tmp_path: Path) -> None:
    artifact = seal_decision_artifact(service_request())

    path = persist_decision_artifact(artifact, artifact_root=tmp_path)
    loaded = load_decision_artifact(path)

    assert loaded == artifact
    assert path.name == f"{sha256_bytes(path.read_bytes())}.json"
    assert path.with_suffix(".sha256").read_text(encoding="ascii") == (
        f"{path.stem}  {path.name}\n"
    )


def test_detached_tampering_fails_closed(tmp_path: Path) -> None:
    artifact = seal_decision_artifact(service_request())
    path = persist_decision_artifact(artifact, artifact_root=tmp_path)
    path.write_bytes(path.read_bytes().replace(b'"confidence":"A"', b'"confidence":"B"', 1))

    with pytest.raises(RankStrategyError) as exc_info:
        load_decision_artifact(path)

    assert "HASH_MISMATCH" in exc_info.value.code


def test_semantically_resealed_tampering_fails_independent_recomputation() -> None:
    payload = deepcopy(seal_decision_artifact(service_request()).model_dump(mode="json"))
    payload["service_result"]["confidence"] = "B"
    payload["service_result"]["result_hash"] = semantic_sha256(
        {key: value for key, value in payload["service_result"].items() if key != "result_hash"}
    )
    unsealed = Stage15DecisionArtifact.model_validate({**payload, "artifact_hash": "0" * 64})
    payload["artifact_hash"] = hash_without(unsealed, "artifact_hash")
    tampered = Stage15DecisionArtifact.model_validate(payload)

    with pytest.raises(RankStrategyError) as exc_info:
        verify_decision_artifact(tampered)

    assert exc_info.value.code == "RANK_ARTIFACT_DECISION_MISMATCH"


def test_noncanonical_sidecar_fails_closed(tmp_path: Path) -> None:
    artifact = seal_decision_artifact(service_request())
    path = persist_decision_artifact(artifact, artifact_root=tmp_path)
    path.with_suffix(".sha256").write_text(f"{path.stem} wrong-name.json\n", encoding="ascii")

    with pytest.raises(RankStrategyError) as exc_info:
        load_decision_artifact(path)

    assert "SIDECAR" in exc_info.value.code


def test_resealing_same_artifact_is_idempotent(tmp_path: Path) -> None:
    artifact = seal_decision_artifact(service_request())

    first = persist_decision_artifact(artifact, artifact_root=tmp_path)
    second = persist_decision_artifact(artifact, artifact_root=tmp_path)

    assert first == second
    assert first.read_bytes() == canonical_json_bytes(artifact)


def _assert_artifact_guard(
    artifact: Stage15DecisionArtifact,
    match: str,
    **updates: object,
) -> None:
    mutated = artifact.model_copy(update={**updates, "artifact_hash": "0" * 64})
    with pytest.raises(ValueError, match=match):
        mutated.artifact_is_coherent()


def test_artifact_contract_rejects_cross_lineage_and_identity_mismatches() -> None:
    artifact = seal_decision_artifact(service_request())
    _assert_artifact_guard(
        artifact,
        "issue time differs",
        issued_at=artifact.issued_at.replace(hour=artifact.issued_at.hour - 1),
    )
    _assert_artifact_guard(
        artifact,
        "result is not bound to its request",
        service_result=artifact.service_result.model_copy(update={"request_hash": "f" * 64}),
    )
    _assert_artifact_guard(
        artifact,
        "raw projection lineage differs",
        service_result=artifact.service_result.model_copy(update={"raw_projection_hash": "f" * 64}),
    )
    _assert_artifact_guard(
        artifact,
        "scenario lineage differs",
        service_result=artifact.service_result.model_copy(update={"scenario_set_hash": "f" * 64}),
    )
    _assert_artifact_guard(
        artifact,
        "identity is not deterministic",
        artifact_id="different-artifact",
    )
    with pytest.raises(ValueError, match="semantic hash mismatch"):
        artifact.model_copy(update={"artifact_hash": "f" * 64}).artifact_is_coherent()
