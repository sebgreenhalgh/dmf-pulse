"""Determinism and cutoff/team/window properties for MIN-007C."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.availability.role_model import fit_role_baseline, predict_role_utilities

pytestmark = pytest.mark.property


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def training(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007/training_dataset.json")
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def policy(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007C/minutes_baseline_policy.json")
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def history(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007/canonical_history.json")
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def stable_context(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007C/role_canaries.json")
    assert isinstance(value, dict)
    return next(item for item in value["cases"] if item["scenario"] == "stable_xi")


@settings(max_examples=8, deadline=None)
@given(st.permutations(tuple(range(60))))
def test_training_row_order_does_not_change_artifact(
    training: dict[str, object], policy: dict[str, object], permutation: tuple[int, ...]
) -> None:
    rows = training["rows"]
    assert isinstance(rows, list)
    shuffled = copy.deepcopy(training)
    shuffled["rows"] = [rows[index] for index in permutation] + rows[60:]
    assert fit_role_baseline(shuffled, policy=policy) == fit_role_baseline(training, policy=policy)


@settings(max_examples=6, deadline=None)
@given(st.permutations(("rows", "schema_version", "training_cutoff")))
def test_training_and_policy_key_order_does_not_change_artifact(
    training: dict[str, object], policy: dict[str, object], key_order: tuple[str, ...]
) -> None:
    reordered_training = {key: training[key] for key in key_order}
    reordered_training["rows"] = [
        {key: row[key] for key in reversed(tuple(row))} for row in training["rows"]
    ]
    reordered_policy = {key: policy[key] for key in reversed(tuple(policy))}
    assert fit_role_baseline(reordered_training, policy=reordered_policy) == fit_role_baseline(
        training, policy=policy
    )


def test_repeated_prediction_does_not_mutate_inputs(
    history: dict[str, object],
    stable_context: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_role_baseline(training, policy=policy)
    original_history = copy.deepcopy(history)
    original_context = copy.deepcopy(stable_context)
    first = predict_role_utilities(
        history,
        artifact,
        context=stable_context,
        player_key=stable_context["focus_player_key"],
        policy=policy,
    )
    second = predict_role_utilities(
        history,
        artifact,
        context=stable_context,
        player_key=stable_context["focus_player_key"],
        policy=policy,
    )
    assert first == second
    assert history == original_history
    assert stable_context == original_context
