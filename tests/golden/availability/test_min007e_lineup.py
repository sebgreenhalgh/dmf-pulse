"""Golden structural checks for MIN-007E coherent lineup results."""

from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from dmf_pulse.availability.lineup import PHASES, SAMPLE_COUNT, sample_coherent_lineups


def _candidates() -> list[dict[str, object]]:
    positions = ["GK", "GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 10
    return [
        {
            "player_id": str(uuid5(NAMESPACE_URL, f"min007e-golden-{index}")),
            "player_key": f"golden_{index}",
            "position": position,
            "start_weight": "0.500000",
            "bench_weight": "0.500000",
            "hard_ineligible": False,
        }
        for index, position in enumerate(positions)
    ]


def test_golden_sampler_shape() -> None:
    policy = {
        "baseline_confidence_cap": "B",
        "coherence_model": "COHERENCE_MODEL_V1",
        "cold_start_min_competitive_observations": 3,
        "default_bench_goalkeeper_slots": 1,
        "default_bench_size": 9,
        "expected_minutes_decimal_places": 6,
        "history_window": 12,
        "lineup_sample_count": 256,
        "lineup_sampler": "DETERMINISTIC_EXPONENTIAL_RACE_V1",
        "minute_bin_alpha": "0.050000",
        "minute_prior_strength": "3.000000",
        "model_family": "REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1",
        "new_manager_min_team_lineups": 3,
        "old_manager_multiplier": "0.350000",
        "other_team_multiplier": "0.000000",
        "policy_id": "minutes-baseline-v1",
        "preseason_multiplier": "0.250000",
        "probability_decimal_places": 12,
        "promoted_team_min_target_league_lineups": 3,
        "recency_decay": "0.850000",
        "role_prior_strength": "2.000000",
        "rounding_mode": "ROUND_HALF_EVEN",
        "schema_version": "minutes-baseline-policy-v1",
        "seed": "MIN-007-COHERENCE-V1",
    }
    result = sample_coherent_lineups(
        _candidates(),
        fixture_id=str(uuid5(NAMESPACE_URL, "min007e-golden-fixture")),
        team_id=str(uuid5(NAMESPACE_URL, "min007e-golden-team")),
        seed_suffix="",
        bench_size=9,
        bench_goalkeeper_slots=1,
        policy=policy,
    )
    assert result.status == "PROJECTED"
    assert result.sample_count == SAMPLE_COUNT
    assert len(result.scenarios) == SAMPLE_COUNT
    assert PHASES == ("START_GK", "START_OUTFIELD", "BENCH_GK", "BENCH_OUTFIELD")
    assert result.sum_p_start == Decimal(11)
    assert result.sum_p_bench == Decimal(9)
    assert result.sum_p_out == Decimal(3)
