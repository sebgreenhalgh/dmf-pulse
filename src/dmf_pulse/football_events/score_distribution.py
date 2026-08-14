"""Strict public joint-score distribution and deterministic derived outcomes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.football_events._decimal import (
    DECIMAL_PRECISION,
    SHA256_PATTERN,
    canonical_json_sha256,
    decimal_sqrt,
    exact_decimal,
    format_utc,
    parse_utc,
    probability,
    public_measure_text,
    public_probability_text,
    quantize_measure,
    quantize_probability,
    rounded_simplex,
)
from dmf_pulse.football_events.market_constraints import (
    MarketConstraint,
    MarketConstraintSet,
    MarketFamily,
    ScoreEvent,
)
from dmf_pulse.football_events.minutes_context import (
    Stage7MinutesContext,
    validate_stage7_context,
)
from dmf_pulse.football_events.score_prior import ScorePrior
from dmf_pulse.football_events.score_projection import (
    ProjectionResult,
    constraint_probabilities,
)

PROBABILITY_PATTERN = r"^(?:0\.\d{12}|1\.000000000000)$"
NONNEGATIVE_MEASURE_PATTERN = r"^\d+\.\d{6}$"
SIGNED_DECIMAL_12_PATTERN = r"^-?\d+\.\d{12}$"
SIGNED_DECIMAL_6_PATTERN = r"^-?\d+\.\d{6}$"
ProbabilityText = Annotated[str, Field(pattern=PROBABILITY_PATTERN)]


def _probability_text(value: str, *, label: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a public decimal string")
    return probability(value, label=label)


def _decimal_text(value: str, *, label: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a public decimal string")
    return exact_decimal(value, label=label)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        del deep
        data = self.model_dump(mode="python", exclude_none=False)
        if update:
            data.update(dict(update))
        return type(self).model_validate(data)


class OneXTwoDistribution(_FrozenModel):
    home_win: str = Field(pattern=PROBABILITY_PATTERN)
    draw: str = Field(pattern=PROBABILITY_PATTERN)
    away_win: str = Field(pattern=PROBABILITY_PATTERN)

    @model_validator(mode="after")
    def validate_simplex(self) -> Self:
        total = sum(
            (
                _probability_text(self.home_win, label="home_win"),
                _probability_text(self.draw, label="draw"),
                _probability_text(self.away_win, label="away_win"),
            ),
            Decimal(0),
        )
        if total != Decimal(1):
            raise ValueError("1X2 probabilities must sum exactly to one")
        return self


class CleanSheetDistribution(_FrozenModel):
    home_clean_sheet: str = Field(pattern=PROBABILITY_PATTERN)
    away_clean_sheet: str = Field(pattern=PROBABILITY_PATTERN)


class BinaryProbability(_FrozenModel):
    yes: str = Field(pattern=PROBABILITY_PATTERN)
    no: str = Field(pattern=PROBABILITY_PATTERN)

    @model_validator(mode="after")
    def validate_simplex(self) -> Self:
        if _probability_text(self.yes, label="yes") + _probability_text(
            self.no, label="no"
        ) != Decimal(1):
            raise ValueError("binary probabilities must sum exactly to one")
        return self


class TotalGoalsProbability(_FrozenModel):
    line: str = Field(pattern=r"^\d+\.5$")
    under: str = Field(pattern=PROBABILITY_PATTERN)
    over: str = Field(pattern=PROBABILITY_PATTERN)

    @model_validator(mode="after")
    def validate_simplex(self) -> Self:
        if _probability_text(self.under, label="under") + _probability_text(
            self.over, label="over"
        ) != Decimal(1):
            raise ValueError("total-goals under/over probabilities must sum exactly to one")
        return self


class ScorelineProbability(_FrozenModel):
    home_goals: int = Field(ge=0)
    away_goals: int = Field(ge=0)
    probability: str = Field(pattern=PROBABILITY_PATTERN)


class MarketResidual(_FrozenModel):
    constraint_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    event: str = Field(min_length=1)
    line: str | None
    home_goals: int | None = Field(default=None, ge=0)
    away_goals: int | None = Field(default=None, ge=0)
    target_probability: str = Field(pattern=PROBABILITY_PATTERN)
    projected_probability: str = Field(pattern=PROBABILITY_PATTERN)
    residual: str = Field(pattern=SIGNED_DECIMAL_12_PATTERN)
    standardized_residual: str = Field(pattern=SIGNED_DECIMAL_6_PATTERN)
    uncertainty: str = Field(pattern=r"^\d+\.\d{12}$")
    weight: str = Field(pattern=r"^\d+\.\d{12}$")
    source_result_sha256: str | None

    @model_validator(mode="after")
    def validate_residual(self) -> Self:
        target = _probability_text(self.target_probability, label="target_probability")
        projected = _probability_text(
            self.projected_probability,
            label="projected_probability",
        )
        residual = _decimal_text(self.residual, label="residual")
        uncertainty = _decimal_text(self.uncertainty, label="uncertainty")
        if uncertainty <= 0:
            raise ValueError("market residual uncertainty must be positive")
        if quantize_probability(projected - target) != residual:
            raise ValueError("market residual does not equal projected minus target")
        if self.source_result_sha256 is not None and (
            SHA256_PATTERN.fullmatch(self.source_result_sha256) is None
        ):
            raise ValueError("source_result_sha256 must be lowercase SHA-256")
        return self


class ProjectionDiagnostics(_FrozenModel):
    projection_status: Literal["PROJECTED", "PRIOR_ONLY", "DEGRADED"]
    solver_converged: bool
    solver_iterations: int = Field(ge=0)
    solver_error_code: str | None
    tail_treatment: Literal["RENORMALISED_TRUNCATION"]
    prior_to_projected_kl: str = Field(pattern=r"^\d+\.\d{12}$")
    market_rmse: str = Field(pattern=r"^\d+\.\d{12}$")
    maximum_absolute_market_residual: str = Field(pattern=r"^\d+\.\d{12}$")
    constraint_count: int = Field(ge=0)


def _constraint_from_public_residual(
    residual: MarketResidual,
    *,
    as_of: str,
    home_max: int,
    away_max: int,
) -> MarketConstraint:
    if (residual.home_goals is not None and residual.home_goals > home_max) or (
        residual.away_goals is not None and residual.away_goals > away_max
    ):
        raise ValueError("market residual score coordinates exceed matrix support")
    return MarketConstraint.model_validate(
        {
            "away_goals": residual.away_goals,
            "constraint_id": residual.constraint_id,
            "event": ScoreEvent(residual.event),
            "family": MarketFamily(residual.family),
            "home_goals": residual.home_goals,
            "line": residual.line,
            "source_result_sha256": residual.source_result_sha256,
            "target_probability": Decimal(residual.target_probability),
            "uncertainty": Decimal(residual.uncertainty),
            "usable_at": as_of,
            "weight": Decimal(residual.weight),
        }
    )


class JointScoreDistribution(_FrozenModel):
    """Canonical Stage-8 public output; all probabilities are exact strings."""

    schema_version: Literal["joint-score-distribution-v1"]
    fixture_id: str
    home_team_id: str
    away_team_id: str
    as_of: str
    information_cutoff: str
    source_minutes_as_of: str
    source_home_minutes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_away_minutes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_minutes_context: Stage7MinutesContext
    source_minutes_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_family: Literal["INDEPENDENT_POISSON_SOFT_KL_V1"]
    prior_home_goal_rate: str = Field(pattern=r"^\d+\.\d{6}$")
    prior_away_goal_rate: str = Field(pattern=r"^\d+\.\d{6}$")
    home_max: int = Field(ge=0)
    away_max: int = Field(ge=0)
    probabilities: tuple[tuple[ProbabilityText, ...], ...]
    tail_mass: str = Field(pattern=PROBABILITY_PATTERN)
    home_goal_pmf: tuple[ProbabilityText, ...]
    away_goal_pmf: tuple[ProbabilityText, ...]
    home_goals_conceded_pmf: tuple[ProbabilityText, ...]
    away_goals_conceded_pmf: tuple[ProbabilityText, ...]
    expected_home_goals: str = Field(pattern=NONNEGATIVE_MEASURE_PATTERN)
    expected_away_goals: str = Field(pattern=NONNEGATIVE_MEASURE_PATTERN)
    one_x_two: OneXTwoDistribution
    total_goals: tuple[TotalGoalsProbability, ...]
    clean_sheets: CleanSheetDistribution
    both_teams_to_score: BinaryProbability
    top_scorelines: tuple[ScorelineProbability, ...]
    market_residuals: tuple[MarketResidual, ...]
    diagnostics: ProjectionDiagnostics
    confidence_grade: Literal["A", "B", "C", "D"]
    confidence_reasons: tuple[
        Literal[
            "BASELINE_MODEL_CAP_B",
            "MARKET_CONSTRAINED",
            "NO_MARKET_CONSTRAINTS",
            "MARKET_RESIDUAL_HIGH",
            "LOW_MARKET_CONFIDENCE",
            "NUMERICAL_FALLBACK_TO_PRIOR",
            "TAIL_RENORMALISED",
            "STAGE7_MINUTES_CONTEXT_BOUND",
        ],
        ...,
    ]
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prior_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_market_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    input_signature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="before")
    @classmethod
    def coerce_sequences(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        for key in (
            "probabilities",
            "home_goal_pmf",
            "away_goal_pmf",
            "home_goals_conceded_pmf",
            "away_goals_conceded_pmf",
            "total_goals",
            "top_scorelines",
            "market_residuals",
            "confidence_reasons",
        ):
            if isinstance(data.get(key), list):
                data[key] = tuple(data[key])
        if isinstance(data.get("probabilities"), tuple):
            data["probabilities"] = tuple(
                tuple(row) if isinstance(row, list) else row for row in data["probabilities"]
            )
        return data

    @model_validator(mode="after")
    def validate_distribution(self) -> Self:
        try:
            UUID(self.fixture_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("fixture_id must be a UUID") from exc
        try:
            home_team_id = UUID(self.home_team_id)
            away_team_id = UUID(self.away_team_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("home_team_id and away_team_id must be UUIDs") from exc
        if home_team_id == away_team_id:
            raise ValueError("home_team_id and away_team_id must be distinct")
        as_of = parse_utc(self.as_of, field_name="as_of")
        cutoff = parse_utc(self.information_cutoff, field_name="information_cutoff")
        minutes_as_of = parse_utc(self.source_minutes_as_of, field_name="source_minutes_as_of")
        if as_of != cutoff:
            raise ValueError("as_of and information_cutoff must be identical in Stage 8")
        if minutes_as_of > cutoff:
            raise ValueError("POST_CUTOFF_MINUTES: source minutes are after cutoff")
        validate_stage7_context(
            self.source_minutes_context,
            fixture_id=UUID(self.fixture_id),
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            information_cutoff=cutoff,
        )
        if self.source_minutes_context.semantic_sha256 != self.source_minutes_context_sha256:
            raise ValueError("source_minutes_context_sha256 does not match its public context")
        if format_utc(self.source_minutes_context.source_as_of) != self.source_minutes_as_of:
            raise ValueError("source_minutes_as_of does not match its public context")
        if self.source_minutes_context.home.result_sha256 != self.source_home_minutes_sha256:
            raise ValueError("source_home_minutes_sha256 does not match its public context")
        if self.source_minutes_context.away.result_sha256 != self.source_away_minutes_sha256:
            raise ValueError("source_away_minutes_sha256 does not match its public context")
        if len(self.probabilities) != self.home_max + 1:
            raise ValueError("score matrix height does not match home_max")
        if any(len(row) != self.away_max + 1 for row in self.probabilities):
            raise ValueError("score matrix width does not match away_max")
        matrix = tuple(
            tuple(_probability_text(value, label="score probability") for value in row)
            for row in self.probabilities
        )
        if sum((sum(row, Decimal(0)) for row in matrix), Decimal(0)) != Decimal(1):
            raise ValueError("score matrix must sum exactly to one")
        if len(self.home_goal_pmf) != self.home_max + 1:
            raise ValueError("home_goal_pmf length does not match home_max")
        if len(self.away_goal_pmf) != self.away_max + 1:
            raise ValueError("away_goal_pmf length does not match away_max")
        home_pmf = tuple(
            _probability_text(value, label="home goal PMF") for value in self.home_goal_pmf
        )
        away_pmf = tuple(
            _probability_text(value, label="away goal PMF") for value in self.away_goal_pmf
        )
        derived_home = tuple(sum(row, Decimal(0)) for row in matrix)
        derived_away = tuple(
            sum((matrix[home][away] for home in range(self.home_max + 1)), Decimal(0))
            for away in range(self.away_max + 1)
        )
        if home_pmf != derived_home or away_pmf != derived_away:
            raise ValueError("published team goal PMFs do not match score matrix")
        home_conceded = tuple(
            _probability_text(value, label="home goals conceded PMF")
            for value in self.home_goals_conceded_pmf
        )
        away_conceded = tuple(
            _probability_text(value, label="away goals conceded PMF")
            for value in self.away_goals_conceded_pmf
        )
        if home_conceded != away_pmf or away_conceded != home_pmf:
            raise ValueError("goals-conceded PMFs must equal the opponent goal PMFs")
        expected_home = sum(
            (Decimal(index) * value for index, value in enumerate(home_pmf)),
            Decimal(0),
        )
        expected_away = sum(
            (Decimal(index) * value for index, value in enumerate(away_pmf)),
            Decimal(0),
        )
        if public_measure_text(expected_home) != self.expected_home_goals:
            raise ValueError("expected_home_goals does not match score matrix")
        if public_measure_text(expected_away) != self.expected_away_goals:
            raise ValueError("expected_away_goals does not match score matrix")
        home_win = sum(
            (
                matrix[home][away]
                for home in range(self.home_max + 1)
                for away in range(self.away_max + 1)
                if home > away
            ),
            Decimal(0),
        )
        draw = sum(
            (matrix[index][index] for index in range(min(self.home_max, self.away_max) + 1)),
            Decimal(0),
        )
        away_win = Decimal(1) - home_win - draw
        if (
            public_probability_text(home_win) != self.one_x_two.home_win
            or public_probability_text(draw) != self.one_x_two.draw
            or public_probability_text(away_win) != self.one_x_two.away_win
        ):
            raise ValueError("published 1X2 values do not match score matrix")
        home_clean_sheet = away_pmf[0]
        away_clean_sheet = home_pmf[0]
        if (
            public_probability_text(home_clean_sheet) != self.clean_sheets.home_clean_sheet
            or public_probability_text(away_clean_sheet) != self.clean_sheets.away_clean_sheet
        ):
            raise ValueError("clean-sheet probabilities do not match zero conceded")
        btts_yes = sum(
            (
                matrix[home][away]
                for home in range(1, self.home_max + 1)
                for away in range(1, self.away_max + 1)
            ),
            Decimal(0),
        )
        if (
            public_probability_text(btts_yes) != self.both_teams_to_score.yes
            or public_probability_text(Decimal(1) - btts_yes) != self.both_teams_to_score.no
        ):
            raise ValueError("BTTS probabilities do not match score matrix")
        for total in self.total_goals:
            line = _decimal_text(total.line, label="total line")
            under = sum(
                (
                    matrix[home][away]
                    for home in range(self.home_max + 1)
                    for away in range(self.away_max + 1)
                    if Decimal(home + away) < line
                ),
                Decimal(0),
            )
            if public_probability_text(under) != total.under:
                raise ValueError("total-goals under probability does not match matrix")
            if public_probability_text(Decimal(1) - under) != total.over:
                raise ValueError("total-goals over probability does not match matrix")
        expected_top = sorted(
            (
                (matrix[home][away], home, away)
                for home in range(self.home_max + 1)
                for away in range(self.away_max + 1)
            ),
            key=lambda item: (-item[0], item[1], item[2]),
        )[: len(self.top_scorelines)]
        supplied_top = [
            (
                _probability_text(item.probability, label="scoreline probability"),
                item.home_goals,
                item.away_goals,
            )
            for item in self.top_scorelines
        ]
        if supplied_top != expected_top:
            raise ValueError("top_scorelines do not match deterministic matrix ranking")
        residual_constraints = tuple(
            _constraint_from_public_residual(
                item,
                as_of=self.as_of,
                home_max=self.home_max,
                away_max=self.away_max,
            )
            for item in self.market_residuals
        )
        projected_residual_probabilities = constraint_probabilities(
            matrix,
            residual_constraints,
        )
        residual_values: list[Decimal] = []
        for residual, projected in zip(
            self.market_residuals,
            projected_residual_probabilities,
            strict=True,
        ):
            expected_projected = quantize_probability(projected)
            if public_probability_text(expected_projected) != residual.projected_probability:
                raise ValueError(
                    "market residual projected_probability does not match score matrix"
                )
            expected_residual = quantize_probability(
                expected_projected - Decimal(residual.target_probability)
            )
            if format(expected_residual, ".12f") != residual.residual:
                raise ValueError("market residual does not match matrix projection")
            uncertainty = Decimal(residual.uncertainty)
            expected_standardized = quantize_measure(expected_residual / uncertainty)
            if format(expected_standardized, ".6f") != residual.standardized_residual:
                raise ValueError(
                    "market residual standardized_residual does not match frozen policy"
                )
            residual_values.append(expected_residual)
        with localcontext() as context:
            context.prec = DECIMAL_PRECISION
            expected_rmse = (
                decimal_sqrt(
                    sum((value * value for value in residual_values), Decimal(0))
                    / Decimal(len(residual_values))
                )
                if residual_values
                else Decimal(0)
            )
        expected_maximum = max(
            (abs(value) for value in residual_values),
            default=Decimal(0),
        )
        if public_probability_text(expected_rmse) != self.diagnostics.market_rmse:
            raise ValueError("market_rmse does not match market residuals")
        if (
            public_probability_text(expected_maximum)
            != self.diagnostics.maximum_absolute_market_residual
        ):
            raise ValueError("maximum_absolute_market_residual does not match market residuals")
        if len(set(self.confidence_reasons)) != len(self.confidence_reasons):
            raise ValueError("confidence_reasons must be unique")
        if self.diagnostics.constraint_count != len(self.market_residuals):
            raise ValueError("constraint_count does not match market_residuals")
        body = self.model_dump(mode="json")
        supplied_hash = body.pop("result_sha256")
        if canonical_json_sha256(body) != supplied_hash:
            raise ValueError("result_sha256 does not match public fields")
        return self


def _matrix_from_flat(
    values: Sequence[Decimal],
    *,
    home_max: int,
    away_max: int,
) -> tuple[tuple[Decimal, ...], ...]:
    width = away_max + 1
    return tuple(
        tuple(values[home * width + away] for away in range(width)) for home in range(home_max + 1)
    )


def _confidence(
    projection: ProjectionResult,
    constraint_set: MarketConstraintSet,
    max_abs_residual: Decimal,
) -> tuple[str, tuple[str, ...]]:
    if projection.status == "DEGRADED":
        return "D", (
            "NUMERICAL_FALLBACK_TO_PRIOR",
            "NO_MARKET_CONSTRAINTS" if not constraint_set.constraints else "MARKET_RESIDUAL_HIGH",
            "TAIL_RENORMALISED",
            "STAGE7_MINUTES_CONTEXT_BOUND",
        )
    if not constraint_set.constraints:
        return "D", (
            "NO_MARKET_CONSTRAINTS",
            "TAIL_RENORMALISED",
            "STAGE7_MINUTES_CONTEXT_BOUND",
        )
    reasons: list[str] = [
        "BASELINE_MODEL_CAP_B",
        "MARKET_CONSTRAINED",
        "TAIL_RENORMALISED",
        "STAGE7_MINUTES_CONTEXT_BOUND",
    ]
    grades = {item.confidence_grade for item in constraint_set.constraints}
    if "D" in grades or "C" in grades:
        reasons.append("LOW_MARKET_CONFIDENCE")
    if max_abs_residual > Decimal("0.03"):
        reasons.append("MARKET_RESIDUAL_HIGH")
    if "MARKET_RESIDUAL_HIGH" in reasons or "LOW_MARKET_CONFIDENCE" in reasons:
        return "C", tuple(reasons)
    return "B", tuple(reasons)


def compose_joint_score_distribution(
    *,
    fixture_id: str,
    home_team_id: str,
    away_team_id: str,
    as_of: str,
    minutes_context: Stage7MinutesContext,
    input_signature_sha256: str,
    policy_sha256: str,
    prior: ScorePrior,
    projection: ProjectionResult,
    constraint_set: MarketConstraintSet,
    total_lines: Sequence[Decimal],
    top_scoreline_count: int,
) -> JointScoreDistribution:
    """Round once, then derive every public field from the same exact matrix."""

    if SHA256_PATTERN.fullmatch(input_signature_sha256) is None:
        raise ValueError("input_signature_sha256 must be lowercase SHA-256")
    if SHA256_PATTERN.fullmatch(policy_sha256) is None:
        raise ValueError("policy_sha256 must be lowercase SHA-256")
    if top_scoreline_count < 1:
        raise ValueError("top_scoreline_count must be positive")
    flattened = tuple(value for row in projection.probabilities for value in row)
    public_flat = rounded_simplex(flattened)
    matrix = _matrix_from_flat(
        public_flat,
        home_max=prior.grid.home_max,
        away_max=prior.grid.away_max,
    )
    home_pmf = tuple(sum(row, Decimal(0)) for row in matrix)
    away_pmf = tuple(
        sum(
            (matrix[home][away] for home in range(prior.grid.home_max + 1)),
            Decimal(0),
        )
        for away in range(prior.grid.away_max + 1)
    )
    expected_home = sum(
        (Decimal(index) * value for index, value in enumerate(home_pmf)),
        Decimal(0),
    )
    expected_away = sum(
        (Decimal(index) * value for index, value in enumerate(away_pmf)),
        Decimal(0),
    )
    home_win = sum(
        (
            matrix[home][away]
            for home in range(prior.grid.home_max + 1)
            for away in range(prior.grid.away_max + 1)
            if home > away
        ),
        Decimal(0),
    )
    draw = sum(
        (
            matrix[index][index]
            for index in range(min(prior.grid.home_max, prior.grid.away_max) + 1)
        ),
        Decimal(0),
    )
    away_win = Decimal(1) - home_win - draw
    btts_yes = sum(
        (
            matrix[home][away]
            for home in range(1, prior.grid.home_max + 1)
            for away in range(1, prior.grid.away_max + 1)
        ),
        Decimal(0),
    )
    totals: list[dict[str, str]] = []
    for line in total_lines:
        exact_line = exact_decimal(line, label="total line")
        if exact_line < 0 or exact_line % 1 != Decimal("0.5"):
            raise ValueError("total lines must be nonnegative half-goal lines")
        under = sum(
            (
                matrix[home][away]
                for home in range(prior.grid.home_max + 1)
                for away in range(prior.grid.away_max + 1)
                if Decimal(home + away) < exact_line
            ),
            Decimal(0),
        )
        totals.append(
            {
                "line": format(exact_line, "f"),
                "over": public_probability_text(Decimal(1) - under),
                "under": public_probability_text(under),
            }
        )
    ranked = sorted(
        (
            (matrix[home][away], home, away)
            for home in range(prior.grid.home_max + 1)
            for away in range(prior.grid.away_max + 1)
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )[:top_scoreline_count]
    projected_constraints = constraint_probabilities(matrix, constraint_set.constraints)
    residuals: list[dict[str, Any]] = []
    residual_values: list[Decimal] = []
    for constraint, projected in zip(
        constraint_set.constraints,
        projected_constraints,
        strict=True,
    ):
        target_public = quantize_probability(constraint.target_probability)
        projected_public = quantize_probability(projected)
        residual = quantize_probability(projected_public - target_public)
        residual_values.append(residual)
        uncertainty_public = quantize_probability(constraint.uncertainty)
        standardized = quantize_measure(residual / uncertainty_public)
        residuals.append(
            {
                "away_goals": constraint.away_goals,
                "constraint_id": constraint.constraint_id,
                "event": constraint.event.value,
                "family": constraint.family.value,
                "home_goals": constraint.home_goals,
                "line": None if constraint.line is None else format(constraint.line, "f"),
                "projected_probability": public_probability_text(projected_public),
                "residual": format(residual, ".12f"),
                "source_result_sha256": constraint.source_result_sha256,
                "standardized_residual": format(standardized, ".6f"),
                "target_probability": public_probability_text(target_public),
                "uncertainty": format(uncertainty_public, ".12f"),
                "weight": format(quantize_probability(constraint.weight), ".12f"),
            }
        )
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        market_rmse = (
            decimal_sqrt(
                sum((value * value for value in residual_values), Decimal(0))
                / Decimal(len(residual_values))
            )
            if residual_values
            else Decimal(0)
        )
    max_abs_residual = max((abs(value) for value in residual_values), default=Decimal(0))
    confidence_grade, confidence_reasons = _confidence(
        projection,
        constraint_set,
        max_abs_residual,
    )
    body: dict[str, Any] = {
        "as_of": as_of,
        "away_goal_pmf": tuple(public_probability_text(value) for value in away_pmf),
        "away_goals_conceded_pmf": tuple(public_probability_text(value) for value in home_pmf),
        "away_max": prior.grid.away_max,
        "away_team_id": away_team_id,
        "both_teams_to_score": {
            "no": public_probability_text(Decimal(1) - btts_yes),
            "yes": public_probability_text(btts_yes),
        },
        "clean_sheets": {
            "away_clean_sheet": public_probability_text(home_pmf[0]),
            "home_clean_sheet": public_probability_text(away_pmf[0]),
        },
        "confidence_grade": confidence_grade,
        "confidence_reasons": confidence_reasons,
        "diagnostics": {
            "constraint_count": len(constraint_set.constraints),
            "market_rmse": public_probability_text(market_rmse),
            "maximum_absolute_market_residual": public_probability_text(max_abs_residual),
            "prior_to_projected_kl": public_probability_text(projection.prior_to_projected_kl),
            "projection_status": projection.status,
            "solver_converged": projection.converged,
            "solver_error_code": projection.error_code,
            "solver_iterations": projection.iterations,
            "tail_treatment": "RENORMALISED_TRUNCATION",
        },
        "expected_away_goals": public_measure_text(expected_away),
        "expected_home_goals": public_measure_text(expected_home),
        "fixture_id": fixture_id,
        "home_goal_pmf": tuple(public_probability_text(value) for value in home_pmf),
        "home_goals_conceded_pmf": tuple(public_probability_text(value) for value in away_pmf),
        "home_max": prior.grid.home_max,
        "home_team_id": home_team_id,
        "information_cutoff": as_of,
        "input_signature_sha256": input_signature_sha256,
        "market_residuals": tuple(residuals),
        "model_family": "INDEPENDENT_POISSON_SOFT_KL_V1",
        "one_x_two": {
            "away_win": public_probability_text(away_win),
            "draw": public_probability_text(draw),
            "home_win": public_probability_text(home_win),
        },
        "policy_sha256": policy_sha256,
        "prior_away_goal_rate": public_measure_text(prior.away_rate),
        "prior_home_goal_rate": public_measure_text(prior.home_rate),
        "prior_sha256": prior.semantic_sha256,
        "probabilities": tuple(
            tuple(public_probability_text(value) for value in row) for row in matrix
        ),
        "schema_version": "joint-score-distribution-v1",
        "source_away_minutes_sha256": minutes_context.away.result_sha256,
        "source_home_minutes_sha256": minutes_context.home.result_sha256,
        "source_market_sha256": constraint_set.source_result_sha256,
        "source_minutes_context": minutes_context.public_dict(),
        "source_minutes_as_of": format_utc(minutes_context.source_as_of),
        "source_minutes_context_sha256": minutes_context.semantic_sha256,
        "tail_mass": public_probability_text(prior.grid.omitted_tail_mass),
        "top_scorelines": tuple(
            {
                "away_goals": away,
                "home_goals": home,
                "probability": public_probability_text(value),
            }
            for value, home, away in ranked
        ),
        "total_goals": tuple(totals),
    }
    body["result_sha256"] = canonical_json_sha256(body)
    return JointScoreDistribution.model_validate(body)


__all__ = [
    "BinaryProbability",
    "CleanSheetDistribution",
    "JointScoreDistribution",
    "MarketResidual",
    "OneXTwoDistribution",
    "ProjectionDiagnostics",
    "ScorelineProbability",
    "TotalGoalsProbability",
    "compose_joint_score_distribution",
]
