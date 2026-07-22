"""Exact schema validation for the RUL-002 split-YAML authoring contract."""

from __future__ import annotations

from datetime import datetime, time
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import SeasonManifest, UnknownRule

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
SourceId = Annotated[StrictStr, Field(pattern=r"^SRC-[A-Z0-9-]+$")]
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


class AssistsFile(AuthoringModel):
    points: StrictInt
    input_contract: Literal["RESOLVED_ELIGIBLE_ASSIST_COUNT"]
    classification_states: tuple[
        Literal["DEFINITE_ASSIST"],
        Literal["DEFINITE_NO_ASSIST"],
        Literal["AMBIGUOUS_ASSIST"],
    ]
    ambiguous_state_allowed_for_exact_scoring: StrictBool


class BonusRanks(AuthoringModel):
    rank_1: StrictInt = Field(alias="1")
    rank_2: StrictInt = Field(alias="2")
    rank_3: StrictInt = Field(alias="3")


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


class BonusFile(AuthoringModel):
    scope: Literal["PER_FIXTURE"]
    bonus_points_by_competition_rank: BonusRanks
    bps: BpsRules


class SquadFile(AuthoringModel):
    squad_size: PositiveInt
    initial_budget_tenths: PositiveInt
    max_per_club: PositiveInt


class LineupFile(AuthoringModel):
    starting_size: PositiveInt
    bench_size: NonNegativeInt
    captain_multiplier: PositiveInt
    vice_fallback: StrictBool


class TransfersFile(AuthoringModel):
    free_transfer_cap: PositiveInt
    hit_points: StrictInt
    state: Literal["REFERENCE_ONLY"]


class PricesFile(AuthoringModel):
    price_unit: Literal["TENTHS_OF_MILLION_GBP"]
    change_threshold_algorithm: Literal["UNDISCLOSED"]


class ChipRule(AuthoringModel):
    key: Literal["WILDCARD", "FREE_HIT", "TRIPLE_CAPTAIN", "BENCH_BOOST"]
    copies: PositiveInt


class ChipsFile(AuthoringModel):
    chips: Annotated[tuple[ChipRule, ...], Field(min_length=1)]
    concurrency_limit: PositiveInt

    @model_validator(mode="after")
    def chip_keys_are_complete(self) -> ChipsFile:
        keys = [chip.key for chip in self.chips]
        expected = {"WILDCARD", "FREE_HIT", "TRIPLE_CAPTAIN", "BENCH_BOOST"}
        if len(keys) != len(set(keys)) or set(keys) != expected:
            raise ValueError("chip keys must be unique and complete")
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


class SpecialEventsFile(AuthoringModel):
    events: Annotated[tuple[dict[str, object], ...], Field(max_length=0)]


class SourceEntry(AuthoringModel):
    source_id: SourceId
    source_type: Annotated[StrictStr, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
    status: Literal["VERIFIED"]
    locator: StrictStr | None = None


class SourceManifestFile(AuthoringModel):
    sources: Annotated[tuple[SourceEntry, ...], Field(min_length=1)]
    rule_source_default: SourceId | None


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
    status: Literal["CAPTURED_UNVERIFIED"]
    production_eligible: Literal[False]
    checked_claims: CheckedClaims
    unknown_blocking_families: Annotated[tuple[StrictStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def blockers_are_unique(self) -> TargetClaimsFile:
        if len(self.unknown_blocking_families) != len(set(self.unknown_blocking_families)):
            raise ValueError("target blocking families must be unique")
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
    if blockers:
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
        claims_model = _validated(
            TargetClaimsFile,
            data.get("target_2026_27_claims.yaml"),
            "target_2026_27_claims.yaml",
        )
        assert isinstance(claims_model, TargetClaimsFile)
        if (
            claims_model.ruleset_id != manifest.ruleset_id
            or claims_model.ruleset_version != manifest.ruleset_version
        ):
            raise RulesValidationError(
                "RULESET_TARGET_IDENTITY", "target claims identity does not match season manifest"
            )
        missing_sources = sorted(_target_source_refs(claims_model) - sources)
        if missing_sources:
            raise RulesValidationError(
                "RULESET_SOURCE_REFERENCE",
                "target claims contain unknown source references",
                blockers=tuple(missing_sources),
            )
        normalized["target_2026_27_claims.yaml"] = claims_model.model_dump(
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
