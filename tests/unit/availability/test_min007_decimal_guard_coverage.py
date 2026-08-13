"""Boundary coverage for typed decimal guards in the Stage-7 core."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.availability.lineup import InvalidLineupResult, sample_coherent_lineups
from dmf_pulse.availability.minutes import (
    MinuteModelValidationError,
    fit_minute_priors,
    predict_conditional_minutes,
)

pytestmark = pytest.mark.unit


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def inputs(repository_root: Path) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    return (
        _read(repository_root / "fixtures/availability/MIN-007/training_dataset.json"),
        _read(repository_root / "fixtures/availability/MIN-007/canonical_history.json"),
        _read(repository_root / "fixtures/availability/MIN-007G/minutes_baseline_policy.json"),
    )


def _candidates() -> list[dict[str, object]]:
    positions = ["GK", "GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 10
    return [
        {
            "player_id": str(uuid5(NAMESPACE_URL, f"min007-decimal-guard-{index}")),
            "player_key": f"decimal_guard_{index}",
            "position": position,
            "start_weight": "0.500000",
            "bench_weight": "0.500000",
            "hard_ineligible": False,
        }
        for index, position in enumerate(positions)
    ]


def test_minutes_rejects_invalid_decimal_text_at_artifact_boundary(
    inputs: tuple[dict[str, object], dict[str, object], dict[str, object]],
) -> None:
    training, history, policy = inputs
    artifact = fit_minute_priors(training, policy=policy)
    invalid = artifact.model_dump(mode="json")
    priors = invalid["minute_priors"]
    assert isinstance(priors, dict)
    gk = priors["GK"]
    assert isinstance(gk, dict)
    start = gk["START"]
    assert isinstance(start, list)
    start[1] = "not-a-decimal"
    rows = history["rows"]
    assert isinstance(rows, list)
    row = next(item for item in rows if item["role_label"] == "START")
    with pytest.raises(MinuteModelValidationError, match="artifact failed schema validation"):
        predict_conditional_minutes(
            history,
            invalid,
            context={
                "as_of": "2026-09-01T12:00:00Z",
                "cutoff_sequence_index": 999,
                "manager_regime_id": row["manager_regime_id"],
                "team_id": row["team_id"],
                "team_key": row["team_key"],
            },
            player_id=row["player_id"],
            position=row["position"],
            role="START",
            policy=policy,
        )


def test_decimal_boundaries_preserve_deterministic_results(
    inputs: tuple[dict[str, object], dict[str, object], dict[str, object]],
) -> None:
    training, _, policy = inputs
    first = fit_minute_priors(training, policy=policy)
    second = fit_minute_priors(copy.deepcopy(training), policy=copy.deepcopy(policy))
    assert first == second
    assert isinstance(first.minute_priors["GK"]["START"][1], Decimal)


def test_lineup_rejects_invalid_decimal_text_at_public_boundary(
    inputs: tuple[dict[str, object], dict[str, object], dict[str, object]],
) -> None:
    _, _, policy = inputs
    candidates = _candidates()
    candidates[0]["start_weight"] = "not-a-decimal"
    result = sample_coherent_lineups(
        candidates,
        fixture_id="decimal-guard-fixture",
        team_id="decimal-guard-team",
        seed_suffix="",
        bench_size=9,
        bench_goalkeeper_slots=1,
        policy=policy,
    )
    assert isinstance(result, InvalidLineupResult)
    assert result.error_code == "INVALID_ROLE_WEIGHTS"
