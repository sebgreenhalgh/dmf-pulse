from __future__ import annotations

import json
from pathlib import Path

from dmf_pulse.availability.pipeline import (
    fit_projection_artifact,
    predict_minutes_baseline,
)


def test_all_nine_registry_contexts_are_typed(repository_root: Path) -> None:
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
    artifact = fit_projection_artifact(training, policy=policy)
    statuses = []
    for path in sorted((root / "fixtures/availability/MIN-007G/contexts").glob("*.json")):
        context = json.loads(path.read_text())
        statuses.append(
            predict_minutes_baseline(history, artifact, context=context, policy=policy).status
        )
    assert statuses.count("PROJECTED") == 8
    assert statuses.count("BLOCKED") == 1
