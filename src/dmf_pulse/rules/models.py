"""Strict public models for authored rules, scenarios, and results."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator


class RulesModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FPLPosition(StrEnum):
    GK = "GK"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"


class RulesetStatus(StrEnum):
    DRAFT_PRELAUNCH = "DRAFT_PRELAUNCH"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    CAPTURED_UNVERIFIED = "CAPTURED_UNVERIFIED"
    CONFLICTED = "CONFLICTED"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class VerificationStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    UNCONFIRMED = "UNCONFIRMED"
    PROVISIONAL = "PROVISIONAL"
    VERIFIED = "VERIFIED"
    CONFLICTED = "CONFLICTED"
    SUPERSEDED = "SUPERSEDED"


class AssistEligibility(StrEnum):
    DEFINITE_ASSIST = "DEFINITE_ASSIST"
    DEFINITE_NO_ASSIST = "DEFINITE_NO_ASSIST"
    AMBIGUOUS_ASSIST = "AMBIGUOUS_ASSIST"


class UnknownRule(RulesModel):
    verification_status: Literal[VerificationStatus.UNKNOWN, VerificationStatus.CONFLICTED]
    value: None
    source_refs: tuple[Annotated[StrictStr, Field(pattern=r"^SRC-[A-Z0-9-]+$")], ...]

    @model_validator(mode="after")
    def source_references_are_unique(self) -> UnknownRule:
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("unknown-rule source references must be unique")
        return self


class SeasonManifest(RulesModel):
    ruleset_id: Annotated[
        str, Field(min_length=3, max_length=100, pattern=r"^[a-z0-9][a-z0-9.-]+$")
    ]
    ruleset_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")]
    schema_version: Literal["1.0"]
    season_code: Annotated[StrictStr, Field(pattern=r"^\d{4}/\d{4}$")]
    status: RulesetStatus
    production_eligible: StrictBool
    required_files: tuple[StrictStr, ...]
    extension_files: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def lifecycle_is_consistent(self) -> SeasonManifest:
        if self.production_eligible and self.status not in {
            RulesetStatus.VERIFIED,
            RulesetStatus.ACTIVE,
        }:
            raise ValueError("non-production ruleset status cannot be production eligible")
        if len(self.required_files) != len(set(self.required_files)):
            raise ValueError("required_files contains duplicates")
        if len(self.extension_files) != len(set(self.extension_files)):
            raise ValueError("extension_files contains duplicates")
        return self


class SourceFileDigest(RulesModel):
    raw_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    semantic_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RulesetValidationReport(RulesModel):
    ruleset_id: str
    ruleset_version: str
    status: RulesetStatus
    production_eligible: bool
    valid: bool
    files: tuple[str, ...]
    source_files: dict[str, SourceFileDigest]
    source_bundle_raw_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source_bundle_semantic_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source_hashes: dict[str, str]
    unknown_blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class RuleSourceReference(RulesModel):
    source_id: Annotated[StrictStr, Field(pattern=r"^SRC-[A-Z0-9-]+$")]
    locator: Annotated[StrictStr, Field(min_length=1)]
    verification_status: Literal["VERIFIED"]
    published_on: StrictStr | None = None
    accessed_on: StrictStr | None = None
    refresh_trigger: Annotated[StrictStr, Field(min_length=1)]


class RuleProvenance(RulesModel):
    rule_id: Annotated[StrictStr, Field(pattern=r"^FPL-[A-Z0-9_-]+$", max_length=96)]
    source_refs: Annotated[
        tuple[Annotated[StrictStr, Field(pattern=r"^SRC-[A-Z0-9-]+$")], ...],
        Field(min_length=1),
    ]
    sources: Annotated[tuple[RuleSourceReference, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def sources_match_references(self) -> RuleProvenance:
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("rule provenance source references must be unique")
        if tuple(source.source_id for source in self.sources) != self.source_refs:
            raise ValueError("rule provenance sources must match source_refs in order")
        return self


class CompiledRuleset(RulesModel):
    compiler_version: str
    schema_version: Literal["1.0"]
    ruleset_id: str
    ruleset_version: str
    season_code: str
    status: RulesetStatus
    production_eligible: bool
    source_files: dict[str, SourceFileDigest]
    source_bundle_raw_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source_bundle_semantic_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    # Deprecated compatibility aliases. New consumers use source_files and the two bundles.
    source_hashes: dict[str, str]
    source_bundle_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    unknown_blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    rules: dict[str, Any]
    rule_provenance: dict[str, RuleProvenance]
    ruleset_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RuleChange(RulesModel):
    path: str
    kind: Literal["ADDED", "REMOVED", "CHANGED"]
    left: Any = None
    right: Any = None


class RulesetDiff(RulesModel):
    left_id: str
    left_hash: str
    right_id: str
    right_hash: str
    changes: tuple[RuleChange, ...]


NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Minutes = Annotated[StrictInt, Field(ge=0, le=130)]


class DefensiveActions(RulesModel):
    ball_recoveries: NonNegativeInt
    blocks: NonNegativeInt
    clearances: NonNegativeInt
    interceptions: NonNegativeInt
    tackles: NonNegativeInt


class BpsEvents(RulesModel):
    big_chances_created: NonNegativeInt
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
            raise ValueError("passes_completed cannot exceed pass_attempts")
        return self


class PlayerScenario(RulesModel):
    player_id: Annotated[str, Field(min_length=1, max_length=100)]
    team_id: str
    position: FPLPosition
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
    dismissed: StrictBool = False
    team_goals_after_dismissal: NonNegativeInt = 0

    @model_validator(mode="after")
    def zero_minutes_have_no_events(self) -> PlayerScenario:
        if self.minutes == 0:
            direct_counts = (
                self.goals_non_penalty,
                self.goals_penalty,
                self.eligible_assists,
                self.goals_conceded_while_eligible,
                self.saves,
                self.penalty_saves,
                self.penalty_misses,
                self.yellow_cards,
                self.red_cards,
                self.own_goals,
                self.team_goals_after_dismissal,
            )
            if (
                any(direct_counts)
                or any(self.defensive_actions.model_dump().values())
                or any(self.bps.model_dump().values())
                or self.dismissed
            ):
                raise ValueError("zero-minute placeholder cannot have scoring events")
        if not self.dismissed and self.team_goals_after_dismissal:
            raise ValueError("post-dismissal goals require dismissed=true")
        if self.red_cards > 0 and not self.dismissed:
            raise ValueError("red cards require dismissed=true")
        if self.dismissed and self.red_cards == 0:
            raise ValueError("dismissed=true requires a red card")
        return self


class FixtureScenario(RulesModel):
    fixture_id: str
    gameweek_id: str
    home_team_id: str
    away_team_id: str
    home_goals: NonNegativeInt
    away_goals: NonNegativeInt
    participant_universe_complete: Literal[True]
    players: tuple[PlayerScenario, ...]
    ruleset_id: StrictStr | None = None
    ruleset_version: StrictStr | None = None
    ruleset_hash: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")] | None = None

    @model_validator(mode="after")
    def fixture_is_coherent(self) -> FixtureScenario:
        if self.home_team_id == self.away_team_id:
            raise ValueError("fixture teams must be distinct")
        ids = [player.player_id for player in self.players]
        if len(ids) != len(set(ids)):
            raise ValueError("fixture player IDs must be unique")
        valid_teams = {self.home_team_id, self.away_team_id}
        if any(player.team_id not in valid_teams for player in self.players):
            raise ValueError("fixture player has an unrelated team")
        for player in self.players:
            conceded = self.away_goals if player.team_id == self.home_team_id else self.home_goals
            if player.goals_conceded_while_eligible > conceded:
                raise ValueError("eligible goals conceded exceeds the fixture score")
            if player.goals_conceded_while_eligible + player.team_goals_after_dismissal > conceded:
                raise ValueError("on-pitch and post-dismissal goals exceed the fixture score")
            if player.bps.match_winning_goals > player.goals_non_penalty + player.goals_penalty:
                raise ValueError("match-winning goal requires a scored goal")
            if player.position is not FPLPosition.GK and (
                player.saves
                or player.penalty_saves
                or player.bps.saves_inside_box
                or player.bps.saves_outside_box
            ):
                raise ValueError("goalkeeper save events require GK position")
        home_players = [player for player in self.players if player.team_id == self.home_team_id]
        away_players = [player for player in self.players if player.team_id == self.away_team_id]
        derived_home = sum(
            player.goals_non_penalty + player.goals_penalty for player in home_players
        ) + sum(player.own_goals for player in away_players)
        derived_away = sum(
            player.goals_non_penalty + player.goals_penalty for player in away_players
        ) + sum(player.own_goals for player in home_players)
        if (derived_home, derived_away) != (self.home_goals, self.away_goals):
            raise ValueError("player goal events do not reconcile to the fixture score")
        if (
            sum(player.eligible_assists for player in home_players) > self.home_goals
            or sum(player.eligible_assists for player in away_players) > self.away_goals
        ):
            raise ValueError("eligible assists exceed the team's scored goals")
        home_winners = sum(player.bps.match_winning_goals for player in home_players)
        away_winners = sum(player.bps.match_winning_goals for player in away_players)
        home_own_goals = sum(player.own_goals for player in away_players)
        away_own_goals = sum(player.own_goals for player in home_players)
        if self.home_goals > self.away_goals:
            winners_are_coherent = away_winners == 0 and home_winners in (
                {0, 1} if home_own_goals else {1}
            )
        elif self.away_goals > self.home_goals:
            winners_are_coherent = home_winners == 0 and away_winners in (
                {0, 1} if away_own_goals else {1}
            )
        else:
            winners_are_coherent = home_winners == 0 and away_winners == 0
        if not winners_are_coherent:
            raise ValueError("match-winning goal events do not match the fixture result")
        return self


class GameweekScenario(RulesModel):
    gameweek_id: str
    fixtures: tuple[FixtureScenario, ...]
    ruleset_id: StrictStr | None = None
    ruleset_version: StrictStr | None = None
    ruleset_hash: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")] | None = None

    @model_validator(mode="after")
    def gameweek_is_coherent(self) -> GameweekScenario:
        ids = [fixture.fixture_id for fixture in self.fixtures]
        if len(ids) != len(set(ids)):
            raise ValueError("gameweek fixture IDs must be unique")
        if any(fixture.gameweek_id != self.gameweek_id for fixture in self.fixtures):
            raise ValueError("fixture gameweek identity mismatch")
        return self


class PlayerScore(RulesModel):
    appearance: int
    assists: int
    bonus: int
    bps: int
    clean_sheet: int
    defensive_contributions: int
    goals: int
    goals_conceded: int
    own_goals: int
    penalty_misses: int
    penalty_saves: int
    red_cards: int
    saves: int
    total: int
    yellow_cards: int

    @model_validator(mode="after")
    def total_is_component_sum(self) -> PlayerScore:
        components = (
            self.appearance,
            self.assists,
            self.bonus,
            self.clean_sheet,
            self.defensive_contributions,
            self.goals,
            self.goals_conceded,
            self.own_goals,
            self.penalty_misses,
            self.penalty_saves,
            self.red_cards,
            self.saves,
            self.yellow_cards,
        )
        if self.total != sum(components):
            raise ValueError("player total does not equal its components")
        if self.bonus < 0:
            raise ValueError("bonus must be non-negative")
        return self


class FixtureScoreResult(RulesModel):
    away_goals: int
    fixture_id: str
    gameweek_id: str
    home_goals: int
    players: dict[str, PlayerScore]
    ruleset_hash: str
    ruleset_id: str
    ruleset_version: str
    sum_player_totals: int

    @model_validator(mode="after")
    def aggregate_is_exact(self) -> FixtureScoreResult:
        if self.sum_player_totals != sum(player.total for player in self.players.values()):
            raise ValueError("fixture total does not equal player totals")
        return self


class GameweekScoreResult(RulesModel):
    fixture_ids: tuple[str, ...]
    gameweek_id: str
    players: dict[str, PlayerScore]
    player_totals: dict[str, int]
    ruleset_hash: str
    ruleset_id: str
    ruleset_version: str
    fixture_results: tuple[FixtureScoreResult, ...]

    @model_validator(mode="after")
    def aggregate_is_exact(self) -> GameweekScoreResult:
        if self.fixture_ids != tuple(result.fixture_id for result in self.fixture_results):
            raise ValueError("fixture_ids must match serialized fixture results")
        if self.fixture_ids != tuple(sorted(self.fixture_ids)):
            raise ValueError("fixture results must use deterministic fixture ordering")
        identity = (self.ruleset_id, self.ruleset_version, self.ruleset_hash)
        if any(
            (result.ruleset_id, result.ruleset_version, result.ruleset_hash) != identity
            for result in self.fixture_results
        ):
            raise ValueError("fixture result ruleset identity mismatch")
        component_names = tuple(PlayerScore.model_fields)
        expected: dict[str, dict[str, int]] = {}
        for result in self.fixture_results:
            for player_id, score in result.players.items():
                player = expected.setdefault(
                    player_id, {component: 0 for component in component_names}
                )
                for component in component_names:
                    player[component] += getattr(score, component)
        expected_players = {
            player_id: PlayerScore.model_validate(components)
            for player_id, components in sorted(expected.items())
        }
        if self.players != expected_players:
            raise ValueError("Gameweek player components do not equal fixture component sums")
        expected_totals = {player_id: score.total for player_id, score in expected_players.items()}
        if self.player_totals != expected_totals:
            raise ValueError("player_totals must equal aggregated component totals")
        return self


class ApprovalRecord(RulesModel):
    ruleset_id: str
    ruleset_version: str
    approved: StrictBool
    approved_at: StrictStr | None
    approved_by: StrictStr | None
    ruleset_hash: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")] | None = None


class ActivationReceipt(RulesModel):
    ruleset_id: str
    ruleset_version: str
    ruleset_hash: str
    verified_ruleset_hash: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    approval_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    activated_at: StrictStr
    artifact: str
    activated: Literal[True] = True
