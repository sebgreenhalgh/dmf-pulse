"""Strict contracts for the Stage-15 synthetic overall-field approximation."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from math import isfinite
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.prices.models import ConfidenceGrade
from dmf_pulse.rank_strategy.models import (
    ManagerTeamPlan,
    NonNegativeFloat,
    PositiveInt,
    Probability,
    RankMass,
    RankModel,
    SampleRightsStatus,
    Sha256,
)

_PERCENTILE_KEYS = ("p10", "p25", "p50", "p75", "p90")
_OVERALL_FIELD_RIGHTS = {
    SampleRightsStatus.SYNTHETIC_APPROVED,
    SampleRightsStatus.REPOSITORY_APPROVED,
}
LineageId = Annotated[StrictStr, Field(min_length=1, max_length=500)]


class SyntheticBandSelectionBasis(StrEnum):
    """Permitted predeadline bases for a synthetic field representative."""

    SYNTHETIC_GENERATOR = "SYNTHETIC_GENERATOR"
    PREDEADLINE_APPROVED_SAMPLE = "PREDEADLINE_APPROVED_SAMPLE"
    REPOSITORY_APPROVED_SAMPLE = "REPOSITORY_APPROVED_SAMPLE"


class SyntheticApproximationStatus(StrEnum):
    """Truth status of the represented overall field."""

    KNOWN_TRUTH_EXHAUSTIVE = "KNOWN_TRUTH_EXHAUSTIVE"
    WEIGHTED_REPRESENTATIVE_APPROXIMATION = "WEIGHTED_REPRESENTATIVE_APPROXIMATION"


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
    provenance_ids: tuple[LineageId, ...] = Field(min_length=1)
    source_bundle_ids: tuple[LineageId, ...] = Field(min_length=1)
    upstream_hashes: tuple[Sha256, ...] = ()
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
        if self.rights_status not in _OVERALL_FIELD_RIGHTS:
            raise ValueError(
                "synthetic overall populations require synthetic or repository-approved rights"
            )
        for label, values in (
            ("provenance IDs", self.provenance_ids),
            ("source bundle IDs", self.source_bundle_ids),
            ("upstream hashes", self.upstream_hashes),
        ):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"synthetic population {label} must be sorted and unique")
        band_ids = tuple(item.band_id for item in self.bands)
        if band_ids != tuple(sorted(band_ids)) or len(band_ids) != len(set(band_ids)):
            raise ValueError("synthetic rank bands must be sorted and unique")
        ordered_by_rank = tuple(
            sorted(self.bands, key=lambda item: (item.best_rank, item.worst_rank))
        )
        for previous, current in pairwise(ordered_by_rank):
            if previous.worst_rank >= current.best_rank:
                raise ValueError("synthetic rank bands cannot overlap")
        if any(item.worst_rank > self.total_population_count for item in self.bands):
            raise ValueError("synthetic rank band lies outside the represented population")
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
        selection_bases = {band.selection_basis for band in self.bands}
        if self.rights_status is SampleRightsStatus.SYNTHETIC_APPROVED:
            if selection_bases != {SyntheticBandSelectionBasis.SYNTHETIC_GENERATOR}:
                raise ValueError("synthetic-approved population must use synthetic generators only")
        elif SyntheticBandSelectionBasis.SYNTHETIC_GENERATOR in selection_bases:
            raise ValueError("repository-approved population cannot relabel a synthetic generator")
        if self.known_truth and self.rights_status is not SampleRightsStatus.SYNTHETIC_APPROVED:
            raise ValueError("known-truth overall populations must be synthetic-approved")
        payload = self.model_dump(mode="json", exclude={"population_hash"})
        if self.population_hash != semantic_sha256(payload):
            raise ValueError("synthetic population hash does not reconcile")
        return self


class SyntheticPopulationDiagnostics(RankModel):
    represented_manager_count: PositiveInt
    input_representative_count: PositiveInt
    semantic_representative_count: PositiveInt
    effective_representative_count: StrictFloat = Field(gt=0.0, allow_inf_nan=False)
    maximum_representative_population_share: Probability
    band_population_entropy: NonNegativeFloat
    known_truth: StrictBool
    approximation_status: SyntheticApproximationStatus

    @model_validator(mode="after")
    def diagnostics_are_finite(self) -> SyntheticPopulationDiagnostics:
        if not isfinite(self.effective_representative_count):
            raise ValueError("effective representative count must be finite")
        if self.semantic_representative_count > self.input_representative_count:
            raise ValueError("semantic representative count cannot exceed input count")
        expected_status = (
            SyntheticApproximationStatus.KNOWN_TRUTH_EXHAUSTIVE
            if self.known_truth
            else SyntheticApproximationStatus.WEIGHTED_REPRESENTATIVE_APPROXIMATION
        )
        if self.approximation_status is not expected_status:
            raise ValueError("synthetic approximation status does not match truth label")
        return self


class SyntheticBandScenarioCount(RankModel):
    band_id: StrictStr = Field(min_length=1, max_length=200)
    population_count: PositiveInt
    managers_strictly_ahead: StrictInt = Field(ge=0)
    managers_exactly_tied: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def counts_fit_band(self) -> SyntheticBandScenarioCount:
        if self.managers_strictly_ahead + self.managers_exactly_tied > self.population_count:
            raise ValueError("synthetic scenario band counts exceed represented population")
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
    band_counts: tuple[SyntheticBandScenarioCount, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def rank_reconciles(self) -> SyntheticOverallScenarioOutcome:
        if self.rank != 1 + self.managers_strictly_ahead:
            raise ValueError("synthetic overall rank must equal one plus managers strictly ahead")
        band_ids = tuple(item.band_id for item in self.band_counts)
        if band_ids != tuple(sorted(band_ids)) or len(band_ids) != len(set(band_ids)):
            raise ValueError("synthetic scenario band counts must be sorted and unique")
        if sum(item.managers_strictly_ahead for item in self.band_counts) != (
            self.managers_strictly_ahead
        ):
            raise ValueError("synthetic scenario ahead count must reconcile across rank bands")
        if sum(item.managers_exactly_tied for item in self.band_counts) != (
            self.managers_exactly_tied
        ):
            raise ValueError("synthetic scenario tied count must reconcile across rank bands")
        return self


class SyntheticOverallDistribution(RankModel):
    """Rank PMF over a weighted overall field, without fake manager expansion."""

    schema_version: Literal["rank-synthetic-overall-distribution-v1"] = (
        "rank-synthetic-overall-distribution-v1"
    )
    target_manager_id: StrictStr = Field(min_length=1, max_length=200)
    population_size: PositiveInt
    population_hash: Sha256
    scenario_set_hash: Sha256
    raw_projection_hash: Sha256
    tie_policy_id: StrictStr = Field(min_length=1, max_length=200)
    tie_policy_hash: Sha256
    manager_multiplier_set_hashes: dict[StrictStr, Sha256]
    target_rank: PositiveInt | None = None
    rank_pmf: tuple[RankMass, ...] = Field(min_length=1)
    expected_rank: StrictFloat = Field(allow_inf_nan=False)
    median_rank: PositiveInt
    rank_percentiles: dict[StrictStr, PositiveInt]
    probability_target_rank: Probability | None = None
    overall_rank_one_probability: Probability
    outcomes: tuple[SyntheticOverallScenarioOutcome, ...] = Field(min_length=1)
    confidence: ConfidenceGrade
    approximation_only: Literal[True] = True
    definitive_overall_win_model: Literal[False] = False
    distribution_hash: Sha256

    @model_validator(mode="after")
    def distribution_is_canonical(self) -> SyntheticOverallDistribution:
        multiplier_manager_ids = tuple(self.manager_multiplier_set_hashes)
        if (
            not multiplier_manager_ids
            or multiplier_manager_ids != tuple(sorted(multiplier_manager_ids))
            or any(not manager_id for manager_id in multiplier_manager_ids)
        ):
            raise ValueError(
                "synthetic multiplier-set lineage must use sorted non-empty manager IDs"
            )
        if self.target_manager_id not in self.manager_multiplier_set_hashes:
            raise ValueError("synthetic target manager is missing multiplier-set lineage")
        ranks = tuple(item.rank for item in self.rank_pmf)
        if ranks != tuple(sorted(ranks)) or len(ranks) != len(set(ranks)):
            raise ValueError("synthetic overall rank PMF must be sorted by unique rank")
        if any(rank > self.population_size for rank in ranks):
            raise ValueError("synthetic overall PMF contains rank outside the population")
        if abs(sum(item.probability for item in self.rank_pmf) - 1.0) > 1e-10:
            raise ValueError("synthetic overall rank probabilities must sum to one")
        expected = sum(item.rank * item.probability for item in self.rank_pmf)
        if abs(self.expected_rank - expected) > 1e-10:
            raise ValueError("synthetic expected rank does not reconcile with the PMF")
        if tuple(self.rank_percentiles) != _PERCENTILE_KEYS:
            raise ValueError("synthetic rank percentiles must use the canonical keys")
        if self.target_rank is not None and self.target_rank > self.population_size:
            raise ValueError("synthetic target rank lies outside the represented population")
        target_probability = (
            None
            if self.target_rank is None
            else sum(item.probability for item in self.rank_pmf if item.rank <= self.target_rank)
        )
        if self.probability_target_rank != target_probability:
            raise ValueError("synthetic target probability must be derived from the PMF")
        rank_one = sum(item.probability for item in self.rank_pmf if item.rank == 1)
        if abs(self.overall_rank_one_probability - rank_one) > 1e-10:
            raise ValueError("synthetic overall rank-one probability must equal PMF mass")
        identities = tuple((item.scenario_id, item.outcome_draw_id) for item in self.outcomes)
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("synthetic overall outcomes must be sorted and unique")
        if abs(sum(item.weight for item in self.outcomes) - 1.0) > 1e-10:
            raise ValueError("synthetic overall outcome weights must sum to one")
        outcome_pmf: dict[int, float] = {}
        for item in self.outcomes:
            if item.rank > self.population_size:
                raise ValueError("synthetic scenario rank lies outside the population")
            outcome_pmf[item.rank] = outcome_pmf.get(item.rank, 0.0) + item.weight
        expected_pmf = tuple(
            RankMass(rank=rank, probability=probability)
            for rank, probability in sorted(outcome_pmf.items())
        )
        if self.rank_pmf != expected_pmf:
            raise ValueError("synthetic overall PMF must be derived from scenario outcomes")
        payload = self.model_dump(mode="json", exclude={"distribution_hash"})
        if self.distribution_hash != semantic_sha256(payload):
            raise ValueError("synthetic overall distribution hash does not reconcile")
        return self


class SyntheticOverallRankResult(RankModel):
    schema_version: Literal["rank-synthetic-overall-result-v1"] = "rank-synthetic-overall-result-v1"
    population_id: StrictStr = Field(min_length=1, max_length=200)
    population_hash: Sha256
    rights_status: SampleRightsStatus
    provenance_ids: tuple[LineageId, ...] = Field(min_length=1)
    source_bundle_ids: tuple[LineageId, ...] = Field(min_length=1)
    upstream_hashes: tuple[Sha256, ...] = ()
    information_cutoff: datetime
    distribution: SyntheticOverallDistribution
    diagnostics: SyntheticPopulationDiagnostics
    approximation_only: Literal[True] = True
    definitive_overall_win_model: Literal[False] = False
    result_hash: Sha256

    @model_validator(mode="after")
    def result_is_canonical(self) -> SyntheticOverallRankResult:
        if (
            self.information_cutoff.tzinfo is None
            or self.information_cutoff.utcoffset() != timedelta(0)
        ):
            raise ValueError("synthetic overall result cutoff must be timezone-aware UTC")
        if self.rights_status not in _OVERALL_FIELD_RIGHTS:
            raise ValueError("synthetic overall result rights are not permitted")
        for label, values in (
            ("provenance IDs", self.provenance_ids),
            ("source bundle IDs", self.source_bundle_ids),
            ("upstream hashes", self.upstream_hashes),
        ):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"synthetic overall result {label} must be sorted and unique")
        if self.distribution.population_size != self.diagnostics.represented_manager_count + 1:
            raise ValueError("synthetic result population does not reconcile with diagnostics")
        if self.distribution.population_hash != self.population_hash:
            raise ValueError("synthetic result population hash does not match its distribution")
        if self.diagnostics.known_truth != (
            self.diagnostics.approximation_status
            is SyntheticApproximationStatus.KNOWN_TRUTH_EXHAUSTIVE
        ):
            raise ValueError("synthetic result truth diagnostics do not reconcile")
        payload = self.model_dump(mode="json", exclude={"result_hash"})
        if self.result_hash != semantic_sha256(payload):
            raise ValueError("synthetic overall result hash does not reconcile")
        return self
