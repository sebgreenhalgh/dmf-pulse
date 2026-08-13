from __future__ import annotations

import json
from pathlib import Path

from dmf_pulse.availability.pipeline import fit_projection_artifact, predict_minutes_baseline


def test_prediction_is_deterministic(repository_root: Path) -> None:
    root = repository_root
    history = json.loads(
        (root / "fixtures/availability/MIN-007/canonical_history.json").read_text()
    )
    training = json.loads(
        (root / "fixtures/availability/MIN-007/training_dataset.json").read_text()
    )
    policy = json.loads(
        (root / "fixtures/availability/MIN-007G/minutes_baseline_policy.json").read_text()
    )
    context = json.loads(
        (root / "fixtures/availability/MIN-007G/contexts/stable_xi.json").read_text()
    )
    artifact = fit_projection_artifact(training, policy=policy)
    first = predict_minutes_baseline(history, artifact, context=context, policy=policy)
    second = predict_minutes_baseline(history, artifact, context=context, policy=policy)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
