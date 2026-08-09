"""Frozen MIN-007C artifact, canary and weighting oracle tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dmf_pulse.availability.role_model import fit_role_baseline, predict_role_utilities

pytestmark = pytest.mark.golden


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_frozen_role_policy_and_artifact_hashes(repository_root: Path) -> None:
    root = repository_root / "fixtures/availability/MIN-007C"
    assert hashlib.sha256(
        (
            repository_root / "fixtures/availability/MIN-007C/minutes_baseline_policy.json"
        ).read_bytes()
    ).hexdigest() == ("99faa598bf1e59a21c967d8649a911c5df2e39bbed07b3e86f53683f0ab1817f")
    assert hashlib.sha256((root / "role_artifact.json").read_bytes()).hexdigest() == (
        "5028789a467082f526d54572fe3c095025c50cf27c0717a3cefd7452e85997e0"
    )


def test_all_eight_role_canaries_match(
    repository_root: Path,
) -> None:
    root = repository_root / "fixtures/availability/MIN-007C"
    history = _read(repository_root / "fixtures/availability/MIN-007/canonical_history.json")
    policy = _read(repository_root / "fixtures/availability/MIN-007C/minutes_baseline_policy.json")
    expected_artifact = _read(root / "role_artifact.json")
    expected = _read(root / "expected_role_canaries.json")
    cases = _read(root / "role_canaries.json")
    assert isinstance(history, dict)
    assert isinstance(policy, dict)
    assert isinstance(expected_artifact, dict)
    assert isinstance(expected, dict)
    assert isinstance(cases, dict)
    artifact = fit_role_baseline(
        _read(repository_root / "fixtures/availability/MIN-007/training_dataset.json"),
        policy=policy,
    )
    assert artifact.model_dump(mode="json") == expected_artifact
    actual = {"schema_version": "role-utility-canaries-v1", "cases": {}}
    for case in cases["cases"]:
        result = predict_role_utilities(
            history,
            artifact,
            context=case,
            player_key=case["focus_player_key"],
            policy=policy,
        )
        actual["cases"][case["scenario"]] = result.model_dump(mode="json")
    assert actual == expected


def test_mixed_manager_preseason_and_other_team_weighting_canary(repository_root: Path) -> None:
    root = repository_root / "fixtures/availability/MIN-007C"
    fixture = _read(root / "role_weight_case.json")
    expected = _read(root / "expected_role_weight_case.json")
    policy = _read(repository_root / "fixtures/availability/MIN-007C/minutes_baseline_policy.json")
    assert isinstance(fixture, dict)
    assert isinstance(expected, dict)
    assert isinstance(policy, dict)
    artifact = fit_role_baseline(
        _read(repository_root / "fixtures/availability/MIN-007/training_dataset.json"),
        policy=policy,
    )
    context = fixture["context"]
    actual = predict_role_utilities(
        fixture["history"],
        artifact,
        context=context,
        player_key=context["focus_player_key"],
        policy=policy,
    )
    assert actual.model_dump(mode="json") == expected
