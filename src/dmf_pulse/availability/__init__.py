"""Cutoff-safe synthetic availability dataset foundations."""

from dmf_pulse.availability.current import (
    CurrentAvailabilityApproval,
    CurrentAvailabilityBundle,
    CurrentAvailabilityEvidence,
    CurrentAvailabilityReviewTemplate,
    CurrentAvailabilitySummary,
    CurrentPlayerAvailabilityDecision,
    CurrentTeamAvailabilityProjection,
    build_current_availability,
    build_current_availability_review,
)
from dmf_pulse.availability.dataset import build_training_dataset, semantic_dataset_hash
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
    "CurrentAvailabilityApproval",
    "CurrentAvailabilityBundle",
    "CurrentAvailabilityEvidence",
    "CurrentAvailabilityReviewTemplate",
    "CurrentAvailabilitySummary",
    "CurrentPlayerAvailabilityDecision",
    "CurrentTeamAvailabilityProjection",
    "DatasetValidationError",
    "HistoryRow",
    "MinutesModelArtifact",
    "MinutesModelEvaluation",
    "MinutesPredictionResult",
    "PlayerMinutesProjection",
    "TeamMinutesProjection",
    "TrainingDataset",
    "build_current_availability",
    "build_current_availability_review",
    "build_training_dataset",
    "evaluate_minutes_baseline",
    "fit_projection_artifact",
    "predict_minutes_baseline",
    "semantic_dataset_hash",
]
