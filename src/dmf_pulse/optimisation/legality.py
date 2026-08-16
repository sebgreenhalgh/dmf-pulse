"""Independent structural legality validator (no solver or candidate enumeration imports)."""

from __future__ import annotations

from dmf_pulse.fpl_points.models import PlayerPosition
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidateSquad,
    LegalityIssue,
    LegalityReport,
    OneGameweekRulesView,
    TacticalConfiguration,
)


def validate_squad_legality(
    squad: CandidateSquad,
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
    *,
    required_player_ids: tuple[str, ...] = (),
    excluded_player_ids: tuple[str, ...] = (),
    stage9_player_ids: tuple[str, ...] | None = None,
    enforce_budget: bool = False,
) -> LegalityReport:
    issues: list[LegalityIssue] = []
    if len(squad.player_ids) != rules.squad_size:
        issues.append(LegalityIssue(code="SQUAD_SIZE", message="squad size is illegal"))
    if len(set(squad.player_ids)) != len(squad.player_ids):
        issues.append(
            LegalityIssue(code="DUPLICATE_PLAYER", message="squad contains duplicate players")
        )
    for player_id in squad.player_ids:
        if player_id not in players:
            issues.append(
                LegalityIssue(
                    code="UNKNOWN_PLAYER",
                    message="squad references unknown player",
                    player_ids=(player_id,),
                )
            )
        elif stage9_player_ids is not None and player_id not in set(stage9_player_ids):
            issues.append(
                LegalityIssue(
                    code="STAGE9_PLAYER_UNIVERSE",
                    message="squad player is outside the accepted Stage-9 universe",
                    player_ids=(player_id,),
                )
            )
    missing_required = tuple(sorted(set(required_player_ids) - set(squad.player_ids)))
    if missing_required:
        issues.append(
            LegalityIssue(
                code="REQUIRED_PLAYER_MISSING",
                message="squad omits a required player",
                player_ids=missing_required,
            )
        )
    included_excluded = tuple(sorted(set(excluded_player_ids) & set(squad.player_ids)))
    if included_excluded:
        issues.append(
            LegalityIssue(
                code="EXCLUDED_PLAYER_INCLUDED",
                message="squad contains an excluded player",
                player_ids=included_excluded,
            )
        )
    for position, quota in rules.position_squad_quota.items():
        count = sum(
            player_id in players and players[player_id].position is position
            for player_id in squad.player_ids
        )
        if count != quota:
            issues.append(
                LegalityIssue(
                    code="SQUAD_POSITION_QUOTA", message=f"illegal {position} squad quota"
                )
            )
    if rules.max_players_per_club is not None:
        for club in {players[player].club_id for player in squad.player_ids if player in players}:
            if (
                sum(
                    player in players and players[player].club_id == club
                    for player in squad.player_ids
                )
                > rules.max_players_per_club
            ):
                issues.append(LegalityIssue(code="CLUB_CAP", message="club cap exceeded"))
    if enforce_budget:
        costs = [
            players[player_id].initial_selection_cost_tenths
            for player_id in squad.player_ids
            if player_id in players
        ]
        if (
            rules.initial_budget_tenths is None
            or len(costs) != len(squad.player_ids)
            or any(cost is None for cost in costs)
        ):
            issues.append(
                LegalityIssue(
                    code="BUDGET_INPUT_UNAVAILABLE",
                    message="bounded player pool requires complete initial costs and a compiled budget",
                )
            )
        elif sum(cost for cost in costs if cost is not None) > rules.initial_budget_tenths:
            issues.append(
                LegalityIssue(code="BUDGET_CAP", message="compiled initial budget exceeded")
            )
    return LegalityReport(legal=not issues, issues=tuple(issues))


def validate_tactical_configuration(
    squad: CandidateSquad,
    tactic: TacticalConfiguration,
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
) -> LegalityReport:
    issues: list[LegalityIssue] = []
    squad_ids = set(squad.player_ids)
    designated = (
        set(tactic.starting_xi) | {tactic.bench_goalkeeper} | set(tactic.outfield_bench_order)
    )
    if designated != squad_ids:
        issues.append(
            LegalityIssue(
                code="TACTIC_SQUAD_MISMATCH", message="tactic does not designate the complete squad"
            )
        )
    all_designations = (*tactic.starting_xi, tactic.bench_goalkeeper, *tactic.outfield_bench_order)
    if len(all_designations) != len(set(all_designations)):
        issues.append(
            LegalityIssue(code="TACTIC_DUPLICATE_PLAYER", message="tactic duplicates a player")
        )
    if len(tactic.starting_xi) != rules.starting_size:
        issues.append(LegalityIssue(code="XI_SIZE", message="starting XI size is illegal"))
    if len(tactic.outfield_bench_order) != rules.bench_size - 1:
        issues.append(LegalityIssue(code="BENCH_SIZE", message="outfield bench size is illegal"))
    if (
        tactic.bench_goalkeeper in players
        and players[tactic.bench_goalkeeper].position is not PlayerPosition.GK
    ):
        issues.append(
            LegalityIssue(code="BENCH_GK", message="bench goalkeeper is not a goalkeeper")
        )
    if tactic.bench_goalkeeper not in squad_ids:
        issues.append(
            LegalityIssue(
                code="BENCH_GK_OUTSIDE_SQUAD", message="bench goalkeeper is outside squad"
            )
        )
    if any(player not in squad_ids for player in tactic.starting_xi):
        issues.append(
            LegalityIssue(code="XI_OUTSIDE_SQUAD", message="starting XI is outside squad")
        )
    if any(player not in squad_ids for player in tactic.outfield_bench_order):
        issues.append(
            LegalityIssue(code="BENCH_OUTSIDE_SQUAD", message="outfield bench is outside squad")
        )
    counts = {
        position: sum(
            player in players and players[player].position is position
            for player in tactic.starting_xi
        )
        for position in PlayerPosition
    }
    if counts[PlayerPosition.GK] != 1:
        issues.append(
            LegalityIssue(
                code="STARTING_GK", message="starting XI must contain exactly one goalkeeper"
            )
        )
    if any(
        player in players and players[player].position is PlayerPosition.GK
        for player in tactic.outfield_bench_order
    ):
        issues.append(
            LegalityIssue(code="OUTFIELD_BENCH_GK", message="outfield bench contains a goalkeeper")
        )
    for position in PlayerPosition:
        if (
            counts[position] < rules.lineup_min[position]
            or counts[position] > rules.lineup_max[position]
        ):
            issues.append(
                LegalityIssue(
                    code="FORMATION", message=f"starting formation violates {position} bounds"
                )
            )
    if tactic.captain not in tactic.starting_xi or tactic.vice_captain not in tactic.starting_xi:
        issues.append(LegalityIssue(code="CAPTAIN_START", message="captain and vice must start"))
    if tactic.captain == tactic.vice_captain:
        issues.append(
            LegalityIssue(code="CAPTAIN_DISTINCT", message="captain and vice must differ")
        )
    return LegalityReport(legal=not issues, issues=tuple(issues))
