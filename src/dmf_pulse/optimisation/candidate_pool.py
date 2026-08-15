"""Lazy candidate and squad enumeration with conservative integer preflight."""

from __future__ import annotations

from collections.abc import Iterator
from itertools import combinations, product
from math import comb

from dmf_pulse.fpl_points.models import PlayerPosition
from dmf_pulse.optimisation.errors import InfeasibleError, ResourceLimitError
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidatePoolSnapshot,
    CandidateSquad,
    OneGameweekOptimisationRequest,
    OneGameweekOptimiserPolicy,
    OneGameweekRulesView,
    SearchScope,
)


def snapshot_hash(snapshot: CandidatePoolSnapshot) -> str:
    from dmf_pulse.fpl_points.artifacts import semantic_sha256

    payload = snapshot.model_dump(mode="json")
    payload["candidate_snapshot_sha256"] = None
    return semantic_sha256(payload)


def _by_position(
    snapshot: CandidatePoolSnapshot,
) -> dict[PlayerPosition, tuple[CandidatePlayer, ...]]:
    return {
        position: tuple(item for item in snapshot.candidates if item.position is position)
        for position in PlayerPosition
    }


def conservative_squad_upper_bound(
    request: OneGameweekOptimisationRequest, rules: OneGameweekRulesView
) -> int:
    if request.search_scope is SearchScope.FIXED_SQUAD:
        return 1
    if request.search_scope is SearchScope.PROVIDED_SQUADS:
        return len(request.provided_squads)
    grouped = _by_position(request.candidate_pool)
    count = 1
    for position, quota in rules.position_squad_quota.items():
        count *= comb(len(grouped[position]), quota) if len(grouped[position]) >= quota else 0
    return count


def _validate_squad(
    squad: CandidateSquad,
    snapshot: CandidatePoolSnapshot,
    rules: OneGameweekRulesView,
    request: OneGameweekOptimisationRequest,
) -> None:
    known = {candidate.player_id: candidate for candidate in snapshot.candidates}
    if any(player not in known for player in squad.player_ids):
        raise InfeasibleError("squad contains a player outside the declared candidate snapshot")
    if len(squad.player_ids) != rules.squad_size:
        raise InfeasibleError("squad size does not match compiled rules")
    if set(request.required_player_ids) - set(squad.player_ids):
        raise InfeasibleError("squad omits a required player")
    if set(request.excluded_player_ids) & set(squad.player_ids):
        raise InfeasibleError("squad contains an excluded player")
    for position, quota in rules.position_squad_quota.items():
        if sum(known[player].position is position for player in squad.player_ids) != quota:
            raise InfeasibleError("squad position quotas are not legal")
    if rules.max_players_per_club is not None:
        for club in {known[player].club_id for player in squad.player_ids}:
            if (
                sum(known[player].club_id == club for player in squad.player_ids)
                > rules.max_players_per_club
            ):
                raise InfeasibleError("squad exceeds the compiled club cap")
    if request.search_scope is SearchScope.BOUNDED_PLAYER_POOL:
        costs = [known[player].initial_selection_cost_tenths for player in squad.player_ids]
        if any(cost is None for cost in costs) or rules.initial_budget_tenths is None:
            raise InfeasibleError("bounded player pool requires complete costs and budget")
        if sum(cost for cost in costs if cost is not None) > rules.initial_budget_tenths:
            raise InfeasibleError("squad exceeds the compiled initial budget")


def enumerate_squads(
    request: OneGameweekOptimisationRequest,
    rules: OneGameweekRulesView,
    policy: OneGameweekOptimiserPolicy,
) -> tuple[Iterator[CandidateSquad], int]:
    upper = conservative_squad_upper_bound(request, rules)
    if upper > policy.max_squad_candidates:
        raise ResourceLimitError(f"conservative squad upper bound {upper} exceeds cap")
    snapshot = request.candidate_pool
    if request.search_scope is SearchScope.FIXED_SQUAD:
        assert request.fixed_squad is not None
        _validate_squad(request.fixed_squad, snapshot, rules, request)
        return iter((request.fixed_squad,)), upper
    if request.search_scope is SearchScope.PROVIDED_SQUADS:
        for squad in request.provided_squads:
            _validate_squad(squad, snapshot, rules, request)
        return iter(request.provided_squads), upper
    grouped = _by_position(snapshot)
    choices = [
        tuple(combinations(grouped[position], rules.position_squad_quota[position]))
        for position in PlayerPosition
    ]

    def generator() -> Iterator[CandidateSquad]:
        for selected in product(*choices):
            players = tuple(sorted(item.player_id for group in selected for item in group))
            squad = CandidateSquad(
                player_ids=players,
                initial_selection_cost_tenths=sum(
                    item.initial_selection_cost_tenths or 0 for group in selected for item in group
                ),
            )
            try:
                _validate_squad(squad, snapshot, rules, request)
            except InfeasibleError:
                continue
            yield squad

    return generator(), upper
