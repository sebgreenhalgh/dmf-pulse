"""First-class temporal leakage detection for historical evaluation."""

from __future__ import annotations

from datetime import datetime

from dmf_pulse.evaluation.artifacts import seal
from dmf_pulse.evaluation.models import (
    DatasetMode,
    FeatureRecord,
    LeakageFinding,
    LeakageKind,
    LeakageReport,
    ObservationKind,
    ObservationRole,
    OperationalUsability,
    require_utc,
)


def _finding(record: FeatureRecord, kind: LeakageKind, explanation: str) -> LeakageFinding:
    return LeakageFinding(
        finding_id=f"{kind.value}:{record.record_id}",
        kind=kind,
        record_ids=(record.record_id,),
        explanation=explanation,
    )


def detect_record_leakage(
    record: FeatureRecord,
    *,
    forecast_origin: datetime,
    dataset_mode: DatasetMode,
) -> tuple[LeakageFinding, ...]:
    """Detect all material temporal contamination carried by one intended feature."""

    if record.role is ObservationRole.LABEL or not record.feature_intended:
        return ()
    findings: list[LeakageFinding] = []
    marker = str(record.values.get("leakage_marker", ""))
    if marker == "FUTURE_LEAKAGE_CANARY":
        findings.append(
            _finding(
                record,
                LeakageKind.FUTURE_LEAKAGE_CANARY,
                "synthetic future-data canary reached the historical feature path",
            )
        )
    if dataset_mode is DatasetMode.LIVE_OBSERVED and (
        record.usable_at is None or record.usable_at > forecast_origin
    ):
        findings.append(
            _finding(
                record,
                LeakageKind.USABLE_AT_AFTER_CUTOFF,
                "record was not operationally usable by the historical cutoff",
            )
        )
    if dataset_mode in {DatasetMode.LIVE_OBSERVED, DatasetMode.RAW_OBSERVED} and (
        record.received_at > forecast_origin
    ):
        findings.append(
            _finding(
                record,
                LeakageKind.LATE_PROVIDER_CORRECTION,
                "record was received after the historical cutoff",
            )
        )
    if dataset_mode is DatasetMode.RAW_OBSERVED and record.source_timestamp > forecast_origin:
        findings.append(
            _finding(
                record,
                LeakageKind.SOURCE_TIMESTAMP_AFTER_CUTOFF,
                "record source event occurred after the historical cutoff",
            )
        )
    if (
        dataset_mode is DatasetMode.LIVE_OBSERVED
        and record.mapped_at is not None
        and record.mapped_at > forecast_origin
    ):
        findings.append(
            _finding(
                record,
                LeakageKind.LATE_ENTITY_MAPPING,
                "entity mapping became usable only after the historical cutoff",
            )
        )
    if (
        dataset_mode is DatasetMode.LIVE_OBSERVED
        and record.corrected_at is not None
        and record.corrected_at > forecast_origin
    ):
        kind = (
            LeakageKind.PRICE_CORRECTION_AFTER_CUTOFF
            if record.kind is ObservationKind.PRICE
            else LeakageKind.LATE_PROVIDER_CORRECTION
        )
        findings.append(
            _finding(
                record,
                kind,
                "later correction was presented as a historical feature",
            )
        )
    if (
        dataset_mode in {DatasetMode.LIVE_OBSERVED, DatasetMode.RAW_OBSERVED}
        and (record.kind is ObservationKind.FIXTURE_ASSIGNMENT)
        and (record.valid_from is not None and record.valid_from > forecast_origin)
    ):
        findings.append(
            _finding(
                record,
                LeakageKind.FIXTURE_MOVED_AFTER_CUTOFF,
                "fixture assignment was learned after the historical cutoff",
            )
        )
    if dataset_mode in {DatasetMode.LIVE_OBSERVED, DatasetMode.RAW_OBSERVED} and (
        record.kind is ObservationKind.MARKET
        and bool(record.values.get("closing_odds", False))
        and (record.source_timestamp > forecast_origin or record.received_at > forecast_origin)
    ):
        findings.append(
            _finding(
                record,
                LeakageKind.CLOSING_ODDS_AFTER_CUTOFF,
                "post-cutoff closing odds entered a predeadline feature bundle",
            )
        )
    if (
        dataset_mode in {DatasetMode.LIVE_OBSERVED, DatasetMode.RAW_OBSERVED}
        and record.kind is ObservationKind.LINEUP
        and record.source_timestamp >= forecast_origin
    ):
        findings.append(
            _finding(
                record,
                LeakageKind.POSTDEADLINE_LINEUP,
                "official lineup published at or after deadline entered the feature bundle",
            )
        )
    if (
        dataset_mode is not DatasetMode.COUNTERFACTUAL
        and (record.kind is ObservationKind.RECENT_POINTS)
        and (record.target_outcome_at is not None and record.target_outcome_at >= forecast_origin)
    ):
        findings.append(
            _finding(
                record,
                LeakageKind.FUTURE_RESULT_IN_RECENT_WINDOW,
                "recent-points window includes an appearance completed after forecast origin",
            )
        )
    if (
        dataset_mode is not DatasetMode.COUNTERFACTUAL
        and record.kind is ObservationKind.MODEL_SELECTION
        and bool(record.values.get("uses_outer_fold_outcome", False))
    ):
        findings.append(
            _finding(
                record,
                LeakageKind.OUTER_FOLD_CONTAMINATION,
                "outer-fold outcome was used to choose a reported model or policy",
            )
        )
    if dataset_mode is DatasetMode.LIVE_OBSERVED:
        if (
            record.source_snapshot_id is None
            or record.mapping_version_id is None
            or record.mapped_at is None
        ):
            findings.append(
                _finding(
                    record,
                    LeakageKind.MISSING_STRICT_LINEAGE,
                    "strict live evidence lacks source-snapshot or mapping-version lineage",
                )
            )
        if record.current_vintage:
            findings.append(
                _finding(
                    record,
                    LeakageKind.CURRENT_VINTAGE_CONTAMINATION,
                    "current-vintage corrected record entered strict historical replay",
                )
            )
        if record.dataset_mode is DatasetMode.RAW_OBSERVED or (
            record.operational_usability is OperationalUsability.RECEIVED_NOT_OPERATIONAL
        ):
            findings.append(
                _finding(
                    record,
                    LeakageKind.RAW_OBSERVED_IN_STRICT_LIVE,
                    "received-but-not-operational record entered strict live evaluation",
                )
            )
        elif record.dataset_mode is not DatasetMode.LIVE_OBSERVED or (
            record.operational_usability is not OperationalUsability.LIVE_OPERATIONAL
        ):
            findings.append(
                _finding(
                    record,
                    LeakageKind.NON_LIVE_EVIDENCE_IN_STRICT_LIVE,
                    "non-live or nonoperational evidence entered strict live evaluation",
                )
            )
    if dataset_mode is not DatasetMode.COUNTERFACTUAL and record.kind is ObservationKind.OUTCOME:
        findings.append(
            _finding(
                record,
                LeakageKind.TARGET_OUTCOME_AS_FEATURE,
                "target outcome was presented as a historical feature",
            )
        )
    unique = {item.finding_id: item for item in findings}
    return tuple(sorted(unique.values(), key=lambda item: item.finding_id))


def scan_for_leakage(
    records: tuple[FeatureRecord, ...],
    *,
    forecast_origin: datetime,
    dataset_mode: DatasetMode,
) -> LeakageReport:
    origin = require_utc(forecast_origin, field_name="forecast_origin")
    record_ids = tuple(record.record_id for record in records)
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("leakage scan record IDs must be unique")
    findings = tuple(
        sorted(
            (
                finding
                for record in records
                for finding in detect_record_leakage(
                    record,
                    forecast_origin=origin,
                    dataset_mode=dataset_mode,
                )
            ),
            key=lambda item: item.finding_id,
        )
    )
    value = LeakageReport(
        status="BLOCKED" if findings else "PASS",
        dataset_mode=dataset_mode,
        forecast_origin=origin,
        findings=findings,
        checked_record_count=len(records),
        report_sha256="0" * 64,
    )
    return seal(value, "report_sha256")
