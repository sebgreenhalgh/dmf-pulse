"""Property proofs for MIN-007B deterministic dataset identity."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.availability.dataset import build_training_dataset, semantic_dataset_hash

pytestmark = pytest.mark.property

TRAINING_CUTOFF = "2026-06-08T17:00:00Z"


@pytest.fixture(scope="module")
def history(repository_root: Path) -> dict[str, object]:
    return json.loads(
        (repository_root / "fixtures/availability/MIN-007/canonical_history.json").read_text(
            encoding="utf-8"
        )
    )


@settings(max_examples=12)
@given(st.permutations(tuple(range(40))))
def test_input_row_permutation_does_not_change_dataset(
    history: dict[str, object], permutation: tuple[int, ...]
) -> None:
    rows = history["rows"]
    assert isinstance(rows, list)
    shuffled = copy.deepcopy(history)
    shuffled["rows"] = [rows[index] for index in permutation] + rows[40:]
    expected = build_training_dataset(history, training_cutoff=TRAINING_CUTOFF)
    actual = build_training_dataset(shuffled, training_cutoff=TRAINING_CUTOFF)
    assert actual == expected
    assert semantic_dataset_hash(actual) == semantic_dataset_hash(expected)


@settings(max_examples=12)
@given(st.permutations(("rows", "schema_version", "training_cutoff")))
def test_semantic_hash_ignores_mapping_key_insertion_order(
    repository_root: Path, key_order: tuple[str, ...]
) -> None:
    expected = json.loads(
        (repository_root / "fixtures/availability/MIN-007/training_dataset.json").read_text(
            encoding="utf-8"
        )
    )
    reordered = {key: expected[key] for key in key_order}
    assert semantic_dataset_hash(reordered) == (
        "1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3"
    )
