from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.chips.service import evaluate_chip_opportunities
from dmf_pulse.chips.service_models import ChipServiceRequest
from dmf_pulse.evaluation.leakage import scan_for_leakage
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.prices.models import ActivationStatus as PriceActivationStatus
from tests.support.stage14_chip_fixtures import NOW, service_request

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("record_id", "updates"),
    (
        ("fixture-assignment", {"valid_from": NOW + timedelta(seconds=1)}),
        ("injury-evidence", {"usable_at": NOW + timedelta(seconds=1)}),
        ("lineup-evidence", {"source_timestamp": NOW}),
        ("manager-state", {"usable_at": NOW + timedelta(seconds=1)}),
        ("points-scenarios", {"usable_at": NOW + timedelta(seconds=1)}),
        ("price-scenarios", {"usable_at": NOW + timedelta(seconds=1)}),
    ),
)
def test_executable_service_rejects_every_future_information_class(
    record_id: str,
    updates: dict[str, object],
) -> None:
    request = service_request(price_statuses=(PriceActivationStatus.SHADOW_ONLY,))
    records = tuple(
        item.model_copy(update=updates) if item.record_id == record_id else item
        for item in request.feature_records
    )
    report = scan_for_leakage(
        records,
        forecast_origin=NOW,
        dataset_mode=DatasetMode.LIVE_OBSERVED,
    )
    assert report.status == "BLOCKED"
    payload = request.model_dump(mode="python")
    payload["feature_records"] = records
    payload["leakage_report"] = report
    payload["service_request_hash"] = "0" * 64

    with pytest.raises(ValidationError, match="future-information leakage"):
        ChipServiceRequest.model_validate(payload)


def test_future_bgw_dgw_assignment_is_blocked_by_stage12_fixture_gate() -> None:
    request = service_request()
    records = tuple(
        item.model_copy(
            update={
                "valid_from": NOW + timedelta(days=2),
                "values": {"category": "FUTURE_BGW_DGW_ASSIGNMENT"},
            }
        )
        if item.record_id == "fixture-assignment"
        else item
        for item in request.feature_records
    )
    report = scan_for_leakage(
        records,
        forecast_origin=NOW,
        dataset_mode=DatasetMode.LIVE_OBSERVED,
    )
    payload = request.model_dump(mode="python")
    payload.update(
        feature_records=records,
        leakage_report=report,
        service_request_hash="0" * 64,
    )

    with pytest.raises(ValidationError, match="future-information leakage"):
        ChipServiceRequest.model_validate(payload)


def test_clean_stage12_leakage_report_is_retained_in_decision_lineage() -> None:
    request = service_request()

    result = evaluate_chip_opportunities(request)

    assert request.leakage_report.status == "PASS"
    assert result.lineage.dataset_mode is DatasetMode.LIVE_OBSERVED
    assert result.lineage.leakage_report_hash == request.leakage_report.report_sha256
    assert len(result.lineage.feature_record_hashes) == len(request.feature_records)
