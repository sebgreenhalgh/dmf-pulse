"""Independent tiny oracle; it intentionally does not import production search components."""

from __future__ import annotations

from fractions import Fraction

from dmf_pulse.fpl_points.models import GameweekPointScenario


def simple_expected_starting_xi(
    scenarios: tuple[GameweekPointScenario, ...],
    starting_xi: tuple[str, ...],
    captain: str,
) -> Fraction:
    total = Fraction(0)
    for scenario in scenarios:
        score = sum(scenario.player_points[player] for player in starting_xi)
        if scenario.player_appeared[captain]:
            score += scenario.player_points[captain]
        total += Fraction(str(scenario.weight)) * score
    return total
