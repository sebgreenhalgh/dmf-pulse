"""Independent algebraic/property checks for the opt-in MQ000 contracts."""

import json
import sys
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.unit.scripts.script_support import load_script

math = load_script("model_quality_math")


def test_original_zero_key_counterexample_is_invariant_on_fixed_grid():
    pmf = {0: Decimal(".5"), 2: Decimal(".5")}
    first = math.fixed_grid_rps(pmf, 1, target_grid=(0, 1, 2))
    second = math.fixed_grid_rps(
        {0: Decimal(".5"), 1: 0, 2: Decimal(".5")}, 1, target_grid=(0, 1, 2)
    )
    assert first == second
    assert first.score == Fraction(1, 2)
    assert first.metric_version == math.METRIC_VERSION


@given(st.integers(0, 1000), st.integers(-8, 8))
@settings(max_examples=80)
def test_zero_insertion_and_mapping_order_do_not_change_fixed_grid_score(count, truth):
    pmf = {-8: Decimal(count).scaleb(-3), 8: Decimal(1000 - count).scaleb(-3)}
    grid = tuple(range(-8, 9))
    padded = {x: pmf.get(x, 0) for x in reversed(grid)}
    assert math.fixed_grid_rps(pmf, truth, target_grid=grid) == math.fixed_grid_rps(
        padded, truth, target_grid=grid
    )


@given(st.integers(1, 99), st.integers(100, 10000))
def test_valid_rare_tail_mean_can_exceed_p90(count, tail):
    result = math.summarize_pmf(
        {0: Decimal(1000 - count).scaleb(-3), tail: Decimal(count).scaleb(-3)}
    )
    assert result.mean > result.p90 == result.p50 == result.p10 == 0


def test_lower_rare_tail_mean_can_fall_below_p10():
    result = math.summarize_pmf({-100: Decimal(".01"), 0: Decimal(".99")})
    assert result.mean == -1 < result.p10 == result.p50 == result.p90 == 0


def test_quantile_at_cdf_tie_uses_lower_inverse():
    result = math.summarize_pmf({-3: Decimal(".1"), 2: Decimal(".4"), 9: Decimal(".5")})
    assert (result.p10, result.p50, result.p90) == (-3, 2, 9)


def test_gapped_grid_is_ordinal_and_grid_changes_are_explicit():
    a = math.fixed_grid_rps({-3: Decimal(".5"), 7: Decimal(".5")}, 2, target_grid=(-3, 2, 7))
    b = math.fixed_grid_rps({0: Decimal(".5"), 2: Decimal(".5")}, 1, target_grid=(0, 1, 2))
    assert a.score == b.score == Fraction(1, 2)
    assert a.grid_sha256 != b.grid_sha256
    with pytest.raises(ValueError, match="GRID_MEMBERSHIP"):
        math.fixed_grid_rps({0: 1}, 1, target_grid=(0, 2))


def test_singleton_grid_and_deterministic_perfect_forecast_score_zero():
    assert math.fixed_grid_rps({2: 1}, 2, target_grid=(2,)).score == 0
    assert math.fixed_grid_rps({2: 1}, 2, target_grid=(-3, 0, 2, 7)).score == 0


def test_normalization_is_exact_even_under_low_decimal_precision():
    with localcontext() as context:
        context.prec = 2
        with pytest.raises(ValueError, match="NORMALIZED"):
            math.summarize_pmf({0: Decimal(1), 2: Decimal("1e-50")})
        assert math.fixed_grid_rps(
            {0: Decimal(".25"), 2: Decimal(".75")}, 1, target_grid=(0, 1, 2)
        ).score == Fraction(5, 8)


@pytest.mark.parametrize(
    "pmf",
    [
        {},
        {0: Decimal("NaN")},
        {0: Decimal("Infinity")},
        {0: Decimal("-.1"), 1: Decimal("1.1")},
        {0: Decimal(".9")},
        {False: 1},
        {0: True},
        {0: 1.0},
        {Decimal("NaN"): 1},
        {0: Decimal("1e-101")},
        {10**128: 1},
    ],
)
def test_invalid_or_unbounded_pmf_is_rejected(pmf):
    with pytest.raises(ValueError):
        math.summarize_pmf(pmf)


@pytest.mark.parametrize(
    "grid,truth",
    [
        ((), 0),
        ((0, 0), 0),
        ((1, 0), 0),
        ((False, 1), 0),
        ((0, Decimal("Infinity")), 0),
        ((0, 1), True),
        ((0, 1), Decimal("NaN")),
        ((0, 1), 2),
    ],
)
def test_grid_and_observation_contract_is_strict(grid, truth):
    with pytest.raises(ValueError):
        math.fixed_grid_rps({0: 1}, truth, target_grid=grid)


def test_expected_score_excess_equals_squared_cdf_distance():
    grid = (-2, 0, 3)
    truth = {-2: Decimal(".2"), 0: Decimal(".5"), 3: Decimal(".3")}
    forecast = {-2: Decimal(".6"), 0: Decimal(".1"), 3: Decimal(".3")}
    expected = sum(
        (
            Fraction(mass)
            * (
                math.fixed_grid_rps(forecast, y, target_grid=grid).score
                - math.fixed_grid_rps(truth, y, target_grid=grid).score
            )
            for y, mass in truth.items()
        ),
        Fraction(),
    )
    assert expected == Fraction(4, 10) ** 2


def test_paired_comparison_rejects_grid_or_observation_changes():
    baseline = math.fixed_grid_rps({0: 1}, 0, target_grid=(0, 1, 2))
    challenger = math.fixed_grid_rps({2: 1}, 0, target_grid=(0, 1, 2))
    assert math.paired_rps_delta(challenger, baseline) == 2
    for other in (
        math.fixed_grid_rps({0: 1}, 0, target_grid=(0, 2)),
        math.fixed_grid_rps({0: 1}, 1, target_grid=(0, 1, 2)),
    ):
        with pytest.raises(ValueError, match="SAME_VERSION_GRID_AND_OBSERVATION"):
            math.paired_rps_delta(other, baseline)


@given(st.integers(0, 1000), st.integers(0, 1000))
def test_expected_score_propriety_identity_for_arbitrary_mass(p_count, q_count):
    grid = (-2, 0, 3)
    p = {-2: Decimal(p_count).scaleb(-3), 3: Decimal(1000 - p_count).scaleb(-3)}
    q = {-2: Decimal(q_count).scaleb(-3), 0: Decimal(1000 - q_count).scaleb(-3)}
    excess = sum(
        (
            Fraction(mass)
            * math.paired_rps_delta(
                math.fixed_grid_rps(p, y, target_grid=grid),
                math.fixed_grid_rps(q, y, target_grid=grid),
            )
            for y, mass in q.items()
        ),
        Fraction(),
    )
    assert excess == Fraction(p_count - q_count, 1000) ** 2 + Fraction(p_count - 1000, 1000) ** 2


def test_cli_requires_explicit_owned_opt_in(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["model_quality_math.py"])
    with pytest.raises(SystemExit) as error:
        math.main()
    assert error.value.code == 2
    monkeypatch.setattr(sys, "argv", ["model_quality_math.py", "--owned-demonstration"])
    math.main()
    result = json.loads(capsys.readouterr().out)
    assert result["score"] == "1/2" and result["zero_key_invariant"] is True
    assert result["rare_tail_mean"] == "1" and result["rare_tail_p90"] == "0"
