"""Generic FPL competition-ranking bonus allocation."""

from __future__ import annotations

from collections.abc import Mapping


def allocate_bonus(bps_by_player: Mapping[str, int]) -> dict[str, int]:
    """Allocate 3/2/1 by competition rank for arbitrary ties and signed BPS."""

    result = {player_id: 0 for player_id in bps_by_player}
    rank = 1
    for score in sorted(set(bps_by_player.values()), reverse=True):
        group = sorted(player_id for player_id, value in bps_by_player.items() if value == score)
        award = {1: 3, 2: 2, 3: 1}.get(rank, 0)
        for player_id in group:
            result[player_id] = award
        rank += len(group)
    return result
