"""Pure Gameweek aggregation of fixture score results."""

from __future__ import annotations

from dmf_pulse.rules.models import (
    CompiledRuleset,
    GameweekScenario,
    GameweekScoreResult,
    PlayerScore,
)
from dmf_pulse.rules.scoring import (
    ensure_ruleset_scoring_allowed,
    score_fixture,
    validate_scenario_ruleset_identity,
)


def score_gameweek(ruleset: CompiledRuleset, scenario: GameweekScenario) -> GameweekScoreResult:
    ensure_ruleset_scoring_allowed(ruleset)
    validate_scenario_ruleset_identity(
        ruleset,
        ruleset_id=scenario.ruleset_id,
        ruleset_version=scenario.ruleset_version,
        ruleset_hash=scenario.ruleset_hash,
    )
    fixture_results = tuple(
        score_fixture(ruleset, fixture)
        for fixture in sorted(scenario.fixtures, key=lambda item: item.fixture_id)
    )
    component_names = tuple(PlayerScore.model_fields)
    components_by_player: dict[str, dict[str, int]] = {}
    for result in fixture_results:
        for player_id, score in result.players.items():
            components = components_by_player.setdefault(
                player_id, {component: 0 for component in component_names}
            )
            for component in component_names:
                components[component] += getattr(score, component)
    players = {
        player_id: PlayerScore.model_validate(components)
        for player_id, components in sorted(components_by_player.items())
    }
    return GameweekScoreResult(
        fixture_ids=tuple(result.fixture_id for result in fixture_results),
        gameweek_id=scenario.gameweek_id,
        players=players,
        player_totals={player_id: score.total for player_id, score in players.items()},
        ruleset_hash=ruleset.ruleset_hash,
        ruleset_id=ruleset.ruleset_id,
        ruleset_version=ruleset.ruleset_version,
        fixture_results=fixture_results,
    )
