"""Recompute frozen Stage-7 identities from production functions and fixtures."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from dmf_pulse.availability.dataset import semantic_dataset_hash
from dmf_pulse.availability.minutes import fit_minute_priors
from dmf_pulse.availability.pipeline import (
    evaluate_minutes_baseline,
    fit_projection_artifact,
    predict_minutes_baseline,
)
from dmf_pulse.availability.registry import (
    canonical_semantic_sha256,
    dataset_version_semantic_sha256,
    model_version_semantic_sha256,
    prediction_input_signature_sha256,
)
from dmf_pulse.availability.role_model import FROZEN_POLICY_SHA256, fit_role_baseline

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence/tickets/MIN-007H"
EXPECTED = {
    "B_dataset": "1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3",
    "C_role": "baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96",
    "D_minutes": "8e0b410e37d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422",
    "E_stable_scenario": "60afa72dbc0340615e2786783ec56186ce1a2e11a497aa4f872a9b0890bc10ee",
    "F_dataset_registry": "5c76f5a41d9926dc0e4f0e15e2100c103d85768893c4ad8b52fe69a44d365da1",
    "F_model_registry": "724eecb596b09074b4014d82ec8d0831c4580751af1ad8cb3991f4704f553e9c",
    "F_prediction_signature": "5662bdec99552813e54453726c9ffdb30ef23365dab8548e78132a2c9d397ed6",
    "G_model_artifact": "80d1aa4cfd4a80eb7f7b291899fd9cf6173b017e308ea3b41d450a7bc87e2aeb",
    "G_evaluation": "f2d075a9497331b73bf896be4610b684f8a3ed41eb17248a27284c79556cd748",
    "G_prediction_registry": "895a7e2a870192ba3ab395d459235f5ed374a562acd5628121de30f8e8ea4c72",
    "current_probability_schema": "6a0dcfb79f5e8939dd54f889b61236783d8c4e05a4bd0272eae25599c2373f9b",
    "historical_nrm_probability_schema": "b2900cdbdb3c6d5dd4300eaa14508c8eb09852dc917d7fa95b5df15cfcba63df",
    "mapping_plan": "490585bed1bce6f9d904ddb12b6df6b6a4d04caca91fb1160af53e83578a3550",
}


def read(relative: str) -> dict[str, Any]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def registry_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    dataset = {
        "schema_version": "minutes-dataset-version-v1",
        "dataset_key": "min007-synthetic-train-v1",
        "competition_code": "SYNTH_EPL",
        "season_code": "2026/27",
        "training_cutoff": "2026-06-08T17:00:00Z",
        "dataset_sha256": EXPECTED["B_dataset"],
        "policy_sha256": FROZEN_POLICY_SHA256,
        "training_example_count": 368,
    }
    model = {
        "schema_version": "minutes-model-version-v1",
        "model_key": "min007-baseline-v1",
        "dataset_version_sha256": EXPECTED["F_dataset_registry"],
        "role_artifact_sha256": EXPECTED["C_role"],
        "minute_artifact_sha256": EXPECTED["D_minutes"],
        "policy_sha256": FROZEN_POLICY_SHA256,
        "model_family": "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
        "code_identity": "MIN-007F-SYNTHETIC-CODE-V1",
    }
    signature = {
        "schema_version": "minutes-prediction-signature-v1",
        "fixture_id": "943094f5-1d10-5d96-b88b-d271464f3e48",
        "team_id": "cc1083fa-0c4a-59ab-b6c5-60c04f760782",
        "as_of": "2026-08-14T17:30:00Z",
        "model_version_sha256": EXPECTED["F_model_registry"],
        "dataset_version_sha256": EXPECTED["F_dataset_registry"],
        "policy_sha256": FROZEN_POLICY_SHA256,
        "source_dependencies": [
            {
                "dependency_type": "CANONICAL_HISTORY",
                "dependency_key": "min007-canonical-history-v1",
                "semantic_sha256": "016408fb52b88faef42afed9f678900fc97847a6fbea18c457fb69cab17cc138",
            },
            {
                "dependency_type": "EXTERNAL_MAPPING_PLAN",
                "dependency_key": "synthetic_availability",
                "semantic_sha256": "d0a26d4a688847098ac3de5f5f9219b2cc105dcc567ccbe2c5f5b4b8ae8c5753",
            },
            {
                "dependency_type": "PREDICTION_CONTEXT",
                "dependency_key": "stable_xi",
                "semantic_sha256": "88ce923fe3e6a749497595d8c3ec36415dda897e222dbf47510cb8c8b81da174",
            },
        ],
        "hard_eligibility": [],
        "manager_context": {
            "manager_regime_id": "b9d90a34-4a83-5f26-9ba2-b17e99883bd5",
            "current_manager_team_lineups": 8,
            "new_manager": False,
            "promoted_team": False,
            "target_league_team_lineups": 8,
        },
        "seed": "MIN-007-COHERENCE-V1",
        "sample_count": 256,
        "bench_size": 9,
        "bench_goalkeeper_slots": 1,
        "code_identity": "MIN-007F-SYNTHETIC-CODE-V1",
    }
    return dataset, model, signature


def main() -> int:
    training = read("fixtures/availability/MIN-007/training_dataset.json")
    history = read("fixtures/availability/MIN-007/canonical_history.json")
    policy = read("fixtures/availability/MIN-007G/minutes_baseline_policy.json")
    context = read("fixtures/availability/MIN-007G/contexts/stable_xi.json")
    eval_data = read("fixtures/availability/MIN-007G/evaluation_dataset.json")
    registry = read("fixtures/availability/MIN-007G/prediction_registry.json")
    role = fit_role_baseline(training, policy=policy)
    minute = fit_minute_priors(training, policy=policy)
    artifact = fit_projection_artifact(training, policy=policy)
    prediction = predict_minutes_baseline(history, artifact, context=context, policy=policy)
    evaluation = evaluate_minutes_baseline(history, artifact, eval_data, policy=policy)
    dataset, model, signature = registry_inputs()
    observed = {
        "B_dataset": semantic_dataset_hash(training),
        "C_role": role.artifact_sha256,
        "D_minutes": minute.artifact_sha256,
        "E_stable_scenario": prediction.projection.scenario_set_sha256
        if prediction.projection
        else "BLOCKED",
        "F_dataset_registry": dataset_version_semantic_sha256(dataset),
        "F_model_registry": model_version_semantic_sha256(model),
        "F_prediction_signature": prediction_input_signature_sha256(signature),
        "G_model_artifact": artifact.artifact_sha256,
        "G_evaluation": evaluation.evaluation_sha256,
        "G_prediction_registry": canonical_semantic_sha256(registry),
        "current_probability_schema": sha("public_contracts/probability.schema.json"),
        "historical_nrm_probability_schema": sha(
            "evidence/tickets/NRM-006/frozen_public_contracts/probability.schema.json"
        ),
        "mapping_plan": sha("fixtures/availability/MIN-007/external_mapping_plan.json"),
    }
    changed = copy.deepcopy(dataset)
    changed["dataset_key"] = "semantic-mutation"
    neutral = copy.deepcopy(dataset)
    neutral["runtime_metadata"] = {"ignored": True}
    self_tests = {
        "semantic_leaf_changes_identity": dataset_version_semantic_sha256(changed)
        != dataset_version_semantic_sha256(dataset),
        "runtime_metadata_is_neutral": dataset_version_semantic_sha256(neutral)
        == dataset_version_semantic_sha256(dataset),
    }
    sources = {name: ["fixtures/availability/MIN-007/training_dataset.json"] for name in EXPECTED}
    sources["C_role"] += ["fixtures/availability/MIN-007G/minutes_baseline_policy.json"]
    sources["D_minutes"] += ["fixtures/availability/MIN-007G/minutes_baseline_policy.json"]
    sources["E_stable_scenario"] = [
        "fixtures/availability/MIN-007/canonical_history.json",
        "fixtures/availability/MIN-007G/contexts/stable_xi.json",
    ]
    sources["G_evaluation"] = [
        "fixtures/availability/MIN-007G/evaluation_dataset.json",
        "src/dmf_pulse/availability/pipeline.py",
    ]
    sources["G_prediction_registry"] = ["fixtures/availability/MIN-007G/prediction_registry.json"]
    sources["current_probability_schema"] = ["public_contracts/probability.schema.json"]
    sources["historical_nrm_probability_schema"] = [
        "evidence/tickets/NRM-006/frozen_public_contracts/probability.schema.json"
    ]
    sources["mapping_plan"] = ["fixtures/availability/MIN-007/external_mapping_plan.json"]
    identities = {
        name: {
            "expected": expected,
            "observed": observed[name],
            "method": "production canonical semantic function or SHA-256 over the specified fixture bytes",
            "source_paths": sources[name],
            "derived": observed[name] == expected,
            "status": "PASS" if observed[name] == expected else "FAIL",
        }
        for name, expected in EXPECTED.items()
    }
    report = {
        "status": "PASS"
        if all(item["status"] == "PASS" for item in identities.values())
        and all(self_tests.values())
        else "FAIL",
        "identities": identities,
        "mutation_self_tests": self_tests,
    }
    (EVIDENCE / "frozen_identity_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if report["status"] != "PASS":
        raise SystemExit("frozen identity mismatch")
    print("PASS: recomputed frozen identities and mutation self-tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
