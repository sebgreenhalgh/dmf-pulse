"""Focused MIN-007D conditional-minute contract tests."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.availability.minutes import (
    MINUTE_ARTIFACT_SHA256,
    MinuteModelValidationError,
    fit_minute_priors,
    predict_conditional_minutes,
)

pytestmark = pytest.mark.unit


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def training(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007/training_dataset.json")
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def history(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007/canonical_history.json")
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def policy(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007C/minutes_baseline_policy.json")
    assert isinstance(value, dict)
    return value


def test_fit_matches_frozen_identity(
    training: dict[str, object], policy: dict[str, object]
) -> None:
    artifact = fit_minute_priors(training, policy=policy)
    body = artifact.model_dump(mode="json")
    assert body["artifact_sha256"] == MINUTE_ARTIFACT_SHA256
    assert body["training_example_count"] == 368
    assert set(body["minute_priors"]) == {"GK", "DEF", "MID", "FWD"}
    for position in body["minute_priors"].values():
        for role, vector in position.items():
            assert len(vector) == 91
            assert vector[0] == "0.000000000000" if role == "START" else True
            assert sum((Decimal(value) for value in vector), Decimal(0)) == Decimal(1)


def test_prediction_keeps_decimal_raw_pmf_and_public_residual(
    history: dict[str, object], training: dict[str, object], policy: dict[str, object]
) -> None:
    artifact = fit_minute_priors(training, policy=policy)
    rows = history["rows"]
    assert isinstance(rows, list) and rows
    source = next(row for row in rows if row["role_label"] == "START")
    context = {
        "as_of": "2026-09-01T12:00:00Z",
        "cutoff_sequence_index": 999,
        "manager_regime_id": source["manager_regime_id"],
        "team_id": source["team_id"],
        "team_key": source["team_key"],
    }
    result = predict_conditional_minutes(
        history,
        artifact,
        context=context,
        player_id=source["player_id"],
        position=source["position"],
        role="START",
        policy=policy,
    )
    assert len(result.minute_pmf) == 91
    assert all(isinstance(value, Decimal) for value in result.minute_pmf)
    public = result.model_dump(mode="json")["minute_pmf"]
    assert len(public) == 91
    assert sum((Decimal(value) for value in public), Decimal(0)) == Decimal(1)


def test_future_and_different_team_rows_do_not_change_result(
    history: dict[str, object], training: dict[str, object], policy: dict[str, object]
) -> None:
    artifact = fit_minute_priors(training, policy=policy)
    rows = history["rows"]
    assert isinstance(rows, list)
    source = next(row for row in rows if row["role_label"] == "START")
    context = {
        "as_of": "2026-06-30T12:00:00Z",
        "cutoff_sequence_index": 100,
        "manager_regime_id": source["manager_regime_id"],
        "team_id": source["team_id"],
        "team_key": source["team_key"],
    }
    baseline = predict_conditional_minutes(
        history,
        artifact,
        context=context,
        player_id=source["player_id"],
        position=source["position"],
        role="START",
        policy=policy,
    )
    changed = copy.deepcopy(history)
    future = copy.deepcopy(source)
    future["example_id"] = "4f8dd823-0d8c-5792-9b04-a5bb4987d999"
    future["fixture_id"] = "140a759f-66b4-5157-aea3-d52d85411899"
    future["sequence_index"] = 1000
    future["feature_cutoff"] = "2027-01-01T12:00:00Z"
    other = copy.deepcopy(source)
    other["example_id"] = "4f8dd823-0d8c-5792-9b04-a5bb4987d998"
    other["fixture_id"] = "140a759f-66b4-5157-aea3-d52d85411898"
    other["team_key"] = "beta"
    other["team_id"] = "180de9c2-c14a-5b04-82b2-7397ebac60e8"
    changed["rows"] = [*rows, future, other]
    actual = predict_conditional_minutes(
        changed,
        artifact,
        context=context,
        player_id=source["player_id"],
        position=source["position"],
        role="START",
        policy=policy,
    )
    assert actual == baseline


def test_invalid_role_position_and_player_fail_closed(
    history: dict[str, object], training: dict[str, object], policy: dict[str, object]
) -> None:
    artifact = fit_minute_priors(training, policy=policy)
    with pytest.raises(MinuteModelValidationError):
        predict_conditional_minutes(
            history,
            artifact,
            context={
                "as_of": "2026-09-01T12:00:00Z",
                "cutoff_sequence_index": 99,
                "manager_regime_id": "b9d90a34-4a83-5f26-9ba2-b17e99883bd5",
                "team_id": "cc1083fa-0c4a-59ab-b6c5-60c04f760782",
                "team_key": "alpha",
            },
            player_id="not-a-uuid",
            position="MID",
            role="START",
            policy=policy,
        )
