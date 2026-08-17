from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.evaluation.decision_regret import calculate_decision_regret
from dmf_pulse.evaluation.distribution_metrics import ranked_probability_score
from dmf_pulse.evaluation.folds import ForecastOrigin, WalkForwardConfig, build_walk_forward_folds
from dmf_pulse.evaluation.models import DatasetMode
from dmf_pulse.evaluation.multivariate_metrics import energy_score
from tests.evaluation_helpers import BASE

pytestmark = pytest.mark.property


def test_semantic_hash_is_key_order_invariant() -> None:
    assert semantic_sha256({"b": 2, "a": 1}) == semantic_sha256({"a": 1, "b": 2})


def test_regret_identity_holds_over_integer_grid() -> None:
    for decision in range(-3, 8):
        for comparator in range(-3, 8):
            result = calculate_decision_regret(
                decision_id="d",
                comparator_id="c",
                realised_decision_utility=Decimal(decision),
                realised_comparator_utility=Decimal(comparator),
            )
            assert result.regret == Decimal(comparator - decision)


def test_rps_and_energy_are_nonnegative_over_small_grid() -> None:
    for observed in (Decimal(0), Decimal(1), Decimal(2)):
        assert (
            ranked_probability_score(
                {
                    Decimal(0): Decimal("0.2"),
                    Decimal(1): Decimal("0.5"),
                    Decimal(2): Decimal("0.3"),
                },
                observed,
            )
            >= 0
        )
    samples = ((Decimal(0), Decimal(1)), (Decimal(1), Decimal(0)))
    for observed in samples:
        assert energy_score(samples, observed) >= 0


def test_future_origin_never_enters_earlier_training_or_inner_selection() -> None:
    origins = tuple(
        ForecastOrigin(
            origin_id=f"o{i}",
            forecast_origin=BASE + timedelta(days=i),
            information_cutoff=BASE + timedelta(days=i),
            label_available_at=BASE + timedelta(days=i, hours=12),
        )
        for i in range(8)
    )
    folds = build_walk_forward_folds(
        origins,
        config=WalkForwardConfig(
            dataset_mode=DatasetMode.COUNTERFACTUAL,
            minimum_training_origins=1,
            inner_minimum_training_origins=1,
        ),
    )
    order = {origin.origin_id: index for index, origin in enumerate(origins)}
    for fold in folds:
        outer_index = order[fold.forecast_origin_id]
        assert all(order[item] < outer_index for item in fold.training_origin_ids)
        for inner in fold.inner_folds:
            validation_index = order[inner.validation_origin_id]
            assert all(order[item] < validation_index for item in inner.training_origin_ids)
