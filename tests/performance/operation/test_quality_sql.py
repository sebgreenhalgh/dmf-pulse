"""Bounded JSON-view query scaling; owned SQL envelope, not forecast accuracy."""

import json
import sqlite3
from time import perf_counter

import pytest

from dmf_pulse.fpl_points.models import POINT_COMPONENT_NAMES, GameweekPlayerProjectionSummary
from dmf_pulse.operation.analysis_store import _QUALITY_VIEWS, _SCHEMA

pytestmark = pytest.mark.performance


def test_full_catalogue_derived_view_queries_fit_existing_time_bound():
    components = {
        name: {
            "expected_points": 2.0 if name == "appearance" else 0.0,
            "probability_nonzero": 1.0 if name == "appearance" else 0.0,
            "minimum": 2 if name == "appearance" else 0,
            "maximum": 2 if name == "appearance" else 0,
            "variance": 0.0,
        }
        for name in POINT_COMPONENT_NAMES
    }
    base = {
        "player_id": "p0",
        "expected_points": 2.0,
        "median_points": 2,
        "points_variance": 0.0,
        "points_standard_deviation": 0.0,
        "probability_negative_points": 0.0,
        "probability_zero_points": 0.0,
        "probability_1_plus": 1.0,
        "probability_2_plus": 1.0,
        "probability_5_plus": 0.0,
        "probability_10_plus": 0.0,
        "probability_15_plus": 0.0,
        "selected_percentiles": {"p10": 2, "p50": 2, "p90": 2},
        "pmf": {"2": 1.0},
        "component_breakdown": components,
        "component_covariance": {
            a: dict.fromkeys(POINT_COMPONENT_NAMES, 0.0) for a in POINT_COMPONENT_NAMES
        },
        "bps_bonus": {
            "expected_bps": 0.0,
            "bps_variance": 0.0,
            "expected_bonus": 0.0,
            "probability_any_bonus": 0.0,
            "completeness_mode": "EVENT_LINKED_PLUS_AUXILIARY_BASELINE",
        },
        "monte_carlo_mean_se": 0.0,
        "threshold_probability_se": {"5": 0.0, "10": 0.0, "15": 0.0},
        "scenario_effective_sample_size": 256.0,
        "confidence_grade": "E",
        "ruleset_hash": "1" * 64,
        "model_version_ids": [],
        "dataset_version_ids": [],
        "source_bundle_ids": [],
        "upstream_stage8_sha256s": ["2" * 64],
    }
    # Full point-summary contract is validated; the SQL envelope deliberately
    # omits unrelated AnalysisSnapshot fields and is never admitted as a run.
    summary = GameweekPlayerProjectionSummary.model_validate_json(json.dumps(base))
    summaries = {
        f"p{i}": summary.model_dump(mode="json") | {"player_id": f"p{i}"} for i in range(760)
    }
    fixtures = []
    for fixture_index in range(10):
        members = range(fixture_index * 76, (fixture_index + 1) * 76)
        fixtures.append(
            {
                "gameweek": 1,
                "official_fixture_id": fixture_index + 11,
                "fixture_id": f"fixture{fixture_index}",
                "summaries": {f"p{i}": summaries[f"p{i}"] for i in members},
                "minutes": {
                    f"p{i}": {
                        "p_start": "1.000000000000",
                        "p_zero_minutes": "0.000000000000",
                        "expected_minutes": "90.000000",
                        "minute_pmf": ["0.000000000000"] * 90 + ["1.000000000000"],
                    }
                    for i in members
                },
            }
        )
    payload = json.dumps(
        {
            "view": {
                "players": [
                    {
                        "catalogue": {"official_id": i + 1, "player_id": f"p{i}"},
                        "expected_points": 2.0,
                    }
                    for i in range(760)
                ]
            },
            "presentation": {
                "gameweeks": [{"gameweek": 1, "summaries": summaries}],
                "fixtures": fixtures,
            },
        }
    )
    assert 10_000_000 < len(payload.encode()) < 32 * 1024 * 1024
    timings = {}
    with sqlite3.connect(":memory:") as database:
        database.executescript(_SCHEMA + _QUALITY_VIEWS)
        database.execute("INSERT INTO snapshots VALUES(?,?,?)", ("owned", "digest", payload))
        database.execute(
            "INSERT INTO publications VALUES(?,?,?,?)", ("owned", "digest", "canonical", "time")
        )
        for view, expected in (
            ("player_gameweek_metrics_v2", 760),
            ("player_fixture_metrics_v2", 760),
            ("player_component_metrics_v2", 2 * 760 * len(POINT_COMPONENT_NAMES)),
        ):
            started = perf_counter()
            database.set_progress_handler(
                lambda origin=started: int(perf_counter() - origin > 5), 10000
            )
            assert database.execute(f"SELECT count(*) FROM {view}").fetchone()[0] == expected
            timings[view] = perf_counter() - started
            assert timings[view] < 5
    print(
        json.dumps(
            {
                "synthetic_sql_only": True,
                "payload_bytes": len(payload.encode()),
                "players": 760,
                "seconds": timings,
            }
        )
    )
