from __future__ import annotations

from pathlib import Path

import pytest

from dmf_pulse.evaluation.service import EvaluationService, load_json

pytestmark = pytest.mark.integration


def test_complete_offline_vertical_slice(tmp_path: Path) -> None:
    service = EvaluationService()
    folds = service.build_folds(
        load_json(Path("fixtures/historical/synthetic_five_gw/folds_input.json"))
    )
    benchmarks = service.benchmark(
        load_json(Path("fixtures/historical/benchmark_player_histories/benchmark_input.json"))
    )
    projections = service.projections(
        load_json(Path("fixtures/historical/synthetic_five_gw/projections_input.json"))
    )
    trajectory = service.policy(
        load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json")),
        artifact_root=tmp_path,
    )
    leakage = service.leakage(
        load_json(Path("fixtures/historical/synthetic_five_gw/leakage_clean_input.json"))
    )
    report = service.report(
        load_json(Path("fixtures/historical/synthetic_five_gw/report_input.json")),
        artifact_root=tmp_path,
    )
    assert len(folds) == 5
    assert len(benchmarks) == 11
    assert projections.count == 4
    assert len(trajectory.steps) == 5
    assert leakage.status == "PASS"
    assert report.forecast_rows == report.decision_rows == report.operational_rows == 1
    assert report.distribution_rows == 3
    assert list((tmp_path / "evaluation" / "reports").rglob("*.md"))


def test_vertical_slice_has_no_network_dependency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    import socket

    monkeypatch.setattr(socket, "create_connection", blocked)
    trajectory = EvaluationService().policy(
        load_json(Path("fixtures/historical/synthetic_five_gw/policy_input.json")),
        artifact_root=tmp_path,
    )
    assert trajectory.cumulative_utility > 0
