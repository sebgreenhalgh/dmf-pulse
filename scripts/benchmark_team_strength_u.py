"""Measured CPU-only synthetic/public benchmark; never invokes an optimizer/provider."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from dmf_pulse.assurance.canonical import canonical_sha256  # noqa: E402
from dmf_pulse.evaluation.team_strength_prospective import (  # noqa: E402
    freeze_public_team_forecasts,
    score_public_team_forecasts,
)
from dmf_pulse.football_events.service import ScoreDistributionService  # noqa: E402
from dmf_pulse.football_events.team_strength_adapter import fixture_prior_bundle  # noqa: E402
from dmf_pulse.football_events.team_strength_mixture import build_parameter_mixture  # noqa: E402
from dmf_pulse.football_events.team_strength_mixture_stage8 import (  # noqa: E402
    project_parameter_mixture,
)
from dmf_pulse.football_events.team_strength_parameter_draws import (  # noqa: E402
    draw_policy,
    joint_parameter_draws,
)
from tests.unit.evaluation.test_team_strength_prospective import frozen, outcome  # noqa: E402
from tests.unit.football_events.test_team_strength_adapter import stage8_request  # noqa: E402


def benchmark() -> dict:
    setup_start = perf_counter()
    public = frozen()
    artifact = public.artifact
    fixtures = tuple(
        row
        for row in public.fixture_registry.fixtures
        if row.season == artifact.model.forecast_season
    )
    if len(fixtures) != 380:
        raise ValueError("benchmark requires the complete 380-fixture synthetic season")
    setup_seconds = perf_counter() - setup_start
    generation, stage8, full_season = [], [], []
    draws64 = None
    for count in (64, 128, 256, 512, 1024, 2048):
        start = perf_counter()
        draws = joint_parameter_draws(artifact, policy=draw_policy(seed=23, draw_count=count))
        generation.append({"draw_count": count, "seconds": perf_counter() - start})
        if count == 64:
            draws64 = draws
        bound = fixture_prior_bundle(
            artifact=artifact,
            fixture=fixtures[0],
            as_of=public.forecast_origin,
            expected_artifact_sha256=artifact.semantic_sha256,
        )
        for market in (False, True):
            request = stage8_request(bound, market=market)
            start = perf_counter()
            ScoreDistributionService().project(request)
            plugin_seconds = perf_counter() - start
            start = perf_counter()
            project_parameter_mixture(
                request,
                artifact=artifact,
                draws=draws,
                fixture=fixtures[0],
                expected_artifact_sha256=artifact.semantic_sha256,
            )
            stage8.append(
                {
                    "draw_count": count,
                    "market_backed": market,
                    "plugin_seconds": plugin_seconds,
                    "mixture_seconds": perf_counter() - start,
                }
            )
        if count in (64, 128):
            start = perf_counter()
            identities = []
            for fixture in fixtures:
                mixture = build_parameter_mixture(
                    artifact=artifact,
                    draws=draws,
                    fixture=fixture,
                    as_of=public.forecast_origin,
                    expected_artifact_sha256=artifact.semantic_sha256,
                )
                identities.append(mixture.semantic_sha256)
            full_season.append(
                {
                    "fixtures": 380,
                    "draw_count": count,
                    "seconds": perf_counter() - start,
                    "artifact_identity_collection_sha256": canonical_sha256(identities),
                }
            )
        print(f"measured generation/stage8/full-season count={count}", flush=True)
    if draws64 is None:
        raise ValueError("measured draw set missing")
    start = perf_counter()
    prospective = freeze_public_team_forecasts(
        artifact=artifact,
        draws=draws64,
        fixture_registry=public.fixture_registry,
        public_schedule=public.public_schedule,
        training_dataset=public.training_dataset,
        forecast_origin=public.forecast_origin,
        fixture_ids=(str(public.forecasts[0].fixture.fixture_id),),
        league_baseline=public.league_baseline,
        clock=lambda: public.frozen_at,
    )
    freeze_seconds = perf_counter() - start
    start = perf_counter()
    scored = score_public_team_forecasts(
        prospective, outcomes=outcome(prospective), as_of=datetime(2026, 10, 6, tzinfo=UTC)
    )
    scoring_seconds = perf_counter() - start
    # A separate traced run measures Python allocations, not RSS or timing with tracer overhead.
    tracemalloc.start()
    traced_draws = joint_parameter_draws(artifact, policy=draw_policy(seed=71, draw_count=2048))
    build_parameter_mixture(
        artifact=artifact,
        draws=traced_draws,
        fixture=fixtures[0],
        as_of=public.forecast_origin,
        expected_artifact_sha256=artifact.semantic_sha256,
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report = {
        "schema_version": "team-strength-u-performance-v1",
        "classification": "SYNTHETIC_OFFLINE_CPU_SINGLE_PROCESS",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "setup_fit_seconds": setup_seconds,
        "parameter_dimension": len(artifact.model.uncertainty.parameter_order),
        "fit_sha256": artifact.semantic_sha256,
        "measurement_conditions": "LOCAL_REGRESSION_RUNNING_CONCURRENTLY_NO_IDLE_MACHINE_CLAIM",
        "source_sha256s": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "scripts/benchmark_team_strength_u.py",
                "src/dmf_pulse/football_events/team_strength_parameter_draws.py",
                "src/dmf_pulse/football_events/team_strength_mixture.py",
                "src/dmf_pulse/football_events/team_strength_mixture_stage8.py",
                "src/dmf_pulse/evaluation/team_strength_prospective.py",
            )
        },
        "draw_generation": generation,
        "stage8_single_fixture": stage8,
        "full_season_mixture_generation": full_season,
        "prospective": {
            "fixtures": 1,
            "products": 3,
            "draw_count": 64,
            "freeze_seconds": freeze_seconds,
            "score_seconds": scoring_seconds,
            "score_sha256": scored.semantic_sha256,
        },
        "memory": {
            "method": "TRACEMALLOC_PYTHON_ALLOCATIONS_NOT_PROCESS_RSS",
            "draw_count": 2048,
            "fixtures": 1,
            "peak_bytes": peak,
            "setup_and_preexisting_caches_excluded": True,
        },
        "stage11_solves": 0,
        "private_live_runtime_claim": "NOT_MEASURED",
        "operational_draw_count": None,
        "production_active": False,
    }
    report["semantic_sha256"] = canonical_sha256(report)
    return report


if __name__ == "__main__":
    destination = ROOT / "evidence/tickets/CURRENT-TEAM-STRENGTH-001U/PERFORMANCE.json"
    destination.write_text(
        json.dumps(benchmark(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print("wrote PERFORMANCE.json")
