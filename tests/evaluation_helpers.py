from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dmf_pulse.evaluation.models import (
    DatasetMode,
    EvaluationLineage,
    FeatureRecord,
    ObservationKind,
    ObservationRole,
    OperationalUsability,
)

ROOT = Path(__file__).resolve().parents[1]
ZERO = "0" * 64
CODE = "4f1274ccef419a7c0bde335c48bd4070e248b2e6"
BASE = datetime(2026, 8, 1, 10, tzinfo=UTC)


def load(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def lineage(origin: datetime = BASE) -> EvaluationLineage:
    return EvaluationLineage(
        forecast_origin=origin,
        information_cutoff=origin,
        usable_at_cutoff=origin,
        training_cutoff=origin - timedelta(days=1),
        label_finality_cutoff=origin + timedelta(days=30),
        model_version_ids=("model-v1",),
        ruleset_id="rules-v1",
        ruleset_hash=ZERO,
        code_commit=CODE,
        dataset_manifest_sha256=ZERO,
        input_manifest_sha256=ZERO,
        benchmark_config_sha256=ZERO,
        metric_config_sha256=ZERO,
        random_seed=12,
    )


def feature(
    record_id: str = "record",
    *,
    kind: ObservationKind = ObservationKind.OTHER,
    mode: DatasetMode = DatasetMode.LIVE_OBSERVED,
    usability: OperationalUsability = OperationalUsability.LIVE_OPERATIONAL,
    origin: datetime = BASE,
    role: ObservationRole = ObservationRole.FEATURE,
    values: dict[str, object] | None = None,
    current_vintage: bool = False,
    usable_offset_hours: int = -1,
    received_offset_hours: int = -2,
    mapped_offset_hours: int = -1,
    corrected_at: datetime | None = None,
    target_outcome_at: datetime | None = None,
    valid_from: datetime | None = None,
) -> FeatureRecord:
    return FeatureRecord(
        record_id=record_id,
        entity_id="player",
        target_id="target",
        gameweek=1,
        dataset_mode=mode,
        operational_usability=usability,
        role=role,
        kind=kind,
        source_timestamp=origin + timedelta(hours=received_offset_hours),
        received_at=origin + timedelta(hours=received_offset_hours),
        mapped_at=origin + timedelta(hours=mapped_offset_hours),
        usable_at=origin + timedelta(hours=usable_offset_hours),
        valid_from=valid_from,
        corrected_at=corrected_at,
        target_outcome_at=target_outcome_at,
        current_vintage=current_vintage,
        feature_intended=role is not ObservationRole.LABEL,
        values=values or {},
        source_snapshot_id=f"snapshot:{record_id}",
        mapping_version_id=f"mapping:{record_id}",
    )


def d(value: str | int) -> Decimal:
    return Decimal(value)
