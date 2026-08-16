"""Exact schema validation for the RUL-002 split-YAML authoring contract."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import (
    InterpretationDecision,
    RuleCapability,
    SeasonManifest,
    UnknownRule,
    VerificationStatus,
)

NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
Percentage = Annotated[StrictInt, Field(ge=0, le=100)]


def _valid_utc_timestamp(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("timestamp must be a real UTC calendar instant") from exc
    return value


def _valid_local_time(value: str) -> str:
    try:
        time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("local time must be a real HH:MM value") from exc
    return value


UtcTimestamp = Annotated[
    StrictStr,
    Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    AfterValidator(_valid_utc_timestamp),
]
LocalTime = Annotated[
    StrictStr,
    Field(pattern=r"^\d{2}:\d{2}$"),
    AfterValidator(_valid_local_time),
]
CalendarDate = Annotated[
    StrictStr,
    Field(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    AfterValidator(lambda value: date.fromisoformat(value).isoformat()),
]
SourceId = Annotated[StrictStr, Field(pattern=r"^SRC-[A-Z0-9-]+$")]
RankKey = Annotated[StrictStr, Field(pattern=r"^[1-9]\d*$")]
StableKey = Annotated[StrictStr, Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")]
RuleEvent = Literal["BALL_RECOVERY", "BLOCK", "CLEARANCE", "INTERCEPTION", "TACKLE"]


class AuthoringModel(BaseModel):
    """Forbid silent authoring drift and retain immutable typed values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PositionRule(AuthoringModel):
    display_name: StrictStr
    squad_quota: NonNegativeInt
    lineup_min: NonNegativeInt
    lineup_max: NonNegativeInt

    @model_validator(mode="after")
    def bounds_are_coherent(self) -> PositionRule:
        if not self.lineup_min <= self.lineup_max <= self.squad_quota:
            raise ValueError("lineup bounds must fit within the squad quota")
        return self


class PositionMap(AuthoringModel):
    GK: PositionRule
    DEF: PositionRule
    MID: PositionRule
    FWD: PositionRule


class PositionsFile(AuthoringModel):
    positions: PositionMap


class AppearanceBand(AuthoringModel):
    id: Literal["SHORT", "LONG"]
    min_inclusive: NonNegativeInt
    max_exclusive: NonNegativeInt | None
    points: StrictInt


class AppearanceRules(AuthoringModel):
    min_minutes_for_any_points: PositiveInt
    stoppage_time_included: StrictBool
    bands: Annotated[tuple[AppearanceBand, ...], Field(min_length=1)]
    combination: Literal["HIGHEST_MATCHING_ONLY"]

    @model_validator(mode="after")
    def bands_are_total_and_exclusive(self) -> AppearanceRules:
        if len({band.id for band in self.bands}) != len(self.bands):
            raise ValueError("appearance band IDs must be unique")
        for minute in range(self.min_minutes_for_any_points, 131):
            matches = sum(
                minute >= band.min_inclusive
                and (band.max_exclusive is None or minute < band.max_exclusive)
                for band in self.bands
            )
            if matches != 1:
                raise ValueError("appearance bands must be total and mutually exclusive")
        return self


class PositionPoints(AuthoringModel):
    GK: StrictInt
    DEF: StrictInt
    MID: StrictInt
    FWD: StrictInt


class GoalRules(AuthoringModel):
    points_by_position: PositionPoints


class PointRule(AuthoringModel):
    points: StrictInt


class CleanSheetRules(AuthoringModel):
    points_by_position: PositionPoints
    min_minutes_inclusive: PositiveInt
    evaluate_goals_while_player_eligible: Literal[True]
    retain_after_normal_substitution: Literal[True]
    continue_goals_after_dismissal: StrictBool


class GoalsConcededRules(AuthoringModel):
    positions: tuple[Literal["GK", "DEF"], Literal["GK", "DEF"]]
    goals_per_deduction: PositiveInt
    points_per_group: StrictInt

    @model_validator(mode="after")
    def position_scope_is_exact(self) -> GoalsConcededRules:
        if set(self.positions) != {"GK", "DEF"}:
            raise ValueError("goals-conceded positions must contain GK and DEF exactly once")
        return self


class GoalkeeperSaveRules(AuthoringModel):
    saves_per_point: PositiveInt
    points_per_group: StrictInt
    cap_per_fixture: NonNegativeInt | None


class PenaltyRules(AuthoringModel):
    save_points: StrictInt
    miss_points: StrictInt
    shootout_eligible: StrictBool


class CardRules(AuthoringModel):
    yellow_points: StrictInt
    red_points: StrictInt


class DefensivePositionRule(AuthoringModel):
    enabled: StrictBool
    event_types: tuple[RuleEvent, ...]
    threshold: PositiveInt | None
    points: NonNegativeInt
    max_points: NonNegativeInt

    @model_validator(mode="after")
    def enabled_shape_is_coherent(self) -> DefensivePositionRule:
        if len(self.event_types) != len(set(self.event_types)):
            raise ValueError("defensive event types must be unique")
        if self.enabled and (self.threshold is None or not self.event_types or self.points == 0):
            raise ValueError("enabled defensive rules require threshold, events, and points")
        if not self.enabled and (
            self.threshold is not None or self.event_types or self.points or self.max_points
        ):
            raise ValueError("disabled defensive rules cannot retain scoring values")
        if self.points > self.max_points:
            raise ValueError("defensive points cannot exceed the per-fixture cap")
        return self


class DefensivePositionMap(AuthoringModel):
    GK: DefensivePositionRule
    DEF: DefensivePositionRule
    MID: DefensivePositionRule
    FWD: DefensivePositionRule


class DefensiveContributionRules(AuthoringModel):
    scope: Literal["PER_FIXTURE"]
    by_position: DefensivePositionMap


class ScoringFile(AuthoringModel):
    appearance: AppearanceRules
    goals: GoalRules
    assists: PointRule
    clean_sheets: CleanSheetRules
    goals_conceded: GoalsConcededRules
    goalkeeper_saves: GoalkeeperSaveRules
    penalties: PenaltyRules
    cards: CardRules
    own_goals: PointRule
    defensive_contributions: DefensiveContributionRules


class ParticipationRules(AuthoringModel):
    fixture_scope: Literal[True]
    appearance_eligibility: Literal["OFFICIAL_MINUTES_GREATER_THAN_ZERO"]
    bonus_eligibility: Literal["OFFICIAL_MINUTES_GREATER_THAN_ZERO"]
    minute_basis: Literal["OFFICIAL_MINUTES_EXCLUDING_STOPPAGE_TIME"]
    position_basis: Literal["TARGET_SEASON_FPL_POSITION"]
    reject_unmapped_position: Literal[True]


class ScoringFileV11(ScoringFile):
    participation: ParticipationRules


class AssistsFile(AuthoringModel):
    points: StrictInt
    input_contract: Literal["RESOLVED_ELIGIBLE_ASSIST_COUNT"]
    classification_states: tuple[
        Literal["DEFINITE_ASSIST"],
        Literal["DEFINITE_NO_ASSIST"],
        Literal["AMBIGUOUS_ASSIST"],
    ]
    ambiguous_state_allowed_for_exact_scoring: StrictBool


class DefensiveTouchZonePolicy(AuthoringModel):
    max_defensive_touches: NonNegativeInt
    intended_destination_required: StrictBool


class AssistDefensiveTouchPolicy(AuthoringModel):
    inside_box: DefensiveTouchZonePolicy
    outside_box: DefensiveTouchZonePolicy
    two_or_more_touches_disqualify: Literal[True]
    defender_attempted_pass_disqualifies: Literal[True]
    woodwork_is_defensive_touch: Literal[False]


class AssistReboundPolicy(AuthoringModel):
    qualifying_origins: tuple[Literal["SHOT", "CROSS_SHOT"], ...]
    qualifying_interventions: tuple[Literal["GOALKEEPER_SAVE", "DEFENSIVE_BLOCK", "WOODWORK"], ...]
    must_reach_scorer_directly: Literal[True]
    defensive_touch_after_rebound_disqualifies: Literal[True]
    scorer_own_rebound_disqualifies: Literal[True]
    multiple_save_touches_are_one_intervention: Literal[True]
    shot_must_be_on_target: Literal[False]
    obvious_pass_or_cross_is_shot: Literal[False]


class AssistPassTouchHandballPolicy(AuthoringModel):
    defensive_touch_before_handball_disqualifies: Literal[True]


class AssistShotHandballPolicy(AuthoringModel):
    direct_shot_required: Literal[True]
    on_target_before_deflection_required: Literal[True]
    on_target_after_deflection_required: Literal[True]


class AssistHandballPolicy(AuthoringModel):
    pass_or_touch: AssistPassTouchHandballPolicy
    shot: AssistShotHandballPolicy


class AssistSetPiecePolicy(AuthoringModel):
    foul_winner_eligible_if_directly_scored: Literal[True]
    last_attacker_before_handball_eligible_if_directly_scored: Literal[True]
    taker_who_won_foul_ineligible: Literal[True]
    handball: AssistHandballPolicy
    corner_or_throw_in_direct_assist: Literal[False]


class AssistOwnGoalPolicy(AuthoringModel):
    forcing_shot_or_pass_eligible: Literal[True]
    requires_identifiable_forcing_action: Literal[True]


class AssistEligibilityPolicy(AuthoringModel):
    policy_version: Annotated[StrictStr, Field(pattern=r"^\d+\.\d+$")]
    final_qualifying_attacking_touch_required: Literal[True]
    eligible_attacking_actions: tuple[
        Literal["PASS", "CROSS", "INADVERTENT_TOUCH", "SHOT", "FOUL_WON", "FORCED_OWN_GOAL_ACTION"],
        ...,
    ]
    inadvertent_touch_must_reach_scorer_directly: Literal[True]
    scorer_loses_and_regains_possession_disqualifies: Literal[True]
    tackle_or_interception_pass_requires_teammate_intent: Literal[True]
    defensive_touches: AssistDefensiveTouchPolicy
    rebounds: AssistReboundPolicy
    own_goals: AssistOwnGoalPolicy
    set_pieces: AssistSetPiecePolicy
    official_fpl_final_decision_controls: Literal[True]


class AssistsFileV11(AssistsFile):
    eligibility_policy: AssistEligibilityPolicy


class BpsAppearanceBand(AuthoringModel):
    min_inclusive: NonNegativeInt | None = None
    min_exclusive: NonNegativeInt | None = None
    max_inclusive: NonNegativeInt | None
    bps: StrictInt

    @model_validator(mode="after")
    def has_one_lower_bound(self) -> BpsAppearanceBand:
        if (self.min_inclusive is None) == (self.min_exclusive is None):
            raise ValueError("BPS appearance band requires exactly one lower-bound form")
        return self


class PenaltyGoalBps(AuthoringModel):
    bps: StrictInt
    exclusive_with_non_penalty_position_goal: Literal[True]


class BpsGoalRules(AuthoringModel):
    penalty_direct: PenaltyGoalBps
    non_penalty_by_position: PositionPoints


class BpsCleanSheetRules(AuthoringModel):
    positions: tuple[Literal["GK"], Literal["DEF"]]
    min_minutes: PositiveInt
    bps: StrictInt


class GroupedBps(AuthoringModel):
    group_size: PositiveInt
    bps_per_group: StrictInt


class PassBand(AuthoringModel):
    min_pct_inclusive: Percentage
    max_pct_exclusive: Percentage | None = None
    max_pct_inclusive: Percentage | None = None
    bps: StrictInt

    @model_validator(mode="after")
    def has_one_ordered_upper_bound(self) -> PassBand:
        if (self.max_pct_exclusive is None) == (self.max_pct_inclusive is None):
            raise ValueError("pass band requires exactly one upper-bound form")
        maximum = (
            self.max_pct_exclusive if self.max_pct_exclusive is not None else self.max_pct_inclusive
        )
        if maximum is None or maximum < self.min_pct_inclusive:
            raise ValueError("pass band upper bound must not precede its lower bound")
        return self


class PassCompletionRules(AuthoringModel):
    min_attempts: PositiveInt
    bands: Annotated[tuple[PassBand, ...], Field(min_length=1)]
    combination: Literal["HIGHEST_MATCHING_ONLY"]

    @model_validator(mode="after")
    def bands_do_not_overlap(self) -> PassCompletionRules:
        for percentage in range(101):
            matches = sum(
                percentage >= band.min_pct_inclusive
                and (
                    percentage < band.max_pct_exclusive
                    if band.max_pct_exclusive is not None
                    else band.max_pct_inclusive is not None and percentage <= band.max_pct_inclusive
                )
                for band in self.bands
            )
            if matches > 1:
                raise ValueError("pass-completion bands must be mutually exclusive")
        return self


class BpsNegativeRules(AuthoringModel):
    goal_conceded_gk_def: StrictInt
    penalty_conceded: StrictInt
    penalty_miss: StrictInt
    yellow: StrictInt
    red: StrictInt
    own_goal: StrictInt
    big_chance_missed: StrictInt
    error_leading_goal: StrictInt
    error_leading_attempt: StrictInt
    being_tackled: StrictInt
    foul_conceded: StrictInt
    offside: StrictInt
    shot_off_target: StrictInt


class BpsNegativeRulesV11(AuthoringModel):
    goal_conceded_gk_def: StrictInt
    penalty_conceded: StrictInt
    penalty_miss: StrictInt
    yellow: StrictInt
    red: StrictInt
    own_goal: StrictInt
    big_chance_missed: StrictInt
    error_leading_goal: StrictInt
    error_leading_attempt: StrictInt
    being_tackled: Literal["REMOVED"]
    foul_conceded: StrictInt
    offside: StrictInt
    shot_off_target: StrictInt


class BpsRules(AuthoringModel):
    appearance_bands: Annotated[tuple[BpsAppearanceBand, ...], Field(min_length=1)]
    goals: BpsGoalRules
    assist: StrictInt
    clean_sheet: BpsCleanSheetRules
    penalty_save: StrictInt
    save_inside_box: StrictInt
    save_outside_box: StrictInt
    successful_open_play_cross: StrictInt
    big_chance_created: StrictInt
    cbi_group: GroupedBps
    recovery_group: GroupedBps
    key_pass: StrictInt
    successful_tackle: StrictInt
    successful_dribble: StrictInt
    match_winning_goal: StrictInt
    goal_line_clearance: StrictInt
    foul_won: StrictInt
    shot_on_target: StrictInt
    pass_completion: PassCompletionRules
    negatives: BpsNegativeRules

    @model_validator(mode="after")
    def appearance_bands_are_total_and_exclusive(self) -> BpsRules:
        for minute in range(1, 131):
            matches = 0
            for band in self.appearance_bands:
                lower = (
                    minute >= band.min_inclusive
                    if band.min_inclusive is not None
                    else band.min_exclusive is not None and minute > band.min_exclusive
                )
                if lower and (band.max_inclusive is None or minute <= band.max_inclusive):
                    matches += 1
            if matches != 1:
                raise ValueError("BPS appearance bands must be total and mutually exclusive")
        return self


class BpsRulesV11(AuthoringModel):
    appearance_bands: Annotated[tuple[BpsAppearanceBand, ...], Field(min_length=1)]
    goals: BpsGoalRules
    assist: StrictInt
    clean_sheet: BpsCleanSheetRules
    penalty_save: StrictInt
    save_any: StrictInt
    save_inside_box_additional: StrictInt
    save_big_chance_additional: StrictInt
    successful_open_play_cross: StrictInt
    big_chance_created: StrictInt
    cbi_group: GroupedBps
    recovery_group: GroupedBps
    key_pass: StrictInt
    successful_tackle: StrictInt
    successful_dribble: StrictInt
    match_winning_goal: StrictInt
    goal_line_clearance: StrictInt
    foul_won: StrictInt
    shot_on_target: StrictInt
    pass_completion: PassCompletionRules
    negatives: BpsNegativeRulesV11

    @model_validator(mode="after")
    def appearance_bands_are_total_and_exclusive(self) -> BpsRulesV11:
        for minute in range(1, 131):
            matches = 0
            for band in self.appearance_bands:
                lower = (
                    minute >= band.min_inclusive
                    if band.min_inclusive is not None
                    else band.min_exclusive is not None and minute > band.min_exclusive
                )
                if lower and (band.max_inclusive is None or minute <= band.max_inclusive):
                    matches += 1
            if matches != 1:
                raise ValueError("BPS appearance bands must be total and mutually exclusive")
        return self


class BonusFile(AuthoringModel):
    scope: Literal["PER_FIXTURE"]
    bonus_points_by_competition_rank: Annotated[dict[RankKey, NonNegativeInt], Field(min_length=1)]
    bps: BpsRules


class BonusFileV11(AuthoringModel):
    scope: Literal["PER_FIXTURE"]
    tie_allocation: Literal["GENERAL_COMPETITION_RANKING"]
    bonus_points_by_competition_rank: Annotated[dict[RankKey, NonNegativeInt], Field(min_length=1)]
    bps: BpsRulesV11


class SquadFile(AuthoringModel):
    squad_size: PositiveInt
    initial_budget_tenths: PositiveInt
    max_per_club: PositiveInt


class LineupFile(AuthoringModel):
    starting_size: PositiveInt
    bench_size: NonNegativeInt
    captain_multiplier: PositiveInt
    vice_fallback: StrictBool


class AutomaticSubstitutionRules(AuthoringModel):
    evaluation_scope: Literal["AFTER_ALL_GAMEWEEK_FIXTURES"]
    absent_definition: Literal["ZERO_OFFICIAL_APPEARANCE_MINUTES"]
    goalkeeper_replacement: Literal["DESIGNATED_BENCH_GOALKEEPER_IF_APPEARED"]
    outfield_order: Literal["MANAGER_BENCH_ORDER"]
    maintain_legal_formation: Literal[True]


class LineupFileV11(LineupFile):
    automatic_substitutions: AutomaticSubstitutionRules | UnknownRule


class TransfersFile(AuthoringModel):
    free_transfer_cap: PositiveInt
    hit_points: StrictInt
    state: Literal["REFERENCE_ONLY", "DRAFT_PRELAUNCH", "CAPTURED_UNVERIFIED", "CONFLICTED"]


class TransferTransitionRules(AuthoringModel):
    preseason_unlimited: StrictBool
    earned_per_deadline: NonNegativeInt
    free_transfer_cap: PositiveInt
    hit_points: StrictInt
    outgoing_and_incoming_same_position: Literal[True]
    club_quota_repair_required: Literal[True]
    transfer_accounting_order: tuple[StableKey, ...]


class TransfersFileV11(AuthoringModel):
    transition: TransferTransitionRules
    chip_interactions: dict[StableKey, tuple[StableKey, ...] | UnknownRule]


class PricesFile(AuthoringModel):
    price_unit: Literal["TENTHS_OF_MILLION_GBP"]
    change_threshold_algorithm: Literal["UNDISCLOSED"]


class SellingPriceBranch(AuthoringModel):
    condition: Literal["CURRENT_AT_OR_BELOW_PURCHASE", "CURRENT_ABOVE_PURCHASE"]
    formula: Literal["CURRENT_PRICE", "PURCHASE_PLUS_FLOOR_HALF_PROFIT"]


class SellingPriceRules(AuthoringModel):
    above_purchase: SellingPriceBranch
    at_or_below_purchase: SellingPriceBranch | UnknownRule


class PricesFileV11(AuthoringModel):
    price_unit: Literal["TENTHS_OF_MILLION_GBP"]
    integer_only: Literal[True]
    initial_purchase_price_basis: Literal["CURRENT_PLAYER_PRICE_AT_INITIAL_SELECTION"]
    current_purchase_price_basis: Literal["PRICE_PAID_FOR_CURRENT_OWNERSHIP"]
    selling_price: SellingPriceRules
    change_threshold_algorithm: Literal["UNDISCLOSED"]


class GameweekWindow(AuthoringModel):
    start_gameweek: PositiveInt
    end_gameweek: PositiveInt

    @model_validator(mode="after")
    def is_ordered(self) -> GameweekWindow:
        if self.end_gameweek < self.start_gameweek:
            raise ValueError("Gameweek range end cannot precede its start")
        return self


class DeclarativeEffect(AuthoringModel):
    surface: StableKey
    operation: StableKey
    parameters: dict[StrictStr, JsonValue]


class ChipRule(AuthoringModel):
    key: StableKey
    copies: PositiveInt | UnknownRule
    activation_window: GameweekWindow | UnknownRule
    expires_after_gameweek: PositiveInt | None | UnknownRule
    duration_gameweeks: PositiveInt | UnknownRule
    concurrency_group: StableKey | UnknownRule
    cancellable: StrictBool | UnknownRule
    effects: tuple[DeclarativeEffect, ...]


class ChipInventory(AuthoringModel):
    copies: PositiveInt
    windows: Annotated[tuple[GameweekWindow, ...], Field(min_length=1)]
    unused_copy_expires_at_window_end: Literal[True]


class ChipRuleV11(AuthoringModel):
    key: StableKey
    inventory: ChipInventory | UnknownRule
    duration_gameweeks: PositiveInt | UnknownRule
    concurrency_group: StableKey | UnknownRule
    cancellable_before_deadline: StrictBool | UnknownRule
    effects: tuple[DeclarativeEffect, ...] | UnknownRule


class ChipsFileV11(AuthoringModel):
    chips: Annotated[tuple[ChipRuleV11, ...], Field(min_length=1)]
    concurrency_limit: PositiveInt

    @model_validator(mode="after")
    def chip_keys_are_unique(self) -> ChipsFileV11:
        keys = [chip.key for chip in self.chips]
        if len(keys) != len(set(keys)):
            raise ValueError("chip keys must be unique")
        return self


class ChipsFile(AuthoringModel):
    chips: Annotated[tuple[ChipRule, ...], Field(min_length=1)]
    concurrency_limit: PositiveInt

    @model_validator(mode="after")
    def chip_keys_are_unique(self) -> ChipsFile:
        keys = [chip.key for chip in self.chips]
        if len(keys) != len(set(keys)):
            raise ValueError("chip keys must be unique")
        return self


class DeadlineRule(AuthoringModel):
    number: PositiveInt
    deadline_utc: UtcTimestamp


class DeadlinesFile(AuthoringModel):
    gameweeks: Annotated[tuple[DeadlineRule, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def gameweek_numbers_are_unique(self) -> DeadlinesFile:
        numbers = [gameweek.number for gameweek in self.gameweeks]
        if len(numbers) != len(set(numbers)):
            raise ValueError("deadline Gameweek numbers must be unique")
        return self


class GameweekFinalityRules(AuthoringModel):
    states: tuple[
        Literal["PROVISIONAL"],
        Literal["REVIEW_WINDOW"],
        Literal["FINAL"],
        Literal["CORRECTED_AFTER_FINAL"],
    ]
    final_time_local: LocalTime
    timezone: Literal["Europe/London"]
    day_offset_after_final_match: PositiveInt
    corrections_after_final_supported: Literal[True]


class DeadlinesFileV11(DeadlinesFile):
    gameweek_finality: GameweekFinalityRules | UnknownRule


class SpecialEvent(AuthoringModel):
    event_id: StableKey
    effective_gameweeks: GameweekWindow
    operation: StableKey
    parameters: dict[StrictStr, JsonValue]


class SpecialEventsFile(AuthoringModel):
    events: tuple[SpecialEvent, ...]

    @model_validator(mode="after")
    def event_ids_are_unique(self) -> SpecialEventsFile:
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("special-event IDs must be unique")
        return self


class SourceEntry(AuthoringModel):
    source_id: SourceId
    source_type: Annotated[StrictStr, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
    status: Literal["VERIFIED"]
    locator: Annotated[StrictStr, Field(min_length=1)]
    published_on: CalendarDate | None = None
    accessed_on: CalendarDate | None = None
    refresh_trigger: Annotated[StrictStr, Field(min_length=1)]


class SourceManifestFile(AuthoringModel):
    sources: Annotated[tuple[SourceEntry, ...], Field(min_length=1)]
    rule_source_default: SourceId | None


class RuleVerificationRecord(AuthoringModel):
    rule_path: Annotated[StrictStr, Field(pattern=r"^/rules/[a-z0-9_/-]+$")]
    verification_status: Literal[
        VerificationStatus.VERIFIED,
        VerificationStatus.INTERPRETATION_REQUIRED,
        VerificationStatus.UNKNOWN,
        VerificationStatus.CONFLICTED,
    ]
    source_refs: tuple[SourceId, ...]
    source_locators: dict[SourceId, Annotated[StrictStr, Field(min_length=1)]]
    interpretation_decision_ids: tuple[
        Annotated[StrictStr, Field(pattern=r"^INT-[A-Z0-9-]+$")], ...
    ] = ()
    interpretation_approval_states: dict[
        Annotated[StrictStr, Field(pattern=r"^INT-[A-Z0-9-]+$")],
        Literal["APPROVED", "UNAPPROVED"],
    ] = {}
    interpretation_note: Annotated[StrictStr, Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def record_is_coherent(self) -> RuleVerificationRecord:
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("rule verification source references must be unique")
        if set(self.source_locators) != set(self.source_refs):
            raise ValueError("rule source locators must match source_refs exactly")
        if (
            self.verification_status
            in {
                VerificationStatus.VERIFIED,
                VerificationStatus.INTERPRETATION_REQUIRED,
            }
            and not self.source_refs
        ):
            raise ValueError("verified or interpreted rules require official evidence")
        if self.verification_status is VerificationStatus.INTERPRETATION_REQUIRED:
            if not self.interpretation_decision_ids or self.interpretation_note is None:
                raise ValueError("interpreted rules require decisions and an interpretation note")
            if set(self.interpretation_approval_states) != set(self.interpretation_decision_ids):
                raise ValueError("interpreted rules require an approval state for every decision")
        elif self.interpretation_decision_ids:
            raise ValueError("official-source claims cannot cite interpretation decisions")
        elif self.interpretation_approval_states:
            raise ValueError("official-source claims cannot describe interpretation approval")
        return self


class RuleVerificationFile(AuthoringModel):
    rules: Annotated[tuple[RuleVerificationRecord, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def paths_are_unique(self) -> RuleVerificationFile:
        paths = [rule.rule_path for rule in self.rules]
        if len(paths) != len(set(paths)):
            raise ValueError("rule verification paths must be unique")
        return self


class CapabilityDefinition(AuthoringModel):
    inherits: tuple[RuleCapability, ...]
    rule_paths: tuple[Annotated[StrictStr, Field(pattern=r"^/rules/[a-z0-9_/-]+$")], ...]


class CapabilityDefinitions(AuthoringModel):
    PLAYER_POINTS: CapabilityDefinition
    GW1_INITIAL_SQUAD: CapabilityDefinition
    TRANSFER_STATE: CapabilityDefinition
    CHIP_STATE: CapabilityDefinition
    FULL_SEASON: CapabilityDefinition


class CapabilitiesFile(AuthoringModel):
    capabilities: CapabilityDefinitions


class InterpretationsFile(AuthoringModel):
    decisions: tuple[InterpretationDecision, ...]

    @model_validator(mode="after")
    def decisions_are_unique(self) -> InterpretationsFile:
        identifiers = [decision.decision_id for decision in self.decisions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("interpretation decision IDs must be unique")
        return self


class VerifiedValueClaim(AuthoringModel):
    verification_status: Literal["VERIFIED"]
    value: StrictInt
    source_refs: Annotated[tuple[SourceId, ...], Field(min_length=1)]


class RemovedClaim(AuthoringModel):
    verification_status: Literal["VERIFIED"]
    value: None
    operation: Literal["REMOVE"]
    source_refs: Annotated[tuple[SourceId, ...], Field(min_length=1)]


class DefensiveClaim(AuthoringModel):
    verification_status: Literal["VERIFIED"]
    threshold: PositiveInt
    points: PositiveInt
    cap: PositiveInt
    events: Annotated[tuple[RuleEvent, ...], Field(min_length=1)]
    source_refs: Annotated[tuple[SourceId, ...], Field(min_length=1)]


class FinalityClaim(AuthoringModel):
    verification_status: Literal["VERIFIED"]
    local_time: LocalTime
    day_offset_after_final_match: PositiveInt
    source_refs: Annotated[tuple[SourceId, ...], Field(min_length=1)]


class DeadlineClaim(AuthoringModel):
    verification_status: Literal["VERIFIED"]
    value: UtcTimestamp
    displayed_source_time: StrictStr
    source_refs: Annotated[tuple[SourceId, ...], Field(min_length=1)]


class CheckedClaims(AuthoringModel):
    bps_being_tackled: RemovedClaim = Field(alias="bps.being_tackled")
    bps_cbi_group_size: VerifiedValueClaim = Field(alias="bps.cbi_group_size")
    bps_any_save: VerifiedValueClaim = Field(alias="bps.any_save")
    bps_inside_box_save_extra: VerifiedValueClaim = Field(alias="bps.inside_box_save_extra")
    bps_big_chance_save_extra: VerifiedValueClaim = Field(alias="bps.big_chance_save_extra")
    bps_penalty_save: VerifiedValueClaim = Field(alias="bps.penalty_save")
    defensive_contributions_defender: DefensiveClaim = Field(
        alias="defensive_contributions.defender"
    )
    defensive_contributions_mid_fwd: DefensiveClaim = Field(alias="defensive_contributions.mid_fwd")
    free_transfer_cap: VerifiedValueClaim
    gameweek_finality: FinalityClaim
    gw1_deadline: DeadlineClaim


class TargetClaimsFile(AuthoringModel):
    ruleset_id: StrictStr
    ruleset_version: StrictStr
    status: Literal["DRAFT_PRELAUNCH", "CAPTURED_UNVERIFIED", "CONFLICTED", "REFERENCE_ONLY"]
    production_eligible: Literal[False]
    checked_claims: CheckedClaims | None
    unknown_blocking_families: Annotated[tuple[StrictStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def blockers_are_unique(self) -> TargetClaimsFile:
        if len(self.unknown_blocking_families) != len(set(self.unknown_blocking_families)):
            raise ValueError("target blocking families must be unique")
        if self.status == "REFERENCE_ONLY" and self.checked_claims is not None:
            raise ValueError("REFERENCE_ONLY synthetic rules must not carry target-season claims")
        if self.status != "REFERENCE_ONLY" and self.checked_claims is None:
            raise ValueError("target-season rules require checked claims")
        return self


COMPLETE_FILE_MODELS: dict[str, type[AuthoringModel]] = {
    "positions.yaml": PositionsFile,
    "scoring.yaml": ScoringFile,
    "assists.yaml": AssistsFile,
    "bonus.yaml": BonusFile,
    "squad.yaml": SquadFile,
    "lineup.yaml": LineupFile,
    "transfers.yaml": TransfersFile,
    "prices.yaml": PricesFile,
    "chips.yaml": ChipsFile,
    "deadlines.yaml": DeadlinesFile,
    "special_events.yaml": SpecialEventsFile,
}

V11_FILE_MODELS: dict[str, type[AuthoringModel]] = {
    **COMPLETE_FILE_MODELS,
    "scoring.yaml": ScoringFileV11,
    "assists.yaml": AssistsFileV11,
    "bonus.yaml": BonusFileV11,
    "lineup.yaml": LineupFileV11,
    "transfers.yaml": TransfersFileV11,
    "prices.yaml": PricesFileV11,
    "chips.yaml": ChipsFileV11,
    "deadlines.yaml": DeadlinesFileV11,
}

V11_EXTENSION_MODELS: dict[str, type[AuthoringModel]] = {
    "capabilities.yaml": CapabilitiesFile,
    "interpretations.yaml": InterpretationsFile,
    "rule_verification.yaml": RuleVerificationFile,
    "target_2026_27_claims.yaml": TargetClaimsFile,
}


def _validated(model_type: type[BaseModel], value: object, filename: str) -> BaseModel:
    try:
        return model_type.model_validate(value)
    except ValidationError as exc:
        raise RulesValidationError(
            "RULESET_SCHEMA_INVALID", f"{filename} failed its exact authoring schema"
        ) from exc


def _source_ids(source_manifest: SourceManifestFile) -> set[str]:
    identifiers = [source.source_id for source in source_manifest.sources]
    if len(identifiers) != len(set(identifiers)):
        raise RulesValidationError("RULESET_SOURCE_INVALID", "source IDs must be unique")
    if (
        source_manifest.rule_source_default is not None
        and source_manifest.rule_source_default not in identifiers
    ):
        raise RulesValidationError("RULESET_SOURCE_REFERENCE", "default rule source does not exist")
    return set(identifiers)


def _target_source_refs(claims: TargetClaimsFile) -> set[str]:
    references: set[str] = set()
    if claims.checked_claims is None:
        return references
    for _, claim in claims.checked_claims:
        references.update(claim.source_refs)
    return references


def _validate_complete_coherence(normalized: dict[str, dict[str, Any]]) -> None:
    positions = PositionsFile.model_validate(normalized["positions.yaml"])
    squad = SquadFile.model_validate(normalized["squad.yaml"])
    lineup = LineupFile.model_validate(normalized["lineup.yaml"])
    scoring = ScoringFile.model_validate(normalized["scoring.yaml"])
    assists = AssistsFile.model_validate(normalized["assists.yaml"])
    position_rules = (
        positions.positions.GK,
        positions.positions.DEF,
        positions.positions.MID,
        positions.positions.FWD,
    )
    if sum(rule.squad_quota for rule in position_rules) != squad.squad_size:
        raise RulesValidationError("RULESET_SQUAD_INVALID", "position quotas must equal squad size")
    if lineup.starting_size + lineup.bench_size != squad.squad_size:
        raise RulesValidationError(
            "RULESET_LINEUP_INVALID", "starting and bench sizes must equal squad size"
        )
    if not (
        sum(rule.lineup_min for rule in position_rules)
        <= lineup.starting_size
        <= sum(rule.lineup_max for rule in position_rules)
    ):
        raise RulesValidationError("RULESET_LINEUP_INVALID", "position bounds cannot form a lineup")
    if assists.points != scoring.assists.points:
        raise RulesValidationError(
            "RULESET_ASSIST_POINTS_MISMATCH",
            "assists.yaml and scoring.yaml must define the same points value",
        )


def validate_and_normalize_authoring_data(
    manifest: SeasonManifest,
    data: dict[str, dict[str, Any]],
    blockers: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Validate every family, controlled value, unit, and source reference."""

    normalized = dict(data)
    normalized["season_manifest.yaml"] = manifest.model_dump(mode="json")
    source_model = _validated(
        SourceManifestFile, data["source_manifest.yaml"], "source_manifest.yaml"
    )
    assert isinstance(source_model, SourceManifestFile)
    sources = _source_ids(source_model)
    normalized["source_manifest.yaml"] = source_model.model_dump(mode="json", by_alias=True)
    if manifest.schema_version == "1.1":
        expected_extensions = set(V11_EXTENSION_MODELS)
        if set(manifest.extension_files) != expected_extensions:
            raise RulesValidationError(
                "RULESET_EXTENSION_STATUS",
                "schema 1.1 requires capability, interpretation, rule-verification, and target-claim extensions",
            )
        family_unknowns = {
            filename: data[filename].get("verification_status") in {"UNKNOWN", "CONFLICTED"}
            for filename in V11_FILE_MODELS
        }
        referenced_sources: set[str] = set()
        for filename, model_type in V11_FILE_MODELS.items():
            if family_unknowns[filename]:
                model = _validated(UnknownRule, data[filename], filename)
                assert isinstance(model, UnknownRule)
                referenced_sources.update(model.source_refs)
            else:
                model = _validated(model_type, data[filename], filename)
            normalized[filename] = model.model_dump(mode="json", by_alias=True)

        for filename, model_type in V11_EXTENSION_MODELS.items():
            model = _validated(model_type, data[filename], filename)
            normalized[filename] = model.model_dump(mode="json", by_alias=True)
        claims_model = TargetClaimsFile.model_validate(normalized["target_2026_27_claims.yaml"])
        if (
            claims_model.ruleset_id != manifest.ruleset_id
            or claims_model.ruleset_version != manifest.ruleset_version
            or claims_model.status != manifest.status.value
        ):
            raise RulesValidationError(
                "RULESET_TARGET_IDENTITY",
                "target claims identity or status does not match season manifest",
            )
        verification = RuleVerificationFile.model_validate(normalized["rule_verification.yaml"])
        interpretations = InterpretationsFile.model_validate(normalized["interpretations.yaml"])
        referenced_sources.update(_target_source_refs(claims_model))
        for rule in verification.rules:
            referenced_sources.update(rule.source_refs)
        for decision in interpretations.decisions:
            referenced_sources.update(decision.evidence_source_refs)
        missing_sources = sorted(referenced_sources - sources)
        if missing_sources:
            raise RulesValidationError(
                "RULESET_SOURCE_REFERENCE",
                "schema 1.1 metadata contains unknown source references",
                blockers=tuple(missing_sources),
            )
        if (
            not family_unknowns["positions.yaml"]
            and not family_unknowns["scoring.yaml"]
            and not family_unknowns["assists.yaml"]
        ):
            scoring = ScoringFileV11.model_validate(normalized["scoring.yaml"])
            assists = AssistsFileV11.model_validate(normalized["assists.yaml"])
            if assists.points != scoring.assists.points:
                raise RulesValidationError(
                    "RULESET_ASSIST_POINTS_MISMATCH",
                    "assists.yaml and scoring.yaml must define the same points value",
                )
        if (
            not family_unknowns["positions.yaml"]
            and not family_unknowns["squad.yaml"]
            and not family_unknowns["lineup.yaml"]
        ):
            positions = PositionsFile.model_validate(normalized["positions.yaml"])
            squad = SquadFile.model_validate(normalized["squad.yaml"])
            lineup = LineupFileV11.model_validate(normalized["lineup.yaml"])
            position_rules = tuple(
                getattr(positions.positions, position) for position in ("GK", "DEF", "MID", "FWD")
            )
            if sum(rule.squad_quota for rule in position_rules) != squad.squad_size:
                raise RulesValidationError(
                    "RULESET_SQUAD_INVALID", "position quotas must equal squad size"
                )
            if lineup.starting_size + lineup.bench_size != squad.squad_size:
                raise RulesValidationError(
                    "RULESET_LINEUP_INVALID", "starting and bench sizes must equal squad size"
                )
        return normalized

    family_unknowns = {
        filename: data[filename].get("verification_status") in {"UNKNOWN", "CONFLICTED"}
        for filename in COMPLETE_FILE_MODELS
    }
    if any(family_unknowns.values()):
        if not all(family_unknowns.values()):
            raise RulesValidationError(
                "RULESET_DRAFT_SHAPE",
                "top-level unknown rule families must cover every complete family",
            )
        draft_references: set[str] = set()
        for filename in COMPLETE_FILE_MODELS:
            unknown = _validated(UnknownRule, data[filename], filename)
            assert isinstance(unknown, UnknownRule)
            draft_references.update(unknown.source_refs)
            normalized[filename] = unknown.model_dump(mode="json", by_alias=True)
        missing_draft_sources = sorted(draft_references - sources)
        if missing_draft_sources:
            raise RulesValidationError(
                "RULESET_SOURCE_REFERENCE",
                "draft rule families contain unknown source references",
                blockers=tuple(missing_draft_sources),
            )
        if not manifest.extension_files:
            raise RulesValidationError(
                "RULESET_EXTENSION_STATUS", "unknown draft families require target claims"
            )
        legacy_claims = _validated(
            TargetClaimsFile, data.get("target_2026_27_claims.yaml"), "target_2026_27_claims.yaml"
        )
        assert isinstance(legacy_claims, TargetClaimsFile)
        if (
            legacy_claims.ruleset_id != manifest.ruleset_id
            or legacy_claims.ruleset_version != manifest.ruleset_version
            or legacy_claims.status != manifest.status.value
        ):
            raise RulesValidationError(
                "RULESET_TARGET_IDENTITY",
                "target claims identity or status does not match season manifest",
            )
        missing_sources = sorted(_target_source_refs(legacy_claims) - sources)
        if missing_sources:
            raise RulesValidationError(
                "RULESET_SOURCE_REFERENCE",
                "target claims contain unknown source references",
                blockers=tuple(missing_sources),
            )
        normalized["target_2026_27_claims.yaml"] = legacy_claims.model_dump(
            mode="json", by_alias=True
        )
        return normalized

    if manifest.extension_files:
        raise RulesValidationError(
            "RULESET_EXTENSION_STATUS", "supported target extensions require a blocked draft"
        )
    for filename, model_type in COMPLETE_FILE_MODELS.items():
        model = _validated(model_type, data[filename], filename)
        normalized[filename] = model.model_dump(mode="json", by_alias=True)
    if source_model.rule_source_default is None:
        raise RulesValidationError(
            "RULESET_SOURCE_REFERENCE", "complete rules require a default source reference"
        )
    _validate_complete_coherence(normalized)
    return normalized
