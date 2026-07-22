"""Configuration-driven Bonus Points System calculation."""

from __future__ import annotations

from typing import cast

from dmf_pulse.rules.errors import RulesIntegrityError
from dmf_pulse.rules.models import CompiledRuleset, FPLPosition, PlayerScenario


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


def _appearance_bps(config: dict[str, object], minutes: int) -> int:
    if minutes == 0:
        return 0
    matches: list[int] = []
    for raw_band in _sequence(config.get("appearance_bands"), "bps.appearance_bands"):
        band = _mapping(raw_band, "bps.appearance_bands[]")
        minimum = band.get("min_inclusive")
        minimum_exclusive = band.get("min_exclusive")
        maximum = band.get("max_inclusive")
        lower_ok = (
            minutes >= _integer(minimum, "appearance.min_inclusive")
            if minimum is not None
            else minutes > _integer(minimum_exclusive, "appearance.min_exclusive")
        )
        upper_ok = maximum is None or minutes <= _integer(maximum, "appearance.max_inclusive")
        if lower_ok and upper_ok:
            matches.append(_integer(band.get("bps"), "appearance.bps"))
    if len(matches) != 1:
        raise RulesIntegrityError(
            "RULESET_APPEARANCE_BANDS", "appearance BPS bands are not exclusive"
        )
    return matches[0]


def _pass_bps(config: dict[str, object], player: PlayerScenario) -> int:
    pass_config = _mapping(config.get("pass_completion"), "bps.pass_completion")
    attempts = player.bps.pass_attempts
    if attempts < _integer(pass_config.get("min_attempts"), "pass_completion.min_attempts"):
        return 0
    completed = player.bps.passes_completed
    matches: list[int] = []
    for raw_band in _sequence(pass_config.get("bands"), "pass_completion.bands"):
        band = _mapping(raw_band, "pass_completion.bands[]")
        minimum = _integer(band.get("min_pct_inclusive"), "pass_completion.min_pct")
        maximum_exclusive = band.get("max_pct_exclusive")
        maximum_inclusive = band.get("max_pct_inclusive")
        lower_ok = completed * 100 >= minimum * attempts
        upper_ok = True
        if maximum_exclusive is not None:
            upper_ok = (
                completed * 100 < _integer(maximum_exclusive, "pass_completion.max_pct") * attempts
            )
        elif maximum_inclusive is not None:
            upper_ok = (
                completed * 100 <= _integer(maximum_inclusive, "pass_completion.max_pct") * attempts
            )
        if lower_ok and upper_ok:
            matches.append(_integer(band.get("bps"), "pass_completion.bps"))
    if len(matches) > 1:
        raise RulesIntegrityError("RULESET_PASS_BANDS", "pass-completion bands overlap")
    return matches[0] if matches else 0


def calculate_bps(
    ruleset: CompiledRuleset,
    player: PlayerScenario,
    *,
    clean_sheet_eligible: bool,
    goals_conceded: int,
) -> int:
    """Calculate one participant's BPS entirely from compiled configuration."""

    if player.minutes == 0:
        return 0
    bonus = _mapping(ruleset.rules.get("bonus"), "bonus")
    config = _mapping(bonus.get("bps"), "bonus.bps")
    total = _appearance_bps(config, player.minutes)
    goals = _mapping(config.get("goals"), "bps.goals")
    total += player.goals_penalty * _integer(
        _mapping(goals.get("penalty_direct"), "bps.goals.penalty_direct").get("bps"),
        "bps.goals.penalty_direct.bps",
    )
    by_position = _mapping(
        goals.get("non_penalty_by_position"), "bps.goals.non_penalty_by_position"
    )
    total += player.goals_non_penalty * _integer(
        by_position.get(player.position.value), "bps.goal.position"
    )
    total += player.eligible_assists * _integer(config.get("assist"), "bps.assist")
    clean = _mapping(config.get("clean_sheet"), "bps.clean_sheet")
    clean_positions = _sequence(clean.get("positions"), "bps.clean_sheet.positions")
    if (
        clean_sheet_eligible
        and player.position.value in clean_positions
        and player.minutes >= _integer(clean.get("min_minutes"), "bps.clean_sheet.min_minutes")
    ):
        total += _integer(clean.get("bps"), "bps.clean_sheet.bps")
    total += player.penalty_saves * _integer(config.get("penalty_save"), "bps.penalty_save")
    total += player.bps.saves_inside_box * _integer(
        config.get("save_inside_box"), "bps.save_inside_box"
    )
    total += player.bps.saves_outside_box * _integer(
        config.get("save_outside_box"), "bps.save_outside_box"
    )
    positive = (
        (player.bps.successful_open_play_crosses, "successful_open_play_cross"),
        (player.bps.big_chances_created, "big_chance_created"),
        (player.bps.key_passes, "key_pass"),
        (player.bps.successful_tackles, "successful_tackle"),
        (player.bps.successful_dribbles, "successful_dribble"),
        (player.bps.match_winning_goals, "match_winning_goal"),
        (player.bps.goal_line_clearances, "goal_line_clearance"),
        (player.bps.fouls_won, "foul_won"),
        (player.bps.shots_on_target, "shot_on_target"),
    )
    total += sum(count * _integer(config.get(key), f"bps.{key}") for count, key in positive)
    cbi = (
        player.defensive_actions.clearances
        + player.defensive_actions.blocks
        + player.defensive_actions.interceptions
    )
    cbi_group = _mapping(config.get("cbi_group"), "bps.cbi_group")
    total += (cbi // _integer(cbi_group.get("group_size"), "bps.cbi_group.group_size")) * _integer(
        cbi_group.get("bps_per_group"), "bps.cbi_group.bps_per_group"
    )
    recovery_group = _mapping(config.get("recovery_group"), "bps.recovery_group")
    total += (
        player.bps.recoveries
        // _integer(recovery_group.get("group_size"), "bps.recovery_group.group_size")
    ) * _integer(recovery_group.get("bps_per_group"), "bps.recovery_group.bps_per_group")
    total += _pass_bps(config, player)
    negatives = _mapping(config.get("negatives"), "bps.negatives")
    if player.position in {FPLPosition.GK, FPLPosition.DEF}:
        total += goals_conceded * _integer(
            negatives.get("goal_conceded_gk_def"), "bps.negatives.goal_conceded"
        )
    negative = (
        (player.bps.penalties_conceded, "penalty_conceded"),
        (player.penalty_misses, "penalty_miss"),
        (player.yellow_cards, "yellow"),
        (player.red_cards, "red"),
        (player.own_goals, "own_goal"),
        (player.bps.big_chances_missed, "big_chance_missed"),
        (player.bps.errors_leading_goal, "error_leading_goal"),
        (player.bps.errors_leading_attempt, "error_leading_attempt"),
        (player.bps.times_tackled, "being_tackled"),
        (player.bps.fouls_conceded, "foul_conceded"),
        (player.bps.offsides, "offside"),
        (player.bps.shots_off_target, "shot_off_target"),
    )
    total += sum(
        count * _integer(negatives.get(key), f"bps.negatives.{key}") for count, key in negative
    )
    return total
