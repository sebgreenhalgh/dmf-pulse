"""Deterministic legal tactical configuration enumeration and scenario evaluation."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Set
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from itertools import combinations, permutations, product
from math import factorial, lcm
from typing import cast

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import GameweekPointScenario, PlayerPosition
from dmf_pulse.optimisation.autosub_evaluator import evaluate_scenario, weight_fraction
from dmf_pulse.optimisation.errors import ResourceLimitError
from dmf_pulse.optimisation.legality import validate_tactical_configuration
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidateSquad,
    ExplanationItem,
    OneGameweekOptimiserPolicy,
    OneGameweekPlan,
    OneGameweekRulesView,
    OptimalityGuarantee,
    PointDistributionSummary,
    PointMass,
    ScenarioManagerScore,
    SearchScope,
    SolverStatus,
    TacticalConfiguration,
)

CANONICAL_DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


def _quantile(masses: dict[int, Fraction], probability: Fraction) -> int:
    accumulated = Fraction(0)
    for points, mass in sorted(masses.items()):
        accumulated += mass
        if accumulated >= probability:
            return points
    raise ValueError("point-mass probabilities must be positive")


def _players_by_position(
    squad: CandidateSquad, players: dict[str, CandidatePlayer]
) -> dict[PlayerPosition, tuple[str, ...]]:
    return {
        position: tuple(
            sorted(player for player in squad.player_ids if players[player].position is position)
        )
        for position in PlayerPosition
    }


def tactical_configuration_upper_bound(
    squad: CandidateSquad, players: dict[str, CandidatePlayer], rules: OneGameweekRulesView
) -> int:
    grouped = _players_by_position(squad, players)
    outfield_bench = rules.bench_size - 1
    bench_orders = factorial(outfield_bench)
    captain_pairs = rules.starting_size * (rules.starting_size - 1)
    formations = 0
    for gk_choice in combinations(grouped[PlayerPosition.GK], rules.lineup_max[PlayerPosition.GK]):
        del gk_choice
        for d in range(
            rules.lineup_min[PlayerPosition.DEF],
            min(rules.lineup_max[PlayerPosition.DEF], len(grouped[PlayerPosition.DEF])) + 1,
        ):
            for m in range(
                rules.lineup_min[PlayerPosition.MID],
                min(rules.lineup_max[PlayerPosition.MID], len(grouped[PlayerPosition.MID])) + 1,
            ):
                for f in range(
                    rules.lineup_min[PlayerPosition.FWD],
                    min(rules.lineup_max[PlayerPosition.FWD], len(grouped[PlayerPosition.FWD])) + 1,
                ):
                    if d + m + f + 1 == rules.starting_size:
                        formations += (
                            factorial(len(grouped[PlayerPosition.DEF]))
                            // (factorial(d) * factorial(len(grouped[PlayerPosition.DEF]) - d))
                            * factorial(len(grouped[PlayerPosition.MID]))
                            // (factorial(m) * factorial(len(grouped[PlayerPosition.MID]) - m))
                            * factorial(len(grouped[PlayerPosition.FWD]))
                            // (factorial(f) * factorial(len(grouped[PlayerPosition.FWD]) - f))
                        )
    return formations * bench_orders * captain_pairs


def enumerate_tactical_configurations(
    squad: CandidateSquad,
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
    policy: OneGameweekOptimiserPolicy,
) -> tuple[Iterator[TacticalConfiguration], int]:
    upper = tactical_configuration_upper_bound(squad, players, rules)
    if upper > policy.max_tactical_configurations:
        raise ResourceLimitError(f"conservative tactical upper bound {upper} exceeds cap")
    grouped = _players_by_position(squad, players)
    gk = grouped[PlayerPosition.GK]
    outfield = {
        position: grouped[position]
        for position in (PlayerPosition.DEF, PlayerPosition.MID, PlayerPosition.FWD)
    }

    def generator() -> Iterator[TacticalConfiguration]:
        for bench_gk in gk:
            starting_gk = next(player for player in gk if player != bench_gk)
            for d_count in range(
                rules.lineup_min[PlayerPosition.DEF], rules.lineup_max[PlayerPosition.DEF] + 1
            ):
                for m_count in range(
                    rules.lineup_min[PlayerPosition.MID], rules.lineup_max[PlayerPosition.MID] + 1
                ):
                    f_count = rules.starting_size - 1 - d_count - m_count
                    if (
                        f_count < rules.lineup_min[PlayerPosition.FWD]
                        or f_count > rules.lineup_max[PlayerPosition.FWD]
                    ):
                        continue
                    for defenders, mids, fwds in product(
                        combinations(outfield[PlayerPosition.DEF], d_count),
                        combinations(outfield[PlayerPosition.MID], m_count),
                        combinations(outfield[PlayerPosition.FWD], f_count),
                    ):
                        selected = (starting_gk, *defenders, *mids, *fwds)
                        bench_outfield = tuple(
                            sorted(set(squad.player_ids) - set(selected) - {bench_gk})
                        )
                        for bench_order in permutations(bench_outfield):
                            for captain, vice in permutations(selected, 2):
                                tactic = TacticalConfiguration(
                                    starting_xi=selected,
                                    bench_goalkeeper=bench_gk,
                                    bench_order=cast(tuple[str, str, str], bench_order),
                                    captain=captain,
                                    vice_captain=vice,
                                )
                                if validate_tactical_configuration(
                                    squad, tactic, players, rules
                                ).legal:
                                    yield tactic

    return generator(), upper


def _tactical_signature(
    squad: CandidateSquad,
    *,
    starting_xi: tuple[str, ...],
    bench_goalkeeper: str,
    bench_order: tuple[str, str, str],
    captain: str,
    vice_captain: str,
) -> str:
    return "|".join(
        (
            ",".join(sorted(squad.player_ids)),
            ",".join(sorted(starting_xi)),
            bench_goalkeeper,
            ",".join(bench_order),
            captain,
            vice_captain,
        )
    )


def _selected_outfield_substitutes(
    *,
    starting_outfield: tuple[str, ...],
    bench_order: tuple[str, str, str],
    positions: Mapping[str, PlayerPosition],
    appeared: Set[str],
    rules: OneGameweekRulesView,
) -> tuple[str, ...]:
    """Exact value-only form of the accepted autosub resolver."""

    absent = tuple(player for player in starting_outfield if player not in appeared)
    eligible = tuple(player for player in bench_order if player in appeared)
    if not absent or not eligible:
        return ()
    best: tuple[tuple[int, ...], tuple[str, ...]] | None = None
    for mask in range(1 << len(eligible)):
        selected = tuple(eligible[index] for index in range(len(eligible)) if mask & (1 << index))
        if len(selected) > len(absent):
            continue
        final = [player for player in starting_outfield if player not in absent]
        final.extend(selected)
        counts = {
            position: sum(positions[player] is position for player in final)
            for position in (PlayerPosition.DEF, PlayerPosition.MID, PlayerPosition.FWD)
        }
        if any(
            counts[position] < rules.lineup_min[position]
            or counts[position] > rules.lineup_max[position]
            for position in counts
        ):
            continue
        vector = tuple(1 if mask & (1 << index) else 0 for index in range(len(eligible)))
        candidate = (vector, selected)
        if best is None or (len(selected), vector) > (len(best[1]), best[0]):
            best = candidate
    if best is None:
        return ()
    selected = best[1]
    for outgoing in permutations(absent, len(selected)):
        active = list(starting_outfield)
        valid = True
        for player_out, player_in in zip(outgoing, selected, strict=True):
            active[active.index(player_out)] = player_in
            counts = {
                position: sum(positions[player] is position for player in active)
                for position in (PlayerPosition.DEF, PlayerPosition.MID, PlayerPosition.FWD)
            }
            if any(
                counts[position] < rules.lineup_min[position]
                or counts[position] > rules.lineup_max[position]
                for position in counts
            ):
                valid = False
                break
        if valid:
            return selected
    return ()


def _base_objective(
    *,
    starting_xi: tuple[str, ...],
    bench_goalkeeper: str,
    bench_order: tuple[str, str, str],
    scenarios: tuple[tuple[Set[str], Mapping[str, int], Fraction], ...],
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
    positions: Mapping[str, PlayerPosition],
) -> Fraction:
    """Return the exact non-captain objective for one XI/bench skeleton."""

    starting_gk_index = next(
        index
        for index, player in enumerate(starting_xi)
        if players[player].position is PlayerPosition.GK
    )
    starting_outfield = tuple(
        player for player in starting_xi if players[player].position is not PlayerPosition.GK
    )
    total = Fraction(0)
    starting_gk = starting_xi[starting_gk_index]
    for appeared, points, weight in scenarios:
        base_points = sum(points[player] for player in starting_xi if player in appeared)
        if starting_gk not in appeared and bench_goalkeeper in appeared:
            base_points += points[bench_goalkeeper]
        substitutes = _selected_outfield_substitutes(
            starting_outfield=starting_outfield,
            bench_order=bench_order,
            positions=positions,
            appeared=appeared,
            rules=rules,
        )
        base_points += sum(points[player] for player in substitutes)
        total += weight * base_points
    return total


@dataclass(frozen=True)
class ExactTacticalKernelWork:
    """Truthful logical and factored work counters for one node kernel."""

    squads_evaluated: int
    logical_scenario_operations: int
    appearance_state_xi_visits: int
    captain_pair_appearance_visits: int
    goalkeeper_pair_appearance_visits: int
    autosub_resolution_cache_misses: int
    canonical_scenario_operations: int

    @property
    def factored_scenario_operations(self) -> int:
        """Return expensive state/scenario interpretations after exact reuse."""

        return (
            self.appearance_state_xi_visits
            + self.captain_pair_appearance_visits
            + self.goalkeeper_pair_appearance_visits
            + self.autosub_resolution_cache_misses
            + self.canonical_scenario_operations
        )


@dataclass(frozen=True)
class _AggregatedAppearanceState:
    appearance_mask: int
    weighted_player_point_numerators: tuple[int, ...]


class ExactTacticalNodeKernel:
    """Exact reusable Stage-10 representation for every fixed squad at one node.

    Scenario weights are represented by one common integer denominator.  Scenarios
    with the same appearance mask are combined by summing each player's exact
    weighted point numerator.  This makes tactical objective comparison integral;
    the winning tactic is still evaluated by the canonical scenario evaluator.
    """

    def __init__(
        self,
        *,
        scenarios: tuple[GameweekPointScenario, ...],
        players: dict[str, CandidatePlayer],
        rules: OneGameweekRulesView,
    ) -> None:
        if not scenarios:
            raise ValueError("exact tactical node kernel requires scenarios")
        self.scenarios = scenarios
        self.players = players
        self.rules = rules
        self._player_ids = tuple(sorted(players))
        self._player_index = {player_id: index for index, player_id in enumerate(self._player_ids)}
        weights = tuple(weight_fraction(scenario.weight) for scenario in scenarios)
        self._common_denominator = lcm(*(weight.denominator for weight in weights))
        aggregated: dict[int, list[int]] = {}
        for scenario, weight in zip(scenarios, weights, strict=True):
            numerator = weight.numerator * (self._common_denominator // weight.denominator)
            mask = 0
            for player_id in self._player_ids:
                if scenario.player_appeared[player_id]:
                    mask |= self._bit(player_id)
            point_numerators = aggregated.setdefault(mask, [0] * len(self._player_ids))
            for index, player_id in enumerate(self._player_ids):
                point_numerators[index] += numerator * scenario.player_points[player_id]
        self._appearance_states = tuple(
            _AggregatedAppearanceState(mask, tuple(point_numerators))
            for mask, point_numerators in sorted(aggregated.items())
        )
        self._appeared_point_numerator = {
            player_id: sum(
                state.weighted_player_point_numerators[index]
                for state in self._appearance_states
                if state.appearance_mask & (1 << index)
            )
            for player_id, index in self._player_index.items()
        }
        self._captain_bonus_cache: dict[tuple[str, str], int] = {}
        self._best_captains_cache: dict[
            tuple[str, ...], tuple[int, tuple[tuple[str, str], ...]]
        ] = {}
        self._goalkeeper_bonus_cache: dict[tuple[str, str], int] = {}
        self._autosub_slots_cache: dict[
            tuple[
                tuple[int, int, int],
                tuple[int, int, int],
                tuple[int, int, int],
                int,
            ],
            tuple[int, ...],
        ] = {}
        self._autosub_tables: dict[
            tuple[tuple[int, int, int], tuple[int, int, int]], list[int]
        ] = {}
        self._squads_evaluated = 0
        self._logical_scenario_operations = 0
        self._appearance_state_xi_visits = 0
        self._captain_pair_appearance_visits = 0
        self._goalkeeper_pair_appearance_visits = 0
        self._autosub_resolution_cache_misses = 0
        self._canonical_scenario_operations = 0

    def _bit(self, player_id: str) -> int:
        return 1 << self._player_index[player_id]

    def _point_numerator(self, state: _AggregatedAppearanceState, player_id: str) -> int:
        return state.weighted_player_point_numerators[self._player_index[player_id]]

    def _squad_appearance_states(
        self, squad: CandidateSquad
    ) -> tuple[tuple[_AggregatedAppearanceState, ...], dict[str, int]]:
        """Regroup node states by the 15-player mask relevant to this squad."""

        squad_ids = squad.player_ids
        local_index = {player_id: index for index, player_id in enumerate(squad_ids)}
        global_indexes = tuple(self._player_index[player_id] for player_id in squad_ids)
        squad_mask = sum(1 << index for index in global_indexes)
        aggregated: dict[int, list[int]] = {}
        for state in self._appearance_states:
            appearance_mask = state.appearance_mask & squad_mask
            point_numerators = aggregated.setdefault(appearance_mask, [0] * len(squad_ids))
            for local, global_index in enumerate(global_indexes):
                point_numerators[local] += state.weighted_player_point_numerators[global_index]
        return (
            tuple(
                _AggregatedAppearanceState(mask, tuple(point_numerators))
                for mask, point_numerators in sorted(aggregated.items())
            ),
            local_index,
        )

    def _captain_bonus_numerator(self, captain: str, vice: str) -> int:
        key = (captain, vice)
        cached = self._captain_bonus_cache.get(key)
        if cached is not None:
            return cached
        captain_bit = self._bit(captain)
        vice_bit = self._bit(vice)
        multiplier = self.rules.captain_multiplier - 1
        total = 0
        for state in self._appearance_states:
            if state.appearance_mask & captain_bit:
                total += multiplier * self._point_numerator(state, captain)
            elif self.rules.vice_captain_fallback and state.appearance_mask & vice_bit:
                total += multiplier * self._point_numerator(state, vice)
        self._captain_pair_appearance_visits += len(self._appearance_states)
        self._captain_bonus_cache[key] = total
        return total

    def _best_captains(
        self, starting_xi: tuple[str, ...]
    ) -> tuple[int, tuple[tuple[str, str], ...]]:
        key = tuple(sorted(starting_xi))
        cached = self._best_captains_cache.get(key)
        if cached is not None:
            return cached
        pair_values = tuple(
            (self._captain_bonus_numerator(captain, vice), captain, vice)
            for captain, vice in permutations(starting_xi, 2)
        )
        best_bonus = max(item[0] for item in pair_values)
        result = (
            best_bonus,
            tuple(
                sorted(
                    (captain, vice) for bonus, captain, vice in pair_values if bonus == best_bonus
                )
            ),
        )
        self._best_captains_cache[key] = result
        return result

    def _goalkeeper_bonus_numerator(self, starting_gk: str, bench_gk: str) -> int:
        key = (starting_gk, bench_gk)
        cached = self._goalkeeper_bonus_cache.get(key)
        if cached is not None:
            return cached
        starting_bit = self._bit(starting_gk)
        bench_bit = self._bit(bench_gk)
        total = sum(
            self._point_numerator(state, bench_gk)
            for state in self._appearance_states
            if not state.appearance_mask & starting_bit and state.appearance_mask & bench_bit
        )
        self._goalkeeper_pair_appearance_visits += len(self._appearance_states)
        self._goalkeeper_bonus_cache[key] = total
        return total

    @staticmethod
    def _position_code(position: PlayerPosition) -> int:
        return {
            PlayerPosition.DEF: 0,
            PlayerPosition.MID: 1,
            PlayerPosition.FWD: 2,
        }[position]

    def _selected_bench_slots(
        self,
        *,
        formation: tuple[int, int, int],
        absent: tuple[int, int, int],
        bench_positions: tuple[int, int, int],
        bench_appeared_mask: int,
    ) -> tuple[int, ...]:
        key = (formation, absent, bench_positions, bench_appeared_mask)
        cached = self._autosub_slots_cache.get(key)
        if cached is not None:
            return cached
        self._autosub_resolution_cache_misses += 1
        eligible = tuple(
            (slot, bench_positions[slot])
            for slot in range(len(bench_positions))
            if bench_appeared_mask & (1 << slot)
        )
        absent_total = sum(absent)
        if absent_total == 0 or not eligible:
            self._autosub_slots_cache[key] = ()
            return ()
        minimum = (
            self.rules.lineup_min[PlayerPosition.DEF],
            self.rules.lineup_min[PlayerPosition.MID],
            self.rules.lineup_min[PlayerPosition.FWD],
        )
        maximum = (
            self.rules.lineup_max[PlayerPosition.DEF],
            self.rules.lineup_max[PlayerPosition.MID],
            self.rules.lineup_max[PlayerPosition.FWD],
        )
        best: tuple[tuple[int, ...], tuple[tuple[int, int], ...]] | None = None
        for selection_mask in range(1 << len(eligible)):
            selected = tuple(
                eligible[index] for index in range(len(eligible)) if selection_mask & (1 << index)
            )
            if len(selected) > absent_total:
                continue
            final = tuple(
                formation[position]
                - absent[position]
                + sum(item[1] == position for item in selected)
                for position in range(3)
            )
            if any(
                final[position] < minimum[position] or final[position] > maximum[position]
                for position in range(3)
            ):
                continue
            vector = tuple(
                1 if selection_mask & (1 << index) else 0 for index in range(len(eligible))
            )
            candidate = (vector, selected)
            if best is None or (len(selected), vector) > (len(best[1]), best[0]):
                best = candidate
        if best is None:
            self._autosub_slots_cache[key] = ()
            return ()
        selected = best[1]
        absent_positions = tuple(
            position for position, count in enumerate(absent) for _ in range(count)
        )
        for outgoing in permutations(absent_positions, len(selected)):
            active = list(formation)
            valid = True
            for player_out, (_, player_in) in zip(outgoing, selected, strict=True):
                active[player_out] -= 1
                active[player_in] += 1
                if any(
                    active[position] < minimum[position] or active[position] > maximum[position]
                    for position in range(3)
                ):
                    valid = False
                    break
            if valid:
                result = tuple(slot for slot, _ in selected)
                self._autosub_slots_cache[key] = result
                return result
        self._autosub_slots_cache[key] = ()
        return ()

    def _bench_order_objective_numerators(
        self,
        *,
        starting_outfield: tuple[str, ...],
        bench_orders: tuple[tuple[str, str, str], ...],
        appearance_states: tuple[_AggregatedAppearanceState, ...],
        local_player_index: Mapping[str, int],
    ) -> tuple[int, ...]:
        by_position = tuple(
            tuple(
                player_id
                for player_id in starting_outfield
                if self.players[player_id].position is position
            )
            for position in (PlayerPosition.DEF, PlayerPosition.MID, PlayerPosition.FWD)
        )
        formation = cast(tuple[int, int, int], tuple(len(group) for group in by_position))
        position_masks = tuple(
            sum(self._bit(player_id) for player_id in group) for group in by_position
        )
        order_data = []
        for bench_order in bench_orders:
            bench_positions = cast(
                tuple[int, int, int],
                tuple(
                    self._position_code(self.players[player_id].position)
                    for player_id in bench_order
                ),
            )
            table_key = (formation, bench_positions)
            autosub_table = self._autosub_tables.get(table_key)
            if autosub_table is None:
                autosub_table = [-1] * (6 * 6 * 6 * 8)
                self._autosub_tables[table_key] = autosub_table
            order_data.append(
                (
                    bench_positions,
                    tuple(self._bit(player_id) for player_id in bench_order),
                    tuple(local_player_index[player_id] for player_id in bench_order),
                    autosub_table,
                )
            )
        values = [0] * len(bench_orders)
        for state in appearance_states:
            self._appearance_state_xi_visits += 1
            absent = (
                formation[0] - (state.appearance_mask & position_masks[0]).bit_count(),
                formation[1] - (state.appearance_mask & position_masks[1]).bit_count(),
                formation[2] - (state.appearance_mask & position_masks[2]).bit_count(),
            )
            absent_code = absent[0] + 6 * absent[1] + 36 * absent[2]
            for order_index, (
                bench_positions,
                bench_bits,
                bench_indexes,
                autosub_table,
            ) in enumerate(order_data):
                appeared_mask = (
                    int(bool(state.appearance_mask & bench_bits[0]))
                    | (int(bool(state.appearance_mask & bench_bits[1])) << 1)
                    | (int(bool(state.appearance_mask & bench_bits[2])) << 2)
                )
                table_index = (absent_code << 3) | appeared_mask
                selected_mask = autosub_table[table_index]
                if selected_mask < 0:
                    slots = self._selected_bench_slots(
                        formation=formation,
                        absent=absent,
                        bench_positions=bench_positions,
                        bench_appeared_mask=appeared_mask,
                    )
                    selected_mask = sum(1 << slot for slot in slots)
                    autosub_table[table_index] = selected_mask
                weighted = state.weighted_player_point_numerators
                if selected_mask & 1:
                    values[order_index] += weighted[bench_indexes[0]]
                if selected_mask & 2:
                    values[order_index] += weighted[bench_indexes[1]]
                if selected_mask & 4:
                    values[order_index] += weighted[bench_indexes[2]]
        return tuple(values)

    def optimise(
        self,
        squad: CandidateSquad,
        policy: OneGameweekOptimiserPolicy,
    ) -> tuple[OneGameweekPlan, Fraction, int, int]:
        """Return the exact fixed-squad result using this node's shared kernel."""

        upper = tactical_configuration_upper_bound(squad, self.players, self.rules)
        if upper > policy.max_tactical_configurations:
            raise ResourceLimitError(f"conservative tactical upper bound {upper} exceeds cap")
        grouped = _players_by_position(squad, self.players)
        appearance_states, local_player_index = self._squad_appearance_states(squad)
        outfield = {
            position: grouped[position]
            for position in (PlayerPosition.DEF, PlayerPosition.MID, PlayerPosition.FWD)
        }
        best_numerator: int | None = None
        best_signature: str | None = None
        best_tactic: TacticalConfiguration | None = None
        tactics_evaluated = 0
        tied_optima = 0
        for bench_gk in grouped[PlayerPosition.GK]:
            starting_gk = next(
                player for player in grouped[PlayerPosition.GK] if player != bench_gk
            )
            goalkeeper_bonus = self._goalkeeper_bonus_numerator(starting_gk, bench_gk)
            for d_count in range(
                self.rules.lineup_min[PlayerPosition.DEF],
                self.rules.lineup_max[PlayerPosition.DEF] + 1,
            ):
                for m_count in range(
                    self.rules.lineup_min[PlayerPosition.MID],
                    self.rules.lineup_max[PlayerPosition.MID] + 1,
                ):
                    f_count = self.rules.starting_size - 1 - d_count - m_count
                    if (
                        f_count < self.rules.lineup_min[PlayerPosition.FWD]
                        or f_count > self.rules.lineup_max[PlayerPosition.FWD]
                    ):
                        continue
                    for defenders, mids, fwds in product(
                        combinations(outfield[PlayerPosition.DEF], d_count),
                        combinations(outfield[PlayerPosition.MID], m_count),
                        combinations(outfield[PlayerPosition.FWD], f_count),
                    ):
                        selected = (starting_gk, *defenders, *mids, *fwds)
                        best_bonus, best_pairs = self._best_captains(selected)
                        bench_outfield = tuple(
                            sorted(set(squad.player_ids) - set(selected) - {bench_gk})
                        )
                        bench_orders = tuple(
                            cast(tuple[str, str, str], order)
                            for order in permutations(bench_outfield)
                        )
                        starting_numerator = sum(
                            self._appeared_point_numerator[player_id] for player_id in selected
                        )
                        bench_numerators = self._bench_order_objective_numerators(
                            starting_outfield=(*defenders, *mids, *fwds),
                            bench_orders=bench_orders,
                            appearance_states=appearance_states,
                            local_player_index=local_player_index,
                        )
                        for bench_order, bench_numerator in zip(
                            bench_orders, bench_numerators, strict=True
                        ):
                            tactics_evaluated += len(selected) * (len(selected) - 1)
                            objective = (
                                starting_numerator + goalkeeper_bonus + bench_numerator + best_bonus
                            )
                            captain, vice = best_pairs[0]
                            signature = _tactical_signature(
                                squad,
                                starting_xi=selected,
                                bench_goalkeeper=bench_gk,
                                bench_order=bench_order,
                                captain=captain,
                                vice_captain=vice,
                            )
                            if best_numerator is None or objective > best_numerator:
                                best_numerator = objective
                                best_signature = signature
                                tied_optima = len(best_pairs)
                                best_tactic = TacticalConfiguration(
                                    starting_xi=selected,
                                    bench_goalkeeper=bench_gk,
                                    bench_order=bench_order,
                                    captain=captain,
                                    vice_captain=vice,
                                )
                            elif objective == best_numerator:
                                tied_optima += len(best_pairs)
                                if best_signature is None or signature < best_signature:
                                    best_signature = signature
                                    best_tactic = TacticalConfiguration(
                                        starting_xi=selected,
                                        bench_goalkeeper=bench_gk,
                                        bench_order=bench_order,
                                        captain=captain,
                                        vice_captain=vice,
                                    )
        if best_tactic is None or best_numerator is None:
            raise ValueError("fixed squad has no legal tactical configuration")
        best_objective = Fraction(best_numerator, self._common_denominator)
        plan, verified_objective = evaluate_tactical_configuration(
            squad,
            best_tactic,
            self.scenarios,
            self.players,
            self.rules,
        )
        if verified_objective != best_objective:
            raise ValueError("node-kernel tactical objective differs from canonical evaluation")
        self._squads_evaluated += 1
        self._logical_scenario_operations += tactics_evaluated * len(self.scenarios)
        self._canonical_scenario_operations += len(self.scenarios)
        return plan, best_objective, tactics_evaluated, tied_optima

    def work_snapshot(self) -> ExactTacticalKernelWork:
        """Return immutable counters without affecting tactical semantics."""

        return ExactTacticalKernelWork(
            squads_evaluated=self._squads_evaluated,
            logical_scenario_operations=self._logical_scenario_operations,
            appearance_state_xi_visits=self._appearance_state_xi_visits,
            captain_pair_appearance_visits=self._captain_pair_appearance_visits,
            goalkeeper_pair_appearance_visits=self._goalkeeper_pair_appearance_visits,
            autosub_resolution_cache_misses=self._autosub_resolution_cache_misses,
            canonical_scenario_operations=self._canonical_scenario_operations,
        )


def optimise_fixed_squad_tactics_exact(
    squad: CandidateSquad,
    scenarios: tuple[GameweekPointScenario, ...],
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
    policy: OneGameweekOptimiserPolicy,
) -> tuple[OneGameweekPlan, Fraction, int, int]:
    """Optimise a fixed squad exactly while factoring captain scoring.

    Autosubstitution is independent of captain and vice designations.  The
    exhaustive tactical space can therefore be evaluated as each legal
    XI/bench skeleton plus every ordered captain pair, without recomputing the
    same autosubs for all 110 pairs.  This preserves the exact objective,
    deterministic tie-break, and declared exhaustive-search counts.
    """

    upper = tactical_configuration_upper_bound(squad, players, rules)
    if upper > policy.max_tactical_configurations:
        raise ResourceLimitError(f"conservative tactical upper bound {upper} exceeds cap")
    grouped = _players_by_position(squad, players)
    multiplier = rules.captain_multiplier - 1
    weighted_scenarios = tuple(
        (scenario, weight_fraction(scenario.weight)) for scenario in scenarios
    )
    base_scenarios = tuple(
        (
            {player for player, appeared in scenario.player_appeared.items() if appeared},
            scenario.player_points,
            weight,
        )
        for scenario, weight in weighted_scenarios
    )
    positions = {player: players[player].position for player in players}
    captain_bonus: dict[tuple[str, str], Fraction] = {}
    for captain in squad.player_ids:
        for vice in squad.player_ids:
            if captain == vice:
                continue
            bonus = Fraction(0)
            for scenario, weight in weighted_scenarios:
                if scenario.player_appeared[captain]:
                    points = scenario.player_points[captain]
                elif rules.vice_captain_fallback and scenario.player_appeared[vice]:
                    points = scenario.player_points[vice]
                else:
                    points = 0
                bonus += weight * multiplier * points
            captain_bonus[(captain, vice)] = bonus

    best_objective: Fraction | None = None
    best_signature: str | None = None
    best_tactic: TacticalConfiguration | None = None
    tactics_evaluated = 0
    tied_optima = 0
    best_captains_by_xi: dict[tuple[str, ...], tuple[Fraction, tuple[tuple[str, str], ...]]] = {}
    outfield = {
        position: grouped[position]
        for position in (PlayerPosition.DEF, PlayerPosition.MID, PlayerPosition.FWD)
    }
    for bench_gk in grouped[PlayerPosition.GK]:
        starting_gk = next(player for player in grouped[PlayerPosition.GK] if player != bench_gk)
        for d_count in range(
            rules.lineup_min[PlayerPosition.DEF], rules.lineup_max[PlayerPosition.DEF] + 1
        ):
            for m_count in range(
                rules.lineup_min[PlayerPosition.MID], rules.lineup_max[PlayerPosition.MID] + 1
            ):
                f_count = rules.starting_size - 1 - d_count - m_count
                if (
                    f_count < rules.lineup_min[PlayerPosition.FWD]
                    or f_count > rules.lineup_max[PlayerPosition.FWD]
                ):
                    continue
                for defenders, mids, fwds in product(
                    combinations(outfield[PlayerPosition.DEF], d_count),
                    combinations(outfield[PlayerPosition.MID], m_count),
                    combinations(outfield[PlayerPosition.FWD], f_count),
                ):
                    selected = (starting_gk, *defenders, *mids, *fwds)
                    best_captains = best_captains_by_xi.get(selected)
                    if best_captains is None:
                        pair_values = tuple(
                            (captain_bonus[(captain, vice)], captain, vice)
                            for captain, vice in permutations(selected, 2)
                        )
                        best_bonus = max(item[0] for item in pair_values)
                        best_pairs = tuple(
                            sorted(
                                (captain, vice)
                                for bonus, captain, vice in pair_values
                                if bonus == best_bonus
                            )
                        )
                        best_captains = (best_bonus, best_pairs)
                        best_captains_by_xi[selected] = best_captains
                    best_bonus, best_pairs = best_captains
                    bench_outfield = tuple(
                        sorted(set(squad.player_ids) - set(selected) - {bench_gk})
                    )
                    for raw_bench_order in permutations(bench_outfield):
                        bench_order = cast(tuple[str, str, str], raw_bench_order)
                        base = _base_objective(
                            starting_xi=selected,
                            bench_goalkeeper=bench_gk,
                            bench_order=bench_order,
                            scenarios=base_scenarios,
                            players=players,
                            rules=rules,
                            positions=positions,
                        )
                        tactics_evaluated += len(selected) * (len(selected) - 1)
                        objective = base + best_bonus
                        captain, vice = best_pairs[0]
                        signature = _tactical_signature(
                            squad,
                            starting_xi=selected,
                            bench_goalkeeper=bench_gk,
                            bench_order=bench_order,
                            captain=captain,
                            vice_captain=vice,
                        )
                        if best_objective is None or objective > best_objective:
                            best_objective = objective
                            best_signature = signature
                            tied_optima = len(best_pairs)
                            best_tactic = TacticalConfiguration(
                                starting_xi=selected,
                                bench_goalkeeper=bench_gk,
                                bench_order=bench_order,
                                captain=captain,
                                vice_captain=vice,
                            )
                        elif objective == best_objective:
                            tied_optima += len(best_pairs)
                            if best_signature is None or signature < best_signature:
                                best_tactic = TacticalConfiguration(
                                    starting_xi=selected,
                                    bench_goalkeeper=bench_gk,
                                    bench_order=bench_order,
                                    captain=captain,
                                    vice_captain=vice,
                                )
                                best_signature = signature
    if best_tactic is None or best_objective is None:
        raise ValueError("fixed squad has no legal tactical configuration")
    plan, verified_objective = evaluate_tactical_configuration(
        squad,
        best_tactic,
        scenarios,
        players,
        rules,
    )
    if verified_objective != best_objective:
        raise ValueError("factored tactical objective differs from canonical evaluation")
    return plan, best_objective, tactics_evaluated, tied_optima


def evaluate_tactical_configuration(
    squad: CandidateSquad,
    tactic: TacticalConfiguration,
    scenarios: tuple[GameweekPointScenario, ...],
    players: dict[str, CandidatePlayer],
    rules: OneGameweekRulesView,
    *,
    search_scope: SearchScope = SearchScope.FIXED_SQUAD,
    report_budget: bool = False,
) -> tuple[OneGameweekPlan, Fraction]:
    report = validate_tactical_configuration(squad, tactic, players, rules)
    if not report.legal:
        raise ValueError("cannot evaluate an illegal tactical configuration")
    scores: list[ScenarioManagerScore] = []
    total = Fraction(0)
    for scenario in scenarios:
        score, weighted = evaluate_scenario(scenario, tactic, players, rules)
        scores.append(score)
        total += weighted
    weighted_scores = tuple(
        (score, weight_fraction(scenario.weight))
        for score, scenario in zip(scores, scenarios, strict=True)
    )
    masses_by_points: dict[int, Fraction] = {}
    for score, weight in weighted_scores:
        masses_by_points[score.manager_points] = (
            masses_by_points.get(score.manager_points, Fraction(0)) + weight
        )
    total_weight = sum(masses_by_points.values(), Fraction(0))
    if total_weight <= 0:
        raise ValueError("scenario weights must sum to a positive value")
    normalized_masses = {
        points: probability / total_weight for points, probability in masses_by_points.items()
    }
    fallback = (
        sum(
            weight
            for score, weight in weighted_scores
            if score.captain_resolution.value == "VICE_CAPTAIN"
        )
        / total_weight
    )
    captain_and_vice_failure = (
        sum(
            weight
            for score, weight in weighted_scores
            if score.captain_resolution.value == "NEITHER"
        )
        / total_weight
    )
    field_11 = (
        sum(
            weight
            for score, weight in weighted_scores
            if len(score.counted_player_ids) == rules.starting_size
        )
        / total_weight
    )
    expected_bench = (
        sum(weight * score.bench_contribution_points for score, weight in weighted_scores)
        / total_weight
    )
    expectation = total / total_weight
    manager_values = tuple(score.manager_points for score in scores)
    manager_weights = tuple(weight / total_weight for _, weight in weighted_scores)
    variance = sum(
        weight * (value - expectation) ** 2
        for value, weight in zip(manager_values, manager_weights, strict=True)
    )
    with localcontext(CANONICAL_DECIMAL_CONTEXT):
        masses = tuple(
            PointMass(
                points=points,
                probability=Decimal(prob.numerator) / Decimal(prob.denominator),
            )
            for points, prob in sorted(normalized_masses.items())
        )
        expected = Decimal(expectation.numerator) / Decimal(expectation.denominator)
        distribution = PointDistributionSummary(
            pmf=masses,
            expected_points=expected,
            minimum=min(normalized_masses),
            p10=_quantile(normalized_masses, Fraction(1, 10)),
            median=_quantile(normalized_masses, Fraction(1, 2)),
            p90=_quantile(normalized_masses, Fraction(9, 10)),
            maximum=max(normalized_masses),
            probability_field_11=Decimal(field_11.numerator) / Decimal(field_11.denominator),
            probability_field_10_or_fewer=Decimal(1)
            - Decimal(field_11.numerator) / Decimal(field_11.denominator),
            captain_fallback_probability=Decimal(fallback.numerator)
            / Decimal(fallback.denominator),
            captain_and_vice_failure_probability=(
                Decimal(captain_and_vice_failure.numerator)
                / Decimal(captain_and_vice_failure.denominator)
            ),
            expected_bench_contribution=(
                Decimal(expected_bench.numerator) / Decimal(expected_bench.denominator)
            ),
            component_means={"manager_points": expected},
            component_covariance={
                "manager_points": {
                    "manager_points": Decimal(variance.numerator) / Decimal(variance.denominator)
                }
            },
        )
    total_cost = (
        sum(players[player_id].initial_selection_cost_tenths or 0 for player_id in squad.player_ids)
        if report_budget
        else None
    )
    remaining_budget = (
        rules.initial_budget_tenths - total_cost
        if report_budget and total_cost is not None and rules.initial_budget_tenths is not None
        else None
    )
    plan = OneGameweekPlan(
        squad=squad.player_ids,
        tactical_configuration=tactic,
        scenario_scores=tuple(scores),
        point_distribution=distribution,
        expected_manager_points=expected,
        total_cost_tenths=total_cost,
        remaining_budget_tenths=remaining_budget,
        legality=report,
        solver_status=SolverStatus(
            search_scope=search_scope,
            guarantee=OptimalityGuarantee.NONE,
        ),
        explanations=(
            ExplanationItem(
                code="EXACT_EXHAUSTIVE_SEARCH",
                message="plan was evaluated within the complete declared search scope",
            ),
        ),
        plan_sha256="0" * 64,
    )
    payload = plan.model_dump(mode="json")
    payload["plan_sha256"] = None
    return plan.model_copy(update={"plan_sha256": semantic_sha256(payload)}), total
