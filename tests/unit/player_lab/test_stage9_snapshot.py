"""Actual Stage-9 owned output, immutable custody, and final-label acceptance."""

from __future__ import annotations

from decimal import Decimal

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import POINT_COMPONENT_NAMES
from dmf_pulse.player_lab.contracts import seal
from dmf_pulse.player_lab.evaluation import MemoryLedger, evaluate_players
from dmf_pulse.player_lab.rights import require_qualified_forecast
from dmf_pulse.player_lab.snapshots import decimal_pmf
from dmf_pulse.player_lab.stage9_demo import (
    load_stage9_fixture,
    snapshot_stage9_fixture,
    stage9_synthetic_evaluation,
)

pytestmark = pytest.mark.unit


def test_actual_stage9_snapshot_freeze_final_label_and_existing_metrics() -> None:
    result = stage9_synthetic_evaluation()
    source = result.fixture
    forecast = result.forecast
    assert source.origin == "run_synthetic_recommendation(1, NullProgress())"
    assert forecast.key == result.label.key == source.key
    assert forecast.source_summary_sha256 == source.summary_sha256
    assert forecast.source_summary_sha256 == canonical_sha256(
        source.summary.model_dump(mode="json")
    )
    assert forecast.mean == Decimal(str(source.summary.expected_points))
    assert forecast.pmf == decimal_pmf(source.summary.pmf)
    assert forecast.components == {
        name: Decimal(str(component.expected_points))
        for name, component in source.summary.component_breakdown.items()
    }
    assert set(forecast.components) == set(POINT_COMPONENT_NAMES)
    assert forecast.model_version_ids == tuple(sorted(source.summary.model_version_ids))
    assert forecast.ruleset_sha256 == source.summary.ruleset_hash
    assert forecast.input_sha256 == source.input_sha256
    assert forecast.generated_at <= result.frozen.recorded_at < forecast.deadline_at
    assert forecast.deadline_at < result.label.finalized_at <= result.label.usable_at
    require_qualified_forecast(forecast)
    result.custody.verify_frozen(result.frozen)
    score = result.scorecard
    assert score.count == score.point_metrics.count == 1
    assert score.point_metrics.mae == abs(forecast.mean - result.label.total_points)
    assert score.pairs[0].predicted == forecast.mean
    assert score.pairs[0].actual == result.label.total_points
    assert score.forecast_hashes == (result.frozen.semantic_sha256,)
    assert score.label_hashes == (result.label.semantic_sha256,)
    assert score.promotion == "FORBIDDEN"
    assert score.real_cohort_status == "NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT"


@pytest.mark.parametrize("field", ["summary", "input"], ids=["summary-hash", "input-hash"])
def test_unregistered_stage9_summary_or_input_cannot_be_retained(field: str) -> None:
    fixture = load_stage9_fixture()
    if field == "summary":
        summary = fixture.summary.model_copy(
            update={"expected_points": fixture.summary.expected_points + 1}
        )
        changed = seal(
            fixture.model_copy(
                update={
                    "summary": summary,
                    "summary_sha256": canonical_sha256(summary.model_dump(mode="json")),
                }
            )
        )
    else:
        changed = seal(fixture.model_copy(update={"input_sha256": "0" * 64}))
    with pytest.raises(ValueError, match="summary/input not qualified"):
        snapshot_stage9_fixture(changed)


def test_complete_forecast_binding_denies_coherent_outcome_informed_replacement() -> None:
    result = stage9_synthetic_evaluation()
    original = result.forecast
    changed = seal(
        original.model_copy(
            update={
                "mean": original.mean + 1,
                "pmf": {points + 1: mass for points, mass in original.pmf.items()},
                "components": {
                    **original.components,
                    "appearance": original.components["appearance"] + 1,
                },
            }
        )
    )
    # A valid internal mean/PMF/component sum cannot confer synthetic retention rights.
    with pytest.raises(ValueError, match="FORECAST_VALUES_NOT_QUALIFIED"):
        require_qualified_forecast(changed)
    ledger = MemoryLedger(clock=lambda: original.generated_at)
    with pytest.raises(ValueError, match="FORECAST_VALUES_NOT_QUALIFIED"):
        ledger.freeze(changed)
    forged = seal(result.frozen.model_copy(update={"forecast": changed}))
    with pytest.raises(ValueError, match="original frozen custody"):
        evaluate_players((forged,), (result.label,), custody=result.custody)


@pytest.mark.parametrize("field", ["code_sha", "expected_minutes", "label_finality_cutoff"])
def test_qualification_binds_forecast_metadata_as_well_as_values(field: str) -> None:
    fixture = load_stage9_fixture()
    original = snapshot_stage9_fixture(fixture)
    if field == "code_sha":
        value = "b" * 40
    elif field == "expected_minutes":
        value = original.expected_minutes / 2 if original.expected_minutes else Decimal(1)
    else:
        from datetime import timedelta

        value = original.label_finality_cutoff + timedelta(seconds=1)
    changed = seal(original.model_copy(update={field: value}))
    with pytest.raises(ValueError, match="FORECAST_VALUES_NOT_QUALIFIED"):
        require_qualified_forecast(changed)
