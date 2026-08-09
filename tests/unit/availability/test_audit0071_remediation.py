"""Direct regression coverage for the AUDIT-007-1 remediation contract."""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.availability.models import parse_utc
from dmf_pulse.availability.role_model import (
    RoleModelValidationError,
    fit_role_baseline,
    predict_role_utilities,
)

pytestmark = pytest.mark.unit


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


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


@pytest.fixture(scope="module")
def training(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007/training_dataset.json")
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def stable_context(repository_root: Path) -> dict[str, object]:
    value = _read(repository_root / "fixtures/availability/MIN-007C/role_canaries.json")
    assert isinstance(value, dict)
    return next(item for item in value["cases"] if item["scenario"] == "stable_xi")


def test_r1_accepts_only_frozen_explicit_utc_timestamp_lexemes() -> None:
    for timestamp in (
        "2026-06-08T17:00:00Z",
        "2026-06-08T17:00:00+00:00",
        "2026-06-08T17:00:00.1Z",
        "2026-06-08T17:00:00.123456+00:00",
    ):
        assert parse_utc(timestamp, field_name="probe").utcoffset() == timedelta(0)

    for timestamp in (
        "2026-06-08T17:00:00",
        "2026-06-08T18:00:00+01:00",
        "2026-06-08T17:00:00-00:00",
        "2026-06-08 17:00:00+00:00",
        "20260608T170000+00:00",
        "2026-06-08t17:00:00Z",
        "2026-02-30T17:00:00Z",
    ):
        with pytest.raises(ValueError):
            parse_utc(timestamp, field_name="probe")


def test_r2_prediction_rejects_duplicate_player_fixture_before_filtering(
    history: dict[str, object],
    stable_context: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_role_baseline(training, policy=policy)
    changed = copy.deepcopy(history)
    rows = changed["rows"]
    assert isinstance(rows, list)
    source = next(
        row
        for row in rows
        if row["player_key"] == stable_context["focus_player_key"]
        and row["team_key"] == stable_context["team_key"]
        and row["sequence_index"] < stable_context["cutoff_sequence_index"]
    )
    assert isinstance(source, dict)
    duplicate = copy.deepcopy(source)
    duplicate["example_id"] = str(uuid5(NAMESPACE_URL, "min007r1-duplicate-example"))
    changed["rows"] = [*rows, duplicate]
    with pytest.raises(RoleModelValidationError, match="duplicate player-fixture target"):
        predict_role_utilities(
            changed,
            artifact,
            context=stable_context,
            player_key=stable_context["focus_player_key"],
            policy=policy,
        )


def test_r3_retains_decimal_utilities_and_exact_json_projection(
    history: dict[str, object],
    stable_context: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_role_baseline(training, policy=policy)
    result = predict_role_utilities(
        history,
        artifact,
        context=stable_context,
        player_key=stable_context["focus_player_key"],
        policy=policy,
    )
    assert all(isinstance(value, Decimal) for value in result.role_utilities.values())
    assert sum(result.role_utilities.values(), Decimal(0)) == Decimal(1)
    assert result.model_dump(mode="json")["role_utilities"] == {
        "START": "0.869934791257",
        "BENCH": "0.115876276881",
        "OUT": "0.014188931863",
    }


def test_r4_rejects_cross_player_canonical_id_override(
    history: dict[str, object],
    stable_context: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    artifact = fit_role_baseline(training, policy=policy)
    changed = copy.deepcopy(stable_context)
    changed["player_overrides"] = {
        stable_context["focus_player_key"]: {"player_id": "06527612-3dbd-5207-869f-a09b477baa3d"}
    }
    with pytest.raises(RoleModelValidationError, match="collides with another identity"):
        predict_role_utilities(
            history,
            artifact,
            context=changed,
            player_key=stable_context["focus_player_key"],
            policy=policy,
        )
