from __future__ import annotations

import json
from pathlib import Path

from dmf_pulse.availability.pipeline import (
    fit_projection_artifact,
    predict_minutes_baseline,
    summarize_prediction_for_oracle,
)


def test_stable_and_blocked_canaries(repository_root: Path) -> None:
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
    expected_path = root / "fixtures/availability/MIN-007G/prediction_registry.json"
    expected = json.loads(expected_path.read_text())
    artifact = fit_projection_artifact(training, policy=policy)
    for name in ("stable_xi", "insufficient_eligible_squad"):
        context = json.loads(
            (root / f"fixtures/availability/MIN-007G/contexts/{name}.json").read_text()
        )
        result = predict_minutes_baseline(history, artifact, context=context, policy=policy)
        assert summarize_prediction_for_oracle(result, context) == expected[name]
