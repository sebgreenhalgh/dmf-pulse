"""Adapter to the accepted Stage-2 rules scorer and joint BPS/bonus engine."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import (
    FixtureEventScenario,
    PlayerScenarioScore,
    ProjectionMode,
    RulesetIdentity,
)
from dmf_pulse.rules.errors import RulesError


@runtime_checkable
class RulesEngine(Protocol):
    @property
    def identity(self) -> RulesetIdentity: ...

    def assert_mode_allowed(self, mode: ProjectionMode) -> None: ...

    def score_fixture(self, scenario: FixtureEventScenario) -> dict[str, PlayerScenarioScore]: ...


class AcceptedRulesAdapter:
    """Thin runtime wrapper; all numerical FPL rules remain in ``dmf_pulse.rules``."""

    def __init__(self, compiled: Any, approval: Any | None = None) -> None:
        self._compiled = compiled
        self._approval = approval
        approved = bool(
            approval is not None
            and getattr(approval, "approved", False)
            and getattr(approval, "ruleset_id", None) == compiled.ruleset_id
            and getattr(approval, "ruleset_version", None) == compiled.ruleset_version
            and getattr(approval, "ruleset_hash", None) == compiled.ruleset_hash
        )
        self._identity = RulesetIdentity(
            ruleset_id=compiled.ruleset_id,
            ruleset_version=compiled.ruleset_version,
            ruleset_hash=compiled.ruleset_hash,
            status=str(
                compiled.status.value if hasattr(compiled.status, "value") else compiled.status
            ),
            production_eligible=bool(compiled.production_eligible),
            human_approval_recorded=approved,
            unknown_blockers=tuple(compiled.unknown_blockers),
        )

    @classmethod
    def from_paths(
        cls, ruleset_path: Path, approval_path: Path | None = None
    ) -> AcceptedRulesAdapter:
        compiler = importlib.import_module("dmf_pulse.rules.compiler")
        models = importlib.import_module("dmf_pulse.rules.models")
        try:
            compiled = compiler.load_compiled_ruleset(ruleset_path)
        except RulesError as exc:
            raise FplPointsError(exc.code, exc.message, blockers=exc.blockers) from exc
        approval = None
        if approval_path is not None:
            try:
                approval = models.ApprovalRecord.model_validate(
                    json.loads(approval_path.read_text(encoding="utf-8"))
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise FplPointsError(
                    "RULESET_APPROVAL_INVALID", "ruleset approval record is unavailable or invalid"
                ) from exc
        return cls(compiled, approval)

    @property
    def identity(self) -> RulesetIdentity:
        return self._identity

    def assert_mode_allowed(self, mode: ProjectionMode) -> None:
        identity = self.identity
        if identity.unknown_blockers:
            raise FplPointsError(
                "RULESET_SCORING_BLOCKED",
                "ruleset has unresolved blocking fields",
                blockers=identity.unknown_blockers,
            )
        if mode is ProjectionMode.PRODUCTION:
            if identity.status != "ACTIVE":
                raise FplPointsError(
                    "RULESET_NOT_ACTIVE", "production projection requires an ACTIVE ruleset"
                )
            if not identity.production_eligible:
                raise FplPointsError(
                    "RULESET_NOT_PRODUCTION_ELIGIBLE",
                    "production projection requires production_eligible=true",
                )
            if not identity.human_approval_recorded:
                raise FplPointsError(
                    "RULESET_APPROVAL_MISSING", "production projection requires human approval"
                )
        elif identity.status not in {"REFERENCE_ONLY", "VERIFIED", "ACTIVE"}:
            raise FplPointsError(
                "RULESET_SCORING_BLOCKED",
                "TEST/REPLAY requires a complete reference, verified, or active ruleset",
            )

    def score_fixture(self, scenario: FixtureEventScenario) -> dict[str, PlayerScenarioScore]:
        if (
            scenario.ruleset_id,
            scenario.ruleset_version,
            scenario.ruleset_hash,
        ) != (
            self.identity.ruleset_id,
            self.identity.ruleset_version,
            self.identity.ruleset_hash,
        ):
            raise FplPointsError(
                "RULESET_SCENARIO_MISMATCH", "scenario and selected ruleset identity differ"
            )
        models = importlib.import_module("dmf_pulse.rules.models")
        scoring = importlib.import_module("dmf_pulse.rules.scoring")
        if getattr(self._compiled, "schema_version", "1.0") == "1.1":
            assists = importlib.import_module("dmf_pulse.rules.assists")
            for goal in scenario.goals:
                if goal.assist_context is None:
                    if goal.assister_player_id is None:
                        continue
                    raise FplPointsError(
                        "RULESET_ASSIST_CONTEXT_REQUIRED",
                        "schema-v1.1 assists require a typed goal-chain context",
                    )
                resolved = assists.classify_assist(self._compiled, goal.assist_context)
                expected_award = resolved.value == "DEFINITE_ASSIST"
                if (
                    resolved.value != goal.assist_classification.value
                    or goal.assist_awarded != expected_award
                    or (goal.assister_player_id is not None) != expected_award
                ):
                    raise FplPointsError(
                        "RULESET_ASSIST_CLASSIFICATION",
                        "goal-chain context and awarded assist disagree with compiled policy",
                    )
        players = tuple(
            models.PlayerScenario(
                player_id=player.player_id,
                team_id=player.team_id,
                position=models.FPLPosition(player.position.value),
                minutes=player.minutes,
                goals_non_penalty=player.goals_non_penalty,
                goals_penalty=player.goals_penalty,
                eligible_assists=player.eligible_assists,
                goals_conceded_while_eligible=player.goals_conceded_while_eligible,
                saves=player.saves,
                penalty_saves=player.penalty_saves,
                penalty_misses=player.penalty_misses,
                yellow_cards=player.yellow_cards,
                red_cards=player.red_cards,
                own_goals=player.own_goals,
                defensive_actions=models.DefensiveActions.model_validate(
                    player.defensive_actions.model_dump(mode="python")
                ),
                bps=models.BpsEvents.model_validate(player.bps.model_dump(mode="python")),
                dismissed=player.dismissed,
                team_goals_after_dismissal=player.team_goals_after_dismissal,
            )
            for player in scenario.players
        )
        accepted = models.FixtureScenario(
            fixture_id=scenario.fixture_id,
            gameweek_id=scenario.gameweek_id,
            home_team_id=scenario.home_team_id,
            away_team_id=scenario.away_team_id,
            home_goals=scenario.home_goals,
            away_goals=scenario.away_goals,
            participant_universe_complete=True,
            players=players,
            ruleset_id=scenario.ruleset_id,
            ruleset_version=scenario.ruleset_version,
            ruleset_hash=scenario.ruleset_hash,
        )
        try:
            result = scoring.score_fixture(self._compiled, accepted)
        except RulesError as exc:
            raise FplPointsError(exc.code, exc.message, blockers=exc.blockers) from exc
        bps_values = {player_id: score.bps for player_id, score in result.players.items()}
        ranks = competition_ranks(bps_values)
        tie_counts: dict[int, int] = {}
        for rank in ranks.values():
            tie_counts[rank] = tie_counts.get(rank, 0) + 1
        return {
            player_id: PlayerScenarioScore(
                **score.model_dump(mode="python"),
                bps_competition_rank=ranks.get(player_id),
                bps_tied_at_rank=tie_counts.get(ranks.get(player_id, -1), 0) > 1,
            )
            for player_id, score in result.players.items()
        }


def competition_ranks(values: dict[str, int]) -> dict[str, int]:
    """Exact competition ranks from one scenario's integer BPS vector."""

    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    result: dict[str, int] = {}
    previous_value: int | None = None
    previous_rank = 0
    for index, (player_id, value) in enumerate(ordered, start=1):
        rank = previous_rank if value == previous_value else index
        result[player_id] = rank
        previous_value = value
        previous_rank = rank
    return result


def rank_expected_bps(_: dict[str, float]) -> None:
    """Prohibit the anti-pattern explicitly rather than leaving it undocumented."""

    raise FplPointsError(
        "EXPECTED_BPS_RANKING_PROHIBITED",
        "bonus must be ranked jointly inside each scenario, never from expected BPS",
    )
