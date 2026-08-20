"""Strict contracts for the Stage-15 synthetic overall-field approximation."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from math import isfinite
from typing import Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.prices.models import ConfidenceGrade
from dmf_pulse.rank_strategy.models import (
    ManagerTeamPlan,
    NonNegativeFloat,
    PositiveInt,
    Probability,
    RankDistribution,
    RankModel,
    SampleRightsStatus,
    Sha256,
)


class SyntheticBandSelectionBasis(StrEnum):
    """Permitted predeadline bases for a synthetic field representative."""

    SYNTHETIC_GENERATOR = "SYNTHETIC_GENERATOR"
    PREDEADLINE_APPROVED_SAMPLE = "PREDEADLINE_APPROVED_SAMPLE"
    REPOSITORY_APPROVED_SAMPLE = "REPOSITORY_APPROVED_SAMPLE"


class SyntheticManagerRepresentative(RankModel):
    """One exact manager plan representing an integer number of field managers."""

    representative_id: StrictStr = Field(min_length=1, max_length=200)
    manager_plan: ManagerTeamPlan
    population_count: PositiveInt


class SyntheticRankBand(RankModel):
    """One weighted rank band with exact representative counts."""

    band_id: StrictStr = Field(min_length=1, max_length=200)
    best_rank: PositiveInt
    worst_rank: PositiveInt
    population_count: PositiveInt
    selection_basis: SyntheticBandSelectionBasis
    representatives: tuple[SyntheticManagerRepresentative, ...] = Field(min_length=1)
    uses_final_season_rank: Literal[False] = False

    @model_validator(mode="after")
    def band_is_canonical(self) -> SyntheticRankBand:
        if self.best_rank > self.worst_rank:
            raise ValueError("synthetic rank-band best rank cannot exceed worst rank")
        ids = tuple(item.representative_id for item in self.representatives)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("synthetic representatives must be sorted and unique")
        manager_ids = tuple(item.manager_plan.manager_id for item in self.representatives)
        if len(manager_ids) != len(set(manager_ids)):
            raise ValueError("synthetic representative manager IDs must be unique within a band")
        if sum(item.population_count for item in self.representatives) != self.population_count:
            raise ValueError("synthetic representative counts must reconcile with band population")
        return self


class SyntheticOverallPopulation(RankModel):
    """Rights-classified weighted approximation of an overall field.

    The target manager is not duplicated inside a band; total population includes
    the target exactly once plus all representative counts.
    """

    schema_version: Literal["rank-synthetic-overall-population-v1"] = (
        "rank-synthetic-overall-population-v1"
    )
    population_id: StrictStr = Field(min_length=1, max_length=200)
    target_plan: ManagerTeamPlan
    rights_status: SampleRightsStatus
    generated_at: datetime
    information_cutoff: datetime
    total_population_count: PositiveInt
    bands: tuple[SyntheticRankBand, ...] = Field(min_length=1)
    known_truth: StrictBool
    confidence: ConfidenceGrade
    mass_scrape_used: Literal[False] = False
    final_rank_hindsight_used: Literal[False] = False
    definitive_overall_win_model: Literal[False] = False
    population_hash: Sha256

    @model_validator(mode="after")
    def population_is_canonical(self) -> SyntheticOverallPopulation:
        for label, value in (
            ("generated_at", self.generated_at),
            ("information_cutoff", self.information_cutoff),
        ):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{label} must be timezone-aware UTC")
        if self.generated_at > self.information_cutoff:
            raise ValueError(
                "synthetic population cannot be generated after the information cutoff"
            )
        band_ids = tuple(item.band_id for item in self.bands)
        if band_ids != tuple(sorted(band_ids)) or len(band_ids) != len(set(band_ids)):
            raise ValueError("synthetic rank bands must be sorted and unique")
        ordered_by_rank = tuple(
            sorted(self.bands, key=lambda item: (item.best_rank, item.worst_rank))
        )
        for previous, current in pairwise(ordered_by_rank):
            if previous.worst_rank >= current.best_rank:
                raise ValueError("synthetic rank bands cannot overlap")
        representatives = tuple(
            representative for band in self.bands for representative in band.representatives
        )
        representative_ids = tuple(item.representative_id for item in representatives)
        if len(representative_ids) != len(set(representative_ids)):
            raise ValueError("synthetic representative IDs must be unique across bands")
        manager_ids = tuple(item.manager_plan.manager_id for item in representatives)
        if len(manager_ids) != len(set(manager_ids)):
            raise ValueError("synthetic representative manager IDs must be unique across bands")
        if self.target_plan.manager_id in manager_ids:
            raise ValueError("target manager cannot be duplicated in the synthetic field")
        expected_total = 1 + sum(item.population_count for item in self.bands)
        if self.total_population_count != expected_total:
            raise ValueError(
                "synthetic total population must include target once plus every band count"
            )
        payload = self.model_dump(mode="json", exclude={"population_hash"})
        if self.population_hash != semantic_sha256(payload):
            raise ValueError("synthetic population hash does not reconcile")
        return self


class SyntheticPopulationDiagnostics(RankModel):
    represented_manager_count: PositiveInt
    representative_count: PositiveInt
    effective_representative_count: StrictFloat = Field(gt=0.0, allow_inf_nan=False)
    maximum_representative_population_share: Probability
    band_population_entropy: NonNegativeFloat
    known_truth: StrictBool

    @model_validator(mode="after")
    def diagnostics_are_finite(self) -> SyntheticPopulationDiagnostics:
        if not isfinite(self.effective_representative_count):
            raise ValueError("effective representative count must be finite")
        return self


class SyntheticOverallScenarioOutcome(RankModel):
    scenario_id: StrictStr = Field(min_length=1, max_length=200)
    outcome_draw_id: StrictStr = Field(min_length=1, max_length=200)
    weight: Probability
    target_final_points: StrictInt
    target_counted_transfers: StrictInt = Field(ge=0)
    managers_strictly_ahead: StrictInt = Field(ge=0)
    managers_exactly_tied: StrictInt = Field(ge=0)
    rank: PositiveInt

    @model_validator(mode="after")
    def rank_reconciles(self) -> SyntheticOverallScenarioOutcome:
        if self.rank != 1 + self.managers_strictly_ahead:
            raise ValueError("synthetic overall rank must equal one plus managers strictly ahead")
        return self


class SyntheticOverallRankResult(RankModel):
    schema_version: Literal["rank-synthetic-overall-result-v1"] = "rank-synthetic-overall-result-v1"
    population_id: StrictStr = Field(min_length=1, max_length=200)
    distribution: RankDistribution
    scenario_outcomes: tuple[SyntheticOverallScenarioOutcome, ...] = Field(min_length=1)
    diagnostics: SyntheticPopulationDiagnostics
    approximation_only: Literal[True] = True
    definitive_overall_win_model: Literal[False] = False
    result_hash: Sha256

    @model_validator(mode="after")
    def result_is_canonical(self) -> SyntheticOverallRankResult:
        identities = tuple(
            (item.scenario_id, item.outcome_draw_id) for item in self.scenario_outcomes
        )
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("synthetic overall scenario outcomes must be sorted and unique")
        if abs(sum(item.weight for item in self.scenario_outcomes) - 1.0) > 1e-10:
            raise ValueError("synthetic overall scenario weights must sum to one")
        return self
