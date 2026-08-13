"""Exact Decimal boundary regressions for MIN-007R4."""

from __future__ import annotations

import json
from decimal import Decimal, getcontext
from fractions import Fraction
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from dmf_pulse.availability.lineup import (
    InvalidLineupResult,
    ProjectedLineupResult,
    sample_coherent_lineups,
)
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


def _pmf(residual: Decimal) -> tuple[Decimal, ...]:
    return (Decimal(0), Decimal(1), residual, *([Decimal(0)] * 88))


def _prediction(
    canonical_history: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
) -> MinuteConditionalPrediction:
    rows = canonical_history["rows"]
    assert isinstance(rows, list)
    source = next(row for row in rows if row["role_label"] == "START")
    assert isinstance(source, dict)
    artifact = fit_minute_priors(training, policy=policy)
    result = predict_conditional_minutes(
        canonical_history,
        artifact,
        context={
            "as_of": "2026-09-01T12:00:00Z",
            "cutoff_sequence_index": 999,
            "manager_regime_id": source["manager_regime_id"],
            "team_id": source["team_id"],
            "team_key": source["team_key"],
        },
        player_id=source["player_id"],
        position=source["position"],
        role="START",
        policy=policy,
    )
    assert isinstance(result, MinuteConditionalPrediction)
    return result


@pytest.mark.parametrize("residual", [Decimal("1E-300"), Decimal("1E-1000")])
def test_exact_pmf_residuals_are_rejected(residual: Decimal) -> None:
    with pytest.raises((MinuteModelValidationError, ValueError)):
        MinuteConditionalPrediction.model_validate(
            {
                "player_id": "00000000-0000-0000-0000-000000000001",
                "position": "MID",
                "role": "START",
                "eligible_history_count": 1,
                "matching_role_history_count": 1,
                "minute_pmf": _pmf(residual),
            }
        )


@pytest.mark.parametrize("ambient_precision", [10, 28, 60, 256])
def test_production_pmf_exact_sum_is_context_free(
    canonical_history: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
    ambient_precision: int,
) -> None:
    previous = getcontext().prec
    try:
        getcontext().prec = ambient_precision
        result = _prediction(canonical_history, training, policy)
        exact_sum = sum(
            (Fraction(*value.as_integer_ratio()) for value in result.minute_pmf), Fraction(0)
        )
    finally:
        getcontext().prec = previous
    assert exact_sum == Fraction(1)
    assert result.minute_pmf[0] == Decimal(0)


def test_model_copy_hidden_pmf_excess_is_rejected(
    canonical_history: dict[str, object],
    training: dict[str, object],
    policy: dict[str, object],
) -> None:
    result = _prediction(canonical_history, training, policy)
    with pytest.raises((MinuteModelValidationError, ValueError)):
        result.model_copy(update={"minute_pmf": _pmf(Decimal("1E-300"))})


def _candidates(
    start: Decimal | str = "0.5", bench: Decimal | str = "0.5"
) -> list[dict[str, object]]:
    positions = ["GK", "GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 10
    values: list[dict[str, object]] = []
    for index, position in enumerate(positions):
        values.append(
            {
                "player_id": str(uuid5(NAMESPACE_URL, f"min007r4-{index}")),
                "player_key": f"min007r4_{index}",
                "position": position,
                "start_weight": start if index == 0 else "0.5",
                "bench_weight": bench if index == 0 else "0.5",
                "hard_ineligible": False,
            }
        )
    return values


def _sample_kwargs(policy: dict[str, object]) -> dict[str, object]:
    return {
        "fixture_id": str(uuid5(NAMESPACE_URL, "min007r4-fixture")),
        "team_id": str(uuid5(NAMESPACE_URL, "min007r4-team")),
        "bench_size": 9,
        "bench_goalkeeper_slots": 1,
        "policy": policy,
    }


@pytest.mark.parametrize(
    ("start", "bench"),
    [
        (Decimal(1), Decimal("1E-300")),
        (Decimal(1), Decimal("1E-1000")),
        (Decimal("0.50000000000000000000000000001"),) * 2,
    ],
    ids=["one-plus-1e300", "one-plus-1e1000", "half-plus-half-tiny"],
)
@pytest.mark.parametrize("ambient_precision", [10, 28, 60, 256])
def test_overweight_candidates_rejected_context_free(
    policy: dict[str, object],
    start: Decimal,
    bench: Decimal,
    ambient_precision: int,
) -> None:
    previous = getcontext().prec
    try:
        getcontext().prec = ambient_precision
        result = sample_coherent_lineups(
            _candidates(start, bench), seed_suffix="", **_sample_kwargs(policy)
        )
    finally:
        getcontext().prec = previous
    assert isinstance(result, InvalidLineupResult)
    assert result.error_code == "INVALID_ROLE_WEIGHTS"


@pytest.mark.parametrize(
    ("start", "bench"),
    [(Decimal("0.7"), Decimal("0.3")), (Decimal(1), Decimal(0))],
    ids=["seven-tenths-plus-three-tenths", "one-plus-zero"],
)
def test_exact_weight_boundaries_are_accepted(
    policy: dict[str, object], start: Decimal, bench: Decimal
) -> None:
    result = sample_coherent_lineups(
        _candidates(start, bench), seed_suffix="", **_sample_kwargs(policy)
    )
    assert isinstance(result, ProjectedLineupResult)


@pytest.mark.parametrize("weight", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_candidate_weights_fail_closed(policy: dict[str, object], weight: str) -> None:
    result = sample_coherent_lineups(
        _candidates(weight, "0"), seed_suffix="", **_sample_kwargs(policy)
    )
    assert isinstance(result, InvalidLineupResult)
    assert result.error_code == "INVALID_ROLE_WEIGHTS"
