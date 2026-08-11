from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from dmf_pulse.availability.projection import (
    MinutesPredictionResult,
    compose_player_minutes_projection,
    compose_team_minutes_projection,
)


def _team() -> object:
    role_players = []
    pmf = tuple(Decimal(0) if index == 0 else Decimal(1) / Decimal(90) for index in range(91))
    for index in range(11):
        role_players.append(
            compose_player_minutes_projection(
                {
                    "player_id": f"00000000-0000-0000-0000-{index + 1:012d}",
                    "position": "GK" if index == 0 else "DEF",
                    "p_start": Decimal("0.8"),
                    "p_bench": Decimal("0.1"),
                    "p_out": Decimal("0.1"),
                },
                {"minute_pmf": pmf},
                {"minute_pmf": pmf},
                confidence_grade="B",
                confidence_reasons=("BASELINE_MODEL_CAP_B",),
            )
        )

    class Lineup:
        fixture_id = "10000000-0000-0000-0000-000000000001"
        team_id = "20000000-0000-0000-0000-000000000001"
        sample_count = 256
        bench_size = 9
        bench_goalkeeper_slots = 1
        scenario_set_sha256 = "a" * 64

    return compose_team_minutes_projection(
        Lineup(),
        role_players,
        as_of="2026-08-14T17:30:00Z",
        model_family="REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
        dataset_sha256="b" * 64,
        model_artifact_sha256="c" * 64,
    )


def test_outer_nested_fixture_team_and_asof_mismatch_rejected() -> None:
    projection = _team()
    body = {
        "status": "PROJECTED",
        "fixture_id": projection.fixture_id,
        "team_id": projection.team_id,
        "as_of": projection.as_of,
        "projection": projection,
        "error_code": None,
    }
    for field, value in (
        ("fixture_id", "30000000-0000-0000-0000-000000000001"),
        ("team_id", "40000000-0000-0000-0000-000000000001"),
        ("as_of", "2026-08-14T18:30:00Z"),
    ):
        changed = {**body, field: value}
        with pytest.raises(ValidationError):
            MinutesPredictionResult.model_validate(changed)


def test_model_copy_revalidates_outer_nested_identity() -> None:
    projection = _team()
    result = MinutesPredictionResult(
        status="PROJECTED",
        fixture_id=projection.fixture_id,
        team_id=projection.team_id,
        as_of=projection.as_of,
        projection=projection,
        error_code=None,
    )
    with pytest.raises(ValueError):
        result.model_copy(update={"team_id": "40000000-0000-0000-0000-000000000001"})
