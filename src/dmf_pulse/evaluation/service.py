"""Application service shared by library and CLI evaluation execution."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dmf_pulse.evaluation.artifacts import canonical_json_bytes, persist_artifact
from dmf_pulse.evaluation.benchmarks import benchmark_suite, project_benchmark
from dmf_pulse.evaluation.folds import ForecastOrigin, WalkForwardConfig, build_walk_forward_folds
from dmf_pulse.evaluation.information_sets import build_information_set
from dmf_pulse.evaluation.leakage import scan_for_leakage
from dmf_pulse.evaluation.models import (
    BenchmarkProjection,
    DatasetMode,
    EvaluationFold,
    EvaluationLineage,
    EvaluationReport,
    FeatureRecord,
    ForecastArtifact,
    LeakageReport,
    OutcomeLabel,
    PointMetricResult,
    PolicyTrajectory,
    ScorecardRow,
    TargetFunctional,
)
from dmf_pulse.evaluation.point_metrics import score_frozen_point_forecasts
from dmf_pulse.evaluation.policy_replay import (
    ReplayDeadline,
    SyntheticManagerState,
    SyntheticReplayExecutor,
    SyntheticReplayPolicy,
    replay_policy,
)
from dmf_pulse.evaluation.reports import build_report, persist_report


def load_json(path: Path) -> dict[str, Any]:
    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"non-finite JSON number is prohibited: {value}")

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_float=Decimal,
            parse_constant=reject_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError("input JSON root must be an object")
    return value


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.write_bytes(canonical_json_bytes(payload))


class EvaluationService:
    """One canonical application path for Stage-12 CLI and Python callers."""

    def build_folds(self, payload: dict[str, Any]) -> tuple[EvaluationFold, ...]:
        origins = tuple(ForecastOrigin.model_validate(item) for item in payload["origins"])
        config = WalkForwardConfig.model_validate(payload["config"])
        return build_walk_forward_folds(origins, config=config)

    def benchmark(self, payload: dict[str, Any]) -> tuple[BenchmarkProjection, ...]:
        bundle = build_information_set(
            tuple(FeatureRecord.model_validate(item) for item in payload["records"]),
            bundle_id=str(payload["bundle_id"]),
            forecast_origin=datetime.fromisoformat(str(payload["forecast_origin"])),
            information_cutoff=datetime.fromisoformat(str(payload["information_cutoff"])),
            dataset_mode=DatasetMode(str(payload["dataset_mode"])),
        )
        requested = tuple(
            str(item)
            for item in payload.get(
                "benchmark_ids",
                [item.benchmark_id for item in benchmark_suite()],
            )
        )
        if len(requested) != len(set(requested)):
            raise ValueError("benchmark IDs must be unique")
        selected = set(requested)
        canonical_ids = {item.benchmark_id for item in benchmark_suite()}
        if not selected:
            raise ValueError("benchmark selection cannot be empty")
        unknown = sorted(selected - canonical_ids)
        if unknown:
            raise ValueError("unknown benchmark IDs: " + ", ".join(unknown))
        raw_oracle_values = payload.get("oracle_values", {})
        if not isinstance(raw_oracle_values, dict):
            raise ValueError("oracle_values must be an object keyed by B5 benchmark ID")
        b5_ids = {
            item.benchmark_id for item in benchmark_suite() if item.benchmark_id.startswith("B5")
        }
        invalid_oracle_ids = sorted(set(raw_oracle_values) - (selected & b5_ids))
        if invalid_oracle_ids:
            raise ValueError(
                "oracle values require a selected canonical B5 benchmark: "
                + ", ".join(str(item) for item in invalid_oracle_ids)
            )
        oracle_values = {str(key): Decimal(str(value)) for key, value in raw_oracle_values.items()}
        target_id = str(payload["target_id"])
        projections = []
        for definition in benchmark_suite():
            if definition.benchmark_id not in selected:
                continue
            projections.append(
                project_benchmark(
                    definition,
                    bundle=bundle,
                    target_id=target_id,
                    forecast_origin=bundle.forecast_origin,
                    oracle_value=oracle_values.get(definition.benchmark_id),
                )
            )
        return tuple(projections)

    def projections(self, payload: dict[str, Any]) -> PointMetricResult:
        return score_frozen_point_forecasts(
            tuple(ForecastArtifact.model_validate(item) for item in payload["forecasts"]),
            tuple(OutcomeLabel.model_validate(item) for item in payload["labels"]),
            target_functional=TargetFunctional(str(payload.get("target_functional", "MEAN"))),
            quantile=(
                Decimal(str(payload["quantile"])) if payload.get("quantile") is not None else None
            ),
        )

    def leakage(self, payload: dict[str, Any]) -> LeakageReport:
        return scan_for_leakage(
            tuple(FeatureRecord.model_validate(item) for item in payload["records"]),
            forecast_origin=datetime.fromisoformat(str(payload["forecast_origin"])),
            dataset_mode=DatasetMode(str(payload["dataset_mode"])),
        )

    def policy(
        self, payload: dict[str, Any], *, artifact_root: Path | None = None
    ) -> PolicyTrajectory:
        lineage = EvaluationLineage.model_validate(payload["lineage"])
        deadlines = tuple(ReplayDeadline.model_validate(item) for item in payload["deadlines"])
        initial = SyntheticManagerState.model_validate(payload["initial_state"])
        return replay_policy(
            deadlines,
            trajectory_id=str(payload["trajectory_id"]),
            dataset_mode=DatasetMode(str(payload["dataset_mode"])),
            initial_state=initial,
            policy=SyntheticReplayPolicy(lineage),
            executor=SyntheticReplayExecutor(),
            artifact_root=artifact_root,
        )

    def report(
        self,
        payload: dict[str, Any],
        *,
        artifact_root: Path | None = None,
    ) -> EvaluationReport:
        report = build_report(
            report_id=str(payload["report_id"]),
            rows=tuple(ScorecardRow.model_validate(item) for item in payload["rows"]),
            lineage=EvaluationLineage.model_validate(payload["lineage"]),
            limitations=tuple(str(item) for item in payload.get("limitations", ())),
        )
        if artifact_root is not None:
            persist_report(report, artifact_root=artifact_root)
        return report

    def persist_forecast(self, forecast: ForecastArtifact, *, artifact_root: Path) -> Path:
        return persist_artifact(
            forecast,
            artifact_root=artifact_root,
            category="forecasts",
            identity=forecast.forecast_id,
        )
