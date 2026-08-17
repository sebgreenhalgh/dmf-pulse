from __future__ import annotations

from datetime import timedelta

import pytest

from dmf_pulse.evaluation.folds import ForecastOrigin, WalkForwardConfig, build_walk_forward_folds
from dmf_pulse.evaluation.models import DatasetMode, FoldWindow
from tests.evaluation_helpers import BASE

pytestmark = pytest.mark.unit


def origins(count: int = 6) -> tuple[ForecastOrigin, ...]:
    return tuple(
        ForecastOrigin(
            origin_id=f"gw{index}",
            forecast_origin=BASE + timedelta(days=7 * index),
            information_cutoff=BASE + timedelta(days=7 * index),
            label_available_at=BASE + timedelta(days=7 * index + 2),
        )
        for index in range(count)
    )


def test_expanding_folds_are_nested_and_hash_deterministic() -> None:
    config = WalkForwardConfig(
        dataset_mode=DatasetMode.COUNTERFACTUAL,
        minimum_training_origins=1,
        inner_minimum_training_origins=1,
        holdout_origins=1,
    )
    first = build_walk_forward_folds(origins(), config=config)
    second = build_walk_forward_folds(origins(), config=config)
    assert first == second
    assert len(first) == 5
    assert first[0].training_origin_ids == ("gw0",)
    assert first[-1].training_origin_ids == ("gw0", "gw1", "gw2", "gw3", "gw4")
    assert first[-1].holdout
    assert not first[-2].holdout
    for fold in first:
        assert fold.forecast_origin_id not in fold.training_origin_ids
        assert all(
            inner.validation_origin_id in fold.training_origin_ids for inner in fold.inner_folds
        )


def test_rolling_window_truncates_history() -> None:
    config = WalkForwardConfig(
        dataset_mode=DatasetMode.RECONSTRUCTED,
        window=FoldWindow.ROLLING,
        minimum_training_origins=2,
        rolling_window_origins=2,
        inner_minimum_training_origins=1,
    )
    folds = build_walk_forward_folds(origins(), config=config)
    assert folds[-1].training_origin_ids == ("gw3", "gw4")


def test_late_label_is_not_used_for_training() -> None:
    values = list(origins(4))
    values[1] = values[1].model_copy(
        update={"label_available_at": values[3].forecast_origin + timedelta(days=1)}
    )
    folds = build_walk_forward_folds(
        tuple(values),
        config=WalkForwardConfig(
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            minimum_training_origins=1,
        ),
    )
    outer_gw3 = next(item for item in folds if item.forecast_origin_id == "gw3")
    assert "gw1" not in outer_gw3.training_origin_ids


def test_noncanonical_origin_order_and_duplicate_ids_fail() -> None:
    with pytest.raises(ValueError, match="chronological"):
        build_walk_forward_folds(
            tuple(reversed(origins(3))),
            config=WalkForwardConfig(dataset_mode=DatasetMode.COUNTERFACTUAL),
        )
    duplicate = list(origins(3))
    duplicate[2] = duplicate[2].model_copy(update={"origin_id": "gw1"})
    with pytest.raises(ValueError, match="unique"):
        build_walk_forward_folds(
            tuple(duplicate),
            config=WalkForwardConfig(dataset_mode=DatasetMode.COUNTERFACTUAL),
        )


def test_training_ids_preserve_chronology_not_lexicographic_name_order() -> None:
    values = list(origins(3))
    values[0] = values[0].model_copy(update={"origin_id": "z-earlier"})
    values[1] = values[1].model_copy(update={"origin_id": "a-later"})
    folds = build_walk_forward_folds(
        tuple(values),
        config=WalkForwardConfig(dataset_mode=DatasetMode.COUNTERFACTUAL),
    )
    assert folds[-1].training_origin_ids == ("z-earlier", "a-later")


def test_invalid_fold_configurations_fail() -> None:
    with pytest.raises(ValueError, match="rolling"):
        WalkForwardConfig(
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            window=FoldWindow.ROLLING,
        )
    with pytest.raises(ValueError, match="cannot declare"):
        WalkForwardConfig(
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            rolling_window_origins=2,
        )
    with pytest.raises(ValueError, match="leave history"):
        WalkForwardConfig(
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            window=FoldWindow.ROLLING,
            rolling_window_origins=1,
            inner_minimum_training_origins=1,
        )
    with pytest.raises(ValueError, match="holdout"):
        build_walk_forward_folds(
            origins(2),
            config=WalkForwardConfig(
                dataset_mode=DatasetMode.COUNTERFACTUAL,
                holdout_origins=3,
            ),
        )
    with pytest.raises(ValueError, match="requires forecast origins"):
        build_walk_forward_folds(
            (),
            config=WalkForwardConfig(dataset_mode=DatasetMode.COUNTERFACTUAL),
        )
    with pytest.raises(ValueError, match="no evaluable"):
        build_walk_forward_folds(
            origins(1),
            config=WalkForwardConfig(
                dataset_mode=DatasetMode.COUNTERFACTUAL,
                minimum_training_origins=2,
            ),
        )
