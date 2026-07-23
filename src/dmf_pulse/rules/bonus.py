"""Generic FPL competition-ranking bonus allocation."""

from __future__ import annotations

from collections.abc import Mapping


def allocate_bonus(
    bps_by_player: Mapping[str, int], rank_awards: Mapping[int, int]
) -> dict[str, int]:
    """Allocate configured awards by competition rank for arbitrary ties and signed BPS."""

    if any(
        not isinstance(rank, int)
        or isinstance(rank, bool)
        or rank <= 0
        or not isinstance(award, int)
        or isinstance(award, bool)
        or award < 0
        for rank, award in rank_awards.items()
    ):
        raise ValueError("bonus rank keys must be positive integers and awards non-negative")

    result = {player_id: 0 for player_id in bps_by_player}
    rank = 1
    for score in sorted(set(bps_by_player.values()), reverse=True):
        group = sorted(player_id for player_id, value in bps_by_player.items() if value == score)
        award = rank_awards.get(rank, 0)
        for player_id in group:
            result[player_id] = award
        rank += len(group)
    return result
