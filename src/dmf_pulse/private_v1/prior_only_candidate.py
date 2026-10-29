"""Inactive owned-source fixture composition over the unchanged Stage-8 service.

This is an offline application candidate, never a private Refresh alternative.
It deliberately cannot construct Odds availability evidence or unified state.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.football_events.service import (
    ScoreDistributionRequest,
    ScoreDistributionResult,
    ScoreDistributionService,
    load_score_baseline_policy,
)
from dmf_pulse.private_v1.models import PrivateFixtureScorePrior

Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _Candidate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        revalidate_instances="always",
    )

    @model_validator(mode="after")
    def aware_times(self) -> Self:
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError("candidate times must be timezone-aware")
                object.__setattr__(self, name, value.astimezone(UTC))
        return self

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        del deep
        values = {name: getattr(self, name) for name in type(self).model_fields}
        if update:
            values.update(update)
        return type(self).model_validate(values)


class PriorOnlyFixture(_Candidate):
    official_fixture_id: Annotated[int, Field(ge=1)]
    official_fixture_lookup_sha256: Sha
    gameweek: Annotated[int, Field(ge=1, le=38)]
    home_official_team_id: Annotated[int, Field(ge=1)]
    away_official_team_id: Annotated[int, Field(ge=1)]
    kickoff_at: datetime
    prior: PrivateFixtureScorePrior
    request: ScoreDistributionRequest

    @model_validator(mode="after")
    def source_and_stage7_match(self) -> Self:
        prior, request = self.prior, self.request
        if self.home_official_team_id == self.away_official_team_id:
            raise ValueError("official fixture teams must differ")
        if prior.source_class != "REPOSITORY_OWNED_SYNTHETIC":
            raise ValueError("offline candidate admits only owned synthetic prior evidence")
        if request.constraints or request.market_consensus is not None:
            raise ValueError("prior-only mode cannot carry market evidence")
        if (
            prior.fixture_id != request.fixture_id
            or prior.home_team_id != request.home_team_id
            or prior.away_team_id != request.away_team_id
            or prior.as_of != request.as_of
            or prior.score_prior_request != request.prior
        ):
            raise ValueError("sealed prior and Stage-8 fixture identity differ")
        if request.fixture_status != "SCHEDULED" or self.kickoff_at <= request.as_of:
            raise ValueError("prior-only candidate requires a future scheduled fixture")
        return self


class PriorOnlyGameweekAssignment(_Candidate):
    gameweek: Annotated[int, Field(ge=1, le=38)]
    official_fixture_ids: tuple[Annotated[int, Field(ge=1)], ...]

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if self.official_fixture_ids != tuple(sorted(set(self.official_fixture_ids))):
            raise ValueError("official fixture assignment must be sorted and unique")
        return self


class PriorOnlyCandidateInput(_Candidate):
    schema_version: Literal["governed-prior-only-candidate-v1"] = "governed-prior-only-candidate-v1"
    status: Literal["INACTIVE_OFFLINE_ONLY"] = "INACTIVE_OFFLINE_ONLY"
    classification: Literal["REPOSITORY_OWNED_SYNTHETIC"] = "REPOSITORY_OWNED_SYNTHETIC"
    mode: Literal["GOVERNED_PRIOR_ONLY"] = "GOVERNED_PRIOR_ONLY"
    season_code: Annotated[str, Field(pattern=r"^20[0-9]{2}/[0-9]{2}$")]
    target_gameweek: Annotated[int, Field(ge=1, le=38)]
    horizon: Literal[1, 3]
    information_cutoff: datetime
    expected_stage8_policy_sha256: Sha
    assignments: tuple[PriorOnlyGameweekAssignment, ...]
    fixtures: tuple[PriorOnlyFixture, ...]

    @model_validator(mode="after")
    def exact_official_horizon(self) -> Self:
        expected_gameweeks = tuple(range(self.target_gameweek, self.target_gameweek + self.horizon))
        if tuple(row.gameweek for row in self.assignments) != expected_gameweeks:
            raise ValueError("candidate assignments must cover exact declared horizon")
        declared = {
            (row.gameweek, fixture_id)
            for row in self.assignments
            for fixture_id in row.official_fixture_ids
        }
        observed = {(row.gameweek, row.official_fixture_id) for row in self.fixtures}
        if declared != observed or len(observed) != len(self.fixtures):
            raise ValueError("candidate must uniquely cover every exact official fixture")
        for values in (
            [row.official_fixture_id for row in self.fixtures],
            [row.official_fixture_lookup_sha256 for row in self.fixtures],
            [str(row.request.fixture_id) for row in self.fixtures],
        ):
            if len(set(values)) != len(values):
                raise ValueError("candidate fixture identity is ambiguous")
        if any(row.request.as_of != self.information_cutoff for row in self.fixtures):
            raise ValueError("candidate must use one information cutoff")
        return self

    @property
    def semantic_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class PriorOnlyCandidateReport(_Candidate):
    schema_version: Literal["governed-prior-only-report-v1"] = "governed-prior-only-report-v1"
    status: Literal["INACTIVE_OFFLINE_ONLY"] = "INACTIVE_OFFLINE_ONLY"
    classification: Literal["REPOSITORY_OWNED_SYNTHETIC"] = "REPOSITORY_OWNED_SYNTHETIC"
    mode: Literal["GOVERNED_PRIOR_ONLY"] = "GOVERNED_PRIOR_ONLY"
    private_workflow_status: Literal["NOT_CONNECTED_TO_PRIVATE_WORKFLOW"] = (
        "NOT_CONNECTED_TO_PRIVATE_WORKFLOW"
    )
    input_sha256: Sha
    stage8_policy_sha256: Sha
    fixture_results: tuple[ScoreDistributionResult, ...]
    limitations: tuple[str, ...] = (
        "INACTIVE_POLICY_NO_LIVE_AUTHORITY",
        "NO_MARKET_CONSTRAINTS_CONFIDENCE_D",
        "NO_CURRENT_TEAM_STRENGTH_OR_MARKET_CALIBRATION",
        "NO_PRIVATE_WORKFLOW_OR_DECISION_PARITY_CLAIM",
    )


def project_prior_only_candidate(value: PriorOnlyCandidateInput) -> PriorOnlyCandidateReport:
    """Reuse accepted mathematics; no network, transport, storage or activation."""
    value = PriorOnlyCandidateInput.model_validate(value)
    policy = load_score_baseline_policy()
    if policy.sha256 != value.expected_stage8_policy_sha256:
        raise ValueError("candidate Stage-8 policy identity differs")
    results = tuple(
        ScoreDistributionService().project(row.request, policy=policy) for row in value.fixtures
    )
    if any(
        result.distribution is None
        or result.distribution.diagnostics.projection_status != "PRIOR_ONLY"
        or result.distribution.confidence_grade != "D"
        for result in results
    ):
        raise ValueError("candidate did not produce the accepted visible prior-only outcome")
    return PriorOnlyCandidateReport(
        input_sha256=value.semantic_sha256,
        stage8_policy_sha256=policy.sha256,
        fixture_results=results,
    )
