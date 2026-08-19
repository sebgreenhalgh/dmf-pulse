from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.artifacts import (
    Stage14DecisionArtifact,
    load_decision_artifact,
    persist_decision_artifact,
    seal_decision_artifact,
    verify_decision_artifact,
)
from dmf_pulse.chips.definitions import semantic_sha256
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.evaluation.artifacts import canonical_json_bytes, sha256_bytes
from tests.support.stage14_chip_fixtures import service_request


def test_decision_artifact_round_trip_is_content_addressed_and_idempotent(
    tmp_path: Path,
) -> None:
    artifact = seal_decision_artifact(service_request())

    first = persist_decision_artifact(artifact, artifact_root=tmp_path)
    second = persist_decision_artifact(artifact, artifact_root=tmp_path)
    loaded = load_decision_artifact(first)

    assert first == second
    assert first.stem == sha256_bytes(first.read_bytes())
    assert first.relative_to(tmp_path).parts[:2] == ("evaluation", "chips")
    assert loaded == artifact
    assert loaded.artifact_hash == seal_decision_artifact(service_request()).artifact_hash


def test_artifact_detached_hash_rejects_byte_tampering(tmp_path: Path) -> None:
    artifact = seal_decision_artifact(service_request())
    path = persist_decision_artifact(artifact, artifact_root=tmp_path)
    path.write_bytes(path.read_bytes().replace(b'"USE"', b'"HOLD"', 1))

    with pytest.raises(ChipError) as exc_info:
        load_decision_artifact(path)

    assert exc_info.value.code == "CHIP_ARTIFACT_HASH_MISMATCH"


def _recompute_hash(payload: dict[str, object], field: str) -> str:
    semantic = dict(payload)
    semantic.pop(field, None)
    return semantic_sha256(semantic)


def test_artifact_recomputation_rejects_resealed_scheduler_diagnostic_tampering(
    tmp_path: Path,
) -> None:
    """An attacker cannot make changed diagnostics executable by updating envelopes."""

    artifact = seal_decision_artifact(service_request())
    raw = artifact.model_dump(mode="json")
    policy = raw["decision_set"]["schedule_policy"]
    policy["diagnostics"]["explored_states"] += 1
    policy["policy_hash"] = _recompute_hash(policy, "policy_hash")
    decision = raw["decision_set"]["decision"]
    decision["schedule_policy_hash"] = policy["policy_hash"]
    decision["decision_hash"] = _recompute_hash(decision, "decision_hash")
    decision_set = raw["decision_set"]
    decision_set["decision_set_hash"] = _recompute_hash(decision_set, "decision_set_hash")
    raw["artifact_hash"] = _recompute_hash(raw, "artifact_hash")

    value = Stage14DecisionArtifact.model_validate(raw)
    data = canonical_json_bytes(value)
    digest = sha256_bytes(data)
    path = tmp_path / f"{digest}.json"
    path.write_bytes(data)
    path.with_suffix(".sha256").write_bytes(f"{digest}  {path.name}\n".encode("ascii"))

    with pytest.raises(ChipError) as exc_info:
        load_decision_artifact(path)

    assert exc_info.value.code == "CHIP_ARTIFACT_DECISION_MISMATCH"


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("service_request", "manager_state_hash"), "8" * 64),
        (("service_request", "chip_bundle", "ruleset_hash"), "8" * 64),
        (("service_request", "inventory", "inventory_hash"), "8" * 64),
        (("service_request", "schedule_request", "scenario_set_hash"), "8" * 64),
        (
            ("service_request", "continuation_configuration_hash"),
            "8" * 64,
        ),
        (("service_request", "information_cutoff"), "2026-08-18T12:00:00Z"),
        (("decision_set", "lineage", "code_commit"), "deadbee"),
    ],
)
def test_artifact_contract_rejects_lineage_and_hash_relationship_tampering(
    path: tuple[str, ...],
    replacement: str,
) -> None:
    raw = seal_decision_artifact(service_request()).model_dump(mode="python")
    cursor: dict[str, object] = raw
    for key in path[:-1]:
        cursor = cursor[key]  # type: ignore[assignment]
    cursor[path[-1]] = replacement

    with pytest.raises((ValueError, ChipError)):
        value = Stage14DecisionArtifact.model_validate(raw)
        verify_decision_artifact(value)


def test_artifact_envelope_rejects_every_cross_contract_mismatch() -> None:
    artifact = seal_decision_artifact(service_request())
    base = artifact.model_dump(mode="python")

    cases: list[tuple[dict[str, object], str]] = []
    payload = artifact.model_dump(mode="python")
    payload["issued_at"] = artifact.issued_at.replace(microsecond=1)
    payload["artifact_hash"] = "0" * 64
    cases.append((payload, "issue time differs"))

    other = seal_decision_artifact(service_request(current_values={"TRIPLE_CAPTAIN": (2.0, 2.0)}))
    payload = dict(
        base,
        decision_set=other.decision_set,
        artifact_hash="0" * 64,
    )
    cases.append((payload, "decision is not bound"))

    payload = artifact.model_dump(mode="python")
    lineage = payload["decision_set"]["lineage"]
    lineage["information_cutoff"] = artifact.service_request.information_cutoff - timedelta(
        seconds=1
    )
    lineage["lineage_hash"] = "0" * 64
    payload["decision_set"]["decision_set_hash"] = "0" * 64
    payload["artifact_hash"] = "0" * 64
    cases.append((payload, "lineage cutoff differs"))

    cases.extend(
        (
            (dict(base, artifact_id="forged", artifact_hash="0" * 64), "identity"),
            (dict(base, artifact_hash="f" * 64), "semantic hash mismatch"),
        )
    )
    for payload, match in cases:
        with pytest.raises(ValidationError, match=match):
            Stage14DecisionArtifact.model_validate(payload)
