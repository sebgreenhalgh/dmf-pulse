"""Cutoff-safe synthetic availability dataset foundations."""

from dmf_pulse.availability.dataset import build_training_dataset, semantic_dataset_hash
from dmf_pulse.availability.manual_override import (
    MANUAL_MODEL_FAMILY,
    MANUAL_POLICY_SHA256,
    ManualFixtureMinutesInput,
    ManualMinutesProjectionBundle,
    ManualOverrideError,
    build_manual_minutes_override,
    load_manual_fixture_minutes,
)
from dmf_pulse.availability.models import (
    DatasetValidationError,
    HistoryRow,
    TrainingDataset,
)
from dmf_pulse.availability.pipeline import (
    MinutesModelArtifact,
    MinutesModelEvaluation,
    evaluate_minutes_baseline,
    fit_projection_artifact,
    predict_minutes_baseline,
)
from dmf_pulse.availability.projection import (
    MinutesPredictionResult,
    PlayerMinutesProjection,
    TeamMinutesProjection,
)

__all__ = [
    "MANUAL_MODEL_FAMILY",
    "MANUAL_POLICY_SHA256",
    "DatasetValidationError",
    "HistoryRow",
    "ManualFixtureMinutesInput",
    "ManualMinutesProjectionBundle",
    "ManualOverrideError",
    "MinutesModelArtifact",
    "MinutesModelEvaluation",
    "MinutesPredictionResult",
    "PlayerMinutesProjection",
    "TeamMinutesProjection",
    "TrainingDataset",
    "build_manual_minutes_override",
    "build_training_dataset",
    "evaluate_minutes_baseline",
    "fit_projection_artifact",
    "load_manual_fixture_minutes",
    "predict_minutes_baseline",
    "semantic_dataset_hash",
]
