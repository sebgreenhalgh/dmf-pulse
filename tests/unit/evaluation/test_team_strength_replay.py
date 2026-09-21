"""Offline metric identities, sealed historical golden and synthetic replay boundary."""

from __future__ import annotations

import math
from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.evaluation import team_strength_replay as replay
from dmf_pulse.football_events.team_strength_model import fit_team_strength
from dmf_pulse.football_events.team_strength_numerics import Observation
from dmf_pulse.ingestion.openfootball.team_strength_data import seal
from tests.unit.football_events.team_strength_support import synthetic_dataset
from tests.unit.football_events.test_team_strength_numerics import history
from tests.unit.ingestion.openfootball.test_team_strength_data import STAMP


def observation(home: int = 1, away: int = 0) -> Observation:
    row = history(repeats=1)[0]
    return Observation(row.fixture_id, row.season, row.played_on, row.home, row.away, home, away)


def test_poisson_metric_reference_and_discrete_crps_identity() -> None:
    metrics = replay.prediction_metrics(observation(), 1.0, 1.0)
    zero = math.exp(-1)
    assert metrics["exact_log_loss"] == pytest.approx(2.0, abs=1e-14)
    assert metrics["clean_sheet_brier"] == pytest.approx(((zero - 1) ** 2 + zero**2) / 2)
    assert metrics["btts_brier"] == pytest.approx((1 - zero) ** 4)
    assert metrics["totals_brier"] == pytest.approx(
        sum((1 - math.exp(-2) * v) ** 2 for v in (3, 5, 19 / 3)) / 3
    )
    pmf = tuple(zero / math.factorial(k) for k in range(37))
    pair = math.fsum(pmf[x] * pmf[y] * abs(x - y) for x in range(37) for y in range(37))
    crps = (
        math.fsum(
            math.fsum(p * abs(k - actual) for k, p in enumerate(pmf)) - pair / 2
            for actual in (1, 0)
        )
        / 2
    )
    assert metrics["goal_rps"] == pytest.approx(crps, abs=1e-14)
    assert metrics["omitted_tail"] < 1e-12
    assert metrics["home_mae"] == 0 and metrics["away_mae"] == 1 and metrics["total_mae"] == 1


@given(
    st.floats(0.01, 8, allow_nan=False, allow_infinity=False),
    st.floats(0.01, 8, allow_nan=False, allow_infinity=False),
    st.integers(0, 12),
    st.integers(0, 12),
)
@settings(max_examples=20)
def test_metrics_are_finite_on_identical_sufficient_support(
    home: float, away: float, hg: int, ag: int
) -> None:
    values = replay.prediction_metrics(observation(hg, ag), home, away)
    assert set(values) == set(replay.METRICS)
    assert all(math.isfinite(value) and value >= 0 for value in values.values())
    assert values["omitted_tail"] < 1e-12


@pytest.mark.parametrize("rate", [0.0, -1.0, 8.000001, math.nan, math.inf])
def test_metric_invalid_rates_fail(rate: float) -> None:
    with pytest.raises(ValueError, match="rates"):
        replay.prediction_metrics(observation(), rate, 1.0)


def test_metric_invalid_population_and_support_fail() -> None:
    with pytest.raises(ValueError, match="support"):
        replay.prediction_metrics(observation(99, 0), 1.0, 1.0)
    with pytest.raises(ValueError, match="population"):
        replay.aggregate(())
    with pytest.raises(ValueError, match="population"):
        replay.aggregate(({"exact_log_loss": 1.0},))


@pytest.mark.golden
def test_explicit_sealed_research_golden_and_policy_identities() -> None:
    golden = replay.load_replay_golden()
    replay.verify_replay_golden(golden)
    assert golden.research_reproduction.metrics.exact_log_loss < golden.baseline.exact_log_loss
    assert golden.governed_d_plus_2.metrics.exact_log_loss < golden.baseline.exact_log_loss
    assert golden.differing_training_origins == (34,)
    assert golden.historical_live_availability_claimed is False
    assert golden.current_2026_27_used_for_selection is False
    assert {row.commit for row in golden.source_resources} == {
        "40b3e1b7391932d133287115106304444bf297e1"
    }
    assert golden.baseline_seasons == ("2022/23", "2023/24", "2024/25")
    assert golden.governed_d_plus_2.parameters_retained
    assert not golden.research_reproduction.model_state_sha256s


def test_changed_secondary_metric_is_not_silently_regenerated() -> None:
    golden = replay.load_replay_golden()
    metrics = golden.baseline.model_copy(update={"hda_brier": Decimal("1.9")})
    changed = seal(
        type(golden),
        **{
            key: getattr(golden, key)
            for key in type(golden).model_fields
            if key not in {"semantic_sha256", "baseline"}
        },
        baseline=metrics,
    )
    with pytest.raises(ValueError, match="golden"):
        replay.verify_replay_golden(changed)
    assert replay.load_replay_golden() == golden


@pytest.mark.parametrize("change", ["delta", "regime", "baseline"])
def test_resealed_contradictory_report_fails(change: str) -> None:
    golden = replay.load_replay_golden()
    values = {
        key: getattr(golden, key) for key in type(golden).model_fields if key != "semantic_sha256"
    }
    if change == "delta":
        values["governed_d_plus_2"] = golden.governed_d_plus_2.model_copy(
            update={"candidate_minus_baseline_exact_log_loss": Decimal("123")}
        )
    elif change == "regime":
        values["research_reproduction"] = golden.research_reproduction.model_copy(
            update={
                "regime": "GOVERNED_D_PLUS_2_RECONSTRUCTED",
                "model_state_sha256s": golden.governed_d_plus_2.model_state_sha256s,
                "parameters_retained": True,
            }
        )
    else:
        values["baseline_seasons"] = tuple(reversed(golden.baseline_seasons))
    with pytest.raises(ValueError, match=r"delta|regimes|baseline seasons"):
        seal(type(golden), **values)


def test_first_synthetic_origin_runs_real_governed_and_legacy_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = synthetic_dataset()

    class OriginComplete(Exception):
        """Stop this bounded controller test after one real origin, not a replay claim."""

    def completed(origin: int) -> None:
        assert origin == 1
        raise OriginComplete

    monkeypatch.setattr(
        replay,
        "fit_team_strength",
        lambda data: fit_team_strength(data, clock=lambda: STAMP + timedelta(seconds=1)),
    )
    with pytest.raises(OriginComplete):
        replay._replay(dataset.fixture_registry, dataset.sources, progress=completed)
    with pytest.raises(ValueError, match="source scope"):
        replay._replay(dataset.fixture_registry, dataset.sources[:-1])
