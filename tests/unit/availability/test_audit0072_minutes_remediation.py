"""Adversarial regressions for the MIN-007D audit remediation."""

from __future__ import annotations

import json
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError

from dmf_pulse.availability.minutes import (
    MinuteConditionalPrediction,
    MinuteModelValidationError,
    fit_minute_priors,
    predict_conditional_minutes,
)

pytestmark = pytest.mark.unit


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def policy(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007C/minutes_baseline_policy.json")
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def training(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007/training_dataset.json")
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def canonical_history(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007/canonical_history.json")
    assert isinstance(value, dict)
    return value


def _source(history: dict[str, object]) -> dict[str, object]:
    rows = history["rows"]
    assert isinstance(rows, list)
    row = next(row for row in rows if row["role_label"] == "START")
    assert isinstance(row, dict)
    return row


def _context(source: dict[str, object]) -> dict[str, object]:
    return {
        "as_of": "2026-09-01T12:00:00Z",
        "cutoff_sequence_index": 999,
        "manager_regime_id": source["manager_regime_id"],
        "team_id": source["team_id"],
        "team_key": source["team_key"],
    }


def _reduced_row(
    source: dict[str, object],
    *,
    example_id: str,
    fixture_id: str,
    sequence_index: int = 1,
    feature_cutoff: str = "2026-06-01T12:00:00Z",
    label_usable_at: str = "2026-06-01T17:00:00Z",
) -> dict[str, object]:
    return {
        "evidence_type": "COMPETITIVE",
        "example_id": example_id,
        "fixture_id": fixture_id,
        "feature_cutoff": feature_cutoff,
        "label_usable_at": label_usable_at,
        "manager_regime_id": source["manager_regime_id"],
        "minutes_label": 80,
        "player_id": source["player_id"],
        "position": source["position"],
        "role_label": "START",
        "sequence_index": sequence_index,
        "team_id": source["team_id"],
        "team_key": source["team_key"],
    }


def _prediction(
    history: dict[str, object],
    artifact: object,
    policy: dict[str, object],
) -> MinuteConditionalPrediction:
    source = _source(history)
    result = predict_conditional_minutes(
        history,
        artifact,
        context=_context(source),
        player_id=source["player_id"],
        position=source["position"],
        role="START",
        policy=policy,
    )
    assert isinstance(result, MinuteConditionalPrediction)
    return result


def test_stored_conditional_pmf_is_exactly_normalized(
    canonical_history: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_minute_priors(training, policy=policy)
    result = _prediction(canonical_history, artifact, policy)
    with localcontext() as context:
        context.prec = 256
        assert sum(result.minute_pmf, Decimal(0)) == Decimal(1)
    with localcontext() as context:
        context.prec = 200
        assert sum(result.minute_pmf, Decimal(0)) == Decimal(1)
    assert result.minute_pmf[0] == Decimal(0)


def test_repeated_prediction_is_identical(
    canonical_history: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_minute_priors(training, policy=policy)
    assert _prediction(canonical_history, artifact, policy) == _prediction(
        canonical_history, artifact, policy
    )


@pytest.mark.parametrize(
    "alias",
    [
        lambda value: "{" + value.upper() + "}",
        lambda value: value.replace("-", ""),
    ],
    ids=["braced-uppercase", "unhyphenated"],
)
def test_uuid_example_aliases_collide_before_filtering(
    canonical_history: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
    alias: object,
) -> None:
    artifact = fit_minute_priors(training, policy=policy)
    source = _source(canonical_history)
    example_id = str(uuid5(UUID(source["player_id"]), "audit-example"))
    alias_fn = alias
    assert callable(alias_fn)
    rows = [
        _reduced_row(
            source,
            example_id=example_id,
            fixture_id=str(uuid5(UUID(source["player_id"]), "fixture-one")),
        ),
        _reduced_row(
            source,
            example_id=alias_fn(example_id),
            fixture_id=str(uuid5(UUID(source["player_id"]), "fixture-two")),
            sequence_index=1000,
            feature_cutoff="2027-01-01T12:00:00Z",
        ),
    ]
    with pytest.raises(MinuteModelValidationError, match="duplicate example_id"):
        predict_conditional_minutes(
            {"rows": rows},
            artifact,
            context=_context(source),
            player_id=source["player_id"],
            position=source["position"],
            role="START",
            policy=policy,
        )


def test_distinct_readable_synthetic_ids_remain_opaque(
    canonical_history: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_minute_priors(training, policy=policy)
    source = _source(canonical_history)
    rows = [
        _reduced_row(
            source,
            example_id="synthetic-a",
            fixture_id=str(uuid5(UUID(source["player_id"]), "fixture-a")),
        ),
        _reduced_row(
            source,
            example_id="synthetic-b",
            fixture_id=str(uuid5(UUID(source["player_id"]), "fixture-b")),
            sequence_index=2,
        ),
    ]
    result = predict_conditional_minutes(
        {"rows": rows},
        artifact,
        context=_context(source),
        player_id=source["player_id"],
        position=source["position"],
        role="START",
        policy=policy,
    )
    assert result.eligible_history_count == 2
    assert result.matching_role_history_count == 2


def test_model_validate_rejects_invalid_pmf_shapes_and_values(
    canonical_history: dict[str, object],
) -> None:
    source = _source(canonical_history)
    base = {
        "player_id": source["player_id"],
        "position": "MID",
        "role": "START",
        "eligible_history_count": 1,
        "matching_role_history_count": 1,
    }
    invalid_vectors = [
        (Decimal(0),) * 91,
        (Decimal(1),) + (Decimal(0),) * 90,
        (Decimal(1),) * 90,
        (Decimal(-1),) + (Decimal(2),) + (Decimal(0),) * 89,
        (Decimal("NaN"),) + (Decimal(0),) * 90,
        (Decimal("Infinity"),) + (Decimal(0),) * 90,
    ]
    for minute_pmf in invalid_vectors:
        with pytest.raises((ValidationError, MinuteModelValidationError)):
            MinuteConditionalPrediction.model_validate({**base, "minute_pmf": minute_pmf})
    with pytest.raises((ValidationError, MinuteModelValidationError)):
        MinuteConditionalPrediction.model_validate(
            {**base, "role": "OUT", "minute_pmf": (Decimal(0),) * 91}
        )


def test_model_copy_revalidates_updates(
    canonical_history: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_minute_priors(training, policy=policy)
    result = _prediction(canonical_history, artifact, policy)
    assert (
        result.model_copy(update={"eligible_history_count": result.eligible_history_count})
        == result
    )
    invalid_updates = [
        {"role": "OUT"},
        {"minute_pmf": (Decimal(-1), *result.minute_pmf[1:])},
        {"minute_pmf": (Decimal(0),) * 91},
    ]
    for update in invalid_updates:
        with pytest.raises((ValidationError, MinuteModelValidationError)):
            result.model_copy(update=update)
