"""Deterministic historical information-set construction."""

from __future__ import annotations

from datetime import datetime

from dmf_pulse.evaluation.artifacts import seal
from dmf_pulse.evaluation.errors import LeakageError
from dmf_pulse.evaluation.leakage import scan_for_leakage
from dmf_pulse.evaluation.models import (
    DatasetMode,
    FeatureRecord,
    InclusionDecision,
    InformationBundle,
    InformationRecordDecision,
    ObservationRole,
    require_utc,
)
from dmf_pulse.evaluation.vintages import mode_allows_feature, temporal_feature_eligible


def build_information_set(
    records: tuple[FeatureRecord, ...],
    *,
    bundle_id: str,
    forecast_origin: datetime,
    information_cutoff: datetime,
    dataset_mode: DatasetMode,
    block_on_leakage: bool = True,
) -> InformationBundle:
    """Freeze the exact historical feature set and its explainable exclusions."""

    origin = require_utc(forecast_origin, field_name="forecast_origin")
    cutoff = require_utc(information_cutoff, field_name="information_cutoff")
    if cutoff > origin:
        raise ValueError("information cutoff cannot follow forecast origin")
    ordered = tuple(sorted(records, key=lambda item: item.record_id))
    leakage = scan_for_leakage(
        ordered,
        forecast_origin=cutoff,
        dataset_mode=dataset_mode,
    )
    finding_kinds_by_record: dict[str, set[str]] = {}
    for finding in leakage.findings:
        for record_id in finding.record_ids:
            finding_kinds_by_record.setdefault(record_id, set()).add(finding.kind.value)
    blocking_ids = {record_id for finding in leakage.findings for record_id in finding.record_ids}
    included: list[FeatureRecord] = []
    decisions: list[InformationRecordDecision] = []
    for record in ordered:
        if record.record_id in blocking_ids:
            kinds = tuple(sorted(finding_kinds_by_record[record.record_id]))
            decisions.append(
                InformationRecordDecision(
                    record_id=record.record_id,
                    decision=InclusionDecision.BLOCKED_LEAKAGE,
                    reason_code="|".join(kinds),
                    explanation=(
                        "record violates the historical information boundary: " + ", ".join(kinds)
                    ),
                )
            )
            continue
        if record.role is ObservationRole.LABEL:
            decisions.append(
                InformationRecordDecision(
                    record_id=record.record_id,
                    decision=InclusionDecision.EXCLUDED_EXPECTED,
                    reason_code="LABEL_RESERVED_FOR_SCORING",
                    explanation="final outcome is retained as a later scoring label, not a feature",
                )
            )
            continue
        if not mode_allows_feature(dataset_mode, record):
            decisions.append(
                InformationRecordDecision(
                    record_id=record.record_id,
                    decision=InclusionDecision.EXCLUDED_EXPECTED,
                    reason_code="DATASET_MODE_INELIGIBLE",
                    explanation="record belongs to another explicitly separated dataset mode",
                )
            )
            continue
        if not temporal_feature_eligible(record, information_cutoff, mode=dataset_mode):
            decisions.append(
                InformationRecordDecision(
                    record_id=record.record_id,
                    decision=InclusionDecision.BLOCKED_LEAKAGE,
                    reason_code="TEMPORAL_ELIGIBILITY_FAILURE",
                    explanation=(
                        "record violates the declared dataset mode's temporal eligibility"
                    ),
                )
            )
            blocking_ids.add(record.record_id)
            continue
        included.append(record)
        decisions.append(
            InformationRecordDecision(
                record_id=record.record_id,
                decision=InclusionDecision.INCLUDED,
                reason_code="ELIGIBLE_AS_OF_CUTOFF",
                explanation="record passed its declared mode and temporal eligibility",
            )
        )
    value = InformationBundle(
        bundle_id=bundle_id,
        dataset_mode=dataset_mode,
        forecast_origin=origin,
        information_cutoff=cutoff,
        records=tuple(included),
        decisions=tuple(sorted(decisions, key=lambda item: item.record_id)),
        blocking_violations=tuple(sorted(blocking_ids)),
        bundle_sha256="0" * 64,
    )
    value = seal(value, "bundle_sha256")
    if blocking_ids and block_on_leakage:
        raise LeakageError(
            "HISTORICAL_INFORMATION_LEAKAGE_BLOCKED",
            "strict information bundle contains blocking leakage: "
            + ", ".join(sorted(blocking_ids)),
        )
    return value
