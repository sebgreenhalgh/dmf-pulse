from __future__ import annotations

from decimal import Decimal

from dmf_pulse.availability.projection import (
    PlayerMinutesProjection,
    compose_player_minutes_projection,
)


def _parts() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    role = {
        "player_id": "00000000-0000-0000-0000-000000000001",
        "position": "MID",
        "p_start": Decimal("0.75"),
        "p_bench": Decimal("0.20"),
        "p_out": Decimal("0.05"),
    }
    pmf = tuple(Decimal(0) if index == 0 else Decimal(1) / Decimal(90) for index in range(91))
    return role, {"minute_pmf": pmf}, {"minute_pmf": pmf}


def test_exact_mixture_has_public_consistency() -> None:
    role, start, bench = _parts()
    result = compose_player_minutes_projection(
        role, start, bench, confidence_grade="B", confidence_reasons=("BASELINE_MODEL_CAP_B",)
    )
    assert isinstance(result, PlayerMinutesProjection)
    assert len(result.minute_pmf) == 91
    assert result.p_zero_minutes == result.minute_pmf[0]
    assert result.projection_sha256


def test_model_copy_revalidates_hash() -> None:
    role, start, bench = _parts()
    result = compose_player_minutes_projection(
        role, start, bench, confidence_grade="B", confidence_reasons=("BASELINE_MODEL_CAP_B",)
    )
    try:
        result.model_copy(update={"p_zero_minutes": "0.000000000000"})
    except ValueError:
        pass
    else:
        raise AssertionError("inconsistent derived fields must be rejected")
