"""Immutable public-source forecasts and D+2-eligible prequential scoring.

Stores only accepted OpenFootball team evidence. No FPL, Odds, player, manager,
market or action contract is accepted. A sufficient forecast representation is
the frozen conditional Poisson rates and weights, evaluated on the existing
36-goal research support. Reconstructed provenance cannot become LIVE_OBSERVED.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.evaluation.calibration import calibration_intercept_slope
from dmf_pulse.evaluation.models import CalibrationResult
from dmf_pulse.evaluation.team_strength_mixture_analysis import distribution_features
from dmf_pulse.evaluation.team_strength_replay import SUPPORT_MAX
from dmf_pulse.football_events.poisson import poisson_pmf
from dmf_pulse.football_events.team_strength_adapter import fixture_prior_bundle
from dmf_pulse.football_events.team_strength_mixture import (
    FixtureParameterRates,
    fixture_draw_rates,
)
from dmf_pulse.football_events.team_strength_model import Number, TeamStrengthModelArtifactV1
from dmf_pulse.football_events.team_strength_parameter_draws import (
    ParameterDrawPolicyV1,
    ParameterDrawSetV1,
    authenticate_parameter_draws,
    joint_parameter_draws,
)
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorResult
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    MODE,
    SHA,
    FixtureRegistration,
    FixtureRegistry,
    FrozenEvidence,
    ParsedSnapshot,
    SealedEvidence,
    StrengthEvidenceError,
    TeamStrengthHistoricalDatasetV1,
    authenticate,
    require_team_strength_rights,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import eligibility_not_before


class PrivateProspectiveStorageDenied(StrengthEvidenceError):
    code = "PRIVATE_PROSPECTIVE_STORAGE_NOT_AUTHORIZED"


def require_public_prospective_storage(data_class: str) -> None:
    if data_class != "PUBLIC_OPENFOOTBALL_TEAM_ONLY":
        raise PrivateProspectiveStorageDenied("private prospective storage is not authorized")
    require_team_strength_rights()


PROMOTION_REQUIREMENTS = (
    "PROPER_SCORES",
    "CALIBRATION",
    "SUBGROUP_CHECKS",
    "LEAKAGE_AND_REPRODUCIBILITY",
    "DOWNSTREAM_DECISIONS",
    "PROSPECTIVE_OR_LOCKED_HOLDOUT",
    "OPERATIONAL_VIABILITY",
    "ROLLBACK",
)
PRODUCT = Literal[
    "LEAGUE_BASELINE", "PLUG_IN_TEAM_STRENGTH_SHADOW", "PARAMETER_MIXTURE_TEAM_STRENGTH_SHADOW"
]
CALIBRATION_EVENTS = (
    "home_win",
    "draw",
    "away_win",
    "home_clean_sheet",
    "away_clean_sheet",
    *(f"total_over_{line}.5" for line in range(6)),
)


class PromotionEvidenceStatus(FrozenEvidence):
    historical_interpretation: Literal["DECISION_MATERIALITY_NOT_MODEL_ACCURACY"] = (
        "DECISION_MATERIALITY_NOT_MODEL_ACCURACY"
    )
    promotion: Literal["SEPARATE_LATER_HUMAN_DECISION_REQUIRED"] = (
        "SEPARATE_LATER_HUMAN_DECISION_REQUIRED"
    )
    required_evidence: tuple[str, ...] = PROMOTION_REQUIREMENTS
    automatic_activation: Literal[False] = False
    production_active: Literal[False] = False
    private_storage: Literal["PRIVATE_PROSPECTIVE_STORAGE_NOT_AUTHORIZED"] = (
        "PRIVATE_PROSPECTIVE_STORAGE_NOT_AUTHORIZED"
    )

    @model_validator(mode="after")
    def preserve_promotion_requirements(self) -> Self:
        if self.required_evidence != PROMOTION_REQUIREMENTS:
            raise ValueError("promotion evidence requirements cannot be weakened")
        return self


class PublicForecastDistribution(FrozenEvidence):
    product: PRODUCT
    representation: Literal["CONDITIONAL_POISSON_RATES_WEIGHTS_RESEARCH_SUPPORT_36_V1"] = (
        "CONDITIONAL_POISSON_RATES_WEIGHTS_RESEARCH_SUPPORT_36_V1"
    )
    support_max: Literal[36] = 36
    prior_identity_sha256: SHA
    rates: tuple[FixtureParameterRates, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_weights(self) -> Self:
        with localcontext() as context:
            context.prec = 120
            if sum((row.draw_weight for row in self.rates), Decimal(0)) != 1:
                raise ValueError("forecast weights do not sum to one")
        if self.product != "PARAMETER_MIXTURE_TEAM_STRENGTH_SHADOW" and len(self.rates) != 1:
            raise ValueError("plug-in forecasts require exactly one component")
        if len({row.parameter_draw_id for row in self.rates}) != len(self.rates):
            raise ValueError("duplicate forecast parameter draw")
        return self


class PublicFixtureForecast(FrozenEvidence):
    fixture: FixtureRegistration
    scheduled_date: date
    distributions: tuple[PublicForecastDistribution, ...]


def _fixture_forecast(
    artifact: TeamStrengthModelArtifactV1,
    draws: ParameterDrawSetV1,
    fixture: FixtureRegistration,
    scheduled_date: date,
    origin: datetime,
    baseline: CurrentScorePriorResult | None,
) -> PublicFixtureForecast:
    bound = fixture_prior_bundle(
        artifact=artifact,
        fixture=fixture,
        as_of=origin,
        expected_artifact_sha256=artifact.semantic_sha256,
    )
    plug_rates = (
        FixtureParameterRates(
            parameter_draw_id=bound.semantic_sha256,
            draw_weight=Decimal(1),
            lambda_home=bound.score_prior.home_goal_rate,
            lambda_away=bound.score_prior.away_goal_rate,
        ),
    )
    rates = fixture_draw_rates(draws, fixture)
    if draws.policy.scale == 0:
        rates = tuple(
            FixtureParameterRates(
                parameter_draw_id=row.parameter_draw_id,
                draw_weight=row.draw_weight,
                lambda_home=plug_rates[0].lambda_home,
                lambda_away=plug_rates[0].lambda_away,
            )
            for row in draws.draws
        )
    values = []
    if baseline is not None:
        values.append(
            PublicForecastDistribution(
                product="LEAGUE_BASELINE",
                prior_identity_sha256=baseline.semantic_sha256,
                rates=(
                    FixtureParameterRates(
                        parameter_draw_id=baseline.semantic_sha256,
                        draw_weight=Decimal(1),
                        lambda_home=baseline.score_prior_request.home_goal_rate,
                        lambda_away=baseline.score_prior_request.away_goal_rate,
                    ),
                ),
            )
        )
    values.extend(
        (
            PublicForecastDistribution(
                product="PLUG_IN_TEAM_STRENGTH_SHADOW",
                prior_identity_sha256=bound.semantic_sha256,
                rates=plug_rates,
            ),
            PublicForecastDistribution(
                product="PARAMETER_MIXTURE_TEAM_STRENGTH_SHADOW",
                prior_identity_sha256=canonical_sha256(
                    {
                        "draws": draws.semantic_sha256,
                        "fixture": fixture.model_dump(mode="json"),
                        "as_of": origin.isoformat(),
                        "rates": [row.model_dump(mode="json") for row in rates],
                    }
                ),
                rates=rates,
            ),
        )
    )
    return PublicFixtureForecast(
        fixture=fixture, scheduled_date=scheduled_date, distributions=tuple(values)
    )


class PublicTeamStrengthForecastV1(SealedEvidence):
    schema_version: Literal["public-team-strength-prospective-forecast-v1"] = (
        "public-team-strength-prospective-forecast-v1"
    )
    data_class: Literal["PUBLIC_OPENFOOTBALL_TEAM_ONLY"] = "PUBLIC_OPENFOOTBALL_TEAM_ONLY"
    status: Literal["SHADOW_NOT_MODEL_INPUT"] = "SHADOW_NOT_MODEL_INPUT"
    production_active: Literal[False] = False
    forecast_origin: datetime
    frozen_at: datetime
    dataset_mode: MODE
    artifact: TeamStrengthModelArtifactV1
    draw_set: ParameterDrawSetV1
    fixture_registry: FixtureRegistry
    public_schedule: ParsedSnapshot
    training_dataset: TeamStrengthHistoricalDatasetV1
    league_baseline: CurrentScorePriorResult | None
    forecasts: tuple[PublicFixtureForecast, ...] = Field(min_length=1, max_length=380)

    @model_validator(mode="after")
    def validate_frozen_forecasts(self) -> Self:
        model = self.artifact.model
        if self.training_dataset.semantic_sha256 != model.training_dataset_sha256:
            raise ValueError("forecast training dataset identity mismatch")
        if self.training_dataset.dataset_mode != model.dataset_mode:
            raise ValueError("training dataset/model mode mismatch")
        if tuple(source.lineage for source in self.training_dataset.sources) != model.sources:
            raise ValueError("forecast source snapshots differ from fit source evidence")
        if self.public_schedule not in self.training_dataset.sources:
            raise ValueError("forecast schedule is not the bound fitted source vintage")
        if self.dataset_mode != model.dataset_mode:
            raise ValueError("reconstructed forecast cannot masquerade as LIVE_OBSERVED")
        if not self.artifact.usable_at <= self.forecast_origin <= self.frozen_at:
            raise ValueError("forecast contains post-origin model evidence")
        if (
            self.fixture_registry.semantic_sha256 != model.fixture_registry_sha256
            or self.public_schedule.fixture_registry_sha256 != self.fixture_registry.semantic_sha256
        ):
            raise ValueError("public forecast fixture lineage mismatch")
        if (
            max(self.fixture_registry.registered_at, self.public_schedule.lineage.usable_at)
            > self.forecast_origin
        ):
            raise ValueError("public schedule or registry unavailable at forecast origin")
        if (
            self.league_baseline is not None
            and self.league_baseline.provenance.usable_at > self.forecast_origin
        ):
            raise ValueError("baseline unavailable at forecast origin")
        draws = authenticate_parameter_draws(self.artifact, self.draw_set)
        ids = tuple(row.fixture.fixture_id for row in self.forecasts)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("forecast fixtures not canonical")
        registry = {row.fixture_id: row for row in self.fixture_registry.fixtures}
        schedule = {row.fixture.fixture_id: row for row in self.public_schedule.matches}
        trained_ids = {row.observation.fixture.fixture_id for row in self.training_dataset.matches}
        for row in self.forecasts:
            if row.fixture.fixture_id in trained_ids:
                raise ValueError("target outcome was already used to fit the model")
            if any(
                match.fixture.fixture_id == row.fixture.fixture_id and match.home_goals is not None
                for source in self.training_dataset.sources
                for match in source.matches
            ):
                raise ValueError("target outcome already present in forecast source evidence")
            observed = schedule.get(row.fixture.fixture_id)
            if (
                registry.get(row.fixture.fixture_id) != row.fixture
                or observed is None
                or observed.fixture != row.fixture
            ):
                raise ValueError("forecast fixture absent from bound public schedule")
            if observed.finality != "NO_SCORE" or observed.home_goals is not None:
                raise ValueError("forecast schedule already contains outcome information")
            if (
                row.scheduled_date != observed.source_match_date
                or row.scheduled_date <= self.frozen_at.date()
            ):
                raise ValueError("date-only forecast must be frozen before scheduled match day")
            expected = _fixture_forecast(
                self.artifact,
                draws,
                row.fixture,
                row.scheduled_date,
                self.forecast_origin,
                self.league_baseline,
            )
            if row != expected:
                raise ValueError("forecast differs from frozen model/draw representation")
        return self


def freeze_public_team_forecasts(
    *,
    artifact: TeamStrengthModelArtifactV1,
    draws: ParameterDrawSetV1,
    fixture_registry: FixtureRegistry,
    public_schedule: ParsedSnapshot,
    training_dataset: TeamStrengthHistoricalDatasetV1,
    forecast_origin: datetime,
    fixture_ids: tuple[str, ...],
    league_baseline: CurrentScorePriorResult | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PublicTeamStrengthForecastV1:
    require_public_prospective_storage("PUBLIC_OPENFOOTBALL_TEAM_ONLY")
    artifact, fixture_registry, public_schedule = (
        authenticate(artifact),
        authenticate(fixture_registry),
        authenticate(public_schedule),
    )
    draws = authenticate_parameter_draws(artifact, draws)
    if league_baseline is not None:
        league_baseline = CurrentScorePriorResult.model_validate(
            league_baseline.model_dump(mode="python")
        )
    origin = FrozenEvidence.utc_datetimes(forecast_origin)
    frozen = (clock or (lambda: datetime.now(UTC)))()
    selected = tuple(
        row for row in public_schedule.matches if str(row.fixture.fixture_id) in fixture_ids
    )
    if len(selected) != len(fixture_ids) or len(set(fixture_ids)) != len(fixture_ids):
        raise StrengthEvidenceError("forecast fixture selection missing or duplicated")
    forecasts = tuple(
        _fixture_forecast(
            artifact, draws, row.fixture, row.source_match_date, origin, league_baseline
        )
        for row in selected
    )
    return seal(
        PublicTeamStrengthForecastV1,
        forecast_origin=origin,
        frozen_at=frozen,
        dataset_mode=artifact.model.dataset_mode,
        artifact=artifact,
        draw_set=draws,
        fixture_registry=fixture_registry,
        public_schedule=public_schedule,
        training_dataset=authenticate(training_dataset),
        league_baseline=league_baseline,
        forecasts=forecasts,
    )


def forecast_matrix(value: PublicForecastDistribution) -> tuple[tuple[Decimal, ...], ...]:
    with localcontext() as context:
        context.prec = 60
        matrix = [[Decimal(0)] * (SUPPORT_MAX + 1) for _ in range(SUPPORT_MAX + 1)]
        for row in value.rates:
            hp, ap = (
                poisson_pmf(row.lambda_home, SUPPORT_MAX),
                poisson_pmf(row.lambda_away, SUPPORT_MAX),
            )
            mass = sum(hp, Decimal(0)) * sum(ap, Decimal(0))
            if 1 - mass > Decimal("1e-12"):
                raise StrengthEvidenceError("forecast exceeds governed research tail tolerance")
            for h in range(SUPPORT_MAX + 1):
                for a in range(SUPPORT_MAX + 1):
                    matrix[h][a] += row.draw_weight * hp[h] * ap[a] / mass
        with localcontext() as exact:
            exact.prec = 120
            residual = 1 - sum((x for line in matrix for x in line), Decimal(0))
            h, a = max(
                ((h, a) for h in range(SUPPORT_MAX + 1) for a in range(SUPPORT_MAX + 1)),
                key=lambda cell: matrix[cell[0]][cell[1]],
            )
            matrix[h][a] += residual
        return tuple(tuple(line) for line in matrix)


class PublicProspectiveScoreV1(SealedEvidence):
    schema_version: Literal["public-team-strength-prospective-score-v1"] = (
        "public-team-strength-prospective-score-v1"
    )
    forecast_sha256: SHA
    outcome_snapshot_sha256: SHA
    scored_at: datetime
    dataset_mode: MODE
    draw_policy_sha256: SHA
    # Tuple rows: fixture UUID, product, typed metric pairs and calibration residuals.
    scores: tuple[tuple[UUID, PRODUCT, tuple[tuple[str, Number], ...]], ...] = Field(min_length=1)
    promotion: PromotionEvidenceStatus = PromotionEvidenceStatus()

    @model_validator(mode="after")
    def validate_metric_contract(self) -> Self:
        expected = {
            "exact_score_log_loss",
            "team_count_log_loss",
            "goal_rps",
            "home_bias",
            "away_bias",
        }
        expected.update(
            event + suffix
            for event in CALIBRATION_EVENTS
            for suffix in ("_probability", "_outcome", "_brier", "_calibration_residual")
        )
        if len({(fixture, product) for fixture, product, _ in self.scores}) != len(self.scores):
            raise ValueError("duplicate public scored fixture/product")
        for _, _, pairs in self.scores:
            metrics = dict(pairs)
            if len(metrics) != len(pairs) or set(metrics) != expected:
                raise ValueError("public score metric contract differs")
            for event in CALIBRATION_EVENTS:
                if not 0 <= metrics[event + "_probability"] <= 1 or metrics[
                    event + "_outcome"
                ] not in (0, 1):
                    raise ValueError("invalid calibration probability/outcome")
        return self


def score_public_team_forecasts(
    forecast: PublicTeamStrengthForecastV1, *, outcomes: ParsedSnapshot, as_of: datetime
) -> PublicProspectiveScoreV1:
    require_public_prospective_storage(forecast.data_class)
    forecast, outcomes = authenticate(forecast), authenticate(outcomes)
    as_of = FrozenEvidence.utc_datetimes(as_of)
    if not forecast.frozen_at < outcomes.lineage.usable_at <= as_of:
        raise StrengthEvidenceError("outcomes not operationally available at scoring cutoff")
    if outcomes.fixture_registry_sha256 != forecast.fixture_registry.semantic_sha256:
        raise StrengthEvidenceError("outcome fixture registry differs from frozen forecast")
    observed = {row.fixture.fixture_id: row for row in outcomes.matches}
    scores = []
    for prediction in forecast.forecasts:
        row = observed.get(prediction.fixture.fixture_id)
        if (
            row is None
            or row.fixture != prediction.fixture
            or row.finality != "FULL_TIME"
            or row.home_goals is None
            or row.away_goals is None
        ):
            raise StrengthEvidenceError("eligible exact public outcome missing")
        if (
            row.source_match_date <= forecast.frozen_at.date()
            or eligibility_not_before(row.source_match_date) > as_of
        ):
            raise StrengthEvidenceError(
                "forecast not frozen before outcome or D+2 lag not satisfied"
            )
        if outcomes.lineage.received_at.date() < row.source_match_date:
            raise StrengthEvidenceError("outcome source received before played date")
        hg, ag = row.home_goals, row.away_goals
        if max(hg, ag) > SUPPORT_MAX:
            raise StrengthEvidenceError("outcome exceeds governed research score support")
        with localcontext() as context:
            context.prec = 60
            for product in prediction.distributions:
                matrix = forecast_matrix(product)
                features = distribution_features(matrix)
                hp = tuple(sum(line, Decimal(0)) for line in matrix)
                ap = tuple(
                    sum((line[k] for line in matrix), Decimal(0)) for k in range(SUPPORT_MAX + 1)
                )
                if matrix[hg][ag] <= 0:
                    raise StrengthEvidenceError(
                        "impossible forecast outcome; no probability clipping"
                    )
                metrics = {
                    "exact_score_log_loss": -matrix[hg][ag].ln(),
                    "team_count_log_loss": -(hp[hg].ln() + ap[ag].ln()) / 2,
                    "goal_rps": sum(
                        (
                            (sum(pmf[: k + 1], Decimal(0)) - int(k >= observed_goal)) ** 2
                            for pmf, observed_goal in ((hp, hg), (ap, ag))
                            for k in range(SUPPORT_MAX)
                        ),
                        Decimal(0),
                    )
                    / 2,
                    "home_bias": features["home_expected_goals"] - hg,
                    "away_bias": features["away_expected_goals"] - ag,
                }
                for name, actual in (
                    ("home_win", hg > ag),
                    ("draw", hg == ag),
                    ("away_win", hg < ag),
                    ("home_clean_sheet", ag == 0),
                    ("away_clean_sheet", hg == 0),
                    *((f"total_over_{line}.5", hg + ag > line) for line in range(6)),
                ):
                    probability = features[name]
                    metrics[name + "_probability"] = probability
                    metrics[name + "_outcome"] = Decimal(int(actual))
                    metrics[name + "_brier"] = (probability - int(actual)) ** 2
                    metrics[name + "_calibration_residual"] = probability - int(actual)
                scores.append(
                    (row.fixture.fixture_id, product.product, tuple(sorted(metrics.items())))
                )
    return seal(
        PublicProspectiveScoreV1,
        forecast_sha256=forecast.semantic_sha256,
        outcome_snapshot_sha256=outcomes.semantic_sha256,
        scored_at=as_of,
        dataset_mode=forecast.dataset_mode,
        draw_policy_sha256=forecast.draw_set.draw_policy_sha256,
        scores=tuple(scores),
    )


class PublicForecastBuildRequestV1(FrozenEvidence):
    schema_version: Literal["public-team-strength-forecast-build-request-v1"] = (
        "public-team-strength-forecast-build-request-v1"
    )
    artifact: TeamStrengthModelArtifactV1
    expected_artifact_sha256: SHA
    training_dataset: TeamStrengthHistoricalDatasetV1
    fixture_registry: FixtureRegistry
    public_schedule: ParsedSnapshot
    draw_policy: ParameterDrawPolicyV1
    forecast_origin: datetime
    fixture_ids: tuple[UUID, ...] = Field(min_length=1, max_length=380)
    league_baseline: CurrentScorePriorResult | None = None


def freeze_public_forecast_request(
    request: PublicForecastBuildRequestV1, *, clock: Callable[[], datetime] | None = None
) -> PublicTeamStrengthForecastV1:
    request = PublicForecastBuildRequestV1.model_validate_json(request.model_dump_json())
    artifact = authenticate(request.artifact, request.expected_artifact_sha256)
    return freeze_public_team_forecasts(
        artifact=artifact,
        draws=joint_parameter_draws(artifact, policy=request.draw_policy),
        training_dataset=request.training_dataset,
        fixture_registry=request.fixture_registry,
        public_schedule=request.public_schedule,
        forecast_origin=request.forecast_origin,
        fixture_ids=tuple(str(x) for x in request.fixture_ids),
        league_baseline=request.league_baseline,
        clock=clock,
    )


class PublicCalibrationDiagnostic(FrozenEvidence):
    product: PRODUCT
    event: str
    dataset_mode: MODE
    draw_policy_sha256: SHA
    score_report_sha256s: tuple[SHA, ...]
    forecast_sha256s: tuple[SHA, ...]
    sampling_interpretation: Literal["FORECAST_ORIGIN_ROWS_NOT_INDEPENDENT_OUTCOMES"] = (
        "FORECAST_ORIGIN_ROWS_NOT_INDEPENDENT_OUTCOMES"
    )
    result: CalibrationResult


def prospective_calibration(
    reports: tuple[PublicProspectiveScoreV1, ...],
) -> tuple[PublicCalibrationDiagnostic, ...]:
    """Accepted Stage-15 diagnostics only; never calibrates or changes forecasts."""
    reports = tuple(authenticate(report) for report in reports)
    if not reports or len({report.forecast_sha256 for report in reports}) != len(reports):
        raise StrengthEvidenceError("calibration requires distinct frozen forecast bundles")
    if len({report.draw_policy_sha256 for report in reports}) != 1:
        raise StrengthEvidenceError("different draw policies require separate calibration evidence")
    if len({report.dataset_mode for report in reports}) != 1:
        raise StrengthEvidenceError("different dataset modes require separate calibration evidence")
    groups: dict[tuple[PRODUCT, str], list[tuple[Decimal, int]]] = {}
    for report in reports:
        for _fixture, product, pairs in report.scores:
            metrics = dict(pairs)
            for name in sorted(metrics):
                if name.endswith("_probability"):
                    event = name.removesuffix("_probability")
                    groups.setdefault((product, event), []).append(
                        (metrics[name], int(metrics[event + "_outcome"]))
                    )
    return tuple(
        PublicCalibrationDiagnostic(
            product=product,
            event=event,
            dataset_mode=reports[0].dataset_mode,
            draw_policy_sha256=reports[0].draw_policy_sha256,
            score_report_sha256s=tuple(sorted(report.semantic_sha256 for report in reports)),
            forecast_sha256s=tuple(sorted(report.forecast_sha256 for report in reports)),
            result=calibration_intercept_slope(
                tuple(p for p, _ in rows), tuple(y for _, y in rows)
            ),
        )
        for (product, event), rows in sorted(groups.items())
    )
