from __future__ import annotations

import json
from pathlib import Path

from dmf_pulse.availability.pipeline import fit_projection_artifact
from tests.contract.markets._draft2020 import validate_instance


def _schemas(root: Path) -> dict[str, dict[str, object]]:
    directory = root / "public_contracts/min007g"
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("*.schema.json")
    }


def test_artifact_schema_and_hash(repository_root: Path) -> None:
    root = repository_root
    training = json.loads(
        (root / "fixtures/availability/MIN-007/training_dataset.json").read_text()
    )
    policy = json.loads(
        (root / "fixtures/availability/MIN-007G/minutes_baseline_policy.json").read_text()
    )
    artifact = fit_projection_artifact(training, policy=policy)
    schemas = _schemas(root)
    validate_instance(
        artifact.model_dump(mode="json"),
        schemas["minutes_model_artifact.schema.json"],
        registry=schemas,
    )


def test_schema_directory_contains_all_g_contracts(repository_root: Path) -> None:
    names = {
        path.name for path in (repository_root / "public_contracts/min007g").glob("*.schema.json")
    }
    assert names == {
        "lineup_scenario.schema.json",
        "minutes_model_artifact.schema.json",
        "minutes_model_evaluation.schema.json",
        "minutes_prediction_result.schema.json",
        "player_minutes_projection.schema.json",
        "probability.schema.json",
        "team_minutes_projection.schema.json",
    }
