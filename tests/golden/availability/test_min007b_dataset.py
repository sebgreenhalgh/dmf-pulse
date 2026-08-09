"""Frozen MIN-007B source, summary and training-dataset oracle tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dmf_pulse.availability.dataset import build_training_dataset, semantic_dataset_hash

pytestmark = pytest.mark.golden

TRAINING_CUTOFF = "2026-06-08T17:00:00Z"
SOURCE_SHA256 = "23cc133b26beba0455ca50e66cbd4fca5bde8b1b38a4b946b197d53039982096"
DATASET_FILE_SHA256 = "4f8624d95517e42cf4403e0356b28f6061f4d6c525f75bfff6d7ad07b9f5a6c5"
DATASET_SEMANTIC_SHA256 = "1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3"


def test_frozen_files_and_summary_match_expected(repository_root: Path) -> None:
    root = repository_root / "fixtures/availability/MIN-007"
    source = root / "canonical_history.json"
    expected = root / "training_dataset.json"
    summary = json.loads((root / "training_dataset_summary.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA256
    assert hashlib.sha256(expected.read_bytes()).hexdigest() == DATASET_FILE_SHA256
    assert summary["source_row_count"] == 460
    assert summary["training_row_count"] == 368
    assert summary["excluded_non_train_row_count"] == 92
    assert summary["training_dataset_semantic_sha256"] == DATASET_SEMANTIC_SHA256


def test_production_builder_matches_frozen_training_dataset(repository_root: Path) -> None:
    root = repository_root / "fixtures/availability/MIN-007"
    history = json.loads((root / "canonical_history.json").read_text(encoding="utf-8"))
    expected = json.loads((root / "training_dataset.json").read_text(encoding="utf-8"))
    dataset = build_training_dataset(history, training_cutoff=TRAINING_CUTOFF)
    assert dataset.model_dump(mode="json") == expected
    assert semantic_dataset_hash(dataset) == DATASET_SEMANTIC_SHA256
    assert all(row["split"] == "TRAIN" for row in expected["rows"])
    assert len(expected["rows"]) == 368
