"""Strict public contracts for the bounded Stage-9 FPL-points vertical slice."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from math import isclose
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from dmf_pulse.football_events.minutes_context import Stage7MinutesContext
from dmf_pulse.football_events.score_distribution import JointScoreDistribution
from dmf_pulse.rules.models import AssistDecisionContext


class PointsModel(BaseModel):
    """Immutable, fail-closed Stage-9 model base."""

    model_config = ConfigDict(extra="forbid", frozen=True)


Probability = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Minutes = Annotated[StrictInt, Field(ge=0, le=130)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ProbabilityText = Annotated[str, Field(pattern=r"^(?:0\.\d{12}|1\.000000000000)$")]
ConfidenceGrade = Literal["A", "B", "C", "D", "E"]

POINT_COMPONENT_NAMES = (
    "appearance",
    "goals",
    "assists",
    "clean_sheet",
    "saves",
    "penalty_saves",
    "defensive_contributions",
    "goals_conceded",
    "penalty_misses",
    "yellow_cards",
    "red_cards",
    "own_goals",
    "bonus",
)


def _parse_utc(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be timezone-aware UTC")
    return parsed


class ProjectionMode(StrEnum):
    PRODUCTION = "PRODUCTION"
    TEST = "TEST"
    REPLAY = "REPLAY"


class PlayerPosition(StrEnum):
    GK = "GK"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"


class AssistClassification(StrEnum):
    DEFINITE_ASSIST = "DEFINITE_ASSIST"
    DEFINITE_NO_ASSIST = "DEFINITE_NO_ASSIST"
    AMBIGUOUS_ASSIST = "AMBIGUOUS_ASSIST"


class GoalMechanism(StrEnum):
    OPEN_PLAY = "OPEN_PLAY"
    SET_PIECE = "SET_PIECE"
    PENALTY = "PENALTY"
    DIRECT_FREE_KICK = "DIRECT_FREE_KICK"
    OPPONENT_OWN_GOAL = "OPPONENT_OWN_GOAL"


class BpsCompletenessMode(StrEnum):
    EVENT_LINKED_ONLY = "EVENT_LINKED_ONLY"
    EVENT_LINKED_PLUS_AUXILIARY_BASELINE = "EVENT_LINKED_PLUS_AUXILIARY_BASELINE"


class SimulationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"


class FixtureReadiness(StrEnum):
    SCHEDULED = "SCHEDULED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class GameweekAssemblyMode(StrEnum):
    BLANK = "BLANK"
    SINGLE_FIXTURE = "SINGLE_FIXTURE"
    SHARED_OUTCOME_DRAW = "SHARED_OUTCOME_DRAW"


class OnPitchInterval(PointsModel):
    """Half-open participation interval: ``[start_minute, end_minute)``."""

    start_minute: Annotated[float, Field(ge=0.0, le=130.0)]
    end_minute: Annotated[float, Field(ge=0.0, le=130.0)]

    @model_validator(mode="after")
    def interval_is_positive(self) -> OnPitchInterval:
        if self.end_minute <= self.start_minute:
            raise ValueError("on-pitch interval must have positive length")
        return self

    def contains(self, minute: float) -> bool:
        return self.start_minute <= minute < self.end_minute


class ParticipantState(PointsModel):
    player_id: Annotated[str, Field(min_length=1, max_length=100)]
    team_id: Annotated[str, Field(min_length=1, max_length=100)]
    position: PlayerPosition
    official_minutes: Minutes
    interval: OnPitchInterval | None
    hard_ineligible: StrictBool = False
    starter: StrictBool = False

    @field_validator("player_id", "team_id")
    @classmethod
    def identifiers_are_uuid(cls, value: str, info: Any) -> str:
        try:
            UUID(value)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f"{info.field_name} must be a UUID") from exc
        return value

    @model_validator(mode="after")
    def participation_is_coherent(self) -> ParticipantState:
        if self.hard_ineligible:
            if self.official_minutes != 0 or self.interval is not None or self.starter:
                raise ValueError("hard-ineligible participant cannot play")
            return self
        if self.official_minutes == 0 and self.interval is not None:
            raise ValueError("zero-minute participant cannot have an on-pitch interval")
        if self.official_minutes > 0 and self.interval is None:
            raise ValueError("positive minutes require an on-pitch interval")
        return self


class ParticipationScenario(PointsModel):
    scenario_id: Annotated[str, Field(min_length=1)]
    fixture_id: str
    gameweek_id: str
    home_team_id: str
    away_team_id: str
    probability: Annotated[float, Field(gt=0.0, le=1.0)]
    participant_universe_complete: Literal[True]
    participants: tuple[ParticipantState, ...]
    stage7_minutes_context: Stage7MinutesContext
    stage7_player_projection_sha256s: dict[str, Sha256]
    information_cutoff_utc: str

    @field_validator("information_cutoff_utc")
    @classmethod
    def cutoff_is_utc(cls, value: str) -> str:
        _parse_utc(value, label="information_cutoff_utc")
        return value

    @model_validator(mode="after")
    def scenario_is_coherent(self) -> ParticipationScenario:
        if self.home_team_id == self.away_team_id:
            raise ValueError("fixture teams must be distinct")
        ids = [participant.player_id for participant in self.participants]
        if len(ids) != len(set(ids)):
            raise ValueError("participant IDs must be unique")
        valid_teams = {self.home_team_id, self.away_team_id}
        if any(participant.team_id not in valid_teams for participant in self.participants):
            raise ValueError("participant belongs to neither fixture team")
        context = self.stage7_minutes_context
        if context.home.fixture_id != self.fixture_id:
            raise ValueError("Stage-7 identity fixture mismatch")
        if (context.home.team_id, context.away.team_id) != (
            self.home_team_id,
            self.away_team_id,
        ):
            raise ValueError("Stage-7 identity team mismatch")
        if context.source_as_of > _parse_utc(
            self.information_cutoff_utc, label="information_cutoff_utc"
        ):
            raise ValueError("POST_CUTOFF_MINUTES: Stage-7 projection is after Stage-9 cutoff")
        if set(self.stage7_player_projection_sha256s) != set(ids):
            raise ValueError("Stage-7 player projection hashes must map one-to-one to participants")
        for team_id in valid_teams:
            team_players = [
                participant for participant in self.participants if participant.team_id == team_id
            ]
            if len(team_players) < 11:
                raise ValueError(
                    "complete participant universe requires at least 11 players per team"
                )
            if not any(player.position is PlayerPosition.GK for player in team_players):
                raise ValueError("complete participant universe requires a goalkeeper per team")
        return self


class ScorelineCell(PointsModel):
    home_goals: NonNegativeInt
    away_goals: NonNegativeInt
    probability: ProbabilityText


class BpsAuxiliaryRates(PointsModel):
    big_chances_created_per90: Annotated[float, Field(ge=0.0)]
    big_chances_missed_per90: Annotated[float, Field(ge=0.0)]
    errors_leading_attempt_per90: Annotated[float, Field(ge=0.0)]
    errors_leading_goal_per90: Annotated[float, Field(ge=0.0)]
    fouls_conceded_per90: Annotated[float, Field(ge=0.0)]
    fouls_won_per90: Annotated[float, Field(ge=0.0)]
    goal_line_clearances_per90: Annotated[float, Field(ge=0.0)]
    key_passes_per90: Annotated[float, Field(ge=0.0)]
    offsides_per90: Annotated[float, Field(ge=0.0)]
    pass_attempts_per90: Annotated[float, Field(ge=0.0)]
    pass_completion_probability: Probability
    recoveries_per90: Annotated[float, Field(ge=0.0)]
    shots_off_target_per90: Annotated[float, Field(ge=0.0)]
    shots_on_target_non_goal_per90: Annotated[float, Field(ge=0.0)]
    successful_dribbles_per90: Annotated[float, Field(ge=0.0)]
    successful_open_play_crosses_per90: Annotated[float, Field(ge=0.0)]
    times_tackled_per90: Annotated[float, Field(ge=0.0)]


class PlayerAllocationProfile(PointsModel):
    player_id: str
    team_id: str
    goal_share: Annotated[float, Field(ge=0.0)]
    assist_share: Annotated[float, Field(ge=0.0)]
    penalty_taker_share: Annotated[float, Field(ge=0.0)]
    own_goal_share: Annotated[float, Field(ge=0.0)]
    goalkeeper_saves_per90: Annotated[float, Field(ge=0.0)]
    saves_inside_box_fraction: Probability
    yellow_cards_per90: Annotated[float, Field(ge=0.0)]
    red_cards_per90: Annotated[float, Field(ge=0.0)]
    clearances_per90: Annotated[float, Field(ge=0.0)]
    blocks_per90: Annotated[float, Field(ge=0.0)]
    interceptions_per90: Annotated[float, Field(ge=0.0)]
    tackles_per90: Annotated[float, Field(ge=0.0)]
    ball_recoveries_per90: Annotated[float, Field(ge=0.0)]
    bps_auxiliary: BpsAuxiliaryRates


class EventAllocationConfig(PointsModel):
    model_version_id: str
    source_tag: Literal["TEMP-EVT-002", "TEST_SYNTHETIC"]
    bps_completeness_mode: BpsCompletenessMode
    auxiliary_source_tag: Literal["TEMP-PTS-001", "NONE", "TEST_SYNTHETIC"]
    match_minutes: Annotated[float, Field(gt=0.0, le=130.0)]
    goal_time_lower: Annotated[float, Field(ge=0.0, le=130.0)]
    goal_time_upper: Annotated[float, Field(gt=0.0, le=130.0)]
    penalty_goal_probability: Probability
    set_piece_goal_probability: Probability
    direct_free_kick_goal_probability: Probability
    own_goal_probability: Probability
    assistable_probability: Probability
    ambiguous_assist_probability: Probability
    ambiguous_assist_eligible_probability: Probability
    extra_penalty_attempt_probability: Probability
    extra_penalty_save_probability: Probability

    @model_validator(mode="after")
    def config_is_coherent(self) -> EventAllocationConfig:
        if not self.goal_time_lower < self.goal_time_upper <= self.match_minutes:
            raise ValueError("goal-time bounds must lie inside match duration")
        mechanism_probability = (
            self.penalty_goal_probability
            + self.set_piece_goal_probability
            + self.direct_free_kick_goal_probability
            + self.own_goal_probability
        )
        if mechanism_probability > 1.0 + 1e-12:
            raise ValueError("goal mechanism probabilities exceed one")
        if self.bps_completeness_mode is BpsCompletenessMode.EVENT_LINKED_ONLY:
            if self.auxiliary_source_tag != "NONE":
                raise ValueError("event-linked-only BPS must not claim auxiliary actions")
        elif self.auxiliary_source_tag == "NONE":
            raise ValueError("auxiliary BPS mode requires an explicit source tag")
        return self


class RulesetIdentity(PointsModel):
    ruleset_id: str
    ruleset_version: str
    ruleset_hash: Sha256
    status: str
    production_eligible: StrictBool
    human_approval_recorded: StrictBool
    unknown_blockers: tuple[str, ...] = ()


class FixtureSimulationRequest(PointsModel):
    schema_version: Literal["fpl-points-fixture-request-v1"]
    gameweek_id: str
    projection_mode: ProjectionMode
    as_of_utc: str
    information_cutoff_utc: str
    root_seed: Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]
    scenario_count: Annotated[StrictInt, Field(ge=1, le=1_000_000)]
    fixture_readiness: FixtureReadiness = FixtureReadiness.SCHEDULED
    score_distribution: JointScoreDistribution
    participation_scenarios: tuple[ParticipationScenario, ...]
    allocation_profiles: tuple[PlayerAllocationProfile, ...]
    allocation_config: EventAllocationConfig
    expected_ruleset_id: str
    expected_ruleset_version: str
    expected_ruleset_hash: Sha256

    @field_validator("as_of_utc", "information_cutoff_utc")
    @classmethod
    def timestamps_are_utc(cls, value: str, info: Any) -> str:
        _parse_utc(value, label=info.field_name)
        return value

    @model_validator(mode="after")
    def request_is_coherent(self) -> FixtureSimulationRequest:
        distribution = self.score_distribution
        if distribution.information_cutoff != self.information_cutoff_utc:
            raise ValueError("Stage-8 cutoff differs from Stage-9 cutoff")
        if distribution.as_of != self.as_of_utc or self.as_of_utc != self.information_cutoff_utc:
            raise ValueError("Stage-8 as_of and Stage-9 cutoff identities differ")
        if not self.participation_scenarios:
            raise ValueError("at least one participation scenario is required")
        if not isclose(
            sum(item.probability for item in self.participation_scenarios),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-10,
        ):
            raise ValueError("participation scenario probabilities must sum to one")
        expected_fixture = (
            distribution.fixture_id,
            self.gameweek_id,
            distribution.home_team_id,
            distribution.away_team_id,
        )
        for scenario in self.participation_scenarios:
            actual = (
                scenario.fixture_id,
                scenario.gameweek_id,
                scenario.home_team_id,
                scenario.away_team_id,
            )
            if actual != expected_fixture:
                raise ValueError("Stage-7 scenario fixture identity differs from Stage-8")
            if scenario.information_cutoff_utc != self.information_cutoff_utc:
                raise ValueError("Stage-7 cutoff differs from Stage-9 cutoff")
            if (
                scenario.stage7_minutes_context.semantic_sha256
                != distribution.source_minutes_context_sha256
            ):
                raise ValueError("Stage-7 context differs from the context bound by Stage 8")
        profile_ids = [profile.player_id for profile in self.allocation_profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("allocation profile player IDs must be unique")
        profile_map = {profile.player_id: profile for profile in self.allocation_profiles}
        participant_ids = {
            participant.player_id
            for scenario in self.participation_scenarios
            for participant in scenario.participants
        }
        if set(profile_map) != participant_ids:
            raise ValueError("allocation profiles must map one-to-one to participant universe")
        for scenario in self.participation_scenarios:
            for participant in scenario.participants:
                if profile_map[participant.player_id].team_id != participant.team_id:
                    raise ValueError("allocation profile team identity mismatch")
        return self


class DefensiveActions(PointsModel):
    ball_recoveries: NonNegativeInt
    blocks: NonNegativeInt
    clearances: NonNegativeInt
    interceptions: NonNegativeInt
    tackles: NonNegativeInt


class BpsEvents(PointsModel):
    big_chances_created: NonNegativeInt
    big_chance_saves: NonNegativeInt = 0
    big_chances_missed: NonNegativeInt
    errors_leading_attempt: NonNegativeInt
    errors_leading_goal: NonNegativeInt
    fouls_conceded: NonNegativeInt
    fouls_won: NonNegativeInt
    goal_line_clearances: NonNegativeInt
    key_passes: NonNegativeInt
    match_winning_goals: NonNegativeInt
    offsides: NonNegativeInt
    pass_attempts: NonNegativeInt
    passes_completed: NonNegativeInt
    penalties_conceded: NonNegativeInt
    recoveries: NonNegativeInt
    saves_inside_box: NonNegativeInt
    saves_outside_box: NonNegativeInt
    shots_off_target: NonNegativeInt
    shots_on_target: NonNegativeInt
    successful_dribbles: NonNegativeInt
    successful_open_play_crosses: NonNegativeInt
    successful_tackles: NonNegativeInt
    times_tackled: NonNegativeInt

    @model_validator(mode="after")
    def pass_counts_are_coherent(self) -> BpsEvents:
        if self.passes_completed > self.pass_attempts:
            raise ValueError("passes completed cannot exceed attempts")
        return self


class GoalEvent(PointsModel):
    goal_id: str
    minute: Annotated[float, Field(ge=0.0, le=130.0)]
    scoring_team_id: str
    conceding_team_id: str
    mechanism: GoalMechanism
    scorer_player_id: str | None
    own_goal_player_id: str | None
    assister_player_id: str | None
    assist_classification: AssistClassification
    assist_awarded: StrictBool
    assist_context: AssistDecisionContext | None = None

    @model_validator(mode="after")
    def goal_is_coherent(self) -> GoalEvent:
        if self.mechanism is GoalMechanism.OPPONENT_OWN_GOAL:
            if self.scorer_player_id is not None or self.own_goal_player_id is None:
                raise ValueError("own goal must have an own-goal player and no credited scorer")
        else:
            if self.scorer_player_id is None or self.own_goal_player_id is not None:
                raise ValueError("credited goal must have exactly one scorer")
            if self.assister_player_id == self.scorer_player_id:
                raise ValueError("scorer cannot assist the same goal")
        if self.assist_awarded != (self.assister_player_id is not None):
            raise ValueError("assist award and assister identity disagree")
        if self.assist_classification is AssistClassification.DEFINITE_ASSIST:
            if not self.assist_awarded:
                raise ValueError("definite assist classification requires an awarded assist")
        elif (
            self.assist_classification is AssistClassification.DEFINITE_NO_ASSIST
            and self.assist_awarded
        ):
            raise ValueError("definite no-assist classification cannot award an assist")
        return self


class PlayerEventVector(PointsModel):
    player_id: str
    team_id: str
    position: PlayerPosition
    minutes: Minutes
    goals_non_penalty: NonNegativeInt
    goals_penalty: NonNegativeInt
    eligible_assists: NonNegativeInt
    goals_conceded_while_eligible: NonNegativeInt
    saves: NonNegativeInt
    penalty_saves: NonNegativeInt
    penalty_misses: NonNegativeInt
    yellow_cards: NonNegativeInt
    red_cards: NonNegativeInt
    own_goals: NonNegativeInt
    defensive_actions: DefensiveActions
    bps: BpsEvents
    dismissed: StrictBool
    team_goals_after_dismissal: NonNegativeInt
    auxiliary_source_tag: str

    @model_validator(mode="after")
    def zero_minutes_have_no_events(self) -> PlayerEventVector:
        if self.minutes == 0:
            values = self.model_dump(mode="python")
            exempt = {"player_id", "team_id", "position", "minutes", "auxiliary_source_tag"}
            for key, value in values.items():
                if key in exempt:
                    continue
                if isinstance(value, dict):
                    if any(value.values()):
                        raise ValueError("zero-minute player cannot have events")
                elif value:
                    raise ValueError("zero-minute player cannot have events")
        if self.dismissed != (self.red_cards > 0):
            raise ValueError("dismissal and red-card state disagree")
        return self


class FixtureEventScenario(PointsModel):
    fixture_id: str
    gameweek_id: str
    home_team_id: str
    away_team_id: str
    home_goals: NonNegativeInt
    away_goals: NonNegativeInt
    participant_universe_complete: Literal[True]
    players: tuple[PlayerEventVector, ...]
    goals: tuple[GoalEvent, ...]
    ruleset_id: str
    ruleset_version: str
    ruleset_hash: Sha256

    @model_validator(mode="after")
    def goals_reconcile(self) -> FixtureEventScenario:
        ids = [player.player_id for player in self.players]
        if len(ids) != len(set(ids)):
            raise ValueError("fixture player IDs must be unique")
        player_map = {player.player_id: player for player in self.players}
        valid_teams = {self.home_team_id, self.away_team_id}
        if self.home_team_id == self.away_team_id or any(
            player.team_id not in valid_teams for player in self.players
        ):
            raise ValueError("fixture player team identity mismatch")
        goal_ids = [goal.goal_id for goal in self.goals]
        if len(goal_ids) != len(set(goal_ids)):
            raise ValueError("goal event IDs must be unique")
        credited_non_penalty: dict[str, int] = {player_id: 0 for player_id in ids}
        credited_penalty: dict[str, int] = {player_id: 0 for player_id in ids}
        assists: dict[str, int] = {player_id: 0 for player_id in ids}
        own_goals: dict[str, int] = {player_id: 0 for player_id in ids}
        for goal in self.goals:
            if {goal.scoring_team_id, goal.conceding_team_id} != valid_teams:
                raise ValueError("goal event team identity mismatch")
            if goal.scoring_team_id == goal.conceding_team_id:
                raise ValueError("goal event scoring and conceding teams must differ")
            if goal.scorer_player_id is not None:
                scorer = player_map.get(goal.scorer_player_id)
                if scorer is None or scorer.team_id != goal.scoring_team_id:
                    raise ValueError("goal scorer identity is outside the scoring team")
                bucket = (
                    credited_penalty
                    if goal.mechanism is GoalMechanism.PENALTY
                    else credited_non_penalty
                )
                bucket[scorer.player_id] += 1
            if goal.own_goal_player_id is not None:
                own_goal_player = player_map.get(goal.own_goal_player_id)
                if own_goal_player is None or own_goal_player.team_id != goal.conceding_team_id:
                    raise ValueError("own-goal player identity is outside the conceding team")
                own_goals[own_goal_player.player_id] += 1
            if goal.assister_player_id is not None:
                assister = player_map.get(goal.assister_player_id)
                if (
                    assister is None
                    or assister.team_id != goal.scoring_team_id
                    or assister.minutes == 0
                ):
                    raise ValueError("assister identity is outside the scoring team")
                assists[assister.player_id] += 1
        for player in self.players:
            if (
                credited_non_penalty[player.player_id] != player.goals_non_penalty
                or credited_penalty[player.player_id] != player.goals_penalty
                or assists[player.player_id] != player.eligible_assists
                or own_goals[player.player_id] != player.own_goals
            ):
                raise ValueError("goal records and player event vectors do not reconcile")
        home_players = [player for player in self.players if player.team_id == self.home_team_id]
        away_players = [player for player in self.players if player.team_id == self.away_team_id]
        derived_home = sum(
            player.goals_non_penalty + player.goals_penalty for player in home_players
        ) + sum(player.own_goals for player in away_players)
        derived_away = sum(
            player.goals_non_penalty + player.goals_penalty for player in away_players
        ) + sum(player.own_goals for player in home_players)
        if (derived_home, derived_away) != (self.home_goals, self.away_goals):
            raise ValueError("player events do not reconcile to team score")
        if len(self.goals) != self.home_goals + self.away_goals:
            raise ValueError("goal event count does not reconcile to scoreline")
        return self


class PlayerScenarioScore(PointsModel):
    appearance: StrictInt
    assists: StrictInt
    bonus: Annotated[StrictInt, Field(ge=0)]
    bps: StrictInt
    clean_sheet: StrictInt
    defensive_contributions: StrictInt
    goals: StrictInt
    goals_conceded: StrictInt
    own_goals: StrictInt
    penalty_misses: StrictInt
    penalty_saves: StrictInt
    red_cards: StrictInt
    saves: StrictInt
    total: StrictInt
    yellow_cards: StrictInt
    bps_competition_rank: Annotated[StrictInt, Field(ge=1)] | None
    bps_tied_at_rank: StrictBool

    @model_validator(mode="after")
    def total_is_component_sum(self) -> PlayerScenarioScore:
        if self.total != sum(getattr(self, name) for name in POINT_COMPONENT_NAMES):
            raise ValueError("scenario total does not equal component sum")
        if self.bps_competition_rank is None and self.bps_tied_at_rank:
            raise ValueError("a player without a BPS rank cannot be tied at that rank")
        return self


class FixturePointScenario(PointsModel):
    scenario_id: str
    outcome_draw_id: str
    scenario_index: NonNegativeInt
    weight: Annotated[float, Field(gt=0.0, le=1.0)]
    upstream_score_probability: ProbabilityText
    upstream_scoreline: tuple[NonNegativeInt, NonNegativeInt]
    upstream_stage8_sha256: Sha256
    participation_scenario_id: str
    stage7_minutes_context: Stage7MinutesContext
    stage7_player_projection_sha256s: dict[str, Sha256]
    fixture_id: str
    gameweek_id: str
    players: dict[str, PlayerScenarioScore]
    event_scenario: FixtureEventScenario
    ruleset: RulesetIdentity
    projection_mode: ProjectionMode
    root_seed: NonNegativeInt
    seed_namespace: str
    rng_algorithm: Literal["python-mt19937-pts-v1"]
    model_version_ids: tuple[str, ...]
    dataset_version_ids: tuple[str, ...]
    source_bundle_ids: tuple[str, ...]
    information_cutoff_utc: str
    bps_completeness_mode: BpsCompletenessMode
    confidence_grade: ConfidenceGrade
    degradation_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def scenario_contract_is_exact(self) -> FixturePointScenario:
        event = self.event_scenario
        if (event.fixture_id, event.gameweek_id) != (self.fixture_id, self.gameweek_id):
            raise ValueError("event scenario fixture/Gameweek identity mismatch")
        if (event.home_goals, event.away_goals) != self.upstream_scoreline:
            raise ValueError("event scenario scoreline differs from upstream scoreline")
        rule_identity = (
            self.ruleset.ruleset_id,
            self.ruleset.ruleset_version,
            self.ruleset.ruleset_hash,
        )
        if (event.ruleset_id, event.ruleset_version, event.ruleset_hash) != rule_identity:
            raise ValueError("event scenario ruleset identity mismatch")
        event_ids = {player.player_id for player in event.players}
        score_ids = set(self.players)
        stage7_ids = set(self.stage7_player_projection_sha256s)
        if event_ids != score_ids or stage7_ids != score_ids:
            raise ValueError("Stage-7, event, and scored participant universes must match")
        if self.stage7_minutes_context.home.fixture_id != self.fixture_id:
            raise ValueError("Stage-7 context fixture identity mismatch")
        if self.projection_mode is ProjectionMode.PRODUCTION and (
            self.ruleset.status != "ACTIVE"
            or not self.ruleset.production_eligible
            or not self.ruleset.human_approval_recorded
        ):
            raise ValueError("production scenario requires an active approved ruleset")
        return self


class ComponentSummary(PointsModel):
    expected_points: float
    probability_nonzero: Probability
    minimum: StrictInt
    maximum: StrictInt
    variance: Annotated[float, Field(ge=0.0)]


class PairDependence(PointsModel):
    covariance: float
    correlation: Annotated[float, Field(ge=-1.0, le=1.0)] | None
    correlation_undefined_reason: str | None

    @model_validator(mode="after")
    def correlation_state_is_explicit(self) -> PairDependence:
        if (self.correlation is None) != (self.correlation_undefined_reason is not None):
            raise ValueError("undefined correlation requires exactly one reason")
        return self


class BpsBonusSummary(PointsModel):
    expected_bps: float
    bps_variance: Annotated[float, Field(ge=0.0)]
    bps_quantiles: dict[str, int]
    probability_bonus_0: Probability
    probability_bonus_1: Probability
    probability_bonus_2: Probability
    probability_bonus_3: Probability
    expected_bonus: float
    probability_any_bonus: Probability
    expected_competition_rank: float | None
    probability_rank_1: Probability
    probability_rank_2: Probability
    probability_rank_3: Probability
    tie_probability: Probability
    completeness_mode: BpsCompletenessMode


class PlayerProjectionSummary(PointsModel):
    player_id: str
    expected_points: float
    median_points: StrictInt
    points_variance: Annotated[float, Field(ge=0.0)]
    points_standard_deviation: Annotated[float, Field(ge=0.0)]
    probability_negative_points: Probability
    probability_zero_points: Probability
    probability_1_plus: Probability
    probability_2_plus: Probability
    probability_5_plus: Probability
    probability_10_plus: Probability
    probability_15_plus: Probability
    selected_percentiles: dict[str, StrictInt]
    pmf: dict[int, float]
    component_breakdown: dict[str, ComponentSummary]
    component_covariance: dict[str, dict[str, float]]
    bps_bonus: BpsBonusSummary
    monte_carlo_mean_se: Annotated[float, Field(ge=0.0)]
    threshold_probability_se: dict[str, Annotated[float, Field(ge=0.0)]]
    scenario_effective_sample_size: Annotated[float, Field(gt=0.0)]
    confidence_grade: ConfidenceGrade
    ruleset_hash: Sha256
    model_version_ids: tuple[str, ...]
    dataset_version_ids: tuple[str, ...]
    source_bundle_ids: tuple[str, ...]
    upstream_stage8_sha256: Sha256

    @model_validator(mode="after")
    def public_summary_is_coherent(self) -> PlayerProjectionSummary:
        if set(self.component_breakdown) != set(POINT_COMPONENT_NAMES):
            raise ValueError("component summary must cover every FPL point component")
        if set(self.component_covariance) != set(POINT_COMPONENT_NAMES):
            raise ValueError("component covariance rows are incomplete")
        if any(
            set(row) != set(POINT_COMPONENT_NAMES) for row in self.component_covariance.values()
        ):
            raise ValueError("component covariance columns are incomplete")
        thresholds = (
            self.probability_1_plus,
            self.probability_2_plus,
            self.probability_5_plus,
            self.probability_10_plus,
            self.probability_15_plus,
        )
        if any(left < right for left, right in pairwise(thresholds)):
            raise ValueError("threshold probabilities must be monotone non-increasing")
        quantile_items = sorted(
            ((int(key[1:]), value) for key, value in self.selected_percentiles.items()),
            key=lambda item: item[0],
        )
        if any(left[1] > right[1] for left, right in pairwise(quantile_items)):
            raise ValueError("selected quantiles must be monotone")
        if not isclose(sum(self.pmf.values()), 1.0, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError("player PMF must sum to one")
        return self


class JointScenarioMatrix(PointsModel):
    scenario_ids: tuple[str, ...]
    outcome_draw_ids: tuple[str, ...]
    player_ids: tuple[str, ...]
    weights: tuple[Annotated[float, Field(gt=0.0, le=1.0)], ...]
    points: tuple[tuple[StrictInt, ...], ...]
    ruleset_hash: Sha256
    dependence: dict[str, dict[str, PairDependence]]

    @model_validator(mode="after")
    def dimensions_align(self) -> JointScenarioMatrix:
        rows = len(self.scenario_ids)
        if rows == 0:
            raise ValueError("joint matrix requires at least one scenario")
        if len(set(self.scenario_ids)) != rows:
            raise ValueError("joint matrix scenario IDs must be unique")
        if (
            len(self.outcome_draw_ids) != rows
            or len(self.weights) != rows
            or len(self.points) != rows
        ):
            raise ValueError("joint matrix scenario dimensions do not align")
        if len(set(self.player_ids)) != len(self.player_ids):
            raise ValueError("joint matrix player mapping must be one-to-one")
        if any(len(row) != len(self.player_ids) for row in self.points):
            raise ValueError("joint matrix player dimensions do not align")
        if not isclose(sum(self.weights), 1.0, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError("joint matrix weights must sum to one")
        expected = set(self.player_ids)
        if set(self.dependence) != expected or any(
            set(row) != expected for row in self.dependence.values()
        ):
            raise ValueError("joint dependence matrix must cover every player pair")
        return self


class MonteCarloDiagnostics(PointsModel):
    scenario_count: NonNegativeInt
    normalized_weight_sum: float
    effective_sample_size: Annotated[float, Field(gt=0.0)]
    max_scenario_weight: Probability
    mean_mcse_by_player: dict[str, float]
    threshold_probability_se_by_player: dict[str, dict[str, float]]
    quantile_stability_max_span_by_player: dict[str, dict[str, int]]
    stopping_result: Literal["PASS", "CONTINUE", "BLOCKED"]
    stopping_reasons: tuple[str, ...]


class MonteCarloPolicy(PointsModel):
    minimum_effective_scenarios: Annotated[float, Field(gt=0.0)]
    maximum_mean_mcse: Annotated[float, Field(gt=0.0)]
    maximum_probability_se: Annotated[float, Field(gt=0.0)]
    maximum_quantile_span: NonNegativeInt
    quantiles: tuple[Probability, ...]
    thresholds: tuple[int, ...]
    batch_count: Annotated[StrictInt, Field(ge=2, le=20)]


class FixtureProjectionResult(PointsModel):
    schema_version: Literal["fpl-points-fixture-result-v1"]
    status: SimulationStatus
    fixture_id: str
    gameweek_id: str
    scenarios: tuple[FixturePointScenario, ...]
    player_summaries: dict[str, PlayerProjectionSummary]
    joint_matrix: JointScenarioMatrix | None
    monte_carlo: MonteCarloDiagnostics | None
    ruleset: RulesetIdentity
    projection_mode: ProjectionMode
    information_cutoff_utc: str
    source_bundle_ids: tuple[str, ...]
    upstream_score_distribution: JointScoreDistribution
    upstream_stage8_sha256: Sha256
    result_sha256: Sha256 | None = None
    error_code: str | None = None
    error_message: str | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def result_state_is_coherent(self) -> FixtureProjectionResult:
        if self.status is SimulationStatus.SUCCESS:
            if not self.scenarios or self.joint_matrix is None or self.monte_carlo is None:
                raise ValueError(
                    "successful projection requires scenarios, matrix, and diagnostics"
                )
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("successful projection cannot carry an error")
        else:
            if self.error_code is None or self.error_message is None:
                raise ValueError("blocked projection requires an error")
        if (
            self.projection_mode is ProjectionMode.PRODUCTION
            and self.status is SimulationStatus.SUCCESS
            and (
                self.ruleset.status != "ACTIVE"
                or not self.ruleset.production_eligible
                or not self.ruleset.human_approval_recorded
                or self.ruleset.unknown_blockers
            )
        ):
            raise ValueError("successful production output requires an active approved ruleset")
        if (
            self.joint_matrix is not None
            and self.joint_matrix.ruleset_hash != self.ruleset.ruleset_hash
        ):
            raise ValueError("joint matrix ruleset hash mismatch")
        if self.upstream_score_distribution.result_sha256 != self.upstream_stage8_sha256:
            raise ValueError("embedded Stage-8 distribution identity mismatch")
        if self.upstream_score_distribution.fixture_id != self.fixture_id:
            raise ValueError("embedded Stage-8 fixture identity mismatch")
        if self.upstream_score_distribution.information_cutoff != self.information_cutoff_utc:
            raise ValueError("embedded Stage-8 cutoff identity mismatch")
        for scenario in self.scenarios:
            if scenario.upstream_stage8_sha256 != self.upstream_stage8_sha256:
                raise ValueError("scenario Stage-8 identity mismatch")
            if (
                scenario.stage7_minutes_context.semantic_sha256
                != self.upstream_score_distribution.source_minutes_context_sha256
            ):
                raise ValueError("scenario Stage-7 identity differs from embedded Stage 8")
        return self


class GameweekPointScenario(PointsModel):
    scenario_id: str
    outcome_draw_id: str
    weight: Annotated[float, Field(gt=0.0, le=1.0)]
    gameweek_id: str
    fixture_ids: tuple[str, ...]
    player_points: dict[str, StrictInt]
    player_components: dict[str, dict[str, StrictInt]]
    player_bps: dict[str, StrictInt]
    player_bonus: dict[str, Annotated[StrictInt, Field(ge=0)]]
    assembly_mode: GameweekAssemblyMode
    approximation_labels: tuple[str, ...]

    @model_validator(mode="after")
    def player_totals_are_exact(self) -> GameweekPointScenario:
        ids = set(self.player_points)
        if (
            set(self.player_components) != ids
            or set(self.player_bps) != ids
            or set(self.player_bonus) != ids
        ):
            raise ValueError("Gameweek player mappings must be one-to-one")
        for player_id, total in self.player_points.items():
            components = self.player_components[player_id]
            if set(components) != set(POINT_COMPONENT_NAMES):
                raise ValueError("Gameweek component vector is incomplete")
            if sum(components.values()) != total:
                raise ValueError("Gameweek total does not equal component sum")
            if components["bonus"] != self.player_bonus[player_id]:
                raise ValueError("Gameweek bonus mapping differs from component vector")
        return self


class GameweekScenarioSet(PointsModel):
    gameweek_id: str
    scenarios: tuple[GameweekPointScenario, ...]
    player_ids: tuple[str, ...]
    ruleset_hash: Sha256
    assembly_mode: GameweekAssemblyMode
    bps_completeness_mode: BpsCompletenessMode
    confidence_grade: ConfidenceGrade
    model_version_ids: tuple[str, ...]
    dataset_version_ids: tuple[str, ...]
    source_bundle_ids: tuple[str, ...]
    upstream_stage8_sha256s: tuple[Sha256, ...]
    warnings: tuple[str, ...]

    @model_validator(mode="after")
    def scenario_set_is_coherent(self) -> GameweekScenarioSet:
        if not self.scenarios:
            raise ValueError("Gameweek scenario set cannot be empty")
        if len(set(self.player_ids)) != len(self.player_ids):
            raise ValueError("Gameweek player mapping must be one-to-one")
        expected_players = set(self.player_ids)
        if any(scenario.gameweek_id != self.gameweek_id for scenario in self.scenarios):
            raise ValueError("Gameweek scenario identity mismatch")
        if any(scenario.assembly_mode is not self.assembly_mode for scenario in self.scenarios):
            raise ValueError("Gameweek assembly mode mismatch")
        if any(set(scenario.player_points) != expected_players for scenario in self.scenarios):
            raise ValueError("every Gameweek scenario must retain the full player universe")
        if not isclose(
            sum(scenario.weight for scenario in self.scenarios), 1.0, rel_tol=0.0, abs_tol=1e-10
        ):
            raise ValueError("Gameweek scenario weights must sum to one")
        return self


class GameweekBpsBonusSummary(PointsModel):
    expected_bps: float
    bps_variance: Annotated[float, Field(ge=0.0)]
    expected_bonus: float
    probability_any_bonus: Probability
    completeness_mode: BpsCompletenessMode


class GameweekPlayerProjectionSummary(PointsModel):
    player_id: str
    expected_points: float
    median_points: StrictInt
    points_variance: Annotated[float, Field(ge=0.0)]
    points_standard_deviation: Annotated[float, Field(ge=0.0)]
    probability_negative_points: Probability
    probability_zero_points: Probability
    probability_1_plus: Probability
    probability_2_plus: Probability
    probability_5_plus: Probability
    probability_10_plus: Probability
    probability_15_plus: Probability
    selected_percentiles: dict[str, StrictInt]
    pmf: dict[int, float]
    component_breakdown: dict[str, ComponentSummary]
    component_covariance: dict[str, dict[str, float]]
    bps_bonus: GameweekBpsBonusSummary
    monte_carlo_mean_se: Annotated[float, Field(ge=0.0)]
    threshold_probability_se: dict[str, Annotated[float, Field(ge=0.0)]]
    scenario_effective_sample_size: Annotated[float, Field(gt=0.0)]
    confidence_grade: ConfidenceGrade
    ruleset_hash: Sha256
    model_version_ids: tuple[str, ...]
    dataset_version_ids: tuple[str, ...]
    source_bundle_ids: tuple[str, ...]
    upstream_stage8_sha256s: tuple[Sha256, ...]


class GameweekProjectionResult(PointsModel):
    schema_version: Literal["fpl-points-gameweek-result-v1"]
    scenario_set: GameweekScenarioSet
    player_summaries: dict[str, GameweekPlayerProjectionSummary]
    joint_matrix: JointScenarioMatrix
    monte_carlo: MonteCarloDiagnostics

    @model_validator(mode="after")
    def output_is_aligned(self) -> GameweekProjectionResult:
        expected = set(self.scenario_set.player_ids)
        if set(self.player_summaries) != expected or set(self.joint_matrix.player_ids) != expected:
            raise ValueError("Gameweek summaries and joint matrix player mapping differ")
        if self.joint_matrix.ruleset_hash != self.scenario_set.ruleset_hash:
            raise ValueError("Gameweek joint matrix ruleset mismatch")
        return self


class DistributionEvaluation(PointsModel):
    player_id: str
    observed_points: int
    probability_mass_observed: Probability
    log_score: float | None
    absolute_error_mean: float
    squared_error_mean: float
    threshold_hits: dict[str, bool]


class ReconciliationDifference(PointsModel):
    player_id: str
    modeled_total: int
    official_total: int
    total_difference: int
    component_differences: dict[str, int]
    exact_match: StrictBool


JsonObject = dict[str, Any]
