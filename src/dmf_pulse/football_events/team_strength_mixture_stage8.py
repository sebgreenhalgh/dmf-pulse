"""Explicit research-only mixture reconciliation through the accepted Stage-8 solver.

No ordinary service registration, private live resolver, or Stage-9/11 execution.
Public matrix views reuse accepted composition and coherence validation, then
are published in a distinct research schema with the correct mixture family.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.football_events._decimal import public_measure_text
from dmf_pulse.football_events.coherence import assert_score_coherence
from dmf_pulse.football_events.score_distribution import (
    CleanSheetDistribution,
    MarketResidual,
    OneXTwoDistribution,
    ProjectionDiagnostics,
    TotalGoalsProbability,
    compose_joint_score_distribution,
)
from dmf_pulse.football_events.score_projection import project_to_markets
from dmf_pulse.football_events.service import (
    ScoreBaselinePolicy,
    ScoreDistributionRequest,
    _constraint_set,
    _required_minimum_support,
    load_score_baseline_policy,
)
from dmf_pulse.football_events.team_strength_adapter import fixture_prior_bundle
from dmf_pulse.football_events.team_strength_mixture import (
    ParameterMixtureFixtureV1,
    build_parameter_mixture,
)
from dmf_pulse.football_events.team_strength_model import TeamStrengthModelArtifactV1
from dmf_pulse.football_events.team_strength_parameter_draws import (
    ParameterDrawSetV1,
    ParameterMixtureUnavailable,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FixtureRegistration,
    SealedEvidence,
    seal,
)


class ParameterMixtureStage8V1(SealedEvidence):
    schema_version: Literal["team-strength-parameter-mixture-stage8-v1"] = (
        "team-strength-parameter-mixture-stage8-v1"
    )
    mode: Literal["TEAM_STRENGTH_PARAMETER_MIXTURE_SHADOW"] = (
        "TEAM_STRENGTH_PARAMETER_MIXTURE_SHADOW"
    )
    model_family: Literal["PARAMETER_MIXTURE_INDEPENDENT_POISSON_SOFT_KL_V1"] = (
        "PARAMETER_MIXTURE_INDEPENDENT_POISSON_SOFT_KL_V1"
    )
    status: Literal["SHADOW_NOT_MODEL_INPUT"] = "SHADOW_NOT_MODEL_INPUT"
    production_active: Literal[False] = False
    research_only: Literal[True] = True
    request_sha256: SHA
    input_signature_sha256: SHA
    constraint_set_sha256: SHA
    stage8_policy_sha256: SHA
    mixture: ParameterMixtureFixtureV1
    probabilities: tuple[tuple[str, ...], ...]
    expected_home_goals: str
    expected_away_goals: str
    one_x_two: OneXTwoDistribution
    clean_sheets: CleanSheetDistribution
    total_goals: tuple[TotalGoalsProbability, ...]
    diagnostics: ProjectionDiagnostics
    market_residuals: tuple[MarketResidual, ...]
    source_market_sha256: SHA | None
    structural_world_id: str
    parameter_draw_ids: tuple[SHA, ...]
    outcome_layer: Literal["ALEATORIC_SCORE_MATRIX_AFTER_PARAMETER_MARGINALISATION"] = (
        "ALEATORIC_SCORE_MATRIX_AFTER_PARAMETER_MARGINALISATION"
    )

    @model_validator(mode="after")
    def check_views(self) -> Self:
        mixture = self.mixture
        if (
            self.structural_world_id != mixture.structural_world_id
            or self.parameter_draw_ids != tuple(row.parameter_draw_id for row in mixture.rates)
        ):
            raise ValueError("nested uncertainty lineage mismatch")
        if self.stage8_policy_sha256 != mixture.stage8_policy_sha256:
            raise ValueError("mixture and reconciliation policy differ")
        matrix = tuple(tuple(Decimal(x) for x in row) for row in self.probabilities)
        if len(matrix) != mixture.home_max + 1 or any(
            len(row) != mixture.away_max + 1 for row in matrix
        ):
            raise ValueError("reconciled support mismatch")
        if (
            any(
                not x.is_finite() or x < 0 or x.as_tuple().exponent != -12
                for row in matrix
                for x in row
            )
            or sum((x for row in matrix for x in row), Decimal(0)) != 1
        ):
            raise ValueError("invalid public matrix")
        home = sum((Decimal(i) * x for i, row in enumerate(matrix) for x in row), Decimal(0))
        away = sum((Decimal(j) * x for row in matrix for j, x in enumerate(row)), Decimal(0))
        if (public_measure_text(home), public_measure_text(away)) != (
            self.expected_home_goals,
            self.expected_away_goals,
        ):
            raise ValueError("reconciled expectations mismatch")
        hda = tuple(
            sum(
                (
                    x
                    for i, row in enumerate(matrix)
                    for j, x in enumerate(row)
                    if (i > j, i == j, i < j)[k]
                ),
                Decimal(0),
            )
            for k in range(3)
        )
        if hda != tuple(
            Decimal(x)
            for x in (self.one_x_two.home_win, self.one_x_two.draw, self.one_x_two.away_win)
        ):
            raise ValueError("reconciled 1X2 mismatch")
        if (sum((row[0] for row in matrix), Decimal(0)), sum(matrix[0], Decimal(0))) != tuple(
            Decimal(x)
            for x in (self.clean_sheets.home_clean_sheet, self.clean_sheets.away_clean_sheet)
        ):
            raise ValueError("reconciled clean sheets mismatch")
        for line in self.total_goals:
            under = sum(
                (
                    x
                    for i, row in enumerate(matrix)
                    for j, x in enumerate(row)
                    if Decimal(i + j) < Decimal(line.line)
                ),
                Decimal(0),
            )
            if under != Decimal(line.under) or 1 - under != Decimal(line.over):
                raise ValueError("reconciled totals mismatch")
        return self


def project_parameter_mixture(
    request: ScoreDistributionRequest,
    *,
    artifact: TeamStrengthModelArtifactV1,
    draws: ParameterDrawSetV1 | None,
    fixture: FixtureRegistration,
    expected_artifact_sha256: str,
    policy: ScoreBaselinePolicy | None = None,
) -> ParameterMixtureStage8V1:
    if draws is None:
        raise ParameterMixtureUnavailable("requested mixture draw set unavailable")
    # Revalidate even deliberately bypassed Pydantic construction.
    request = ScoreDistributionRequest.model_validate(request.model_dump(mode="python"))
    if request.fixture_status != "SCHEDULED":
        raise ParameterMixtureUnavailable("research mixture requires a scheduled fixture")
    if (request.fixture_id, request.home_team_id, request.away_team_id) != (
        fixture.fixture_id,
        fixture.home_team_id,
        fixture.away_team_id,
    ):
        raise ParameterMixtureUnavailable("research fixture/request identity mismatch")
    plugin = fixture_prior_bundle(
        artifact=artifact,
        fixture=fixture,
        as_of=request.as_of,
        expected_artifact_sha256=expected_artifact_sha256,
    )
    if request.prior != plugin.score_prior:
        raise ParameterMixtureUnavailable("reference request is not the bound plug-in prior")
    selected = policy or load_score_baseline_policy()
    constraints = _constraint_set(request, selected)
    mixture = build_parameter_mixture(
        artifact=artifact,
        draws=draws,
        fixture=fixture,
        as_of=request.as_of,
        expected_artifact_sha256=expected_artifact_sha256,
        policy=selected,
        minimum_support=_required_minimum_support(constraints, selected),
    )
    signature = canonical_sha256(
        {
            "request": request.public_identity(),
            "mixture": mixture.semantic_sha256,
            "constraints": constraints.public_dict(),
            "policy": selected.sha256,
            "mode": mixture.mode,
        }
    )
    projection = project_to_markets(
        mixture.score_prior(),
        constraints,
        max_iterations=selected.projection.max_iterations,
        gradient_tolerance=selected.projection.gradient_tolerance,
        line_search_min_step=selected.projection.line_search_min_step,
        allow_prior_fallback=selected.projection.allow_prior_fallback,
    )
    # Composition is used only as a validated generic matrix/view representation;
    # its baseline family label is not published as the research model family.
    distribution = compose_joint_score_distribution(
        fixture_id=str(request.fixture_id),
        home_team_id=str(request.home_team_id),
        away_team_id=str(request.away_team_id),
        as_of=request.as_of.isoformat().replace("+00:00", "Z"),
        minutes_context=request.minutes_context,
        input_signature_sha256=signature,
        policy_sha256=selected.sha256,
        prior=mixture.score_prior(),
        projection=projection,
        constraint_set=constraints,
        total_lines=selected.derived_outputs.total_goal_lines,
        top_scoreline_count=selected.derived_outputs.top_scoreline_count,
    )
    assert_score_coherence(distribution)
    return seal(
        ParameterMixtureStage8V1,
        request_sha256=canonical_sha256(request.model_dump(mode="json")),
        input_signature_sha256=signature,
        constraint_set_sha256=canonical_sha256(constraints.public_dict()),
        stage8_policy_sha256=selected.sha256,
        mixture=mixture,
        probabilities=distribution.probabilities,
        expected_home_goals=distribution.expected_home_goals,
        expected_away_goals=distribution.expected_away_goals,
        one_x_two=distribution.one_x_two,
        clean_sheets=distribution.clean_sheets,
        total_goals=distribution.total_goals,
        diagnostics=distribution.diagnostics,
        market_residuals=distribution.market_residuals,
        source_market_sha256=distribution.source_market_sha256,
        structural_world_id=draws.structural_world_id,
        parameter_draw_ids=tuple(row.parameter_draw_id for row in draws.draws),
    )
