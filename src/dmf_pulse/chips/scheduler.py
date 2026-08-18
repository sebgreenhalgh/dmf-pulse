"""Transparent finite-inventory chip scheduling.

Small state spaces are solved by exhaustive dynamic programming. Larger spaces
use a deterministic bounded beam with finite-state optimistic bounds. The
executable decision is always the root action; later activations are advisory
and must be re-solved by the replay/service layer.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations
from math import comb

from dmf_pulse.chips.definitions import semantic_sha256
from dmf_pulse.chips.inventory import TokenStatus
from dmf_pulse.chips.schedule_models import (
    ChipScheduleCandidate,
    ChipScheduleOpportunity,
    ChipSchedulePolicy,
    ChipScheduleRequest,
    PerfectInformationUpperBound,
    ProbabilityNowOptimalDiagnostic,
    RootScheduleAction,
    ScheduledActivation,
    ScheduleObjectiveMode,
    ScheduleScenarioOutcome,
    ScheduleSearchDiagnostics,
    ScheduleSearchMethod,
    TokenDisposition,
    TokenDispositionKind,
)

_TOLERANCE = 1e-9


@dataclass(frozen=True)
class _Occupancy:
    start: int
    end: int
    concurrency_group: str
    token_id: str
    chip_key: str


@dataclass(frozen=True)
class _SearchState:
    selected_ids: tuple[str, ...]
    used_token_ids: frozenset[str]
    occupancies: tuple[_Occupancy, ...]
    gross: tuple[float, ...]
    continuation: tuple[float, ...]
    policy_cost: tuple[float, ...]
    net: tuple[float, ...]
    cash: tuple[float, ...]
    terminal: tuple[float, ...]
    robust_penalty: float


@dataclass
class _Counters:
    explored: int = 0
    pruned: int = 0
    memo_hits: int = 0


@dataclass(frozen=True)
class _SearchResult:
    states: tuple[_SearchState, ...]
    method: ScheduleSearchMethod
    estimated_state_space: int
    counters: _Counters


def _verify_hashes(request: ChipScheduleRequest) -> None:
    expected_request = semantic_sha256(request.model_dump(mode="json", exclude={"request_hash"}))
    if request.request_hash != expected_request:
        raise ValueError("chip schedule request semantic hash mismatch")
    inventory_payload = request.inventory.model_dump(mode="json", exclude={"inventory_hash"})
    if request.inventory.inventory_hash != semantic_sha256(inventory_payload):
        raise ValueError("chip inventory semantic hash mismatch")
    for opportunity in request.opportunities:
        payload = opportunity.model_dump(mode="json", exclude={"opportunity_hash"})
        if opportunity.opportunity_hash != semantic_sha256(payload):
            raise ValueError(
                f"chip schedule opportunity semantic hash mismatch: {opportunity.opportunity_id}"
            )


def _overlaps(left: _Occupancy, right: _Occupancy) -> bool:
    return left.start <= right.end and right.start <= left.end


def _existing_occupancies(request: ChipScheduleRequest) -> tuple[_Occupancy, ...]:
    values: list[_Occupancy] = []
    for token in request.inventory.tokens:
        if token.status is not TokenStatus.ACTIVE:
            continue
        if token.active_from_gameweek is None or token.active_until_gameweek is None:
            raise ValueError("active inventory token lacks an occupied interval")
        values.append(
            _Occupancy(
                start=token.active_from_gameweek,
                end=token.active_until_gameweek,
                concurrency_group=token.concurrency_group,
                token_id=token.token_id,
                chip_key=token.chip_key,
            )
        )
    return tuple(sorted(values, key=lambda item: (item.start, item.end, item.token_id)))


def _empty_state(request: ChipScheduleRequest) -> _SearchState:
    count = len(request.scenario_universe)
    zeros = tuple(0.0 for _ in range(count))
    return _SearchState(
        selected_ids=(),
        used_token_ids=frozenset(),
        occupancies=_existing_occupancies(request),
        gross=zeros,
        continuation=zeros,
        policy_cost=zeros,
        net=zeros,
        cash=zeros,
        terminal=zeros,
        robust_penalty=0.0,
    )


def _action_bundle_count(candidate_count: int, concurrency_limit: int) -> int:
    maximum = min(candidate_count, concurrency_limit)
    return 1 + sum(comb(candidate_count, size) for size in range(1, maximum + 1))


def estimate_state_space(request: ChipScheduleRequest) -> int:
    """Return a capped deterministic upper estimate of schedule action paths."""

    counts: dict[int, int] = defaultdict(int)
    for opportunity in request.opportunities:
        counts[opportunity.activation_gameweek] += 1
    threshold = request.objective.exact_state_threshold
    estimate = 1
    for gameweek in sorted(counts):
        estimate *= _action_bundle_count(counts[gameweek], request.inventory.concurrency_limit)
        if estimate > threshold:
            return threshold + 1
    return max(1, estimate)


def _opportunities_by_gameweek(
    request: ChipScheduleRequest,
) -> tuple[tuple[int, tuple[ChipScheduleOpportunity, ...]], ...]:
    grouped: dict[int, list[ChipScheduleOpportunity]] = defaultdict(list)
    for opportunity in request.opportunities:
        grouped[opportunity.activation_gameweek].append(opportunity)
    return tuple(
        (
            gameweek,
            tuple(
                sorted(
                    values,
                    key=lambda item: (
                        item.chip_key,
                        item.token_id,
                        item.opportunity_id,
                    ),
                )
            ),
        )
        for gameweek, values in sorted(grouped.items())
    )


def _bundle_signature(bundle: Sequence[ChipScheduleOpportunity]) -> tuple[str, ...]:
    return tuple(item.opportunity_id for item in bundle)


def _full_action_bundles(
    opportunities: tuple[ChipScheduleOpportunity, ...],
    *,
    concurrency_limit: int,
) -> tuple[tuple[ChipScheduleOpportunity, ...], ...]:
    bundles: list[tuple[ChipScheduleOpportunity, ...]] = [()]
    maximum = min(len(opportunities), concurrency_limit)
    for size in range(1, maximum + 1):
        bundles.extend(combinations(opportunities, size))
    return tuple(sorted(bundles, key=lambda item: (len(item), _bundle_signature(item))))


def _beam_action_bundles(
    opportunities: tuple[ChipScheduleOpportunity, ...],
    request: ChipScheduleRequest,
) -> tuple[tuple[ChipScheduleOpportunity, ...], ...]:
    """Generate a deterministic bounded branch set without exponential suffix work."""

    limit = request.objective.beam_branch_limit
    concurrency = request.inventory.concurrency_limit
    ranked = tuple(
        sorted(
            opportunities,
            key=lambda item: (
                -item.optimistic_upper_bound,
                item.chip_key,
                item.token_id,
                item.opportunity_id,
            ),
        )
    )
    candidate_cap = min(len(ranked), max(concurrency, min(16, limit)))
    shortlist = ranked[:candidate_cap]
    generated: list[tuple[ChipScheduleOpportunity, ...]] = [()]
    maximum = min(len(shortlist), concurrency)
    for size in range(1, maximum + 1):
        generated.extend(combinations(shortlist, size))
    ordered = sorted(
        generated,
        key=lambda bundle: (
            -sum(item.optimistic_upper_bound for item in bundle),
            len(bundle),
            _bundle_signature(bundle),
        ),
    )
    retained = ordered[:limit]
    if () not in retained:
        retained[-1:] = [()]
    return tuple(sorted(set(retained), key=lambda item: (len(item), _bundle_signature(item))))


def _prior_end_for_chip(
    state: _SearchState,
    request: ChipScheduleRequest,
    chip_key: str,
) -> int | None:
    ends = [item.end for item in state.occupancies if item.chip_key == chip_key]
    for token in request.inventory.tokens:
        if token.chip_key == chip_key and token.used_at_gameweek is not None:
            ends.append(token.used_at_gameweek)
    return max(ends) if ends else None


def _legal_add(
    state: _SearchState,
    opportunity: ChipScheduleOpportunity,
    request: ChipScheduleRequest,
    *,
    opportunity_map: dict[str, ChipScheduleOpportunity],
) -> bool:
    del opportunity_map
    if opportunity.token_id in state.used_token_ids:
        return False
    selected = set(state.selected_ids)
    if not set(opportunity.requires_prior_opportunity_ids) <= selected:
        return False
    if set(opportunity.forbids_prior_opportunity_ids) & selected:
        return False
    token = request.inventory.token(opportunity.token_id)
    candidate = _Occupancy(
        start=opportunity.activation_gameweek,
        end=opportunity.activation_gameweek + opportunity.duration_gameweeks - 1,
        concurrency_group=token.concurrency_group,
        token_id=token.token_id,
        chip_key=token.chip_key,
    )
    overlapping = tuple(item for item in state.occupancies if _overlaps(item, candidate))
    if any(item.concurrency_group == candidate.concurrency_group for item in overlapping):
        return False
    for gameweek in range(candidate.start, candidate.end + 1):
        occupied = sum(item.start <= gameweek <= item.end for item in state.occupancies)
        if occupied >= request.inventory.concurrency_limit:
            return False
    prior_end = _prior_end_for_chip(state, request, opportunity.chip_key)
    return not (
        prior_end is not None and candidate.start - prior_end <= token.minimum_gap_gameweeks
    )


def _add_opportunity(
    state: _SearchState,
    opportunity: ChipScheduleOpportunity,
    request: ChipScheduleRequest,
    *,
    opportunity_map: dict[str, ChipScheduleOpportunity],
) -> _SearchState | None:
    if not _legal_add(state, opportunity, request, opportunity_map=opportunity_map):
        return None
    token = request.inventory.token(opportunity.token_id)
    occupancy = _Occupancy(
        start=opportunity.activation_gameweek,
        end=opportunity.activation_gameweek + opportunity.duration_gameweeks - 1,
        concurrency_group=token.concurrency_group,
        token_id=token.token_id,
        chip_key=token.chip_key,
    )

    def add_values(
        current: tuple[float, ...],
        values: Iterable[float],
    ) -> tuple[float, ...]:
        return tuple(left + right for left, right in zip(current, values, strict=True))

    scenarios = opportunity.scenario_values
    return _SearchState(
        selected_ids=(*state.selected_ids, opportunity.opportunity_id),
        used_token_ids=state.used_token_ids | {opportunity.token_id},
        occupancies=tuple(
            sorted(
                (*state.occupancies, occupancy),
                key=lambda item: (item.start, item.end, item.token_id),
            )
        ),
        gross=add_values(state.gross, (item.gross_current_gain for item in scenarios)),
        continuation=add_values(
            state.continuation, (item.continuation_value for item in scenarios)
        ),
        policy_cost=add_values(state.policy_cost, (item.policy_cost for item in scenarios)),
        net=add_values(state.net, (item.net_policy_value for item in scenarios)),
        cash=add_values(state.cash, (item.cash_like_value for item in scenarios)),
        terminal=add_values(state.terminal, (item.terminal_state_value for item in scenarios)),
        robust_penalty=state.robust_penalty + opportunity.robust_penalty,
    )


def _apply_bundle(
    state: _SearchState,
    bundle: tuple[ChipScheduleOpportunity, ...],
    request: ChipScheduleRequest,
    *,
    opportunity_map: dict[str, ChipScheduleOpportunity],
) -> _SearchState | None:
    result = state
    for opportunity in sorted(bundle, key=lambda item: item.opportunity_id):
        next_state = _add_opportunity(
            result,
            opportunity,
            request,
            opportunity_map=opportunity_map,
        )
        if next_state is None:
            return None
        result = next_state
    return result


def _state_key(index: int, state: _SearchState) -> tuple[object, ...]:
    """Include the complete prefix so same-token route histories never alias."""

    return (
        index,
        state.selected_ids,
        tuple(sorted(state.used_token_ids)),
        tuple(
            (item.start, item.end, item.concurrency_group, item.token_id)
            for item in state.occupancies
        ),
    )


def _exact_search(request: ChipScheduleRequest, estimated: int) -> _SearchResult:
    groups = _opportunities_by_gameweek(request)
    opportunity_map = {item.opportunity_id: item for item in request.opportunities}
    bundles = tuple(
        _full_action_bundles(values, concurrency_limit=request.inventory.concurrency_limit)
        for _, values in groups
    )
    counters = _Counters()
    memo: dict[tuple[object, ...], tuple[_SearchState, ...]] = {}

    def solve(index: int, state: _SearchState) -> tuple[_SearchState, ...]:
        key = _state_key(index, state)
        cached = memo.get(key)
        if cached is not None:
            counters.memo_hits += 1
            return cached
        counters.explored += 1
        if index == len(groups):
            terminal: tuple[_SearchState, ...] = (state,)
            memo[key] = terminal
            return terminal
        completions: list[_SearchState] = []
        for bundle in bundles[index]:
            next_state = _apply_bundle(
                state,
                bundle,
                request,
                opportunity_map=opportunity_map,
            )
            if next_state is None:
                counters.pruned += 1
                continue
            completions.extend(solve(index + 1, next_state))
        result: tuple[_SearchState, ...] = tuple(completions)
        memo[key] = result
        return result

    states = solve(0, _empty_state(request))
    return _SearchResult(
        states=states,
        method=ScheduleSearchMethod.EXACT_DYNAMIC_PROGRAMMING,
        estimated_state_space=estimated,
        counters=counters,
    )


def _partial_expected(state: _SearchState, request: ChipScheduleRequest) -> float:
    return sum(
        scenario.weight * (net + terminal)
        for scenario, net, terminal in zip(
            request.scenario_universe,
            state.net,
            state.terminal,
            strict=True,
        )
    )


def _partial_selected_value(state: _SearchState, request: ChipScheduleRequest) -> float:
    expected = _partial_expected(state, request)
    if request.objective.objective_mode is ScheduleObjectiveMode.EXPECTED:
        return expected
    if request.objective.objective_mode is ScheduleObjectiveMode.ROBUST:
        return expected - request.objective.robust_penalty_weight * state.robust_penalty
    cash_terminal = sum(
        scenario.weight
        * (
            net
            + request.objective.cash_like_weight * cash
            + request.objective.terminal_state_weight * terminal
        )
        for scenario, net, cash, terminal in zip(
            request.scenario_universe,
            state.net,
            state.cash,
            state.terminal,
            strict=True,
        )
    )
    return cash_terminal


def _finite_suffix_bound(
    state: _SearchState,
    groups: tuple[tuple[int, tuple[ChipScheduleOpportunity, ...]], ...],
    index: int,
) -> float:
    by_token: dict[str, float] = {}
    for _, opportunities in groups[index:]:
        for opportunity in opportunities:
            if opportunity.token_id in state.used_token_ids:
                continue
            by_token[opportunity.token_id] = max(
                by_token.get(opportunity.token_id, 0.0),
                opportunity.optimistic_upper_bound,
            )
    return sum(max(0.0, value) for value in by_token.values())


def _beam_state_rank(
    state: _SearchState,
    request: ChipScheduleRequest,
    groups: tuple[tuple[int, tuple[ChipScheduleOpportunity, ...]], ...],
    next_index: int,
) -> tuple[float, float, int, tuple[str, ...]]:
    value = _partial_selected_value(state, request)
    bound = value + _finite_suffix_bound(state, groups, next_index)
    return (
        round(bound, 12),
        round(value, 12),
        -len(state.selected_ids),
        tuple(reversed(state.selected_ids)),
    )


def _beam_comparator_class(
    state: _SearchState,
    request: ChipScheduleRequest,
    opportunity_map: dict[str, ChipScheduleOpportunity],
) -> str:
    if not state.selected_ids:
        return "NEVER_USE"
    if any(
        opportunity_map[item].activation_gameweek == request.horizon_start_gameweek
        for item in state.selected_ids
    ):
        return "USE_NOW"
    return "DELAY"


def _deduplicate_states(
    states: Iterable[_SearchState],
    *,
    index: int,
) -> tuple[_SearchState, ...]:
    unique: dict[tuple[object, ...], _SearchState] = {}
    for state in states:
        unique.setdefault(_state_key(index, state), state)
    return tuple(unique.values())


def _beam_search(request: ChipScheduleRequest, estimated: int) -> _SearchResult:
    groups = _opportunities_by_gameweek(request)
    opportunity_map = {item.opportunity_id: item for item in request.opportunities}
    counters = _Counters()
    baseline = _empty_state(request)
    beam: tuple[_SearchState, ...] = (baseline,)
    comparator_lanes: dict[str, _SearchState] = {"NEVER_USE": baseline}
    seen: set[tuple[object, ...]] = set()
    for index, (_, opportunities) in enumerate(groups):
        bundles = _beam_action_bundles(opportunities, request)
        # Keep a fixed number of comparator lanes outside the main beam. This
        # guarantees that use-now, delay and never-use remain observable while
        # retaining a strictly bounded deterministic frontier.
        frontier = _deduplicate_states(
            (*beam, *comparator_lanes.values()),
            index=index,
        )
        expanded: list[_SearchState] = []
        for state in frontier:
            counters.explored += 1
            for bundle in bundles:
                next_state = _apply_bundle(
                    state,
                    bundle,
                    request,
                    opportunity_map=opportunity_map,
                )
                if next_state is None:
                    counters.pruned += 1
                    continue
                key = _state_key(index + 1, next_state)
                if key in seen:
                    counters.memo_hits += 1
                    continue
                seen.add(key)
                expanded.append(next_state)
        ranked = sorted(
            expanded,
            key=lambda item: _beam_state_rank(item, request, groups, index + 1),
            reverse=True,
        )
        if len(ranked) > request.objective.beam_width:
            counters.pruned += len(ranked) - request.objective.beam_width
        beam = tuple(ranked[: request.objective.beam_width])
        if not beam:
            # HOLD is always generated, so reaching this state indicates a programming error.
            raise RuntimeError("bounded chip scheduler pruned every legal state")

        next_lanes: dict[str, _SearchState] = {}
        for state in expanded:
            category = _beam_comparator_class(state, request, opportunity_map)
            current = next_lanes.get(category)
            if current is None or _candidate_rank(
                _candidate_from_state(state, request)
            ) > _candidate_rank(_candidate_from_state(current, request)):
                next_lanes[category] = state
        comparator_lanes = next_lanes

    final_states = _deduplicate_states(
        (*beam, *comparator_lanes.values(), baseline),
        index=len(groups),
    )
    return _SearchResult(
        states=final_states,
        method=ScheduleSearchMethod.BOUNDED_BEAM,
        estimated_state_space=estimated,
        counters=counters,
    )


def _terminal_value_map(request: ChipScheduleRequest) -> dict[str, object]:
    return {item.token_id: item for item in request.terminal_token_values}


def _token_dispositions(
    state: _SearchState,
    request: ChipScheduleRequest,
    opportunity_map: dict[str, ChipScheduleOpportunity],
) -> tuple[TokenDisposition, ...]:
    selected_by_token = {
        opportunity_map[item].token_id: opportunity_map[item] for item in state.selected_ids
    }
    values: list[TokenDisposition] = []
    for token in sorted(request.inventory.tokens, key=lambda item: item.token_id):
        selected = selected_by_token.get(token.token_id)
        if selected is not None:
            values.append(
                TokenDisposition(
                    token_id=token.token_id,
                    chip_key=token.chip_key,
                    disposition=TokenDispositionKind.SCHEDULED,
                    disposition_gameweek=selected.activation_gameweek,
                )
            )
        elif token.status is TokenStatus.ACTIVE:
            values.append(
                TokenDisposition(
                    token_id=token.token_id,
                    chip_key=token.chip_key,
                    disposition=TokenDispositionKind.ALREADY_ACTIVE,
                    disposition_gameweek=token.active_from_gameweek,
                )
            )
        elif token.status is TokenStatus.USED:
            values.append(
                TokenDisposition(
                    token_id=token.token_id,
                    chip_key=token.chip_key,
                    disposition=TokenDispositionKind.ALREADY_USED,
                    disposition_gameweek=token.used_at_gameweek,
                )
            )
        elif token.status is TokenStatus.EXPIRED:
            values.append(
                TokenDisposition(
                    token_id=token.token_id,
                    chip_key=token.chip_key,
                    disposition=TokenDispositionKind.ALREADY_EXPIRED,
                    disposition_gameweek=token.expires_after_gameweek,
                )
            )
        elif token.expires_after_gameweek <= request.horizon_end_gameweek:
            values.append(
                TokenDisposition(
                    token_id=token.token_id,
                    chip_key=token.chip_key,
                    disposition=TokenDispositionKind.EXPIRE_UNUSED,
                    disposition_gameweek=token.expires_after_gameweek,
                )
            )
        else:
            values.append(
                TokenDisposition(
                    token_id=token.token_id,
                    chip_key=token.chip_key,
                    disposition=TokenDispositionKind.HOLD,
                )
            )
    return tuple(values)


def _root_action(
    activations: tuple[ScheduledActivation, ...],
    dispositions: tuple[TokenDisposition, ...],
    request: ChipScheduleRequest,
) -> tuple[RootScheduleAction, tuple[str, ...]]:
    current = tuple(
        sorted(
            item.opportunity_id
            for item in activations
            if item.activation_gameweek == request.horizon_start_gameweek
        )
    )
    if current:
        return RootScheduleAction.ACTIVATE, current
    future = any(item.activation_gameweek > request.horizon_start_gameweek for item in activations)
    expires_now = any(
        item.disposition is TokenDispositionKind.EXPIRE_UNUSED
        and item.disposition_gameweek == request.horizon_start_gameweek
        for item in dispositions
    )
    if expires_now and not future:
        return RootScheduleAction.EXPIRE_UNUSED, ()
    return RootScheduleAction.HOLD, ()


def _seal_candidate(value: ChipScheduleCandidate) -> ChipScheduleCandidate:
    payload = value.model_dump(mode="json", exclude={"schedule_hash"})
    return ChipScheduleCandidate.model_validate(
        value.model_copy(update={"schedule_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def _candidate_from_state(
    state: _SearchState, request: ChipScheduleRequest
) -> ChipScheduleCandidate:
    opportunity_map = {item.opportunity_id: item for item in request.opportunities}
    selected = tuple(opportunity_map[item] for item in state.selected_ids)
    activations = tuple(
        ScheduledActivation(
            opportunity_id=item.opportunity_id,
            candidate_history_key=item.candidate_history_key,
            token_id=item.token_id,
            chip_key=item.chip_key,
            activation_gameweek=item.activation_gameweek,
            active_until_gameweek=item.activation_gameweek + item.duration_gameweeks - 1,
            expected_gross_current_gain=item.expected_gross_current_gain,
            expected_continuation_value=item.expected_continuation_value,
            expected_policy_cost=item.expected_policy_cost,
            expected_net_policy_value=item.expected_net_policy_value,
            expected_cash_like_value=item.expected_cash_like_value,
            expected_terminal_state_value=item.expected_terminal_state_value,
            robust_penalty=item.robust_penalty,
            opportunity_hash=item.opportunity_hash,
        )
        for item in sorted(
            selected,
            key=lambda value: (
                value.activation_gameweek,
                value.chip_key,
                value.token_id,
                value.opportunity_id,
            ),
        )
    )
    dispositions = _token_dispositions(state, request, opportunity_map)
    terminal_values = _terminal_value_map(request)
    extra_terminal = 0.0
    extra_cash = 0.0
    extra_robust = 0.0
    for disposition in dispositions:
        if disposition.disposition is not TokenDispositionKind.HOLD:
            continue
        value = terminal_values.get(disposition.token_id)
        if value is None:
            continue
        extra_terminal += value.expected_terminal_value  # type: ignore[attr-defined]
        extra_cash += value.cash_like_value  # type: ignore[attr-defined]
        extra_robust += value.robust_penalty  # type: ignore[attr-defined]

    outcomes: list[ScheduleScenarioOutcome] = []
    for index, scenario in enumerate(request.scenario_universe):
        terminal = state.terminal[index] + extra_terminal
        cash = state.cash[index] + extra_cash
        outcomes.append(
            ScheduleScenarioOutcome(
                scenario_id=scenario.scenario_id,
                outcome_draw_id=scenario.outcome_draw_id,
                weight=scenario.weight,
                gross_current_gain=state.gross[index],
                continuation_value=state.continuation[index],
                policy_cost=state.policy_cost[index],
                net_policy_value=state.net[index],
                cash_like_value=cash,
                terminal_state_value=terminal,
                expected_mode_value=state.net[index] + terminal,
            )
        )
    scenario_outcomes = tuple(outcomes)
    expected_gross = sum(item.weight * item.gross_current_gain for item in scenario_outcomes)
    expected_continuation = sum(item.weight * item.continuation_value for item in scenario_outcomes)
    expected_cost = sum(item.weight * item.policy_cost for item in scenario_outcomes)
    expected_net = sum(item.weight * item.net_policy_value for item in scenario_outcomes)
    expected_cash = sum(item.weight * item.cash_like_value for item in scenario_outcomes)
    expected_terminal = sum(item.weight * item.terminal_state_value for item in scenario_outcomes)
    expected_objective = expected_net + expected_terminal
    robust_penalty = state.robust_penalty + extra_robust
    risk_adjusted = expected_objective - request.objective.robust_penalty_weight * robust_penalty
    cash_terminal = (
        expected_net
        + request.objective.cash_like_weight * expected_cash
        + request.objective.terminal_state_weight * expected_terminal
    )
    selected_objective = {
        ScheduleObjectiveMode.EXPECTED: expected_objective,
        ScheduleObjectiveMode.ROBUST: risk_adjusted,
        ScheduleObjectiveMode.CASH_TERMINAL: cash_terminal,
    }[request.objective.objective_mode]
    current_action, current_ids = _root_action(activations, dispositions, request)
    schedule_id = (
        "schedule-"
        + semantic_sha256(
            {
                "request_hash": request.request_hash,
                "selected_opportunity_ids": list(state.selected_ids),
                "objective_mode": request.objective.objective_mode,
            }
        )[:32]
    )
    return _seal_candidate(
        ChipScheduleCandidate(
            schedule_id=schedule_id,
            objective_mode=request.objective.objective_mode,
            activations=activations,
            token_dispositions=dispositions,
            scenario_outcomes=scenario_outcomes,
            expected_gross_current_gain=expected_gross,
            expected_continuation_value=expected_continuation,
            expected_policy_cost=expected_cost,
            expected_net_policy_value=expected_net,
            expected_cash_like_value=expected_cash,
            expected_terminal_state_value=expected_terminal,
            robust_penalty=robust_penalty,
            expected_objective=expected_objective,
            risk_adjusted_objective=risk_adjusted,
            cash_terminal_objective=cash_terminal,
            selected_objective=selected_objective,
            current_action=current_action,
            current_opportunity_ids=current_ids,
            schedule_hash="0" * 64,
        )
    )


def _candidate_rank(candidate: ChipScheduleCandidate) -> tuple[object, ...]:
    activation_signature = tuple(
        (item.activation_gameweek, item.chip_key, item.token_id, item.opportunity_id)
        for item in candidate.activations
    )
    # reverse=True is used by callers. Reversing code points makes lexicographically
    # smaller signatures win the final deterministic tie.
    inverted_signature = tuple(
        tuple(-ord(char) for char in "|".join(map(str, item))) for item in activation_signature
    )
    return (
        round(candidate.selected_objective, 12),
        round(candidate.expected_objective, 12),
        -round(candidate.robust_penalty, 12),
        -len(candidate.activations),
        inverted_signature,
    )


def _sort_candidates(
    candidates: Iterable[ChipScheduleCandidate],
) -> tuple[ChipScheduleCandidate, ...]:
    return tuple(sorted(candidates, key=_candidate_rank, reverse=True))


def _best(
    candidates: Iterable[ChipScheduleCandidate],
) -> ChipScheduleCandidate | None:
    ordered = _sort_candidates(candidates)
    return ordered[0] if ordered else None


def _scenario_objective(
    candidate: ChipScheduleCandidate,
    index: int,
    request: ChipScheduleRequest,
) -> float:
    outcome = candidate.scenario_outcomes[index]
    if request.objective.objective_mode is ScheduleObjectiveMode.EXPECTED:
        return outcome.net_policy_value + outcome.terminal_state_value
    if request.objective.objective_mode is ScheduleObjectiveMode.ROBUST:
        return (
            outcome.net_policy_value
            + outcome.terminal_state_value
            - request.objective.robust_penalty_weight * candidate.robust_penalty
        )
    return (
        outcome.net_policy_value
        + request.objective.cash_like_weight * outcome.cash_like_value
        + request.objective.terminal_state_weight * outcome.terminal_state_value
    )


def _probability_now_optimal(
    candidates: tuple[ChipScheduleCandidate, ...],
    request: ChipScheduleRequest,
    *,
    exact: bool,
) -> ProbabilityNowOptimalDiagnostic:
    numerator = 0.0
    denominator = sum(item.weight for item in request.scenario_universe)
    for index, scenario in enumerate(request.scenario_universe):
        best = max(
            candidates,
            key=lambda item: (
                round(_scenario_objective(item, index, request), 12),
                _candidate_rank(item),
            ),
        )
        if best.current_action is RootScheduleAction.ACTIVATE:
            numerator += scenario.weight
    return ProbabilityNowOptimalDiagnostic(
        probability_now_optimal=numerator / denominator,
        numerator_weight=numerator,
        denominator_weight=denominator,
        scenario_set_hash=request.scenario_set_hash,
        objective_config_hash=semantic_sha256(request.objective),
        exact_search=exact,
    )


def _exact_perfect_information(
    candidates: tuple[ChipScheduleCandidate, ...],
    selected: ChipScheduleCandidate,
    request: ChipScheduleRequest,
) -> PerfectInformationUpperBound:
    weighted = 0.0
    ids: list[str] = []
    for index, scenario in enumerate(request.scenario_universe):
        best = max(
            candidates,
            key=lambda item: (
                round(_scenario_objective(item, index, request), 12),
                _candidate_rank(item),
            ),
        )
        weighted += scenario.weight * _scenario_objective(best, index, request)
        ids.append(best.schedule_id)
    executable = selected.selected_objective
    upper = max(weighted, executable)
    return PerfectInformationUpperBound(
        expected_upper_bound=upper,
        executable_expected_objective=executable,
        upper_bound_gap=max(0.0, upper - executable),
        scenario_best_schedule_ids=tuple(ids),
        bound_method="EXACT_SCENARIO_ORACLE",
        exact_search=True,
    )


def _relaxed_perfect_information(
    selected: ChipScheduleCandidate,
    request: ChipScheduleRequest,
) -> PerfectInformationUpperBound:
    terminal_map = {item.token_id: item for item in request.terminal_token_values}
    opportunities_by_token: dict[str, list[ChipScheduleOpportunity]] = defaultdict(list)
    for opportunity in request.opportunities:
        opportunities_by_token[opportunity.token_id].append(opportunity)
    weighted = 0.0
    for index, scenario in enumerate(request.scenario_universe):
        relaxed = 0.0
        for token in request.inventory.tokens:
            if token.status in {TokenStatus.USED, TokenStatus.EXPIRED, TokenStatus.ACTIVE}:
                continue
            values = [0.0]
            terminal = terminal_map.get(token.token_id)
            if terminal is not None:
                values.append(
                    request.objective.terminal_state_weight * terminal.expected_terminal_value
                    + request.objective.cash_like_weight * terminal.cash_like_value
                )
            for opportunity in opportunities_by_token.get(token.token_id, []):
                scenario_value = opportunity.scenario_values[index]
                if request.objective.objective_mode is ScheduleObjectiveMode.CASH_TERMINAL:
                    value = (
                        scenario_value.net_policy_value
                        + request.objective.cash_like_weight * scenario_value.cash_like_value
                        + request.objective.terminal_state_weight
                        * scenario_value.terminal_state_value
                    )
                else:
                    # Ignore non-negative robust penalties for a valid relaxed upper bound.
                    value = scenario_value.net_policy_value + scenario_value.terminal_state_value
                values.append(value)
            relaxed += max(values)
        weighted += scenario.weight * relaxed
    executable = selected.selected_objective
    upper = max(weighted, executable)
    marker = tuple("RELAXED_FINITE_STATE_BOUND" for _ in request.scenario_universe)
    return PerfectInformationUpperBound(
        expected_upper_bound=upper,
        executable_expected_objective=executable,
        upper_bound_gap=max(0.0, upper - executable),
        scenario_best_schedule_ids=marker,
        bound_method="RELAXED_FINITE_STATE_BOUND",
        exact_search=False,
    )


def _retain_alternatives(
    ordered: tuple[ChipScheduleCandidate, ...],
    required: tuple[ChipScheduleCandidate | None, ...],
    limit: int,
) -> tuple[ChipScheduleCandidate, ...]:
    retained: list[ChipScheduleCandidate] = list(ordered[:limit])
    hashes = {item.schedule_hash for item in retained}
    for item in required:
        if item is not None and item.schedule_hash not in hashes:
            retained.append(item)
            hashes.add(item.schedule_hash)
    return _sort_candidates(retained)


def _seal_policy(value: ChipSchedulePolicy) -> ChipSchedulePolicy:
    payload = value.model_dump(mode="json", exclude={"policy_hash"})
    return ChipSchedulePolicy.model_validate(
        value.model_copy(update={"policy_hash": semantic_sha256(payload)}).model_dump(mode="python")
    )


def _build_policy(request: ChipScheduleRequest, search: _SearchResult) -> ChipSchedulePolicy:
    candidates = _sort_candidates(_candidate_from_state(item, request) for item in search.states)
    if not candidates:
        raise RuntimeError("chip schedule search produced no legal HOLD policy")
    selected = candidates[0]
    current = request.horizon_start_gameweek
    best_use = _best(
        item for item in candidates if item.current_action is RootScheduleAction.ACTIVATE
    )
    best_delay = _best(
        item
        for item in candidates
        if item.current_action is not RootScheduleAction.ACTIVATE
        and any(activation.activation_gameweek > current for activation in item.activations)
    )
    best_never = _best(item for item in candidates if not item.activations)
    if best_never is None:
        raise RuntimeError("chip scheduler failed to retain the legal never-use policy")
    hold_value = best_never.selected_objective
    if best_delay is not None:
        hold_value = max(hold_value, best_delay.selected_objective)
    exercise_advantage = best_use.selected_objective - hold_value if best_use is not None else 0.0
    selected_root_ids = set(selected.current_opportunity_ids)
    selected_root = tuple(
        item for item in selected.activations if item.opportunity_id in selected_root_ids
    )
    gross_current = sum(item.expected_gross_current_gain for item in selected_root)
    root_net = sum(item.expected_net_policy_value for item in selected_root)
    continuation = selected.selected_objective - root_net
    opportunity_cost = max(0.0, hold_value - best_never.selected_objective)
    exact = search.method is ScheduleSearchMethod.EXACT_DYNAMIC_PROGRAMMING
    probability = _probability_now_optimal(candidates, request, exact=exact)
    perfect = (
        _exact_perfect_information(candidates, selected, request)
        if exact
        else _relaxed_perfect_information(selected, request)
    )
    alternatives = _retain_alternatives(
        candidates,
        (selected, best_use, best_delay, best_never),
        request.objective.max_returned_alternatives,
    )
    selected_keys = tuple(sorted(item.chip_key for item in selected_root))
    selected_tokens = tuple(sorted(item.token_id for item in selected_root))
    diagnostics = ScheduleSearchDiagnostics(
        method=search.method,
        estimated_state_space=search.estimated_state_space,
        explored_states=search.counters.explored,
        pruned_states=search.counters.pruned,
        feasible_schedules=len(candidates),
        memo_hits=search.counters.memo_hits,
        beam_width=(
            request.objective.beam_width
            if search.method is ScheduleSearchMethod.BOUNDED_BEAM
            else None
        ),
        exact_optimality=exact,
        prefix_sensitive_memoisation=True,
        finite_state_optimistic_bounds=True,
        deterministic_tie_breaking=True,
    )
    return _seal_policy(
        ChipSchedulePolicy(
            request_hash=request.request_hash,
            selected_schedule=selected,
            best_use_now_schedule=best_use,
            best_delay_schedule=best_delay,
            best_never_use_schedule=best_never,
            alternatives=alternatives,
            recommended_action=selected.current_action,
            selected_chip_keys=selected_keys,
            selected_token_ids=selected_tokens,
            gross_current_gain=gross_current,
            net_policy_value=selected.selected_objective - best_never.selected_objective,
            continuation_value=continuation,
            opportunity_cost=opportunity_cost,
            exercise_advantage=exercise_advantage,
            probability_now_optimal=probability,
            perfect_information_upper_bound=perfect,
            diagnostics=diagnostics,
            policy_hash="0" * 64,
        )
    )


def optimise_chip_schedule(request: ChipScheduleRequest) -> ChipSchedulePolicy:
    """Optimise one deadline-safe finite chip inventory deterministically."""

    _verify_hashes(request)
    estimated = estimate_state_space(request)
    if estimated <= request.objective.exact_state_threshold:
        search = _exact_search(request, estimated)
    else:
        search = _beam_search(request, estimated)
    return _build_policy(request, search)


def exact_small_schedule_oracle(request: ChipScheduleRequest) -> ChipSchedulePolicy:
    """Independently force exhaustive search for tiny golden/oracle comparisons."""

    _verify_hashes(request)
    estimated = estimate_state_space(request)
    # The oracle intentionally ignores the configured threshold but remains bounded
    # by a hard safety ceiling suitable for tests and golden fixtures.
    if estimated > 2_000_000:
        raise ValueError("exact small schedule oracle state space exceeds safety ceiling")
    return _build_policy(request, _exact_search(request, estimated))
