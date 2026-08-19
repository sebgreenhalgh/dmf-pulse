"""Deterministic competition-rank primitives shared by Stage-15 simulators."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from dmf_pulse.rank_strategy.models import RankMass


def competition_ranks(
    final_state: Mapping[str, tuple[int, int]],
) -> dict[str, int]:
    """Return exact classic ranks from points and counted-transfer state.

    A manager is outranked by every manager with more points, or equal points and
    fewer counted transfers. Equal points and equal counted transfers therefore
    share the same competition rank.
    """

    return {
        manager_id: 1
        + sum(
            other_points > points or (other_points == points and other_transfers < transfers)
            for other_id, (other_points, other_transfers) in final_state.items()
            if other_id != manager_id
        )
        for manager_id, (points, transfers) in final_state.items()
    }


def rank_probability_mass(outcomes: Iterable[tuple[int, float]]) -> tuple[RankMass, ...]:
    mass: dict[int, float] = {}
    for rank, weight in outcomes:
        mass[rank] = mass.get(rank, 0.0) + weight
    return tuple(
        RankMass(rank=rank, probability=probability) for rank, probability in sorted(mass.items())
    )


def weighted_rank_quantile(pmf: tuple[RankMass, ...], probability: float) -> int:
    cumulative = 0.0
    for item in pmf:
        cumulative += item.probability
        if cumulative + 1e-15 >= probability:
            return item.rank
    return pmf[-1].rank
