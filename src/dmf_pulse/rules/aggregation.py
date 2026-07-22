"""Pure Gameweek aggregation of fixture score results."""

from __future__ import annotations

from dmf_pulse.rules.models import CompiledRuleset, GameweekScenario, GameweekScoreResult
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
    totals: dict[str, int] = {}
    for result in fixture_results:
        for player_id, score in result.players.items():
            totals[player_id] = totals.get(player_id, 0) + score.total
    return GameweekScoreResult(
        fixture_ids=tuple(result.fixture_id for result in fixture_results),
        gameweek_id=scenario.gameweek_id,
        player_totals=dict(sorted(totals.items())),
        ruleset_hash=ruleset.ruleset_hash,
        ruleset_id=ruleset.ruleset_id,
        fixture_results=fixture_results,
    )
