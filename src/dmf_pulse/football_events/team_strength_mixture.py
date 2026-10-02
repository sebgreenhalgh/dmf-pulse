"""Coherent finite parameter mixture of accepted independent Poisson priors."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Literal, Self

from pydantic import Field, model_validator

from dmf_pulse.football_events.poisson import poisson_pmf
from dmf_pulse.football_events.score_grid import ScoreGrid
from dmf_pulse.football_events.score_prior import ScorePrior, build_score_prior
from dmf_pulse.football_events.service import ScoreBaselinePolicy, load_score_baseline_policy
from dmf_pulse.football_events.team_strength_adapter import _context, _rates, _request
from dmf_pulse.football_events.team_strength_model import Number, TeamStrengthModelArtifactV1
from dmf_pulse.football_events.team_strength_numerics import _features
from dmf_pulse.football_events.team_strength_parameter_draws import (
    ParameterDrawSetV1,
    ParameterMixtureUnavailable,
    authenticate_parameter_draws,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FixtureRegistration,
    FrozenEvidence,
    SealedEvidence,
    seal,
)

MIXTURE_FAMILY = "PARAMETER_MIXTURE_INDEPENDENT_POISSON_V1"


class FixtureParameterRates(FrozenEvidence):
    parameter_draw_id: SHA
    draw_weight: Number = Field(gt=0, le=1)
    lambda_home: Number = Field(gt=0, le=8)
    lambda_away: Number = Field(gt=0, le=8)


def _matrix_moments(matrix: tuple[tuple[Decimal, ...], ...]) -> tuple[Decimal, Decimal]:
    values = tuple(
        sum(
            (
                Decimal(i if side == 0 else j) * x
                for i, row in enumerate(matrix)
                for j, x in enumerate(row)
            ),
            Decimal(0),
        )
        for side in (0, 1)
    )
    return values[0], values[1]


class ParameterMixtureFixtureV1(SealedEvidence):
    schema_version: Literal["team-strength-parameter-mixture-fixture-v1"] = (
        "team-strength-parameter-mixture-fixture-v1"
    )
    mode: Literal["TEAM_STRENGTH_PARAMETER_MIXTURE_SHADOW"] = (
        "TEAM_STRENGTH_PARAMETER_MIXTURE_SHADOW"
    )
    fixture: FixtureRegistration
    as_of: datetime
    fit_artifact_sha256: SHA
    model_sha256: SHA
    covariance_sha256: SHA
    parameter_order_sha256: SHA
    draw_policy_sha256: SHA
    draw_set_sha256: SHA
    structural_world_id: str
    parameter_uncertainty_method: Literal["LOCAL_LAPLACE_GAUSSIAN"] = "LOCAL_LAPLACE_GAUSSIAN"
    outcome_layer: Literal["CONDITIONAL_POISSON_ALEATORIC_SCORE"] = (
        "CONDITIONAL_POISSON_ALEATORIC_SCORE"
    )
    stage8_policy_sha256: SHA
    rates: tuple[FixtureParameterRates, ...] = Field(min_length=1)
    home_max: int = Field(ge=0)
    away_max: int = Field(ge=0)
    probabilities: tuple[tuple[Number, ...], ...]
    omitted_tail_mass: Number = Field(ge=0, le=1)
    home_marginal_tail: Number = Field(ge=0, le=1)
    away_marginal_tail: Number = Field(ge=0, le=1)
    weighted_lambda_home: Number = Field(gt=0)
    weighted_lambda_away: Number = Field(gt=0)
    epistemic_lambda_variance_home: Number = Field(ge=0)
    epistemic_lambda_variance_away: Number = Field(ge=0)
    total_predictive_variance_home: Number = Field(gt=0)
    total_predictive_variance_away: Number = Field(gt=0)
    home_truncation_mean_error: Number = Field(ge=0)
    away_truncation_mean_error: Number = Field(ge=0)
    status: Literal["SHADOW_NOT_MODEL_INPUT"] = "SHADOW_NOT_MODEL_INPUT"
    convergence_status: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"
    production_active: Literal[False] = False

    @model_validator(mode="after")
    def check_coherence(self) -> Self:
        with localcontext() as context:
            context.prec = 120
            if len(self.probabilities) != self.home_max + 1 or any(
                len(row) != self.away_max + 1 for row in self.probabilities
            ):
                raise ValueError("mixture support mismatch")
            if (
                any(x < 0 for row in self.probabilities for x in row)
                or sum((x for row in self.probabilities for x in row), Decimal(0)) != 1
            ):
                raise ValueError("mixture probability simplex invalid")
            if (
                len({row.parameter_draw_id for row in self.rates}) != len(self.rates)
                or sum((row.draw_weight for row in self.rates), Decimal(0)) != 1
            ):
                raise ValueError("mixture draw identities/weights invalid")
            for side, name in (("home", "lambda_home"), ("away", "lambda_away")):
                mean = sum((row.draw_weight * getattr(row, name) for row in self.rates), Decimal(0))
                variance = sum(
                    (row.draw_weight * (getattr(row, name) - mean) ** 2 for row in self.rates),
                    Decimal(0),
                )
                if abs(mean - getattr(self, f"weighted_lambda_{side}")) > Decimal("1e-50") or abs(
                    variance - getattr(self, f"epistemic_lambda_variance_{side}")
                ) > Decimal("1e-50"):
                    raise ValueError("weighted lambda moments mismatch")
                if abs(
                    mean + variance - getattr(self, f"total_predictive_variance_{side}")
                ) > Decimal("1e-50"):
                    raise ValueError("nested predictive variance identity mismatch")
            moments = _matrix_moments(self.probabilities)
            if any(
                abs(abs(mean - target) - error) > Decimal("1e-50")
                for mean, target, error in zip(
                    moments,
                    (self.weighted_lambda_home, self.weighted_lambda_away),
                    (self.home_truncation_mean_error, self.away_truncation_mean_error),
                    strict=True,
                )
            ):
                raise ValueError("mixture truncation reconciliation mismatch")
        return self

    def score_prior(self) -> ScorePrior:
        return ScorePrior(
            model_family=MIXTURE_FAMILY,
            home_rate=self.weighted_lambda_home,
            away_rate=self.weighted_lambda_away,
            grid=ScoreGrid(
                self.home_max,
                self.away_max,
                self.probabilities,
                self.omitted_tail_mass,
                self.home_marginal_tail,
                self.away_marginal_tail,
            ),
            semantic_sha256=self.semantic_sha256,
        )


def fixture_draw_rates(
    draws: ParameterDrawSetV1, fixture: FixtureRegistration
) -> tuple[FixtureParameterRates, ...]:
    try:
        h, a = draws.teams.index(fixture.home_team_id), draws.teams.index(fixture.away_team_id)
    except ValueError as exc:
        raise ParameterMixtureUnavailable("fixture team outside fitted universe") from exc
    xh = _features(len(draws.teams), h, a, home=True)
    xa = _features(len(draws.teams), a, h, home=False)
    result = []
    for row in draws.draws:
        try:
            home, away = tuple(
                math.exp(math.fsum(float(row.free_parameters[j]) * x for j, x in features))
                for features in (xh, xa)
            )
            if any(not math.isfinite(x) or not 0 < x <= 8 for x in (home, away)):
                raise ParameterMixtureUnavailable("draw rate outside accepted range")
            # Identical accepted six-place rate boundary, range checks without clamping.
            request = _request(home, away)
        except (OverflowError, ValueError) as exc:
            raise ParameterMixtureUnavailable("invalid drawn fixture rates; no clipping") from exc
        result.append(
            FixtureParameterRates(
                parameter_draw_id=row.parameter_draw_id,
                draw_weight=row.draw_weight,
                lambda_home=request.home_goal_rate,
                lambda_away=request.away_goal_rate,
            )
        )
    return tuple(result)


def build_parameter_mixture(
    *,
    artifact: TeamStrengthModelArtifactV1,
    draws: ParameterDrawSetV1,
    fixture: FixtureRegistration,
    as_of: datetime,
    expected_artifact_sha256: str,
    policy: ScoreBaselinePolicy | None = None,
    minimum_support: int | None = None,
) -> ParameterMixtureFixtureV1:
    artifact, _, _ = _context(artifact, fixture, as_of, expected_artifact_sha256)
    draws = authenticate_parameter_draws(artifact, draws)
    selected = policy or load_score_baseline_policy()
    rates = fixture_draw_rates(draws, fixture)
    if draws.policy.scale == 0:
        request = _request(*_rates(artifact, fixture))
        rates = tuple(
            FixtureParameterRates(
                parameter_draw_id=row.parameter_draw_id,
                draw_weight=row.draw_weight,
                lambda_home=request.home_goal_rate,
                lambda_away=request.away_goal_rate,
            )
            for row in draws.draws
        )
    minimum = selected.grid.minimum_max_goals if minimum_support is None else minimum_support
    common = build_score_prior(
        max(row.lambda_home for row in rates),
        max(row.lambda_away for row in rates),
        minimum_max_goals=minimum,
        maximum_max_goals=selected.grid.maximum_max_goals,
        tail_tolerance=selected.grid.tail_tolerance,
        hard_tail_limit=selected.grid.hard_tail_limit,
    ).grid
    with localcontext() as context:
        context.prec = 60
        if len({(row.lambda_home, row.lambda_away) for row in rates}) == 1:
            # Exact mathematical degeneracy, labelled as a mixture; no unavailable-mixture fallback.
            grid = common
        else:
            matrix = [[Decimal(0)] * (common.away_max + 1) for _ in range(common.home_max + 1)]
            omitted, ht, at = Decimal(0), Decimal(0), Decimal(0)
            for row in rates:
                hp, ap = (
                    poisson_pmf(row.lambda_home, common.home_max),
                    poisson_pmf(row.lambda_away, common.away_max),
                )
                hm, am = sum(hp, Decimal(0)), sum(ap, Decimal(0))
                weight = row.draw_weight / (hm * am)
                for i, hprob in enumerate(hp):
                    weighted = weight * hprob
                    for j, aprob in enumerate(ap):
                        matrix[i][j] += weighted * aprob
                omitted += row.draw_weight * (1 - hm * am)
                ht += row.draw_weight * (1 - hm)
                at += row.draw_weight * (1 - am)
            with localcontext() as exact:
                exact.prec = 120
                total = sum((x for line in matrix for x in line), Decimal(0))
                i, j = max(
                    ((i, j) for i, line in enumerate(matrix) for j in range(len(line))),
                    key=lambda ij: matrix[ij[0]][ij[1]],
                )
                matrix[i][j] += 1 - total
            grid = ScoreGrid(
                common.home_max,
                common.away_max,
                tuple(tuple(line) for line in matrix),
                omitted,
                ht,
                at,
            )
        means = tuple(
            sum((row.draw_weight * getattr(row, name) for row in rates), Decimal(0))
            for name in ("lambda_home", "lambda_away")
        )
        variances = tuple(
            sum((row.draw_weight * (getattr(row, name) - mean) ** 2 for row in rates), Decimal(0))
            for name, mean in zip(("lambda_home", "lambda_away"), means, strict=True)
        )
        moments = _matrix_moments(grid.probabilities)
        return seal(
            ParameterMixtureFixtureV1,
            fixture=fixture,
            as_of=as_of,
            fit_artifact_sha256=artifact.semantic_sha256,
            model_sha256=draws.model_sha256,
            covariance_sha256=draws.covariance_sha256,
            parameter_order_sha256=draws.parameter_order_sha256,
            draw_policy_sha256=draws.draw_policy_sha256,
            draw_set_sha256=draws.semantic_sha256,
            structural_world_id=draws.structural_world_id,
            stage8_policy_sha256=selected.sha256,
            rates=rates,
            home_max=grid.home_max,
            away_max=grid.away_max,
            probabilities=grid.probabilities,
            omitted_tail_mass=grid.omitted_tail_mass,
            home_marginal_tail=grid.home_marginal_tail,
            away_marginal_tail=grid.away_marginal_tail,
            weighted_lambda_home=means[0],
            weighted_lambda_away=means[1],
            epistemic_lambda_variance_home=variances[0],
            epistemic_lambda_variance_away=variances[1],
            total_predictive_variance_home=means[0] + variances[0],
            total_predictive_variance_away=means[1] + variances[1],
            home_truncation_mean_error=abs(moments[0] - means[0]),
            away_truncation_mean_error=abs(moments[1] - means[1]),
        )
