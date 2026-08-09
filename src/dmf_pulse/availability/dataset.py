"""Pure deterministic construction of the MIN-007B training dataset."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import ValidationError

from dmf_pulse.availability.models import (
    POSITION_RANK,
    DatasetValidationError,
    HistoryRow,
    TrainingDataset,
    parse_utc,
)

DATASET_SCHEMA_VERSION: Literal["minutes-training-dataset-v1"] = "minutes-training-dataset-v1"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _as_rows(history: object) -> tuple[HistoryRow, ...]:
    if isinstance(history, Mapping):
        raw_rows = history.get("rows")
    else:
        raw_rows = getattr(history, "rows", None)
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes, bytearray)):
        raise DatasetValidationError("history must contain a rows sequence")
    rows: list[HistoryRow] = []
    try:
        for raw_row in raw_rows:
            if isinstance(raw_row, HistoryRow):
                rows.append(raw_row)
            elif isinstance(raw_row, Mapping):
                rows.append(HistoryRow.model_validate(raw_row))
            else:
                raise DatasetValidationError("history rows must be mappings or HistoryRow models")
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, DatasetValidationError):
            raise
        raise DatasetValidationError("history contains an invalid row") from exc
    return tuple(rows)


def _canonical_row_key(row: HistoryRow) -> tuple[str, datetime, int, str, str]:
    return (
        row.team_key,
        row.feature_cutoff,
        POSITION_RANK[row.position],
        row.player_key,
        str(row.example_id),
    )


def validate_history_identities(rows: Sequence[HistoryRow]) -> None:
    """Reject duplicate immutable history identities before any filtering."""

    seen_examples: set[str] = set()
    seen_targets: set[tuple[str, str]] = set()
    for row in rows:
        example_id = str(row.example_id)
        if example_id in seen_examples:
            raise DatasetValidationError("duplicate example_id")
        seen_examples.add(example_id)
        target = (str(row.player_id), str(row.fixture_id))
        if target in seen_targets:
            raise DatasetValidationError("duplicate player-fixture target")
        seen_targets.add(target)


def build_training_dataset(history: object, *, training_cutoff: str) -> TrainingDataset:
    """Validate history and construct the cutoff-safe TRAIN-only dataset."""

    cutoff = parse_utc(training_cutoff, field_name="training_cutoff")
    rows = _as_rows(history)
    validate_history_identities(rows)
    eligible: list[HistoryRow] = []
    for row in rows:
        if row.split != "TRAIN":
            continue
        if row.feature_cutoff > cutoff or row.label_usable_at > cutoff:
            continue
        eligible.append(row)
    eligible.sort(key=_canonical_row_key)
    try:
        return TrainingDataset(
            rows=tuple(eligible),
            schema_version=DATASET_SCHEMA_VERSION,
            training_cutoff=cutoff,
        )
    except (ValidationError, ValueError) as exc:
        raise DatasetValidationError("training dataset violates the frozen contract") from exc


def semantic_dataset_hash(dataset: object) -> str:
    """Hash canonical semantic JSON bytes independent of mapping insertion order."""

    if isinstance(dataset, TrainingDataset):
        value: Any = dataset.model_dump(mode="json")
    elif isinstance(dataset, Mapping):
        value = dict(dataset)
    else:
        dump = getattr(dataset, "model_dump", None)
        if not callable(dump):
            raise DatasetValidationError("dataset must be a mapping or validated model")
        value = dump(mode="json")
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


__all__ = ["build_training_dataset", "semantic_dataset_hash", "validate_history_identities"]
