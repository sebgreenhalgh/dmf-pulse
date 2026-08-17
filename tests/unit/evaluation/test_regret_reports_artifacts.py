from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.evaluation.artifacts import (
    canonical_json_bytes,
    load_verified_artifact,
    persist_artifact,
    seal,
)
from dmf_pulse.evaluation.decision_regret import calculate_decision_regret
from dmf_pulse.evaluation.errors import EvaluationError
from dmf_pulse.evaluation.models import (
    ComparatorInformationSet,
    DatasetMode,
    ForecastArtifact,
    MetricFamily,
    ScorecardRow,
)
from dmf_pulse.evaluation.reports import build_report, persist_report, render_markdown
from tests.evaluation_helpers import BASE, lineage

pytestmark = pytest.mark.unit


def test_decision_regret_separates_feasible_and_oracle_comparators() -> None:
    feasible = calculate_decision_regret(
        decision_id="d",
        comparator_id="no-transfer",
        realised_decision_utility=Decimal(8),
        realised_comparator_utility=Decimal(6),
        transfer_hit_points=Decimal(4),
        no_transfer_utility=Decimal(6),
    )
    assert feasible.regret == Decimal(-2)
    assert feasible.hit_adjusted_transfer_value == Decimal(2)
    assert feasible.horizon_gameweeks == 1
    assert feasible.outcome_convention == "REALISED_PATH"
    assert feasible.utilities_include_hit_costs
    assert not feasible.comparator_is_oracle
    oracle = calculate_decision_regret(
        decision_id="d",
        comparator_id="perfect",
        realised_decision_utility=Decimal(8),
        realised_comparator_utility=Decimal(12),
        comparator_information_set=ComparatorInformationSet.COUNTERFACTUAL_HINDSIGHT,
    )
    assert oracle.comparator_is_oracle and oracle.regret == Decimal(4)
    with pytest.raises(ValueError, match="non-negative"):
        calculate_decision_regret(
            decision_id="d",
            comparator_id="c",
            realised_decision_utility=Decimal(1),
            realised_comparator_utility=Decimal(1),
            transfer_hit_points=Decimal(-1),
        )


def _row(layer: str, mode: DatasetMode = DatasetMode.COUNTERFACTUAL) -> ScorecardRow:
    families = {
        "FORECAST": MetricFamily.POINT,
        "DISTRIBUTION": MetricFamily.DISTRIBUTION,
        "DECISION": MetricFamily.DECISION,
        "OPERATIONAL": MetricFamily.OPERATIONAL,
    }
    return ScorecardRow(
        layer=layer,
        metric_family=families[layer],
        dataset_mode=mode,
        forecast_origin=BASE,
        information_cutoff=BASE,
        horizon=1,
        subgroup="ALL",
        benchmark_id="B4",
        metric_name=f"{layer}_METRIC",
        metric_value=Decimal(1),
        status="PASS",
        limitations=(),
    )


def test_report_keeps_layers_and_modes_separate(tmp_path: Path) -> None:
    report = build_report(
        report_id="report",
        rows=tuple(
            _row(layer) for layer in ("FORECAST", "DISTRIBUTION", "DECISION", "OPERATIONAL")
        ),
        lineage=lineage(),
        limitations=("synthetic",),
    )
    assert report.headline_mode is DatasetMode.COUNTERFACTUAL
    markdown = render_markdown(report)
    assert "## Forecast" in markdown and "## Decision" in markdown
    json_path, markdown_path = persist_report(report, artifact_root=tmp_path)
    assert json_path.exists() and markdown_path.exists()
    mixed = build_report(
        report_id="mixed",
        rows=(_row("FORECAST"), _row("FORECAST", DatasetMode.RECONSTRUCTED)),
        lineage=lineage(),
    )
    assert mixed.headline_mode is None
    assert len(mixed.dataset_modes) == 2

    unsafe = build_report(
        report_id="escaped",
        rows=(_row("FORECAST").model_copy(update={"subgroup": "a|b\nnext"}),),
        lineage=lineage(),
    )
    assert "a\\|b next" in render_markdown(unsafe)


def test_report_keeps_probability_and_multivariate_metrics_in_distribution_panel() -> None:
    report = build_report(
        report_id="layers",
        rows=(
            _row("DISTRIBUTION").model_copy(
                update={"metric_family": MetricFamily.PROBABILITY, "metric_name": "LOG_LOSS"}
            ),
            _row("DISTRIBUTION").model_copy(update={"metric_name": "RPS"}),
            _row("DISTRIBUTION").model_copy(
                update={"metric_family": MetricFamily.MULTIVARIATE, "metric_name": "ENERGY_SCORE"}
            ),
        ),
        lineage=lineage(),
    )
    assert report.distribution_rows == 3
    assert {row.metric_name for row in report.rows} == {"LOG_LOSS", "RPS", "ENERGY_SCORE"}
    assert {row.metric_family for row in report.rows} == {
        MetricFamily.PROBABILITY,
        MetricFamily.DISTRIBUTION,
        MetricFamily.MULTIVARIATE,
    }


def test_report_cannot_present_b5_as_feasible_or_live() -> None:
    with pytest.raises(ValueError, match="COUNTERFACTUAL"):
        ScorecardRow.model_validate(
            {
                **_row("FORECAST", DatasetMode.LIVE_OBSERVED).model_dump(mode="python"),
                "benchmark_id": "B5D_PERFECT_SEASON_POLICY",
            }
        )
    with pytest.raises(ValueError, match="hindsight"):
        ScorecardRow.model_validate(
            {
                **_row("FORECAST").model_dump(mode="python"),
                "benchmark_id": "B5D_PERFECT_SEASON_POLICY",
                "limitations": (),
            }
        )


def test_immutable_artifact_hash_tamper_collision_and_confinement(tmp_path: Path) -> None:
    value = ForecastArtifact(
        forecast_id="forecast",
        benchmark_id="B4",
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        target_id="target",
        horizon=1,
        point_forecast=Decimal(5),
        lineage=lineage(),
        issued_at=BASE,
        forecast_sha256="0" * 64,
    )
    value = seal(value, "forecast_sha256")
    path = persist_artifact(
        value, artifact_root=tmp_path, category="forecasts", identity="forecast"
    )
    assert (
        persist_artifact(value, artifact_root=tmp_path, category="forecasts", identity="forecast")
        == path
    )
    assert load_verified_artifact(path, ForecastArtifact, hash_field="forecast_sha256") == value
    forged = value.model_copy(update={"forecast_sha256": "f" * 64})
    with pytest.raises(EvaluationError, match="semantic payload"):
        persist_artifact(forged, artifact_root=tmp_path, category="forged", identity="forecast")
    data = path.read_bytes()
    path.write_bytes(data.replace(b'"point_forecast":"5"', b'"point_forecast":"6"'))
    with pytest.raises(EvaluationError, match="detached"):
        load_verified_artifact(path, ForecastArtifact, hash_field="forecast_sha256")
    path.write_bytes(data)
    with pytest.raises(EvaluationError, match="identity"):
        persist_artifact(value, artifact_root=tmp_path, category="../escape", identity="x")
    for unsafe_identity in ("CON", "line\nbreak", "trailing.", "wild*card"):
        with pytest.raises(EvaluationError, match="identity"):
            persist_artifact(
                value,
                artifact_root=tmp_path,
                category="forecasts",
                identity=unsafe_identity,
            )
    assert canonical_json_bytes(value).endswith(b"\n")


def test_artifact_loader_enforces_content_address_and_sidecar_filename(tmp_path: Path) -> None:
    value = ForecastArtifact(
        forecast_id="forecast",
        benchmark_id="B4",
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        target_id="target",
        horizon=1,
        point_forecast=Decimal(1),
        lineage=lineage(),
        issued_at=BASE,
        forecast_sha256="0" * 64,
    )
    value = seal(value, "forecast_sha256")
    path = persist_artifact(value, artifact_root=tmp_path, category="forecasts", identity="address")
    renamed = path.with_name("0" * 64 + ".json")
    renamed.write_bytes(path.read_bytes())
    renamed.with_suffix(".sha256").write_text(
        f"{path.stem}  {renamed.name}\n",
        encoding="ascii",
    )
    with pytest.raises(EvaluationError, match="content-addressed"):
        load_verified_artifact(renamed, ForecastArtifact)

    path.with_suffix(".sha256").write_text(f"{path.stem}  wrong.json\n", encoding="ascii")
    with pytest.raises(EvaluationError, match="filename"):
        load_verified_artifact(path, ForecastArtifact)

    path.with_suffix(".sha256").write_text(f"{path.stem} {path.name}\n", encoding="ascii")
    with pytest.raises(EvaluationError, match="not canonical"):
        load_verified_artifact(path, ForecastArtifact)

    invalid = value.model_copy(update={"scenario_weights": (Decimal(1),)})
    with pytest.raises(ValueError, match="without scenario"):
        seal(invalid, "forecast_sha256")
    with pytest.raises(ValueError, match="without scenario"):
        persist_artifact(invalid, artifact_root=tmp_path, category="forecasts", identity="invalid")


def test_report_rejects_empty_rows() -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_report(report_id="empty", rows=(), lineage=lineage(BASE + timedelta(days=1)))
    duplicate = _row("FORECAST")
    with pytest.raises(ValueError, match="unique"):
        build_report(report_id="duplicate", rows=(duplicate, duplicate), lineage=lineage())


def test_service_json_helpers_and_persist_forecast_cover_failure_boundaries(tmp_path: Path) -> None:
    from dmf_pulse.evaluation.service import EvaluationService, load_json, write_canonical_json

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="root must be an object"):
        load_json(invalid)
    with pytest.raises(ValueError, match="invalid JSON"):
        load_json(tmp_path / "missing.json")

    precise = tmp_path / "precise.json"
    precise.write_text('{"value":0.12345678901234567890123456789}', encoding="utf-8")
    assert load_json(precise)["value"] == Decimal("0.12345678901234567890123456789")
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_json(nonfinite)

    output = tmp_path / "nested" / "value.json"
    write_canonical_json(output, {"b": 2, "a": 1})
    assert output.read_text(encoding="utf-8") == '{"a":1,"b":2}\n'

    forecast = seal(
        ForecastArtifact(
            forecast_id="service-forecast",
            benchmark_id="B4",
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            target_id="target",
            horizon=1,
            point_forecast=Decimal(5),
            lineage=lineage(),
            issued_at=BASE,
            forecast_sha256="0" * 64,
        ),
        "forecast_sha256",
    )
    path = EvaluationService().persist_forecast(forecast, artifact_root=tmp_path)
    assert path.exists()
