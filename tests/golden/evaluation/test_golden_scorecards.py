from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.evaluation.service import EvaluationService, load_json

pytestmark = pytest.mark.golden


def test_walk_forward_golden_hashes_and_shape() -> None:
    folds = EvaluationService().build_folds(
        load_json(Path("fixtures/historical/synthetic_five_gw/folds_input.json"))
    )
    assert tuple(item.forecast_origin_id for item in folds) == ("gw2", "gw3", "gw4", "gw5", "gw6")
    assert tuple(item.holdout for item in folds) == (False, False, False, False, True)
    assert all(len(item.fold_sha256) == 64 for item in folds)


def test_benchmark_golden_values() -> None:
    values = {
        item.benchmark.benchmark_id: item.point_forecast
        for item in EvaluationService().benchmark(
            load_json(Path("fixtures/historical/benchmark_player_histories/benchmark_input.json"))
        )
    }
    assert values == {
        "B0A_RECENT_POINTS_LAST_3": Decimal(8),
        "B0B_RECENT_POINTS_LAST_5": Decimal(6),
        "B0C_RECENT_POINTS_EWMA": Decimal("7.8750"),
        "B1_OFFICIAL_FPL_FORM": Decimal("6.2"),
        "B2_MARKET_ONLY": Decimal("5.5"),
        "B3_MARKET_PLUS_MINUTES": Decimal("5.6"),
        "B4_ACCEPTED_PULSE_BASELINE": Decimal("6.1"),
        "B5A_PERFECT_LINEUP_MINUTES": Decimal(7),
        "B5B_PERFECT_FOOTBALL_OUTCOMES": Decimal(11),
        "B5C_PERFECT_GAMEWEEK_TRANSFERS": Decimal(12),
        "B5D_PERFECT_SEASON_POLICY": Decimal(15),
    }
