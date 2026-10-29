"""Complete population, original custody and separate diagnostic acceptance."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

import pytest

from dmf_pulse.evaluation.point_metrics import score_forecast
from dmf_pulse.fpl_points.models import POINT_COMPONENT_NAMES
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.rights import load_rights_profiles
from dmf_pulse.player_lab.actuals import FinalityContext
from dmf_pulse.player_lab.cohort import SyntheticCohortLedger
from dmf_pulse.player_lab.contracts import seal
from dmf_pulse.player_lab.diagnostics import FixtureMinutes, minutes_diagnostics, qualified_minutes
from dmf_pulse.player_lab.rights import ingest_offline_actuals, profile_identity
from dmf_pulse.player_lab.runner import (
    PlayerEvaluationService,
    finalize_owned_cohort,
    freeze_owned_cohort,
    operational_synthetic_evaluation,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def complete():
    phase = freeze_owned_cohort()
    final = finalize_owned_cohort(phase)
    report = PlayerEvaluationService().run(
        phase.cohort, final, custody=phase.custody, evaluated_at=phase.clock[0]
    )
    return phase, final, report


def test_full_registered_population_precedes_every_outcome_body(monkeypatch):
    reads = []
    original = Path.read_bytes

    def tracked(path):
        reads.append(path.name)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    phase = freeze_owned_cohort()
    assert not any(name.startswith("actuals-") for name in reads)
    assert len(phase.cohort.protocol.targets) == 8
    assert len(phase.cohort.forecasts) == 16
    assert all(
        item.forecast.generated_at <= item.recorded_at < item.forecast.deadline_at
        for item in phase.cohort.forecasts
    )
    final = finalize_owned_cohort(phase)
    assert len(final.labels) == 8
    assert any(name.startswith("actuals-") for name in reads)
    assert min(item.finalized_at for item in final.labels) > min(
        item.recorded_at for item in phase.cohort.forecasts
    )


def test_report_inherits_kernels_and_exposes_full_components_minutes_and_holdout(complete):
    phase, final, report = complete
    assert report == operational_synthetic_evaluation()
    assert report.population_players == 4 and report.gameweek_count == 2
    assert report.expected_targets == report.scored_targets == 8
    assert report.attrition_count == report.real_cohort_size == 0
    assert report.champion.point_metrics.mae == report.champion.point_metrics.rmse == 2
    assert report.champion.probability_5plus.brier_score == Decimal("0.25")
    assert report.champion.mean_ranked_probability_score == Decimal("0.25")
    assert report.champion.central_80_coverage == 1
    assert report.champion.calibration_5plus.status == "INSUFFICIENT_VARIATION"
    assert report.holdout.holdout_count == report.holdout.development_count == 4
    assert report.holdout.paired_absolute_error_delta == 0
    assert set(report.champion_components) == set(POINT_COMPONENT_NAMES)
    assert set(report.challenger_components) == set(POINT_COMPONENT_NAMES)
    champion = [
        item
        for item in phase.cohort.forecasts
        if item.forecast.model_id == phase.cohort.experiment.champion_id
    ]
    by_target = {item.key.target_id(): item for item in final.labels}
    for component in POINT_COMPONENT_NAMES:
        assert report.champion_components[component] == score_forecast(
            tuple(item.forecast.components[component] for item in champion),
            tuple(
                Decimal(by_target[item.forecast.key.target_id()].components[component])
                for item in champion
            ),
        )
    minutes = report.champion_minutes
    assert minutes.expected_count == minutes.scored_count == 8
    assert minutes.unavailable_forecast_count == 0
    assert minutes.mean_minutes.mae == Decimal("37.5")
    assert minutes.mean_minutes.signed_bias == Decimal("-37.5")
    assert all(item.observed_minutes == 90 for item in minutes.sidecars)
    assert all(
        item.evidence == "EXACT_QUALIFIED_RAW_COUNTS_NOT_POINTS_INFERENCE"
        for item in minutes.sidecars
    )
    assert all(
        fixture.observed_start is None for item in minutes.sidecars for fixture in item.fixtures
    )
    assert "UNAVAILABLE" in minutes.start_probability_status
    assert "UNAVAILABLE" in minutes.sixty_plus_status
    assert {item.benchmark_id for item in report.benchmarks} == {f"B{i}" for i in range(6)}
    assert {item.status for item in report.benchmarks} == {"UNAVAILABLE"}
    assert report.diagnostic_zero_baseline == "NOT_A_B0_B5_BENCHMARK"
    assert report.predictive_skill_claim == "NONE"
    assert report.promotion == "FORBIDDEN"


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "wrong_model", "unsorted", "wrong_key"]
)
def test_forecast_product_cannot_drop_duplicate_or_substitute_targets(complete, mutation):
    phase, _, _ = complete
    original = phase.cohort
    values = original.forecasts
    if mutation == "missing":
        values = values[:-1]
    elif mutation == "duplicate":
        values = (*values[:-1], values[0])
    elif mutation == "wrong_model":
        changed = seal(values[0].forecast.model_copy(update={"model_id": "UNREGISTERED"}))
        values = (seal(values[0].model_copy(update={"forecast": changed})), *values[1:])
    elif mutation == "unsorted":
        values = tuple(reversed(values))
    else:
        changed = seal(values[0].forecast.model_copy(update={"key": values[-1].forecast.key}))
        values = (seal(values[0].model_copy(update={"forecast": changed})), *values[1:])
    with pytest.raises(ValueError):
        seal(original.model_copy(update={"forecasts": values}))


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "season", "gameweek", "fixture", "cohort", "early", "future", "naive"],
)
def test_exact_final_join_and_reveal_clock_fail_closed(complete, mutation):
    phase, final, _ = complete
    labels = final.labels
    value = final
    when = phase.clock[0]
    if mutation == "missing":
        value = seal(final.model_copy(update={"labels": labels[:-1]}))
    elif mutation == "duplicate":
        with pytest.raises(ValueError):
            seal(final.model_copy(update={"labels": (*labels[:-1], labels[0])}))
        return
    elif mutation in {"season", "gameweek", "fixture"}:
        from uuid import uuid4

        update = (
            {"season": "2025/26"}
            if mutation == "season"
            else {"gameweek": 8}
            if mutation == "gameweek"
            else {"fixture_ids": (uuid4(),)}
        )
        changed = seal(
            labels[0].model_copy(update={"key": labels[0].key.model_copy(update=update)})
        )
        value = seal(
            final.model_copy(
                update={
                    "labels": tuple(
                        sorted((changed, *labels[1:]), key=lambda item: item.key.target_id())
                    )
                }
            )
        )
    elif mutation == "cohort":
        value = seal(final.model_copy(update={"forecast_cohort_sha256": "0" * 64}))
    elif mutation in {"early", "future"}:
        when = max(item.usable_at for item in labels) - timedelta(seconds=1)
    else:
        when = when.replace(tzinfo=None)
    with pytest.raises(ValueError):
        PlayerEvaluationService().run(phase.cohort, value, custody=phase.custody, evaluated_at=when)


def test_self_resealed_receipt_and_empty_custody_do_not_authenticate_origin(complete):
    phase, final, _ = complete
    first = phase.cohort.forecasts[0]
    changed = seal(
        first.model_copy(update={"recorded_at": first.recorded_at + timedelta(seconds=1)})
    )
    forged = seal(
        phase.cohort.model_copy(update={"forecasts": (changed, *phase.cohort.forecasts[1:])})
    )
    with pytest.raises(ValueError, match="original custody"):
        PlayerEvaluationService().run(
            forged, final, custody=phase.custody, evaluated_at=phase.clock[0]
        )
    empty = SyntheticCohortLedger(clock=lambda: phase.clock[0])
    with pytest.raises(ValueError, match="original custody"):
        PlayerEvaluationService().run(
            phase.cohort, final, custody=empty, evaluated_at=phase.clock[0]
        )


def test_protocol_population_and_registration_cannot_be_rechosen(complete):
    phase, final, _ = complete
    protocol = phase.cohort.protocol
    for update in (
        {"targets": ()},
        {"targets": protocol.targets[:-1]},
        {"targets": tuple(reversed(protocol.targets))},
        {"model_ids": ("same", "same")},
        {"sources": ()},
    ):
        with pytest.raises(ValueError):
            seal(protocol.model_copy(update=update))
    clock = [protocol.registered_at]
    ledger = SyntheticCohortLedger(clock=lambda: clock[0])
    with pytest.raises(ValueError):
        ledger.freeze(phase.cohort.forecasts[0].forecast)
    with pytest.raises(ValueError):
        ledger.record_outcome(final.labels[0])
    ledger.register(protocol, phase.cohort.experiment)
    with pytest.raises(ValueError):
        ledger.register(protocol, phase.cohort.experiment)
    clock[0] = phase.cohort.forecasts[0].recorded_at
    with pytest.raises(ValueError):
        ledger.freeze(
            seal(phase.cohort.forecasts[0].forecast.model_copy(update={"model_id": "wrong"}))
        )
    with pytest.raises(ValueError):
        ledger.close(phase.cohort)
    with pytest.raises(ValueError):
        phase.custody.freeze(phase.cohort.forecasts[0].forecast)
    with pytest.raises(ValueError):
        phase.custody.close(phase.cohort)


def test_private_dependency_denied_before_custody_and_real_mode_never_admitted(complete):
    phase, _, _ = complete
    protocol = phase.cohort.protocol
    profile = load_rights_profiles()["fpl_official_private_operator_initiated_read_v1"]
    private = protocol.sources[0].model_copy(
        update={
            "profile_id": profile.rights_profile_id,
            "profile_sha256": profile_identity(profile),
        }
    )
    denied = seal(protocol.model_copy(update={"sources": (*protocol.sources, private)}))
    ledger = SyntheticCohortLedger(clock=lambda: protocol.registered_at)
    with pytest.raises(IngestionError):
        ledger.register(denied, phase.cohort.experiment)
    assert ledger._protocol is None and ledger._cohort is None
    forecast = phase.cohort.forecasts[0].forecast
    with pytest.raises(ValueError):
        ledger.register(
            protocol,
            seal(phase.cohort.experiment.model_copy(update={"dataset_mode": "PROSPECTIVE_REAL"})),
        )
    with pytest.raises(ValueError):
        seal(
            phase.cohort.model_copy(
                update={
                    "forecasts": (
                        seal(
                            phase.cohort.forecasts[0].model_copy(
                                update={
                                    "forecast": seal(
                                        forecast.model_copy(
                                            update={"dataset_mode": "PROSPECTIVE_REAL"}
                                        )
                                    )
                                }
                            )
                        ),
                        *phase.cohort.forecasts[1:],
                    )
                }
            )
        )


def test_complete_correction_vintage_is_separate_and_mixed_vintage_is_blocked(complete):
    phase, final, original = complete
    root = files("dmf_pulse.player_lab.resources")
    context = FinalityContext.model_validate_json(
        root.joinpath("context-gw2-revision1.json").read_bytes()
    )
    corrected = ingest_offline_actuals(
        root.joinpath("actuals-gw2-revision1.json").read_bytes(), context
    ).labels
    labels = tuple(
        sorted(
            (*corrected, *(item for item in final.labels if item.key.gameweek == 3)),
            key=lambda item: item.key.target_id(),
        )
    )
    changed = seal(final.model_copy(update={"labels": labels}))
    result = PlayerEvaluationService().run(
        phase.cohort, changed, custody=phase.custody, evaluated_at=phase.clock[0]
    )
    assert result.champion.point_metrics.mae == Decimal("1.875")
    assert original.champion.point_metrics.mae == 2
    assert result.semantic_sha256 != original.semantic_sha256
    selected = next(item for item in labels if item.key.gameweek == 2)
    prior = next(item for item in final.labels if item.key == selected.key)
    with pytest.raises(ValueError, match="mixed correction"):
        seal(
            changed.model_copy(
                update={"labels": tuple(prior if item == selected else item for item in labels)}
            )
        )


def test_evaluation_clock_cannot_reverse(complete):
    phase, final, _ = complete
    service = PlayerEvaluationService()
    service.run(
        phase.cohort,
        final,
        custody=phase.custody,
        evaluated_at=phase.clock[0] + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="clock"):
        service.run(phase.cohort, final, custody=phase.custody, evaluated_at=phase.clock[0])


def test_unavailable_expected_minutes_are_counted_and_never_imputed(complete):
    phase, final, _ = complete
    champion = tuple(
        item
        for item in phase.cohort.forecasts
        if item.forecast.model_id == phase.cohort.experiment.champion_id
    )
    # The runner authenticates custody before calling this pure diagnostic helper.
    # Exercise missingness without qualifying a new forecast or admitting it to custody.
    missing = tuple(
        item.model_copy(
            update={"forecast": item.forecast.model_copy(update={"expected_minutes": None})}
        )
        for item in champion
    )
    result = minutes_diagnostics(missing, final.labels)
    assert result.scored_count == 0 and result.unavailable_forecast_count == 8
    assert result.mean_minutes is None


def test_sidecar_reconciles_original_counts_and_rejects_fabricated_labels(complete):
    _, final, report = complete
    sidecar = report.champion_minutes.sidecars[0]
    with pytest.raises(ValueError):
        seal(sidecar.model_copy(update={"observed_minutes": sidecar.observed_minutes + 1}))
    with pytest.raises(ValueError):
        seal(
            sidecar.model_copy(
                update={
                    "fixtures": (*sidecar.fixtures, *sidecar.fixtures),
                    "observed_minutes": sidecar.observed_minutes * 2,
                }
            )
        )
    with pytest.raises(ValueError):
        FixtureMinutes(fixture_id=sidecar.fixtures[0].fixture_id, actual_minutes=91)
    with pytest.raises(ValueError):
        FixtureMinutes(fixture_id=sidecar.fixtures[0].fixture_id, actual_minutes=True)
    label = final.labels[0]
    invented = seal(
        label.model_copy(
            update={
                "total_points": label.total_points + 1,
                "components": {**label.components, "bonus": label.components["bonus"] + 1},
            }
        )
    )
    with pytest.raises(ValueError, match="LABEL_VALUES"):
        qualified_minutes(invented)


def test_future_source_or_training_values_cannot_be_resealed_into_registered_forecast(complete):
    phase, _, _ = complete
    forecast = phase.cohort.forecasts[0].forecast
    for update in (
        {"information_cutoff": forecast.generated_at + timedelta(seconds=1)},
        {"training_cutoff": forecast.information_cutoff + timedelta(seconds=1)},
        {
            "sources": (
                forecast.sources[0].model_copy(
                    update={"usable_at": forecast.information_cutoff + timedelta(seconds=1)}
                ),
            )
        },
    ):
        with pytest.raises(ValueError):
            seal(forecast.model_copy(update=update))
