from __future__ import annotations

from datetime import timedelta

import pytest

from dmf_pulse.evaluation.errors import LeakageError
from dmf_pulse.evaluation.information_sets import build_information_set
from dmf_pulse.evaluation.leakage import scan_for_leakage
from dmf_pulse.evaluation.models import (
    DatasetMode,
    InclusionDecision,
    LeakageKind,
    ObservationKind,
    ObservationRole,
    OperationalUsability,
)
from dmf_pulse.evaluation.vintages import mode_allows_feature, temporal_feature_eligible
from tests.evaluation_helpers import BASE, feature

pytestmark = pytest.mark.unit


def test_strict_live_includes_only_live_operational() -> None:
    live = feature("live")
    raw = feature(
        "raw",
        mode=DatasetMode.RAW_OBSERVED,
        usability=OperationalUsability.RECEIVED_NOT_OPERATIONAL,
    )
    label = feature(
        "label",
        mode=DatasetMode.FINAL_OUTCOME,
        usability=OperationalUsability.LABEL_ONLY,
        role=ObservationRole.LABEL,
        kind=ObservationKind.OUTCOME,
    )
    bundle = build_information_set(
        (live, raw, label),
        bundle_id="bundle",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.LIVE_OBSERVED,
        block_on_leakage=False,
    )
    assert tuple(item.record_id for item in bundle.records) == ("live",)
    decisions = {item.record_id: item.decision for item in bundle.decisions}
    assert decisions["live"] is InclusionDecision.INCLUDED
    assert decisions["label"] is InclusionDecision.EXCLUDED_EXPECTED
    assert decisions["raw"] is InclusionDecision.BLOCKED_LEAKAGE
    assert bundle.blocking_violations == ("raw",)


def test_reconstructed_mode_accepts_raw_and_reconstructed() -> None:
    raw = feature(
        "raw",
        mode=DatasetMode.RAW_OBSERVED,
        usability=OperationalUsability.RECEIVED_NOT_OPERATIONAL,
    )
    reconstructed = feature(
        "recon",
        mode=DatasetMode.RECONSTRUCTED,
        usability=OperationalUsability.RECONSTRUCTED_ONLY,
    )
    assert mode_allows_feature(DatasetMode.RECONSTRUCTED, raw)
    assert mode_allows_feature(DatasetMode.RECONSTRUCTED, reconstructed)
    assert not mode_allows_feature(DatasetMode.FINAL_OUTCOME, reconstructed)


def test_nonlive_modes_do_not_collapse_to_strict_live_timing() -> None:
    raw = feature(
        "raw-late-processing",
        mode=DatasetMode.RAW_OBSERVED,
        usability=OperationalUsability.RECEIVED_NOT_OPERATIONAL,
        usable_offset_hours=2,
        mapped_offset_hours=1,
    )
    raw_bundle = build_information_set(
        (raw,),
        bundle_id="raw-bundle",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.RAW_OBSERVED,
    )
    assert raw_bundle.records == (raw,)
    assert raw_bundle.blocking_violations == ()

    reconstructed = feature(
        "retrospective",
        mode=DatasetMode.RECONSTRUCTED,
        usability=OperationalUsability.RECONSTRUCTED_ONLY,
        usable_offset_hours=24,
        received_offset_hours=20,
        mapped_offset_hours=22,
    ).model_copy(update={"source_timestamp": BASE - timedelta(days=1)})
    reconstructed_bundle = build_information_set(
        (reconstructed,),
        bundle_id="reconstructed-bundle",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.RECONSTRUCTED,
    )
    assert reconstructed_bundle.records == (reconstructed,)
    assert reconstructed_bundle.blocking_violations == ()


def test_nonlive_modes_block_source_events_after_cutoff() -> None:
    future = feature(
        "future-source",
        mode=DatasetMode.RAW_OBSERVED,
        usability=OperationalUsability.RECEIVED_NOT_OPERATIONAL,
        usable_offset_hours=1,
    ).model_copy(update={"source_timestamp": BASE + timedelta(minutes=1)})
    report = scan_for_leakage(
        (future,), forecast_origin=BASE, dataset_mode=DatasetMode.RAW_OBSERVED
    )
    assert LeakageKind.SOURCE_TIMESTAMP_AFTER_CUTOFF in {
        finding.kind for finding in report.findings
    }
    with pytest.raises(LeakageError):
        build_information_set(
            (future,),
            bundle_id="future-raw",
            forecast_origin=BASE,
            information_cutoff=BASE,
            dataset_mode=DatasetMode.RAW_OBSERVED,
        )


def test_reconstructed_and_counterfactual_modes_allow_explicit_later_information() -> None:
    reconstructed = feature(
        "retrospective-lineup",
        kind=ObservationKind.LINEUP,
        mode=DatasetMode.RECONSTRUCTED,
        usability=OperationalUsability.RECONSTRUCTED_ONLY,
        received_offset_hours=2,
        mapped_offset_hours=3,
        usable_offset_hours=4,
    ).model_copy(update={"source_timestamp": BASE + timedelta(hours=1)})
    reconstructed_bundle = build_information_set(
        (reconstructed,),
        bundle_id="retrospective-lineup",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.RECONSTRUCTED,
    )
    assert reconstructed_bundle.records == (reconstructed,)

    perfect_outcome = feature(
        "perfect-outcome",
        kind=ObservationKind.OUTCOME,
        mode=DatasetMode.COUNTERFACTUAL,
        usability=OperationalUsability.COUNTERFACTUAL_ONLY,
        received_offset_hours=24,
        mapped_offset_hours=24,
        usable_offset_hours=24,
    )
    perfect_bundle = build_information_set(
        (perfect_outcome,),
        bundle_id="perfect-information",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.COUNTERFACTUAL,
    )
    assert perfect_bundle.records == (perfect_outcome,)


def test_strict_live_blocks_every_nonoperational_mode_instead_of_silent_exclusion() -> None:
    reconstructed = feature(
        "reconstructed-in-live",
        mode=DatasetMode.RECONSTRUCTED,
        usability=OperationalUsability.RECONSTRUCTED_ONLY,
    )
    bundle = build_information_set(
        (reconstructed,),
        bundle_id="strict-bundle",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.LIVE_OBSERVED,
        block_on_leakage=False,
    )
    assert bundle.records == ()
    assert bundle.blocking_violations == ("reconstructed-in-live",)


def test_strict_live_blocks_missing_snapshot_or_mapping_lineage() -> None:
    unbound = feature("unbound").model_copy(update={"mapping_version_id": None})
    bundle = build_information_set(
        (unbound,),
        bundle_id="missing-lineage",
        forecast_origin=BASE,
        information_cutoff=BASE,
        dataset_mode=DatasetMode.LIVE_OBSERVED,
        block_on_leakage=False,
    )
    assert bundle.blocking_violations == ("unbound",)


def test_temporal_eligibility_requires_all_system_times() -> None:
    eligible = feature("eligible")
    assert temporal_feature_eligible(eligible, BASE)
    late = feature("late", usable_offset_hours=1)
    assert not temporal_feature_eligible(late, BASE)
    corrected = feature("corrected", corrected_at=BASE + timedelta(minutes=1))
    assert not temporal_feature_eligible(corrected, BASE)
    target = feature("target", target_outcome_at=BASE)
    assert not temporal_feature_eligible(target, BASE)


def test_blocking_leakage_raises_in_strict_builder() -> None:
    canary = feature("canary", values={"leakage_marker": "FUTURE_LEAKAGE_CANARY"})
    with pytest.raises(LeakageError, match="canary"):
        build_information_set(
            (canary,),
            bundle_id="bundle",
            forecast_origin=BASE,
            information_cutoff=BASE,
            dataset_mode=DatasetMode.LIVE_OBSERVED,
        )


def test_cutoff_after_origin_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot follow"):
        build_information_set(
            (feature(),),
            bundle_id="bundle",
            forecast_origin=BASE,
            information_cutoff=BASE + timedelta(seconds=1),
            dataset_mode=DatasetMode.LIVE_OBSERVED,
        )
    duplicate = feature("duplicate")
    with pytest.raises(ValueError, match="record IDs"):
        build_information_set(
            (duplicate, duplicate),
            bundle_id="duplicates",
            forecast_origin=BASE,
            information_cutoff=BASE,
            dataset_mode=DatasetMode.LIVE_OBSERVED,
        )
