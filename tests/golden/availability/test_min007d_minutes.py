"""Golden checks for the frozen MIN-007D minute-prior artifact."""

from __future__ import annotations

import json
from pathlib import Path

from dmf_pulse.availability.minutes import MINUTE_ARTIFACT_SHA256, fit_minute_priors


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_frozen_minute_artifact(repository_root: Path) -> None:
    training = _read(repository_root / "fixtures/availability/MIN-007/training_dataset.json")
    policy = _read(repository_root / "fixtures/availability/MIN-007C/minutes_baseline_policy.json")
    assert isinstance(training, dict) and isinstance(policy, dict)
    artifact = fit_minute_priors(training, policy=policy)
    assert artifact.artifact_sha256 == MINUTE_ARTIFACT_SHA256
    assert artifact.model_dump(mode="json")["schema_version"] == "minute-prior-artifact-v1"


def test_prior_vectors_have_frozen_support(repository_root: Path) -> None:
    training = _read(repository_root / "fixtures/availability/MIN-007/training_dataset.json")
    policy = _read(repository_root / "fixtures/availability/MIN-007C/minutes_baseline_policy.json")
    assert isinstance(training, dict) and isinstance(policy, dict)
    artifact = fit_minute_priors(training, policy=policy)
    for position in ("GK", "DEF", "MID", "FWD"):
        assert artifact.minute_priors[position]["START"][0] == 0
        assert len(artifact.minute_priors[position]["BENCH"]) == 91
