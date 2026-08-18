"""Deterministic P0 and regularized competing-logit P1 models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext
from typing import Literal, cast

from dmf_pulse.evaluation.artifacts import semantic_sha256, verify_sealed
from dmf_pulse.prices.artifacts import seal_competing_logit
from dmf_pulse.prices.configuration import PriceConfig, price_config_sha256
from dmf_pulse.prices.errors import PriceLeakageError
from dmf_pulse.prices.models import (
    CompetingLogitArtifact,
    EventCoefficients,
    FeatureValue,
    PriceEvent,
    PriceFeatureVector,
    PriceProbabilityVector,
    PriceTrainingExample,
    require_utc,
)


def predict_no_change() -> PriceProbabilityVector:
    """Mandatory honest null benchmark."""

    return PriceProbabilityVector(
        probability_fall=Decimal(0),
        probability_no_change=Decimal(1),
        probability_rise=Decimal(0),
    )


def _bounded_exp(value: Decimal, *, score_cap: Decimal) -> Decimal:
    bounded = min(max(value, -score_cap), score_cap)
    with localcontext() as context:
        context.prec = 50
        return bounded.exp()


def _probabilities(
    fall_score: Decimal, rise_score: Decimal, *, score_cap: Decimal
) -> PriceProbabilityVector:
    fall_exp = _bounded_exp(fall_score, score_cap=score_cap)
    rise_exp = _bounded_exp(rise_score, score_cap=score_cap)
    denominator = Decimal(1) + fall_exp + rise_exp
    fall = fall_exp / denominator
    raw_rise = rise_exp / denominator
    no_change = Decimal(1) - fall - raw_rise
    rise = Decimal(1) - (fall + no_change)
    return PriceProbabilityVector(
        probability_fall=fall,
        probability_no_change=no_change,
        probability_rise=rise,
    )


def _linear_score(coefficients: EventCoefficients, vector: PriceFeatureVector) -> Decimal:
    values = vector.as_mapping()
    return coefficients.intercept + sum(
        (item.value * values[item.name] for item in coefficients.coefficients),
        Decimal(0),
    )


def predict_competing_logit(
    artifact: CompetingLogitArtifact,
    vector: PriceFeatureVector,
) -> PriceProbabilityVector:
    verify_sealed(artifact, "artifact_sha256")
    if tuple(item.name for item in vector.values) != artifact.feature_names:
        raise ValueError("prediction feature vector differs from the fitted model schema")
    fall_coefficients, rise_coefficients = artifact.event_coefficients
    return _probabilities(
        _linear_score(fall_coefficients, vector),
        _linear_score(rise_coefficients, vector),
        score_cap=artifact.score_cap,
    )


def fit_competing_logit(
    examples: tuple[PriceTrainingExample, ...],
    *,
    training_cutoff: datetime,
    config: PriceConfig,
) -> CompetingLogitArtifact:
    """Fit a small auditable multinomial model using chronological full-batch updates."""

    training_cutoff = require_utc(training_cutoff, field_name="training_cutoff")
    if not examples:
        raise ValueError("competing-logit training requires examples")
    canonical = tuple(
        sorted(
            examples,
            key=lambda item: (
                item.feature_vector.information_cutoff,
                item.label_available_at,
                item.example_id,
            ),
        )
    )
    if examples != canonical:
        raise ValueError("training examples must be supplied in chronological canonical order")
    ids = tuple(item.example_id for item in examples)
    if len(ids) != len(set(ids)):
        raise ValueError("training example IDs must be unique")
    contaminated = tuple(
        item.example_id for item in examples if item.label_available_at > training_cutoff
    )
    if contaminated:
        raise PriceLeakageError(
            "PRICE_TRAINING_FUTURE_LABEL_BLOCKED",
            "training cutoff precedes label availability for: " + ", ".join(contaminated),
        )
    names = config.competing_logit.feature_names
    for item in examples:
        if tuple(value.name for value in item.feature_vector.values) != names:
            raise ValueError("training feature vector differs from configured schema")
    coefficients = {
        PriceEvent.FALL: {name: Decimal(0) for name in names},
        PriceEvent.RISE: {name: Decimal(0) for name in names},
    }
    intercepts = {PriceEvent.FALL: Decimal(0), PriceEvent.RISE: Decimal(0)}
    count = Decimal(len(examples))
    for _ in range(config.competing_logit.epochs):
        gradients = {
            PriceEvent.FALL: {name: Decimal(0) for name in names},
            PriceEvent.RISE: {name: Decimal(0) for name in names},
        }
        intercept_gradients = {PriceEvent.FALL: Decimal(0), PriceEvent.RISE: Decimal(0)}
        for example in examples:
            values = example.feature_vector.as_mapping()
            scores = {
                event: intercepts[event]
                + sum((coefficients[event][name] * values[name] for name in names), Decimal(0))
                for event in (PriceEvent.FALL, PriceEvent.RISE)
            }
            probabilities = _probabilities(
                scores[PriceEvent.FALL],
                scores[PriceEvent.RISE],
                score_cap=config.competing_logit.score_cap,
            )
            for event in (PriceEvent.FALL, PriceEvent.RISE):
                residual = Decimal(example.event is event) - probabilities.for_event(event)
                intercept_gradients[event] += residual
                for name in names:
                    gradients[event][name] += residual * values[name]
        for event in (PriceEvent.FALL, PriceEvent.RISE):
            intercepts[event] += (
                config.competing_logit.learning_rate * intercept_gradients[event] / count
            )
            for name in names:
                regularized = gradients[event][name] / count - (
                    config.competing_logit.regularization_l2 * coefficients[event][name]
                )
                coefficients[event][name] += config.competing_logit.learning_rate * regularized
    model_id = semantic_sha256(
        {
            "model_version": config.competing_logit.model_version,
            "training_cutoff": training_cutoff.isoformat(),
            "training_example_ids": sorted(ids),
            "configuration_sha256": price_config_sha256(config),
        }
    )
    value = CompetingLogitArtifact(
        model_id=f"p1-{model_id[:24]}",
        model_version=config.competing_logit.model_version,
        feature_schema_version=config.competing_logit.feature_schema_version,
        feature_names=names,
        event_coefficients=cast(
            tuple[EventCoefficients, EventCoefficients],
            tuple(
                EventCoefficients(
                    event=cast(Literal[PriceEvent.FALL, PriceEvent.RISE], event),
                    intercept=intercepts[event],
                    coefficients=tuple(
                        FeatureValue(name=name, value=coefficients[event][name]) for name in names
                    ),
                )
                for event in (PriceEvent.FALL, PriceEvent.RISE)
            ),
        ),
        regularization_l2=config.competing_logit.regularization_l2,
        learning_rate=config.competing_logit.learning_rate,
        epochs=config.competing_logit.epochs,
        score_cap=config.competing_logit.score_cap,
        training_cutoff=training_cutoff,
        training_example_ids=tuple(sorted(ids)),
        dataset_modes=tuple(sorted({item.dataset_mode for item in examples}, key=str)),
        calibration_version=config.competing_logit.calibration_version,
        configuration_sha256=price_config_sha256(config),
        artifact_sha256="0" * 64,
    )
    return seal_competing_logit(value)
