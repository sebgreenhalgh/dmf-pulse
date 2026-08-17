from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.evaluation.artifacts import seal
from dmf_pulse.evaluation.errors import EvaluationError
from dmf_pulse.evaluation.models import (
    DatasetMode,
    ForecastArtifact,
    OutcomeLabel,
    ProbabilityBoundaryPolicy,
    TargetFunctional,
)
from dmf_pulse.evaluation.point_metrics import (
    pinball_loss,
    score_forecast,
    score_frozen_point_forecasts,
)
from dmf_pulse.evaluation.probability_metrics import (
    multiclass_brier,
    score_multiclass_probabilities,
    score_probabilities,
)
from dmf_pulse.evaluation.service import load_json

pytestmark = pytest.mark.unit


def test_point_metrics_match_audited_values() -> None:
    result = score_forecast(
        (Decimal(5), Decimal(7), Decimal(4), Decimal(8)),
        (Decimal(4), Decimal(9), Decimal(4), Decimal(7)),
    )
    assert result.mae == Decimal(1)
    assert result.rmse == Decimal("1.2247448713915890490986420373529456959829737403283")
    assert result.signed_bias == Decimal(0)
    assert result.median_absolute_error == Decimal(1)
    assert result.target_functional is TargetFunctional.MEAN


def test_quantile_metrics_require_alignment() -> None:
    assert pinball_loss(Decimal(4), Decimal(6), Decimal("0.75")) == Decimal("1.50")
    result = score_forecast(
        (Decimal(4), Decimal(5)),
        (Decimal(6), Decimal(4)),
        target_functional=TargetFunctional.QUANTILE,
        quantile=Decimal("0.75"),
    )
    assert result.pinball_loss == Decimal("0.875")
    with pytest.raises(ValueError, match="explicit"):
        score_forecast(
            (Decimal(1),),
            (Decimal(1),),
            target_functional=TargetFunctional.QUANTILE,
        )
    with pytest.raises(ValueError, match="only valid"):
        score_forecast((Decimal(1),), (Decimal(1),), quantile=Decimal("0.5"))
    with pytest.raises(ValueError, match="same nonzero"):
        score_forecast((), ())


def test_point_scoring_requires_sealed_forecasts_and_later_final_labels() -> None:
    payload = load_json(Path("fixtures/historical/synthetic_five_gw/projections_input.json"))
    forecasts = tuple(ForecastArtifact.model_validate(item) for item in payload["forecasts"])
    labels = tuple(OutcomeLabel.model_validate(item) for item in payload["labels"])
    result = score_frozen_point_forecasts(forecasts, labels)
    assert result.count == 4 and result.mae == Decimal(1)

    tampered = forecasts[0].model_copy(update={"point_forecast": Decimal(99)})
    with pytest.raises(EvaluationError, match="semantic payload"):
        score_frozen_point_forecasts((tampered, *forecasts[1:]), labels)

    too_late = seal(
        labels[0].model_copy(
            update={"finalized_at": forecasts[0].lineage.label_finality_cutoff + timedelta(days=1)}
        ),
        "label_sha256",
    )
    with pytest.raises(ValueError, match="finality cutoff"):
        score_frozen_point_forecasts(forecasts, (too_late, *labels[1:]))


def test_frozen_point_scoring_rejects_incompatible_or_unscorable_cohorts() -> None:
    payload = load_json(Path("fixtures/historical/synthetic_five_gw/projections_input.json"))
    forecasts = tuple(ForecastArtifact.model_validate(item) for item in payload["forecasts"])
    labels = tuple(OutcomeLabel.model_validate(item) for item in payload["labels"])

    with pytest.raises(ValueError, match="same nonzero"):
        score_frozen_point_forecasts((), ())
    duplicate_id = forecasts[1].model_copy(update={"forecast_id": forecasts[0].forecast_id})
    with pytest.raises(ValueError, match="forecast IDs"):
        score_frozen_point_forecasts((forecasts[0], duplicate_id, *forecasts[2:]), labels)
    wrong_target = labels[0].model_copy(update={"target_id": "another-target"})
    with pytest.raises(ValueError, match="targets differ"):
        score_frozen_point_forecasts(forecasts, (wrong_target, *labels[1:]))

    def altered_forecast(**updates: object) -> ForecastArtifact:
        return seal(forecasts[0].model_copy(update=updates), "forecast_sha256")

    incompatible = (
        (altered_forecast(dataset_mode=DatasetMode.RECONSTRUCTED), "dataset modes"),
        (altered_forecast(benchmark_id="B0A_RECENT_POINTS_LAST_3"), "benchmarks"),
        (altered_forecast(horizon=2), "horizons"),
    )
    for changed, message in incompatible:
        with pytest.raises(ValueError, match=message):
            score_frozen_point_forecasts((changed, *forecasts[1:]), labels)

    probability_only = altered_forecast(
        point_forecast=None,
        probability_forecast=Decimal("0.5"),
    )
    with pytest.raises(ValueError, match="point payload"):
        score_frozen_point_forecasts((probability_only, *forecasts[1:]), labels)

    wrong_parent = forecasts[0].lineage.model_copy(update={"code_commit": "f" * 40})
    with pytest.raises(ValueError, match="exact Stage-12 parent"):
        score_frozen_point_forecasts(
            (altered_forecast(lineage=wrong_parent), *forecasts[1:]),
            labels,
        )
    early_label = seal(
        labels[0].model_copy(update={"finalized_at": forecasts[0].lineage.forecast_origin}),
        "label_sha256",
    )
    with pytest.raises(ValueError, match="revealed after"):
        score_frozen_point_forecasts(forecasts, (early_label, *labels[1:]))
    no_finality = forecasts[0].lineage.model_copy(update={"label_finality_cutoff": None})
    with pytest.raises(ValueError, match="finality cutoff"):
        score_frozen_point_forecasts(
            (altered_forecast(lineage=no_finality), *forecasts[1:]),
            labels,
        )


def test_probability_metrics_exact_boundaries_are_not_silently_clipped() -> None:
    unbounded = score_probabilities((Decimal(0),), (1,))
    assert unbounded.status == "UNBOUNDED"
    assert unbounded.log_loss is None

    multirow_unbounded = score_multiclass_probabilities(
        (
            (Decimal(1), Decimal(0)),
            (Decimal("0.2"), Decimal("0.8")),
        ),
        (1, 0),
    )
    assert multirow_unbounded.status == "UNBOUNDED"
    assert multirow_unbounded.brier_score == Decimal("1.64")
    clipped = score_probabilities(
        (Decimal(0),),
        (1,),
        boundary_policy=ProbabilityBoundaryPolicy.DECLARED_EPSILON,
        epsilon=Decimal("0.01"),
    )
    assert clipped.status == "FINITE"
    assert clipped.epsilon == Decimal("0.01")
    assert clipped.brier_score == Decimal(1)


def test_probability_input_validation_and_finite_score() -> None:
    result = score_probabilities((Decimal("0.8"), Decimal("0.2")), (1, 0))
    assert result.brier_score == Decimal("0.04")
    assert result.log_loss is not None
    with pytest.raises(ValueError, match="binary"):
        score_probabilities((Decimal("0.5"),), (2,))
    with pytest.raises(ValueError, match="epsilon"):
        score_probabilities((Decimal("0.5"),), (1,), epsilon=Decimal("0.1"))
    with pytest.raises(ValueError, match="requires epsilon"):
        score_probabilities(
            (Decimal("0.5"),),
            (1,),
            boundary_policy=ProbabilityBoundaryPolicy.DECLARED_EPSILON,
        )


def test_multiclass_brier_is_proper_and_validated() -> None:
    value = multiclass_brier(
        ((Decimal("0.7"), Decimal("0.2"), Decimal("0.1")),),
        (0,),
    )
    assert value == Decimal("0.14")
    with pytest.raises(ValueError, match="sum"):
        multiclass_brier(((Decimal("0.7"), Decimal("0.2")),), (0,))
    with pytest.raises(ValueError, match="outside"):
        multiclass_brier(((Decimal("0.5"), Decimal("0.5")),), (2,))
    with pytest.raises(ValueError, match="probabilities"):
        multiclass_brier(((Decimal("-0.1"), Decimal("1.1")),), (1,))


def test_multiclass_log_and_brier_boundary_policy_is_explicit() -> None:
    finite = score_multiclass_probabilities(
        ((Decimal("0.7"), Decimal("0.2"), Decimal("0.1")),),
        (0,),
    )
    assert finite.status == "FINITE"
    assert finite.brier_score == Decimal("0.14")
    assert finite.class_count == 3

    unbounded = score_multiclass_probabilities(
        ((Decimal(1), Decimal(0), Decimal(0)),),
        (1,),
    )
    assert unbounded.status == "UNBOUNDED"
    assert unbounded.log_loss is None

    floored = score_multiclass_probabilities(
        ((Decimal(1), Decimal(0), Decimal(0)),),
        (1,),
        boundary_policy=ProbabilityBoundaryPolicy.DECLARED_EPSILON,
        epsilon=Decimal("0.01"),
    )
    assert floored.status == "FINITE"
    assert floored.epsilon == Decimal("0.01")

    with pytest.raises(ValueError, match="class_count"):
        score_multiclass_probabilities(
            ((Decimal("0.5"), Decimal("0.5")),),
            (0,),
            boundary_policy=ProbabilityBoundaryPolicy.DECLARED_EPSILON,
            epsilon=Decimal("0.5"),
        )
    with pytest.raises(ValueError, match="at least two"):
        score_multiclass_probabilities(((Decimal(1),),), (0,))
    with pytest.raises(ValueError, match="outside"):
        score_multiclass_probabilities(((Decimal("0.5"), Decimal("0.5")),), (True,))
