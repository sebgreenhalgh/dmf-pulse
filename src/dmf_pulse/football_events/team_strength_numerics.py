"""Ticket-local float64 Poisson Newton kernel; no provider, market or I/O access.

Unlike existing Stage-8 Decimal mathematics, the explicitly approved 001A fitting
boundary uses Python binary64. The last club is structurally minus the sum of
the first N-1 effects throughout optimization, never post-hoc recentered.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from uuid import UUID


class StrengthFitError(ValueError):
    """Finite numerical failure: no accepted fit or silent pseudo-inverse."""


@dataclass(frozen=True, slots=True)
class Observation:
    fixture_id: UUID
    season: str
    played_on: date
    home: UUID
    away: UUID
    home_goals: int
    away_goals: int

    def __post_init__(self) -> None:
        if self.home == self.away or any(
            type(y) is not int or not 0 <= y <= 99 for y in (self.home_goals, self.away_goals)
        ):
            raise StrengthFitError("invalid numerical match observation")


def decay_weight(played_on: date, cutoff: datetime) -> float:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise StrengthFitError("numerical cutoff must be timezone-aware")
    age = (cutoff - datetime.combine(played_on, time(), UTC)).total_seconds() / 86400.0
    if age < 0:
        raise StrengthFitError("future observation cannot receive a decay weight")
    return math.exp2(-age / 365.0)


def reconstruct(free: tuple[float, ...]) -> tuple[float, ...]:
    return (*free, -math.fsum(free))


def cholesky(matrix: tuple[tuple[float, ...], ...]) -> tuple[tuple[float, ...], ...]:
    """Deterministic SPD factorization. No damping, jitter or pseudo-inverse."""
    n = len(matrix)
    if n == 0 or any(len(row) != n for row in matrix):
        raise StrengthFitError("invalid information matrix shape")
    if any(not math.isfinite(x) for row in matrix for x in row):
        raise StrengthFitError("nonfinite information matrix")
    if any(matrix[i][j] != matrix[j][i] for i in range(n) for j in range(i)):
        raise StrengthFitError("information matrix is not symmetric")
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            value = matrix[i][j] - math.fsum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if not math.isfinite(value) or value <= 0:
                    raise StrengthFitError("information matrix is not positive definite")
                lower[i][j] = math.sqrt(value)
            else:
                lower[i][j] = value / lower[j][j]
    return tuple(tuple(row) for row in lower)


def solve(lower: tuple[tuple[float, ...], ...], rhs: tuple[float, ...]) -> tuple[float, ...]:
    n = len(lower)
    if len(rhs) != n or any(not math.isfinite(x) for x in rhs):
        raise StrengthFitError("invalid linear solve right-hand side")
    values = [0.0] * n
    for i in range(n):
        values[i] = (rhs[i] - math.fsum(lower[i][j] * values[j] for j in range(i))) / lower[i][i]
    for i in reversed(range(n)):
        values[i] = (
            values[i] - math.fsum(lower[j][i] * values[j] for j in range(i + 1, n))
        ) / lower[i][i]
    if any(not math.isfinite(x) for x in values):
        raise StrengthFitError("nonfinite linear solve")
    return tuple(values)


def inverse_information(lower: tuple[tuple[float, ...], ...]) -> tuple[tuple[float, ...], ...]:
    n = len(lower)
    columns = [solve(lower, tuple(float(i == j) for i in range(n))) for j in range(n)]
    # The inverse is symmetric mathematically; averaging round-off gives a
    # deterministic symmetric serialized representation, not a pseudo-inverse.
    return tuple(tuple((columns[j][i] + columns[i][j]) / 2 for j in range(n)) for i in range(n))


@dataclass(frozen=True, slots=True)
class ScoreObservation:
    features: tuple[tuple[int, float], ...]
    weight: float
    weighted_goals: float


@dataclass(frozen=True, slots=True)
class Design:
    teams: tuple[UUID, ...]
    rows: tuple[ScoreObservation, ...]
    attack_centres: tuple[float, ...]
    defence_centres: tuple[float, ...]
    kappa: float
    mean_goal: float
    weighted_observations: float
    initial: tuple[float, ...]


def _features(n: int, scoring: int, defending: int, *, home: bool) -> tuple[tuple[int, float], ...]:
    values = [(0, 1.0)]
    if home:
        values.append((1, 1.0))
    for team, start, sign in ((scoring, 2, 1.0), (defending, n + 1, -1.0)):
        if team == n - 1:
            values.extend((start + j, -sign) for j in range(n - 1))
        else:
            values.append((start + team, sign))
    return tuple(values)


def _design(
    observations: tuple[Observation, ...],
    teams: tuple[UUID, ...],
    cutoff: datetime,
    centres: dict[UUID, tuple[float, float]],
    *,
    prior_matches: int,
    decay: bool,
    cold_entrants: frozenset[UUID] = frozenset(),
) -> Design:
    if any(type(row) is not Observation for row in observations):
        raise StrengthFitError("unexpected training observation type")
    rows = tuple(sorted(observations, key=lambda row: row.fixture_id))
    teams = tuple(sorted(teams))
    n = len(teams)
    if n < 2 or n != len(set(teams)) or not rows:
        raise StrengthFitError("insufficient or duplicate team universe")
    if len({row.fixture_id for row in rows}) != len(rows):
        raise StrengthFitError("duplicate numerical fixture")
    if not set(centres) <= set(teams) or any(
        not math.isfinite(value) for pair in centres.values() for value in pair
    ):
        raise StrengthFitError("invalid shrinkage centres")
    adjacency: dict[UUID, set[UUID]] = {}
    for row in rows:
        if type(row) is not Observation or row.home not in teams or row.away not in teams:
            raise StrengthFitError("unexpected training observation or club identity")
        adjacency.setdefault(row.home, set()).add(row.away)
        adjacency.setdefault(row.away, set()).add(row.home)
    if set(teams) - adjacency.keys() - cold_entrants:
        raise StrengthFitError("unsupported club has no history or entrant prior")
    reached: set[UUID] = set()
    pending = [min(adjacency)]
    while pending:
        team = pending.pop()
        if team not in reached:
            reached.add(team)
            pending.extend(adjacency[team] - reached)
    if reached != adjacency.keys():
        raise StrengthFitError("disconnected observed team history")
    home_mean = math.fsum(row.home_goals for row in rows) / len(rows)
    away_mean = math.fsum(row.away_goals for row in rows) / len(rows)
    if home_mean <= 0 or away_mean <= 0:
        raise StrengthFitError("unpenalized goal baseline has no finite optimum")
    # Research-locked UNWEIGHTED mean over both team-score observations.
    mean = (home_mean + away_mean) / 2
    indexes = {team: i for i, team in enumerate(teams)}
    grouped: dict[tuple[int, int, bool], list[tuple[float, float]]] = {}
    for row in rows:
        # Always reject future rows even for the fixed no-decay auxiliary fit.
        w = decay_weight(row.played_on, cutoff)
        if not decay:
            w = 1.0
        h, a = indexes[row.home], indexes[row.away]
        grouped.setdefault((h, a, True), []).append((w, w * row.home_goals))
        grouped.setdefault((a, h, False), []).append((w, w * row.away_goals))
    coded = tuple(
        ScoreObservation(
            _features(n, h, a, home=home),
            math.fsum(w for w, _ in group),
            math.fsum(y for _, y in group),
        )
        for (h, a, home), group in sorted(grouped.items())
    )
    return Design(
        teams,
        coded,
        tuple(centres.get(t, (0.0, 0.0))[0] for t in teams),
        tuple(centres.get(t, (0.0, 0.0))[1] for t in teams),
        prior_matches * mean,
        mean,
        math.fsum(row.weight for row in coded),
        (math.log(away_mean), math.log(home_mean / away_mean), *((0.0,) * (2 * n - 2))),
    )


def objective(
    design: Design, beta: tuple[float, ...], *, information: bool = True
) -> tuple[float, tuple[float, ...], tuple[tuple[float, ...], ...]]:
    n = len(design.teams)
    p = 2 * n
    if len(beta) != p or any(not math.isfinite(x) for x in beta):
        raise StrengthFitError("invalid model parameter vector")
    gradient = [0.0] * p
    hessian = [[0.0] * p for _ in range(p)] if information else []
    terms = []
    for row in design.rows:
        eta = math.fsum(beta[j] * x for j, x in row.features)
        try:
            rate = math.exp(eta)
        except OverflowError as exc:
            raise StrengthFitError("nonfinite model trial rate") from exc
        if not math.isfinite(rate) or rate <= 0:
            raise StrengthFitError("invalid model trial rate")
        terms.append(row.weight * rate - row.weighted_goals * eta)
        residual = row.weight * rate - row.weighted_goals
        curvature = row.weight * rate
        for pos, (i, x) in enumerate(row.features):
            gradient[i] += residual * x
            if information:
                for j, y in row.features[: pos + 1]:
                    hessian[i][j] += curvature * x * y
    for start, centres in ((2, design.attack_centres), (n + 1, design.defence_centres)):
        effects = reconstruct(beta[start : start + n - 1])
        delta = tuple(x - c for x, c in zip(effects, centres, strict=True))
        terms.append(0.5 * design.kappa * math.fsum(x * x for x in delta))
        for i in range(n - 1):
            gradient[start + i] += design.kappa * (delta[i] - delta[-1])
            if information:
                for j in range(i + 1):
                    hessian[start + i][start + j] += design.kappa * (2.0 if i == j else 1.0)
    if information:
        for i in range(p):
            for j in range(i):
                hessian[j][i] = hessian[i][j]
    value = math.fsum(terms)
    if not math.isfinite(value) or any(not math.isfinite(x) for x in gradient):
        raise StrengthFitError("nonfinite likelihood or gradient")
    return value, tuple(gradient), tuple(tuple(row) for row in hessian)


@dataclass(frozen=True, slots=True)
class NumericalFit:
    teams: tuple[UUID, ...]
    beta: tuple[float, ...]
    attack: tuple[float, ...]
    defence: tuple[float, ...]
    kappa: float
    mean_goal: float
    weighted_observations: float
    objective: float
    gradient_infinity: float
    relative_objective_change: float
    iterations: int
    line_search_halvings: tuple[int, ...]
    information: tuple[tuple[float, ...], ...]
    covariance: tuple[tuple[float, ...], ...]


def _newton(design: Design) -> NumericalFit:
    beta = design.initial
    relative = math.inf
    halvings: list[int] = []
    for iteration in range(101):
        value, gradient, information = objective(design, beta)
        norm = max(abs(x) for x in gradient)
        lower = cholesky(information)
        if norm <= 1e-8 and relative <= 1e-12:
            n = len(design.teams)
            return NumericalFit(
                design.teams,
                beta,
                reconstruct(beta[2 : n + 1]),
                reconstruct(beta[n + 1 :]),
                design.kappa,
                design.mean_goal,
                design.weighted_observations,
                value,
                norm,
                relative,
                iteration,
                tuple(halvings),
                information,
                inverse_information(lower),
            )
        if iteration == 100:
            break
        step = solve(lower, gradient)
        decrement = math.fsum(g * d for g, d in zip(gradient, step, strict=True))
        if not math.isfinite(decrement) or decrement < 0:
            raise StrengthFitError("Newton direction is not a finite descent direction")
        for halving in range(41):
            scale = 2.0 ** (-halving)
            candidate = tuple(b - scale * d for b, d in zip(beta, step, strict=True))
            try:
                trial, trial_gradient, _ = objective(design, candidate, information=False)
            except StrengthFitError:
                continue
            armijo = trial <= value - 1e-4 * scale * decrement
            # Near the optimum the objective's float64 ulp can exceed the
            # Newton improvement. Permit only roundoff-sized non-increase AND
            # a strictly improving gradient (or an already-converged vector).
            roundoff = abs(trial - value) <= 8 * math.ulp(max(1.0, abs(value)))
            improves = max(abs(x) for x in trial_gradient) < norm or norm <= 1e-8
            if armijo or (roundoff and improves):
                relative = abs(trial - value) / max(1.0, abs(value))
                beta = candidate
                halvings.append(halving)
                break
        else:
            raise StrengthFitError("deterministic line search exhausted")
    raise StrengthFitError("Newton fit did not meet both convergence criteria in 100 iterations")


def fit_strength(
    observations: tuple[Observation, ...],
    *,
    teams: tuple[UUID, ...],
    cutoff: datetime,
    centres: dict[UUID, tuple[float, float]],
    cold_entrants: frozenset[UUID] = frozenset(),
) -> NumericalFit:
    """Fixed 365-day / 12-match numerical fit; caller supplies governed eligible rows."""
    return _newton(
        _design(
            observations,
            teams,
            cutoff,
            centres,
            prior_matches=12,
            decay=True,
            cold_entrants=cold_entrants,
        )
    )


def fit_cohort_season(observations: tuple[Observation, ...], cutoff: datetime) -> NumericalFit:
    """Fixed auxiliary research definition: one complete season, no decay, 4/4 prior."""
    if len({row.season for row in observations}) != 1:
        raise StrengthFitError("cohort auxiliary fit requires exactly one season")
    teams = tuple(sorted({team for row in observations for team in (row.home, row.away)}))
    return _newton(_design(observations, teams, cutoff, {}, prior_matches=4, decay=False))
