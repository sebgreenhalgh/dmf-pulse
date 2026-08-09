"""Focused MIN-007B validation and cutoff contract tests."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from dmf_pulse.availability.dataset import build_training_dataset, semantic_dataset_hash
from dmf_pulse.availability.models import DatasetValidationError, HistoryRow

pytestmark = pytest.mark.unit

TRAINING_CUTOFF = "2026-06-08T17:00:00Z"


@pytest.fixture(scope="module")
def history(repository_root: Path) -> dict[str, object]:
    return json.loads(
        (repository_root / "fixtures/availability/MIN-007/canonical_history.json").read_text(
            encoding="utf-8"
        )
    )


def test_frozen_dataset_has_exact_rows_and_semantic_hash(
    repository_root: Path, history: dict[str, object]
) -> None:
    expected = json.loads(
        (repository_root / "fixtures/availability/MIN-007/training_dataset.json").read_text(
            encoding="utf-8"
        )
    )
    dataset = build_training_dataset(history, training_cutoff=TRAINING_CUTOFF)
    assert dataset.model_dump(mode="json") == expected
    assert len(dataset.rows) == 368
    assert semantic_dataset_hash(dataset) == (
        "1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3"
    )


def test_builder_is_idempotent_and_does_not_mutate_history(
    history: dict[str, object],
) -> None:
    original = copy.deepcopy(history)
    first = build_training_dataset(history, training_cutoff=TRAINING_CUTOFF)
    second = build_training_dataset(history, training_cutoff=TRAINING_CUTOFF)
    assert first == second
    assert history == original


@pytest.mark.parametrize(
    ("case_id", "mutation"),
    (
        ("missing_role_label", {"remove": "role_label"}),
        ("invalid_role_label", {"set": {"role_label": "UNKNOWN_ROLE"}}),
        ("minutes_above_90", {"set": {"minutes_label": 91}}),
        ("minutes_below_zero", {"set": {"minutes_label": -1}}),
        ("out_with_positive_minutes", {"set": {"minutes_label": 15, "role_label": "OUT"}}),
        ("start_with_zero_minutes", {"set": {"minutes_label": 0, "role_label": "START"}}),
    ),
)
def test_invalid_role_and_minutes_cases_fail_closed(
    history: dict[str, object], case_id: str, mutation: dict[str, object]
) -> None:
    rows = copy.deepcopy(history["rows"])
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    if "remove" in mutation:
        row.pop(str(mutation["remove"]))
    else:
        updates = mutation["set"]
        assert isinstance(updates, dict)
        row.update(updates)
    with pytest.raises(DatasetValidationError, match="invalid row"):
        build_training_dataset({"rows": rows}, training_cutoff=TRAINING_CUTOFF)
    assert case_id


def test_future_label_and_eval_rows_are_excluded_even_when_timestamp_is_early(
    history: dict[str, object],
) -> None:
    rows = copy.deepcopy(history["rows"])
    assert isinstance(rows, list)
    future = copy.deepcopy(rows[0])
    assert isinstance(future, dict)
    future["label_usable_at"] = "2026-06-08T17:00:01Z"
    evaluation = copy.deepcopy(rows[1])
    assert isinstance(evaluation, dict)
    evaluation["split"] = "EVAL"
    evaluation["label_usable_at"] = "2026-06-08T16:59:59Z"
    baseline = build_training_dataset(history, training_cutoff=TRAINING_CUTOFF)
    changed = build_training_dataset(
        {"rows": [future, evaluation, *rows[2:]]}, training_cutoff=TRAINING_CUTOFF
    )
    assert len(changed.rows) == len(baseline.rows) - 2
    assert str(future["example_id"]) not in {str(row.example_id) for row in changed.rows}
    assert str(evaluation["example_id"]) not in {str(row.example_id) for row in changed.rows}


def test_label_exactly_at_cutoff_is_included(history: dict[str, object]) -> None:
    dataset = build_training_dataset(history, training_cutoff=TRAINING_CUTOFF)
    assert (
        sum(row.label_usable_at == datetime(2026, 6, 8, 17, tzinfo=UTC) for row in dataset.rows)
        == 46
    )


def test_duplicate_example_and_player_fixture_targets_are_rejected(
    history: dict[str, object],
) -> None:
    rows = copy.deepcopy(history["rows"])
    assert isinstance(rows, list)
    duplicate_example = copy.deepcopy(rows)
    duplicate_example.append(copy.deepcopy(rows[0]))
    with pytest.raises(DatasetValidationError, match="duplicate example_id"):
        build_training_dataset({"rows": duplicate_example}, training_cutoff=TRAINING_CUTOFF)

    duplicate_target = copy.deepcopy(rows)
    target_copy = copy.deepcopy(rows[1])
    assert isinstance(target_copy, dict)
    target_copy["example_id"] = str(uuid4())
    duplicate_target.append(target_copy)
    with pytest.raises(DatasetValidationError, match="duplicate player-fixture target"):
        build_training_dataset({"rows": duplicate_target}, training_cutoff=TRAINING_CUTOFF)


@pytest.mark.parametrize(
    "timestamp",
    ("2026-06-08T17:00:00", "2026-06-08T18:00:00+01:00"),
)
def test_naive_and_non_utc_cutoffs_are_rejected(history: dict[str, object], timestamp: str) -> None:
    with pytest.raises((DatasetValidationError, ValueError)):
        build_training_dataset(history, training_cutoff=timestamp)


def test_history_row_is_strict_and_explicit() -> None:
    with pytest.raises(ValidationError):
        HistoryRow.model_validate({"role_label": "START"})
