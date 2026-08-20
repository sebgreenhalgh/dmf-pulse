"""Strict public contracts for RANK-015.

The contracts keep beliefs (shared raw player scenarios) separate from preference
(rank/competition utility).  Every semantic object is immutable and rejects
unknown fields so that Stage-15 outputs remain replayable.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from dmf_pulse.evaluation.artifacts import semantic_sha256
from dmf_pulse.optimisation.models import AutosubEvent, CaptainResolution, TacticalConfiguration
from dmf_pulse.prices.models import ConfidenceGrade

Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Probability = Annotated[StrictFloat, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
FiniteFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0.0, allow_inf_nan=False)]
PositiveFloat = Annotated[StrictFloat, Field(gt=0.0, allow_inf_nan=False)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
_ZERO_HASH = "0" * 64
_PERCENTILES = (
    ("p10", 0.10),
    ("p25", 0.25),
    ("p50", 0.50),
    ("p75", 0.75),
    ("p90", 0.90),
)


class RankModel(BaseModel):
    """Immutable strict Stage-15 model base."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ManagerChip(StrEnum):
    NONE = "NONE"
    TRIPLE_CAPTAIN = "TRIPLE_CAPTAIN"
    BENCH_BOOST = "BENCH_BOOST"
    FREE_HIT = "FREE_HIT"


class SampleRightsStatus(StrEnum):
    SYNTHETIC_APPROVED = "SYNTHETIC_APPROVED"
    REPOSITORY_APPROVED = "REPOSITORY_APPROVED"
    NAMED_RIVAL_AUTHORISED = "NAMED_RIVAL_AUTHORISED"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"

    @property
    def permitted(self) -> bool:
        return self in {
            SampleRightsStatus.SYNTHETIC_APPROVED,
            SampleRightsStatus.REPOSITORY_APPROVED,
            SampleRightsStatus.NAMED_RIVAL_AUTHORISED,
        }


class CohortKind(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    REPOSITORY_SAMPLE = "REPOSITORY_SAMPLE"
    NAMED_MINI_LEAGUE = "NAMED_MINI_LEAGUE"
    RANK_BAND = "RANK_BAND"


class ManagerMultiplierPolicy(RankModel):
    schema_version: Literal["rank-manager-multiplier-policy-v1"] = (
        "rank-manager-multiplier-policy-v1"
    )
    triple_captain_multiplier: PositiveInt
    bench_boost_counts_all_appearing_squad_players: Literal[True] = True
    free_hit_uses_temporary_squad_only: Literal[True] = True


class ManagerTeamPlan(RankModel):
    """One exact manager squad/tactical state for a Gameweek."""

    plan_id: StrictStr = Field(min_length=1, max_length=200)
    manager_id: StrictStr = Field(min_length=1, max_length=200)
    permanent_squad: tuple[StrictStr, ...] = Field(min_length=1)
    tactical_configuration: TacticalConfiguration
    active_chip: ManagerChip = ManagerChip.NONE
    temporary_free_hit_squad: tuple[StrictStr, ...] | None = None
    cumulative_points: StrictInt = 0
    counted_transfers: NonNegativeInt = 0
    transfer_hit_points: NonNegativeInt = 0

    @model_validator(mode="after")
    def team_shape_is_exact(self) -> ManagerTeamPlan:
        for label, squad in (
            ("permanent", self.permanent_squad),
            ("temporary Free Hit", self.temporary_free_hit_squad),
        ):
            if squad is None:
                continue
            if tuple(sorted(squad)) != squad or len(squad) != len(set(squad)):
                raise ValueError(f"{label} squad must be sorted and unique")
        if self.active_chip is ManagerChip.FREE_HIT:
            if self.temporary_free_hit_squad is None:
                raise ValueError("Free Hit requires a temporary squad")
        elif self.temporary_free_hit_squad is not None:
            raise ValueError("temporary squad is only valid for Free Hit")
        designations = (
            *self.tactical_configuration.starting_xi,
            self.tactical_configuration.bench_goalkeeper,
            *self.tactical_configuration.bench_order,
        )
        if set(designations) != set(self.active_squad):
            raise ValueError("tactical designations must cover the active squad exactly")
        return self

    @property
    def active_squad(self) -> tuple[str, ...]:
        if self.active_chip is ManagerChip.FREE_HIT:
            assert self.temporary_free_hit_squad is not None
            return self.temporary_free_hit_squad
        return self.permanent_squad


class CohortMember(RankModel):
    sample_unit_id: StrictStr = Field(min_length=1, max_length=200)
    manager_plan: ManagerTeamPlan
    weight: PositiveFloat


class CohortSample(RankModel):
    """Rights-classified weighted manager sample."""

    schema_version: Literal["rank-cohort-sample-v1"] = "rank-cohort-sample-v1"
    sample_id: StrictStr = Field(min_length=1, max_length=200)
    kind: CohortKind
    rights_status: SampleRightsStatus
    observed_at: datetime
    information_cutoff: datetime
    members: tuple[CohortMember, ...] = Field(min_length=1)
    confidence: ConfidenceGrade
    source_reference: StrictStr | None = None

    @model_validator(mode="after")
    def sample_is_valid(self) -> CohortSample:
        for label, value in (
            ("observed_at", self.observed_at),
            ("information_cutoff", self.information_cutoff),
        ):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{label} must be timezone-aware UTC")
        if self.observed_at > self.information_cutoff:
            raise ValueError("cohort observation cannot follow the information cutoff")
        units = tuple(item.sample_unit_id for item in self.members)
        managers = tuple(item.manager_plan.manager_id for item in self.members)
        if len(units) != len(set(units)):
            raise ValueError("cohort sample units must be unique")
        if len(managers) != len(set(managers)):
            raise ValueError("cohort manager IDs must be unique")
        if self.kind is CohortKind.SYNTHETIC and (
            self.rights_status is not SampleRightsStatus.SYNTHETIC_APPROVED
        ):
            raise ValueError("synthetic cohort must use synthetic-approved rights")
        if self.kind is CohortKind.NAMED_MINI_LEAGUE and (
            self.rights_status is not SampleRightsStatus.NAMED_RIVAL_AUTHORISED
        ):
            raise ValueError("named mini-league requires authorised named-rival rights")
        return self


class ScenarioManagerMultiplier(RankModel):
    manager_id: StrictStr = Field(min_length=1)
    plan_id: StrictStr = Field(min_length=1)
    scenario_id: StrictStr = Field(min_length=1)
    outcome_draw_id: StrictStr = Field(min_length=1)
    weight: Probability
    active_chip: ManagerChip
    player_multipliers: dict[StrictStr, NonNegativeInt]
    counted_player_ids: tuple[StrictStr, ...]
    autosubs: tuple[AutosubEvent, ...]
    captain_resolution: CaptainResolution
    effective_captain_id: StrictStr | None
    gross_points: StrictInt
    transfer_hit_points: NonNegativeInt
    net_points: StrictInt
    multiplier_hash: Sha256

    @model_validator(mode="after")
    def multiplier_is_canonical(self) -> ScenarioManagerMultiplier:
        if tuple(self.player_multipliers) != tuple(sorted(self.player_multipliers)):
            raise ValueError("player multipliers must be sorted by player ID")
        expected_counted = tuple(
            player_id for player_id, multiplier in self.player_multipliers.items() if multiplier > 0
        )
        if self.counted_player_ids != expected_counted:
            raise ValueError("counted player IDs must match positive multipliers")
        if self.net_points != self.gross_points - self.transfer_hit_points:
            raise ValueError("net manager score must deduct transfer hits exactly once")
        payload = self.model_dump(mode="json", exclude={"multiplier_hash"})
        if self.multiplier_hash != _ZERO_HASH and self.multiplier_hash != semantic_sha256(payload):
            raise ValueError("scenario manager multiplier hash does not reconcile")
        return self


class ManagerMultiplierSet(RankModel):
    schema_version: Literal["rank-manager-multiplier-set-v1"] = "rank-manager-multiplier-set-v1"
    manager_id: StrictStr = Field(min_length=1)
    plan_id: StrictStr = Field(min_length=1)
    scenario_set_hash: Sha256
    raw_projection_hash: Sha256
    scenarios: tuple[ScenarioManagerMultiplier, ...] = Field(min_length=1)
    expected_gross_points: FiniteFloat
    expected_net_points: FiniteFloat
    multiplier_set_hash: Sha256

    @model_validator(mode="after")
    def scenario_set_is_valid(self) -> ManagerMultiplierSet:
        identities = tuple((item.scenario_id, item.outcome_draw_id) for item in self.scenarios)
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("manager multiplier scenarios must be sorted and unique")
        if abs(sum(item.weight for item in self.scenarios) - 1.0) > 1e-10:
            raise ValueError("manager multiplier scenario weights must sum to one")
        if any(
            item.manager_id != self.manager_id or item.plan_id != self.plan_id
            for item in self.scenarios
        ):
            raise ValueError("manager multiplier scenarios must match their manager and plan")
        expected_gross = sum(item.weight * item.gross_points for item in self.scenarios)
        expected_net = sum(item.weight * item.net_points for item in self.scenarios)
        if abs(self.expected_gross_points - expected_gross) > 1e-10:
            raise ValueError("expected gross points do not reconcile with multiplier scenarios")
        if abs(self.expected_net_points - expected_net) > 1e-10:
            raise ValueError("expected net points do not reconcile with multiplier scenarios")
        payload = self.model_dump(mode="json", exclude={"multiplier_set_hash"})
        if self.multiplier_set_hash != _ZERO_HASH and self.multiplier_set_hash != semantic_sha256(
            payload
        ):
            raise ValueError("manager multiplier set hash does not reconcile")
        return self


class PlayerOwnership(RankModel):
    player_id: StrictStr = Field(min_length=1)
    raw_ownership: NonNegativeFloat
    starting_ownership: NonNegativeFloat
    normal_captain_ownership: NonNegativeFloat
    triple_captain_ownership: NonNegativeFloat
    vice_ownership: NonNegativeFloat
    bench_boost_counted_ownership: NonNegativeFloat
    saved_effective_ownership: NonNegativeFloat
    expected_scenario_effective_ownership: NonNegativeFloat
    scenario_effective_ownership: dict[StrictStr, NonNegativeFloat]
    eo_p10: NonNegativeFloat
    eo_p90: NonNegativeFloat
    sebastian_expected_multiplier: NonNegativeFloat | None = None
    expected_leverage: FiniteFloat | None = None

    @model_validator(mode="after")
    def ownership_is_canonical(self) -> PlayerOwnership:
        percentage_fields = (
            self.raw_ownership,
            self.starting_ownership,
            self.normal_captain_ownership,
            self.triple_captain_ownership,
            self.vice_ownership,
            self.bench_boost_counted_ownership,
        )
        if any(value > 100.0 for value in percentage_fields):
            raise ValueError("raw/action ownership percentages cannot exceed 100")
        if tuple(self.scenario_effective_ownership) != tuple(
            sorted(self.scenario_effective_ownership)
        ):
            raise ValueError("scenario EO keys must be sorted")
        if self.eo_p10 > self.eo_p90:
            raise ValueError("EO interval is inverted")
        if (self.sebastian_expected_multiplier is None) != (self.expected_leverage is None):
            raise ValueError("Sebastian multiplier and leverage must be supplied together")
        if self.expected_leverage is not None:
            assert self.sebastian_expected_multiplier is not None
            expected = self.sebastian_expected_multiplier - (
                self.expected_scenario_effective_ownership / 100.0
            )
            if abs(self.expected_leverage - expected) > 1e-10:
                raise ValueError("player leverage does not reconcile with EO")
        return self


class EffectiveOwnershipReport(RankModel):
    schema_version: Literal["rank-effective-ownership-report-v1"] = (
        "rank-effective-ownership-report-v1"
    )
    sample_id: StrictStr = Field(min_length=1)
    rights_status: SampleRightsStatus
    scenario_set_hash: Sha256
    raw_projection_hash: Sha256
    entries: tuple[PlayerOwnership, ...]
    confidence: ConfidenceGrade
    report_hash: Sha256

    @model_validator(mode="after")
    def report_is_canonical(self) -> EffectiveOwnershipReport:
        ids = tuple(item.player_id for item in self.entries)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("EO entries must be sorted and unique")
        payload = self.model_dump(mode="json", exclude={"report_hash"})
        if self.report_hash != _ZERO_HASH and self.report_hash != semantic_sha256(payload):
            raise ValueError("effective ownership report hash does not reconcile")
        return self


class ProjectionInvarianceResult(RankModel):
    identical: StrictBool
    points_mode_hash: Sha256
    rank_mode_hash: Sha256
    code: Literal["RAW_PROJECTIONS_IDENTICAL", "RAW_PROJECTIONS_DIFFER"]


class RankTiePolicy(RankModel):
    """Versioned classic-rank tie mechanics required by exact simulation."""

    schema_version: Literal["rank-tie-policy-v1"] = "rank-tie-policy-v1"
    policy_id: StrictStr = Field(min_length=1, max_length=200)
    target_season: StrictStr = Field(min_length=1, max_length=20)
    rules_verified: StrictBool
    points_primary: Literal[True] = True
    fewer_counted_transfers_breaks_points_ties: Literal[True] = True
    equal_points_and_counted_transfers_share_rank: Literal[True] = True
    wildcard_transfers_excluded: Literal[True] = True
    free_hit_transfers_excluded: Literal[True] = True


class RankMass(RankModel):
    rank: PositiveInt
    probability: Probability


class ManagerScenarioStanding(RankModel):
    manager_id: StrictStr = Field(min_length=1, max_length=200)
    scenario_id: StrictStr = Field(min_length=1)
    outcome_draw_id: StrictStr = Field(min_length=1)
    cumulative_points: StrictInt
    gameweek_net_points: StrictInt
    final_points: StrictInt
    counted_transfers: NonNegativeInt
    rank: PositiveInt
    shared_rank: StrictBool

    @model_validator(mode="after")
    def points_reconcile(self) -> ManagerScenarioStanding:
        if self.final_points != self.cumulative_points + self.gameweek_net_points:
            raise ValueError("final points must equal cumulative plus scenario net points")
        return self


class MiniLeagueScenarioOutcome(RankModel):
    scenario_id: StrictStr = Field(min_length=1)
    outcome_draw_id: StrictStr = Field(min_length=1)
    weight: Probability
    standings: tuple[ManagerScenarioStanding, ...] = Field(min_length=2)
    winner_manager_ids: tuple[StrictStr, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def outcome_is_canonical(self) -> MiniLeagueScenarioOutcome:
        manager_ids = tuple(item.manager_id for item in self.standings)
        if manager_ids != tuple(sorted(manager_ids)) or len(manager_ids) != len(set(manager_ids)):
            raise ValueError("mini-league standings must be sorted by unique manager ID")
        if any(
            (item.scenario_id, item.outcome_draw_id) != (self.scenario_id, self.outcome_draw_id)
            for item in self.standings
        ):
            raise ValueError("every manager standing must use the shared scenario identity")
        expected_winners = tuple(item.manager_id for item in self.standings if item.rank == 1)
        if self.winner_manager_ids != expected_winners:
            raise ValueError("winner IDs must exactly match all managers sharing rank one")
        final_state = {
            item.manager_id: (item.final_points, item.counted_transfers) for item in self.standings
        }
        expected_ranks = {
            manager_id: 1
            + sum(
                other_points > points or (other_points == points and other_transfers < transfers)
                for other_id, (other_points, other_transfers) in final_state.items()
                if other_id != manager_id
            )
            for manager_id, (points, transfers) in final_state.items()
        }
        rank_counts = {
            rank: sum(value == rank for value in expected_ranks.values())
            for rank in set(expected_ranks.values())
        }
        if any(item.rank != expected_ranks[item.manager_id] for item in self.standings):
            raise ValueError("mini-league standing ranks do not reconcile with points and ties")
        if any(item.shared_rank != (rank_counts[item.rank] > 1) for item in self.standings):
            raise ValueError("mini-league shared-rank flags do not reconcile")
        return self


class RankDistribution(RankModel):
    """Exact probability distribution over one manager's classic rank."""

    schema_version: Literal["rank-distribution-v1"] = "rank-distribution-v1"
    target_manager_id: StrictStr = Field(min_length=1, max_length=200)
    population_size: PositiveInt
    scenario_set_hash: Sha256
    raw_projection_hash: Sha256
    tie_policy_id: StrictStr = Field(min_length=1)
    target_rank: PositiveInt | None = None
    rank_pmf: tuple[RankMass, ...] = Field(min_length=1)
    expected_rank: FiniteFloat
    median_rank: PositiveInt
    rank_percentiles: dict[StrictStr, PositiveInt]
    probability_target_rank: Probability | None = None
    mini_league_win_probability: Probability
    outcomes: tuple[MiniLeagueScenarioOutcome, ...] = Field(min_length=1)
    confidence: ConfidenceGrade
    distribution_hash: Sha256

    @model_validator(mode="after")
    def distribution_is_canonical(self) -> RankDistribution:
        ranks = tuple(item.rank for item in self.rank_pmf)
        if ranks != tuple(sorted(ranks)) or len(ranks) != len(set(ranks)):
            raise ValueError("rank PMF must be sorted by unique rank")
        if any(rank > self.population_size for rank in ranks):
            raise ValueError("rank PMF contains rank outside the population")
        if abs(sum(item.probability for item in self.rank_pmf) - 1.0) > 1e-10:
            raise ValueError("rank probabilities must sum to one")
        expected = sum(item.rank * item.probability for item in self.rank_pmf)
        if abs(self.expected_rank - expected) > 1e-10:
            raise ValueError("expected rank does not reconcile with rank PMF")
        if tuple(self.rank_percentiles) != tuple(label for label, _ in _PERCENTILES):
            raise ValueError("rank percentiles must use the canonical keys")

        def quantile(probability: float) -> int:
            cumulative = 0.0
            for item in self.rank_pmf:
                cumulative += item.probability
                if cumulative + 1e-15 >= probability:
                    return item.rank
            return self.rank_pmf[-1].rank

        expected_percentiles = {label: quantile(probability) for label, probability in _PERCENTILES}
        if self.rank_percentiles != expected_percentiles:
            raise ValueError("rank percentiles must be derived from the rank PMF")
        if self.median_rank != expected_percentiles["p50"]:
            raise ValueError("median rank must be derived from the rank PMF")
        if self.target_rank is not None and self.target_rank > self.population_size:
            raise ValueError("target rank lies outside the represented population")
        target_probability = (
            None
            if self.target_rank is None
            else sum(item.probability for item in self.rank_pmf if item.rank <= self.target_rank)
        )
        if self.probability_target_rank != target_probability:
            raise ValueError("target probability must be derived from the rank PMF")
        win_probability = sum(item.probability for item in self.rank_pmf if item.rank == 1)
        if abs(self.mini_league_win_probability - win_probability) > 1e-10:
            raise ValueError("mini-league win probability must equal rank-one mass")
        identities = tuple((item.scenario_id, item.outcome_draw_id) for item in self.outcomes)
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("rank outcomes must be sorted by unique shared scenario identity")
        if abs(sum(item.weight for item in self.outcomes) - 1.0) > 1e-10:
            raise ValueError("rank outcome weights must sum to one")
        outcome_pmf: dict[int, float] = {}
        for outcome in self.outcomes:
            if len(outcome.standings) != self.population_size:
                raise ValueError("rank outcome standings must cover the represented population")
            targets = tuple(
                item for item in outcome.standings if item.manager_id == self.target_manager_id
            )
            if len(targets) != 1:
                raise ValueError("rank outcome must contain the target manager exactly once")
            target_outcome_rank = targets[0].rank
            outcome_pmf[target_outcome_rank] = (
                outcome_pmf.get(target_outcome_rank, 0.0) + outcome.weight
            )
        expected_pmf = tuple(
            RankMass(rank=rank, probability=probability)
            for rank, probability in sorted(outcome_pmf.items())
        )
        if self.rank_pmf != expected_pmf:
            raise ValueError("rank PMF must be derived from scenario outcomes")
        payload = self.model_dump(mode="json", exclude={"distribution_hash"})
        if self.distribution_hash != _ZERO_HASH and self.distribution_hash != semantic_sha256(
            payload
        ):
            raise ValueError("rank distribution hash does not reconcile")
        return self
