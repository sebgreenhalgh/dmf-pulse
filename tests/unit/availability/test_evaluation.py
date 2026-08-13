from __future__ import annotations

import json
from pathlib import Path

from dmf_pulse.availability.pipeline import (
    evaluate_minutes_baseline,
    fit_projection_artifact,
)


def _read(root: Path, relative: str) -> dict[str, object]:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def test_frozen_evaluation(repository_root: Path) -> None:
    history = _read(repository_root, "fixtures/availability/MIN-007/canonical_history.json")
    training = _read(repository_root, "fixtures/availability/MIN-007/training_dataset.json")
    policy = _read(repository_root, "fixtures/availability/MIN-007G/minutes_baseline_policy.json")
    evaluation = _read(repository_root, "fixtures/availability/MIN-007G/evaluation_dataset.json")
    result = evaluate_minutes_baseline(
        history, fit_projection_artifact(training, policy=policy), evaluation, policy=policy
    )
    assert (
        result.evaluation_sha256
        == "f2d075a9497331b73bf896be4610b684f8a3ed41eb17248a27284c79556cd748"
    )
    assert result.n_examples == 92
