from __future__ import annotations

import json
from pathlib import Path

from dmf_pulse.availability.pipeline import evaluate_minutes_baseline, fit_projection_artifact


def test_evaluation_hash(repository_root: Path) -> None:
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
    evaluation = json.loads(
        (root / "fixtures/availability/MIN-007G/evaluation_dataset.json").read_text()
    )
    result = evaluate_minutes_baseline(
        history, fit_projection_artifact(training, policy=policy), evaluation, policy=policy
    )
    assert (
        result.evaluation_sha256
        == "f2d075a9497331b73bf896be4610b684f8a3ed41eb17248a27284c79556cd748"
    )
