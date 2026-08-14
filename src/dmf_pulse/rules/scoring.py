"""Pure fixture scoring bound to one explicit compiled ruleset."""

from __future__ import annotations

from typing import cast

from dmf_pulse.rules.bonus import allocate_bonus
from dmf_pulse.rules.bps import calculate_bps
from dmf_pulse.rules.compiler import ensure_compiled_ruleset_integrity
from dmf_pulse.rules.errors import RulesIntegrityError, RulesValidationError
from dmf_pulse.rules.models import (
    CompiledRuleset,
    FixtureScenario,
    FixtureScoreResult,
    PlayerScenario,
    PlayerScore,
    RulesetStatus,
    validate_v11_save_contract,
)


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RulesIntegrityError(
            "RULESET_SCORING_CONFIG", f"compiled rule mapping is invalid: {label}"
        )
    return cast(dict[str, object], value)


def _sequence(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise RulesIntegrityError(
            "RULESET_SCORING_CONFIG", f"compiled rule list is invalid: {label}"
        )
    return cast(list[object], value)


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RulesIntegrityError(
            "RULESET_SCORING_CONFIG", f"compiled integer rule is invalid: {label}"
        )
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise RulesIntegrityError(
            "RULESET_SCORING_CONFIG", f"compiled boolean rule is invalid: {label}"
        )
    return value


def _bonus_rank_awards(ruleset: CompiledRuleset) -> dict[int, int]:
    bonus = _mapping(ruleset.rules.get("bonus"), "bonus")
    tie_allocation = bonus.get("tie_allocation")
    if tie_allocation is not None and tie_allocation != "GENERAL_COMPETITION_RANKING":
        raise RulesIntegrityError(
            "RULESET_BONUS_TIE_INVALID", "compiled bonus tie allocation is unsupported"
        )
    raw_awards = _mapping(
        bonus.get("bonus_points_by_competition_rank"),
        "bonus.bonus_points_by_competition_rank",
    )
    awards: dict[int, int] = {}
    for raw_rank, raw_award in raw_awards.items():
        if not raw_rank.isdigit() or int(raw_rank) <= 0:
            raise RulesIntegrityError(
                "RULESET_BONUS_RANK_INVALID", "compiled bonus rank must be a positive integer"
            )
        rank = int(raw_rank)
        award = _integer(raw_award, "bonus.rank_award")
        if award < 0:
            raise RulesIntegrityError(
                "RULESET_BONUS_RANK_INVALID", "compiled bonus award must be non-negative"
            )
        awards[rank] = award
    return awards


def _appearance(config: dict[str, object], minutes: int) -> int:
    matches: list[int] = []
    for raw_band in _sequence(config.get("bands"), "appearance.bands"):
        band = _mapping(raw_band, "appearance.bands[]")
        minimum = _integer(band.get("min_inclusive"), "appearance.min_inclusive")
        maximum = band.get("max_exclusive")
        if minutes >= minimum and (
            maximum is None or minutes < _integer(maximum, "appearance.max_exclusive")
        ):
            matches.append(_integer(band.get("points"), "appearance.points"))
    if len(matches) > 1:
        raise RulesIntegrityError("RULESET_APPEARANCE_BANDS", "appearance point bands overlap")
    return max(matches, default=0)


def _effective_conceded(player: PlayerScenario, scoring: dict[str, object]) -> int:
    clean = _mapping(scoring.get("clean_sheets"), "clean_sheets")
    conceded = player.goals_conceded_while_eligible
    if player.dismissed and _boolean(
        clean.get("continue_goals_after_dismissal"), "clean_sheets.continue_goals_after_dismissal"
    ):
        conceded += player.team_goals_after_dismissal
    return conceded


def _defensive_contribution(player: PlayerScenario, config: dict[str, object]) -> int:
    by_position = _mapping(config.get("by_position"), "defensive_contributions.by_position")
    position = _mapping(by_position.get(player.position.value), "defensive_contributions.position")
    if not _boolean(position.get("enabled"), "defensive_contributions.enabled"):
        return 0
    counts = {
        "BALL_RECOVERY": player.defensive_actions.ball_recoveries,
        "BLOCK": player.defensive_actions.blocks,
        "CLEARANCE": player.defensive_actions.clearances,
        "INTERCEPTION": player.defensive_actions.interceptions,
        "TACKLE": player.defensive_actions.tackles,
    }
    event_types = _sequence(position.get("event_types"), "defensive_contributions.event_types")
    if not all(isinstance(item, str) and item in counts for item in event_types):
        raise RulesIntegrityError("RULESET_DEFENSIVE_EVENTS", "defensive event type is unsupported")
    total_events = sum(counts[cast(str, item)] for item in event_types)
    threshold = _integer(position.get("threshold"), "defensive_contributions.threshold")
    if total_events < threshold:
        return 0
    return min(
        _integer(position.get("points"), "defensive_contributions.points"),
        _integer(position.get("max_points"), "defensive_contributions.max_points"),
    )


def _components(ruleset: CompiledRuleset, player: PlayerScenario) -> tuple[dict[str, int], int]:
    scoring = _mapping(ruleset.rules.get("scoring"), "scoring")
    participation = scoring.get("participation")
    if participation is not None:
        expected = {
            "appearance_eligibility": "OFFICIAL_MINUTES_GREATER_THAN_ZERO",
            "bonus_eligibility": "OFFICIAL_MINUTES_GREATER_THAN_ZERO",
            "fixture_scope": True,
            "minute_basis": "OFFICIAL_MINUTES_EXCLUDING_STOPPAGE_TIME",
            "position_basis": "TARGET_SEASON_FPL_POSITION",
            "reject_unmapped_position": True,
        }
        if _mapping(participation, "scoring.participation") != expected:
            raise RulesIntegrityError(
                "RULESET_PARTICIPATION_INVALID", "compiled participation policy is unsupported"
            )
    conceded = _effective_conceded(player, scoring)
    appearance = _appearance(_mapping(scoring.get("appearance"), "appearance"), player.minutes)
    goals_config = _mapping(scoring.get("goals"), "goals")
    goal_points = _mapping(goals_config.get("points_by_position"), "goals.points_by_position")
    goals = (player.goals_non_penalty + player.goals_penalty) * _integer(
        goal_points.get(player.position.value), "goals.position"
    )
    assists = player.eligible_assists * _integer(
        _mapping(ruleset.rules.get("assists"), "assists").get("points"), "assists.points"
    )
    clean_config = _mapping(scoring.get("clean_sheets"), "clean_sheets")
    clean_points = _mapping(
        clean_config.get("points_by_position"), "clean_sheets.points_by_position"
    )
    clean_eligible = (
        player.minutes
        >= _integer(clean_config.get("min_minutes_inclusive"), "clean_sheets.min_minutes")
        and conceded == 0
    )
    clean_sheet = (
        _integer(clean_points.get(player.position.value), "clean_sheets.position")
        if clean_eligible
        else 0
    )
    saves_config = _mapping(scoring.get("goalkeeper_saves"), "goalkeeper_saves")
    saves = (
        player.saves
        // _integer(saves_config.get("saves_per_point"), "goalkeeper_saves.saves_per_point")
    ) * _integer(saves_config.get("points_per_group"), "goalkeeper_saves.points_per_group")
    cap = saves_config.get("cap_per_fixture")
    if cap is not None:
        saves = min(saves, _integer(cap, "goalkeeper_saves.cap_per_fixture"))
    penalties = _mapping(scoring.get("penalties"), "penalties")
    penalty_saves = player.penalty_saves * _integer(
        penalties.get("save_points"), "penalties.save_points"
    )
    penalty_misses = player.penalty_misses * _integer(
        penalties.get("miss_points"), "penalties.miss_points"
    )
    cards = _mapping(scoring.get("cards"), "cards")
    yellow_cards = player.yellow_cards * _integer(cards.get("yellow_points"), "cards.yellow_points")
    red_cards = player.red_cards * _integer(cards.get("red_points"), "cards.red_points")
    own_goals = player.own_goals * _integer(
        _mapping(scoring.get("own_goals"), "own_goals").get("points"), "own_goals.points"
    )
    goals_conceded_config = _mapping(scoring.get("goals_conceded"), "goals_conceded")
    positions = _sequence(goals_conceded_config.get("positions"), "goals_conceded.positions")
    goals_conceded = 0
    if player.position.value in positions:
        goals_conceded = (
            conceded
            // _integer(goals_conceded_config.get("goals_per_deduction"), "goals_conceded.group")
        ) * _integer(goals_conceded_config.get("points_per_group"), "goals_conceded.points")
    defensive = _defensive_contribution(
        player, _mapping(scoring.get("defensive_contributions"), "defensive_contributions")
    )
    components = {
        "appearance": appearance,
        "assists": assists,
        "clean_sheet": clean_sheet,
        "defensive_contributions": defensive,
        "goals": goals,
        "goals_conceded": goals_conceded,
        "own_goals": own_goals,
        "penalty_misses": penalty_misses,
        "penalty_saves": penalty_saves,
        "red_cards": red_cards,
        "saves": saves,
        "yellow_cards": yellow_cards,
    }
    return components, calculate_bps(
        ruleset,
        player,
        clean_sheet_eligible=clean_eligible,
        goals_conceded=conceded,
    )


def validate_scenario_ruleset_identity(
    ruleset: CompiledRuleset,
    *,
    ruleset_id: str | None,
    ruleset_version: str | None,
    ruleset_hash: str | None,
) -> None:
    """Reject an explicit scenario binding that differs from the selected artifact."""

    supplied = (ruleset_id, ruleset_version, ruleset_hash)
    expected = (ruleset.ruleset_id, ruleset.ruleset_version, ruleset.ruleset_hash)
    if any(value is not None for value in supplied) and supplied != expected:
        raise RulesValidationError(
            "RULESET_SCENARIO_MISMATCH",
            "scenario ruleset identity does not match the selected artifact",
        )


def ensure_ruleset_scoring_allowed(ruleset: CompiledRuleset) -> None:
    """Validate artifact integrity and lifecycle before any scoring path."""

    ensure_compiled_ruleset_integrity(ruleset)
    if ruleset.schema_version == "1.1":
        from dmf_pulse.rules.capabilities import compile_capability_artifact
        from dmf_pulse.rules.models import RuleCapability

        player_points = compile_capability_artifact(ruleset, RuleCapability.PLAYER_POINTS)
        if player_points.production_eligible:
            return
    if ruleset.unknown_blockers:
        raise RulesValidationError(
            "RULESET_SCORING_BLOCKED",
            "ruleset has unresolved required scoring values",
            blockers=ruleset.unknown_blockers,
        )
    if ruleset.status not in {
        RulesetStatus.REFERENCE_ONLY,
        RulesetStatus.VERIFIED,
        RulesetStatus.ACTIVE,
    }:
        raise RulesValidationError(
            "RULESET_SCORING_BLOCKED", "ruleset lifecycle status does not permit scoring"
        )


def score_fixture(ruleset: CompiledRuleset, scenario: FixtureScenario) -> FixtureScoreResult:
    """Score a coherent fixture without I/O or mutable global state."""

    ensure_ruleset_scoring_allowed(ruleset)
    if ruleset.schema_version == "1.1":
        for player in scenario.players:
            validate_v11_save_contract(player)
    validate_scenario_ruleset_identity(
        ruleset,
        ruleset_id=scenario.ruleset_id,
        ruleset_version=scenario.ruleset_version,
        ruleset_hash=scenario.ruleset_hash,
    )
    calculated = {player.player_id: _components(ruleset, player) for player in scenario.players}
    eligible_bps = {
        player.player_id: calculated[player.player_id][1]
        for player in scenario.players
        if player.minutes > 0
    }
    bonus = allocate_bonus(eligible_bps, _bonus_rank_awards(ruleset))
    players: dict[str, PlayerScore] = {}
    for player in sorted(scenario.players, key=lambda item: item.player_id):
        components, bps = calculated[player.player_id]
        award = bonus.get(player.player_id, 0)
        players[player.player_id] = PlayerScore(
            **components,
            bonus=award,
            bps=bps,
            total=sum(components.values()) + award,
        )
    return FixtureScoreResult(
        away_goals=scenario.away_goals,
        fixture_id=scenario.fixture_id,
        gameweek_id=scenario.gameweek_id,
        home_goals=scenario.home_goals,
        players=players,
        ruleset_hash=ruleset.ruleset_hash,
        ruleset_id=ruleset.ruleset_id,
        ruleset_version=ruleset.ruleset_version,
        sum_player_totals=sum(player.total for player in players.values()),
    )
