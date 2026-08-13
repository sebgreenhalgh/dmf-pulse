from __future__ import annotations

from copy import deepcopy

from dmf_pulse.availability.registry import (
    dataset_version_semantic_sha256,
    model_version_semantic_sha256,
    prediction_input_signature_sha256,
)


def _prediction() -> dict[str, object]:
    return {
        "schema_version": "minutes-prediction-signature-v1",
        "fixture_id": "943094f5-1d10-5d96-b88b-d271464f3e48",
        "team_id": "cc1083fa-0c4a-59ab-b6c5-60c04f760782",
        "as_of": "2026-08-14T17:30:00Z",
        "model_version_sha256": "7" * 64,
        "dataset_version_sha256": "8" * 64,
        "policy_sha256": "9" * 64,
        "source_dependencies": [
            {
                "dependency_type": "CONTEXT",
                "dependency_key": "stable",
                "semantic_sha256": "a" * 64,
                "created_at": "ignored",
            }
        ],
        "hard_eligibility": [
            {"player_id": "player-1", "reason": "BLOCKED", "hard_ineligible": True, "id": "ignored"}
        ],
        "manager_context": {
            "manager_regime_id": "manager",
            "new_manager": False,
            "request_id": "ignored",
        },
        "seed": "seed",
        "sample_count": 1,
        "bench_size": 9,
        "bench_goalkeeper_slots": 1,
        "code_identity": "code",
        "prediction_run_id": "ignored",
        "created_at": "ignored",
    }


def test_typed_hashes_ignore_unknown_nested_runtime_metadata() -> None:
    value = _prediction()
    baseline = prediction_input_signature_sha256(value)
    changed = deepcopy(value)
    changed["request_id"] = "ignored"
    changed["source_dependencies"][0]["updated_at"] = "ignored"  # type: ignore[index]
    changed["manager_context"]["trace_id"] = "ignored"  # type: ignore[index]
    assert prediction_input_signature_sha256(changed) == baseline


def test_typed_hashes_change_for_each_allowed_leaf() -> None:
    value = _prediction()
    baseline = prediction_input_signature_sha256(value)
    for field in (
        "schema_version",
        "fixture_id",
        "team_id",
        "as_of",
        "model_version_sha256",
        "dataset_version_sha256",
        "policy_sha256",
        "seed",
        "sample_count",
        "bench_size",
        "bench_goalkeeper_slots",
        "code_identity",
    ):
        changed = deepcopy(value)
        changed[field] = "changed" if isinstance(value[field], str) else int(value[field]) + 1
        assert prediction_input_signature_sha256(changed) != baseline, field


def test_generic_helper_remains_distinct_from_typed_allowlists() -> None:
    dataset = {"schema_version": "v1", "dataset_key": "d", "runtime": "ignored"}
    assert dataset_version_semantic_sha256(dataset) == dataset_version_semantic_sha256(
        {"schema_version": "v1", "dataset_key": "d"}
    )
    model = {"schema_version": "v1", "model_key": "m", "runtime": "ignored"}
    assert model_version_semantic_sha256(model) == model_version_semantic_sha256(
        {"schema_version": "v1", "model_key": "m"}
    )
