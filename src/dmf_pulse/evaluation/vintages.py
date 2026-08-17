"""Authoritative dataset-mode and vintage eligibility semantics."""

from __future__ import annotations

from datetime import datetime

from dmf_pulse.evaluation.models import (
    DatasetMode,
    FeatureRecord,
    ObservationRole,
    OperationalUsability,
)


def mode_allows_feature(mode: DatasetMode, record: FeatureRecord) -> bool:
    """Return whether a record's declared vintage is eligible in the requested dataset mode."""

    if not record.feature_intended or (
        record.role is not ObservationRole.FEATURE
        and record.role is not ObservationRole.MANAGER_STATE
    ):
        return False
    if mode is DatasetMode.LIVE_OBSERVED:
        return (
            record.dataset_mode is DatasetMode.LIVE_OBSERVED
            and record.operational_usability is OperationalUsability.LIVE_OPERATIONAL
            and not record.current_vintage
        )
    if mode is DatasetMode.RAW_OBSERVED:
        return record.dataset_mode in {DatasetMode.LIVE_OBSERVED, DatasetMode.RAW_OBSERVED}
    if mode is DatasetMode.RECONSTRUCTED:
        return record.dataset_mode in {
            DatasetMode.LIVE_OBSERVED,
            DatasetMode.RAW_OBSERVED,
            DatasetMode.RECONSTRUCTED,
        }
    if mode is DatasetMode.COUNTERFACTUAL:
        return record.dataset_mode is not DatasetMode.FINAL_OUTCOME
    return False


def temporal_feature_eligible(
    record: FeatureRecord,
    cutoff: datetime,
    *,
    mode: DatasetMode = DatasetMode.LIVE_OBSERVED,
) -> bool:
    """Apply the declared mode's time boundary without collapsing dataset vintages."""

    if mode is DatasetMode.LIVE_OBSERVED:
        if record.usable_at is None or record.usable_at > cutoff:
            return False
        if record.received_at > cutoff:
            return False
        if record.mapped_at is not None and record.mapped_at > cutoff:
            return False
        if record.corrected_at is not None and record.corrected_at > cutoff:
            return False
    elif mode is DatasetMode.RAW_OBSERVED:
        if record.received_at > cutoff or record.source_timestamp > cutoff:
            return False
    elif mode is DatasetMode.FINAL_OUTCOME:
        return False
    if mode is DatasetMode.COUNTERFACTUAL:
        return True
    return record.target_outcome_at is None or record.target_outcome_at < cutoff
