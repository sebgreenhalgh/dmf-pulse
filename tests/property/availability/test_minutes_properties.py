"""Deterministic property checks for MIN-007D."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.availability.minutes import fit_minute_priors


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


@given(st.integers(min_value=0, max_value=20))
def test_fit_is_invariant_to_training_row_order(
    training: dict[str, object], policy: dict[str, object], seed: int
) -> None:
    rows = training["rows"]
    assert isinstance(rows, list)
    shuffled = copy.deepcopy(training)
    permutation = list(range(len(rows)))
    random.Random(seed).shuffle(permutation)
    shuffled["rows"] = [rows[index] for index in permutation]
    assert fit_minute_priors(shuffled, policy=policy) == fit_minute_priors(training, policy=policy)


def test_fit_is_repeatable_across_independent_copies(
    training: dict[str, object], policy: dict[str, object]
) -> None:
    first = fit_minute_priors(copy.deepcopy(training), policy=copy.deepcopy(policy))
    second_input = copy.deepcopy(training)
    random.Random(7007).shuffle(second_input["rows"])
    second = fit_minute_priors(second_input, policy=copy.deepcopy(policy))
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
