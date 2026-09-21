"""Analytic derivatives, structural identification and adversarial Newton fits."""

from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dmf_pulse.football_events import team_strength_numerics as kernel
from dmf_pulse.football_events.team_strength_numerics import (
    Observation,
    StrengthFitError,
    _design,
    _newton,
    cholesky,
    decay_weight,
    fit_cohort_season,
    fit_strength,
    inverse_information,
    objective,
    reconstruct,
    solve,
)

CUTOFF = datetime(2026, 6, 1, tzinfo=UTC)
TEAMS = tuple(UUID(int=(7 << 76) | (2 << 62) | i) for i in range(1, 7))


def history(*, repeats: int = 24) -> tuple[Observation, ...]:
    rng = random.Random(811)
    attacks = (0.5, 0.25, 0.1, -0.1, -0.25, -0.5)
    defences = (-0.4, -0.2, -0.1, 0.1, 0.2, 0.4)

    def poisson(rate: float) -> int:
        value, product = -1, 1.0
        while product > math.exp(-rate):
            value += 1
            product *= rng.random()
        return value

    rows = []
    for repeat in range(repeats):
        for h, home in enumerate(TEAMS):
            for a, away in enumerate(TEAMS):
                if h == a:
                    continue
                rows.append(
                    Observation(
                        UUID(int=(7 << 76) | (2 << 62) | (100 + len(rows))),
                        "2025/26",
                        date(2025, 8, 1) + timedelta(days=repeat * 8),
                        home,
                        away,
                        poisson(math.exp(0.25 + 0.3 + attacks[h] - defences[a])),
                        poisson(math.exp(0.25 + attacks[a] - defences[h])),
                    )
                )
    return tuple(rows)


def test_synthetic_recovery_and_constraints() -> None:
    fit = fit_strength(history(), teams=TEAMS, cutoff=CUTOFF, centres={})
    assert fit.attack[0] > fit.attack[2] > fit.attack[-1]
    assert fit.defence[-1] > fit.defence[2] > fit.defence[0]
    assert fit.beta[1] == pytest.approx(0.3, abs=0.12)
    assert abs(math.fsum(fit.attack)) < 1e-14
    assert abs(math.fsum(fit.defence)) < 1e-14
    assert fit.gradient_infinity <= 1e-8
    assert fit.relative_objective_change <= 1e-12
    assert 0 < fit.iterations <= 100
    assert len(fit.beta) == 2 * len(TEAMS)  # exactly one global home parameter
    p = len(fit.beta)
    for i in range(p):
        for j in range(p):
            assert math.fsum(
                fit.information[i][k] * fit.covariance[k][j] for k in range(p)
            ) == pytest.approx(float(i == j), abs=2e-12)


def test_analytic_gradient_and_hessian_match_finite_differences() -> None:
    design = _design(
        history(repeats=2), TEAMS, CUTOFF, {TEAMS[0]: (-0.2, -0.1)}, prior_matches=12, decay=True
    )
    beta = tuple(0.02 * (i - 5) for i in range(12))
    _, gradient, hessian = objective(design, beta)
    eps = 1e-5
    for j in range(12):
        plus = tuple(x + (eps if i == j else 0) for i, x in enumerate(beta))
        minus = tuple(x - (eps if i == j else 0) for i, x in enumerate(beta))
        vp, gp, _ = objective(design, plus)
        vm, gm, _ = objective(design, minus)
        assert gradient[j] == pytest.approx((vp - vm) / (2 * eps), abs=1e-7)
        for i in range(12):
            assert hessian[i][j] == pytest.approx((gp[i] - gm[i]) / (2 * eps), abs=1e-7)


def test_permutation_and_unweighted_penalty_definition() -> None:
    rows = history(repeats=3)
    fit = fit_strength(rows, teams=TEAMS, cutoff=CUTOFF, centres={})
    shuffled = list(rows)
    random.Random(41).shuffle(shuffled)
    other = fit_strength(tuple(shuffled), teams=tuple(reversed(TEAMS)), cutoff=CUTOFF, centres={})
    assert fit == other
    assert fit.kappa == pytest.approx(
        12 * sum(row.home_goals + row.away_goals for row in rows) / (2 * len(rows))
    )
    assert fit.weighted_observations < 2 * len(rows)


def test_stronger_internal_prior_shrinks_to_neutral_centre() -> None:
    rows = history(repeats=1)
    weak = _newton(_design(rows, TEAMS, CUTOFF, {}, prior_matches=4, decay=True))
    strong = _newton(_design(rows, TEAMS, CUTOFF, {}, prior_matches=24, decay=True))
    assert math.fsum(x * x for x in (*strong.attack, *strong.defence)) < math.fsum(
        x * x for x in (*weak.attack, *weak.defence)
    )
    auxiliary = fit_cohort_season(rows, CUTOFF)
    assert auxiliary.kappa == pytest.approx(4 * auxiliary.mean_goal)
    assert auxiliary.weighted_observations == 2 * len(rows)


def test_exact_half_life_and_naive_future_rejection() -> None:
    assert [decay_weight((CUTOFF - timedelta(days=d)).date(), CUTOFF) for d in (0, 365, 730)] == [
        1.0,
        0.5,
        0.25,
    ]
    with pytest.raises(StrengthFitError, match="timezone"):
        decay_weight(date(2026, 1, 1), CUTOFF.replace(tzinfo=None))
    with pytest.raises(StrengthFitError, match="future"):
        decay_weight(date(2027, 1, 1), CUTOFF)


@given(st.lists(st.floats(-10, 10, allow_nan=False, allow_infinity=False), min_size=1, max_size=41))
def test_structural_reconstruction_property(values: list[float]) -> None:
    assert abs(math.fsum(reconstruct(tuple(values)))) < 1e-12


@given(st.integers(0, 10000), st.integers(1, 1000))
def test_monotone_decay(age: int, extra: int) -> None:
    assert decay_weight((CUTOFF - timedelta(days=age)).date(), CUTOFF) > decay_weight(
        (CUTOFF - timedelta(days=age + extra)).date(), CUTOFF
    )


@given(st.integers(0, 100000))
@settings(max_examples=8, deadline=None)
def test_deterministic_fit_and_positive_fixture_rates(seed: int) -> None:
    rows = list(history(repeats=1))
    random.Random(seed).shuffle(rows)
    fit = fit_strength(tuple(rows), teams=TEAMS, cutoff=CUTOFF, centres={})
    reference = fit_strength(history(repeats=1), teams=TEAMS, cutoff=CUTOFF, centres={})
    assert fit == reference
    for h in range(6):
        for a in range(6):
            assert math.isfinite(
                math.exp(fit.beta[0] + fit.beta[1] + fit.attack[h] - fit.defence[a])
            )
            assert math.exp(fit.beta[0] + fit.attack[a] - fit.defence[h]) > 0


@pytest.mark.parametrize(
    "matrix",
    [
        (),
        ((1.0, 2.0),),
        ((1.0, 2.0), (0.0, 1.0)),
        ((1.0, 1.0), (1.0, 1.0)),
        ((-1.0,),),
        ((math.nan,),),
        ((math.inf,),),
    ],
)
def test_invalid_or_singular_factorization_rejected(matrix: tuple[tuple[float, ...], ...]) -> None:
    with pytest.raises(StrengthFitError):
        cholesky(matrix)


def test_linear_solve_reference_and_nonfinite_rejection() -> None:
    factor = cholesky(((4.0, 2.0), (2.0, 3.0)))
    assert solve(factor, (6.0, 5.0)) == pytest.approx((1.0, 1.0))
    inverse = inverse_information(factor)
    assert inverse[0] == pytest.approx((0.375, -0.25))
    with pytest.raises(StrengthFitError):
        solve(factor, (math.inf, 1.0))
    with pytest.raises(StrengthFitError):
        solve(factor, (1.0,))


def test_invalid_histories_fail_closed() -> None:
    rows = history(repeats=1)
    with pytest.raises(StrengthFitError, match="duplicate numerical"):
        fit_strength((*rows, rows[0]), teams=TEAMS, cutoff=CUTOFF, centres={})
    disconnected = tuple(row for row in rows if (row.home in TEAMS[:3]) == (row.away in TEAMS[:3]))
    with pytest.raises(StrengthFitError, match="disconnected"):
        fit_strength(disconnected, teams=TEAMS, cutoff=CUTOFF, centres={})
    zero = tuple(
        Observation(row.fixture_id, row.season, row.played_on, row.home, row.away, 0, 0)
        for row in rows
    )
    with pytest.raises(StrengthFitError, match="finite optimum"):
        fit_strength(zero, teams=TEAMS, cutoff=CUTOFF, centres={})
    with pytest.raises(StrengthFitError, match="invalid numerical"):
        Observation(rows[0].fixture_id, "2025/26", date(2025, 8, 1), TEAMS[0], TEAMS[0], 2, 1)
    with pytest.raises(StrengthFitError, match="invalid numerical"):
        Observation(rows[0].fixture_id, "2025/26", date(2025, 8, 1), TEAMS[0], TEAMS[1], 100, 1)


def test_nonfinite_predictors_are_rejected_not_clipped() -> None:
    design = _design(history(repeats=1), TEAMS, CUTOFF, {}, prior_matches=12, decay=True)
    for bad in (math.nan, math.inf, -math.inf, 1000.0, -1000.0):
        with pytest.raises(StrengthFitError):
            objective(design, (bad, *((0.0,) * 11)))


def test_line_search_and_nonconvergence_are_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    design = _design(history(repeats=1), TEAMS, CUTOFF, {}, prior_matches=12, decay=True)
    original = kernel.objective
    value, gradient, _ = original(design, design.initial)

    def uphill_trial(
        design_value: kernel.Design, beta: tuple[float, ...], *, information: bool = True
    ) -> tuple[float, tuple[float, ...], tuple[tuple[float, ...], ...]]:
        result = original(design_value, beta, information=information)
        return result if information else (value + 100.0, gradient, ())

    monkeypatch.setattr(kernel, "objective", uphill_trial)
    with pytest.raises(StrengthFitError, match="line search exhausted"):
        _newton(design)
    monkeypatch.setattr(kernel, "objective", original)
    monkeypatch.setattr(kernel, "solve", lambda lower, rhs: (0.0,) * len(rhs))
    with pytest.raises(StrengthFitError, match="100 iterations"):
        _newton(design)


def test_sparse_entrant_and_high_goals_are_numerically_explicit() -> None:
    newcomer = UUID(int=(7 << 76) | (2 << 62) | 99)
    fit = fit_strength(
        history(repeats=1),
        teams=(*TEAMS, newcomer),
        cutoff=CUTOFF,
        centres={newcomer: (-0.3, -0.2)},
        cold_entrants=frozenset({newcomer}),
    )
    assert fit.attack[-1] < 0 and fit.defence[-1] < 0
    high = tuple(
        Observation(row.fixture_id, row.season, row.played_on, row.home, row.away, 99, 99)
        for row in history(repeats=1)
    )
    fitted = fit_strength(high, teams=TEAMS, cutoff=CUTOFF, centres={})
    assert math.exp(fitted.beta[0]) == pytest.approx(99.0)
    with pytest.raises(StrengthFitError, match="no history"):
        fit_strength(history(repeats=1), teams=(*TEAMS, newcomer), cutoff=CUTOFF, centres={})


def test_foreign_observation_invalid_centres_and_nonfinite_solve() -> None:
    with pytest.raises(StrengthFitError, match="observation type"):
        fit_strength((object(),), teams=TEAMS, cutoff=CUTOFF, centres={})
    with pytest.raises(StrengthFitError, match="centres"):
        fit_strength(
            history(repeats=1), teams=TEAMS, cutoff=CUTOFF, centres={TEAMS[0]: (math.nan, 0.0)}
        )
    with pytest.raises(StrengthFitError, match="nonfinite linear"):
        solve(((1e-300,),), (1e300,))
