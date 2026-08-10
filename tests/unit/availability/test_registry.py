from __future__ import annotations

from dmf_pulse.availability.registry import (
    canonical_semantic_sha256,
    dataset_version_semantic_sha256,
    model_version_semantic_sha256,
    prediction_input_signature_sha256,
)


def test_canonical_semantic_hash_is_order_independent() -> None:
    left = {"b": [1, "é"], "a": {"z": True, "n": None}}
    right = {"a": {"n": None, "z": True}, "b": [1, "é"]}
    assert canonical_semantic_sha256(left) == canonical_semantic_sha256(right)


def test_registry_canary_hashes() -> None:
    dataset = {
        "schema_version": "minutes-dataset-version-v1",
        "dataset_key": "min007-synthetic-train-v1",
        "competition_code": "SYNTH_EPL",
        "season_code": "2026/27",
        "training_cutoff": "2026-06-08T17:00:00Z",
        "dataset_sha256": "1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3",
        "policy_sha256": "d54afbb27f4ea2512801e1e8588c8c6c4454388c824dacd00f18fecdb35c6994",
        "training_example_count": 368,
    }
    model = {
        "schema_version": "minutes-model-version-v1",
        "model_key": "min007-baseline-v1",
        "dataset_version_sha256": "5c76f5a41d9926dc0e4f0e15e2100c103d85768893c4ad8b52fe69a44d365da1",
        "role_artifact_sha256": "baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96",
        "minute_artifact_sha256": "8e0b410e37d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422",
        "policy_sha256": "d54afbb27f4ea2512801e1e8588c8c6c4454388c824dacd00f18fecdb35c6994",
        "model_family": "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
        "code_identity": "MIN-007F-SYNTHETIC-CODE-V1",
    }
    prediction = {
        "schema_version": "minutes-prediction-signature-v1",
        "fixture_id": "943094f5-1d10-5d96-b88b-d271464f3e48",
        "team_id": "cc1083fa-0c4a-59ab-b6c5-60c04f760782",
        "as_of": "2026-08-14T17:30:00Z",
        "model_version_sha256": "724eecb596b09074b4014d82ec8d0831c4580751af1ad8cb3991f4704f553e9c",
        "dataset_version_sha256": "5c76f5a41d9926dc0e4f0e15e2100c103d85768893c4ad8b52fe69a44d365da1",
        "policy_sha256": "d54afbb27f4ea2512801e1e8588c8c6c4454388c824dacd00f18fecdb35c6994",
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
    assert (
        dataset_version_semantic_sha256(dataset)
        == "5c76f5a41d9926dc0e4f0e15e2100c103d85768893c4ad8b52fe69a44d365da1"
    )
    assert (
        model_version_semantic_sha256(model)
        == "724eecb596b09074b4014d82ec8d0831c4580751af1ad8cb3991f4704f553e9c"
    )
    assert (
        prediction_input_signature_sha256(prediction)
        == "5662bdec99552813e54453726c9ffdb30ef23365dab8548e78132a2c9d397ed6"
    )


def test_non_finite_values_are_rejected() -> None:
    try:
        canonical_semantic_sha256({"value": float("nan")})
    except ValueError:
        pass
    else:  # pragma: no cover - assertion branch
        raise AssertionError("non-finite semantic values must be rejected")
