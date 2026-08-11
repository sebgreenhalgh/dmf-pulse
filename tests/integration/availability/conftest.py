from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from dmf_pulse.availability.registry import (
    dataset_version_semantic_sha256,
    model_version_semantic_sha256,
)

DATASET = {
    "schema_version": "minutes-dataset-version-v1",
    "dataset_key": "integration-dataset",
    "competition_code": "SYNTH_EPL",
    "season_code": "2026/27",
    "training_cutoff": "2026-06-08T17:00:00Z",
    "dataset_sha256": "1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3",
    "policy_sha256": "d54afbb27f4ea2512801e1e8588c8c6c4454388c824dacd00f18fecdb35c6994",
    "training_example_count": 0,
}
DATASET_HASH = dataset_version_semantic_sha256(DATASET)
MODEL = {
    "schema_version": "minutes-model-version-v1",
    "model_key": "integration-model",
    "dataset_version_sha256": DATASET_HASH,
    "role_artifact_sha256": "baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96",
    "minute_artifact_sha256": "8e0b410e37d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422",
    "policy_sha256": "d54afbb27f4ea2512801e1e8588c8c6c4454388c824dacd00f18fecdb35c6994",
    "model_family": "INTEGRATION",
    "code_identity": "MIN-007F-INTEGRATION",
}
MODEL_HASH = model_version_semantic_sha256(MODEL)
FIXTURE_ID = UUID("943094f5-1d10-5d96-b88b-d271464f3e48")
TEAM_ID = UUID("cc1083fa-0c4a-59ab-b6c5-60c04f760782")


@pytest.fixture
def dataset() -> dict[str, object]:
    return dict(DATASET)


@pytest.fixture
def model() -> dict[str, object]:
    return dict(MODEL)


@pytest.fixture
def prediction() -> dict[str, object]:
    return {
        "schema_version": "minutes-prediction-signature-v1",
        "fixture_id": str(FIXTURE_ID),
        "team_id": str(TEAM_ID),
        "as_of": "2026-08-14T17:30:00Z",
        "model_version_sha256": MODEL_HASH,
        "dataset_version_sha256": DATASET_HASH,
        "policy_sha256": DATASET["policy_sha256"],
        "source_dependencies": [
            {
                "dependency_type": "PREDICTION_CONTEXT",
                "dependency_key": "integration",
                "semantic_sha256": "88ce923fe3e6a749497595d8c3ec36415dda897e222dbf47510cb8c8b81da174",
            }
        ],
        "hard_eligibility": [],
        "manager_context": {"manager_regime_id": "integration"},
        "seed": "integration",
        "sample_count": 1,
        "bench_size": 9,
        "bench_goalkeeper_slots": 1,
        "code_identity": "MIN-007F-INTEGRATION",
    }


@pytest.fixture
def bundle_parts() -> dict[str, list[dict[str, object]]]:
    pmf = [Decimal("0")] + [Decimal("0.01")] * 89 + [Decimal("0.11")]
    members = [
        {
            "player_id": f"starter-{index}",
            "role": "START",
            "position": "GK" if index == 0 else "DEF",
        }
        for index in range(11)
    ]
    members.extend(
        {"player_id": f"bench-{index}", "role": "BENCH", "position": "GK" if index == 0 else "DEF"}
        for index in range(9)
    )
    marginals = [
        {
            "player_id": member["player_id"],
            "player_key": member["player_id"],
            "position": member["position"],
            "p_start": Decimal("0.8") if member["role"] == "START" else Decimal("0.1"),
            "p_bench": Decimal("0.1") if member["role"] == "START" else Decimal("0.8"),
            "p_out": Decimal("0.1"),
        }
        for member in members
    ]
    minute_pmfs = [
        {"player_id": member["player_id"], "role": role, "minute_pmf": pmf}
        for member in members
        for role in ("START", "BENCH")
    ]
    return {
        "role_marginals": marginals,
        "minute_pmfs": minute_pmfs,
        "scenarios": [{"scenario_index": 0, "scenario_sha256": "a" * 64, "members": members}],
    }


@pytest.fixture
def cutoff() -> datetime:
    return datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
