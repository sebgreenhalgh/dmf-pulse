"""Adapter to the accepted Stage-2 rules scorer and joint BPS/bonus engine."""

from __future__ import annotations

import hashlib
import importlib
import json
from datetime import UTC, datetime
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


def _parse_approval_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() == UTC.utcoffset(parsed) else None


def _load_approval(path: Path, models: Any) -> Any:
    try:
        return models.ApprovalRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise FplPointsError(
            "RULESET_APPROVAL_INVALID", "ruleset approval record is unavailable or invalid"
        ) from exc


def _load_canonical_json(path: Path, *, code: str) -> tuple[dict[str, Any], bytes]:
    canonical = importlib.import_module("dmf_pulse.rules.canonical")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("activation child must be a JSON object")
        expected = canonical.pretty_rules_json(value).encode("utf-8")
        if raw != expected:
            raise ValueError("activation child is not canonical JSON")
        return value, raw
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise FplPointsError(code, "ruleset activation bundle is unavailable or invalid") from exc


def _load_activation_bundle(
    ruleset_path: Path, compiler: Any, models: Any, approval_path: Path | None
) -> tuple[Any, bool]:
    """Load and cross-check the immutable Stage-2 activation directory.

    An ACTIVE JSON file is not sufficient evidence of activation: all four Stage-2
    children and their manifest hashes must agree.  In particular, an approval file
    supplied from outside the activation directory is never accepted as a substitute.
    """

    integrity = importlib.import_module("dmf_pulse.rules.compiler")
    active_path = ruleset_path.resolve()
    directory = active_path.parent
    expected_names = {
        "verified_ruleset.json",
        "active_ruleset.json",
        "approval.json",
        "activation_receipt.json",
        "activation_manifest.json",
    }
    if active_path.name != "active_ruleset.json" or not directory.is_dir():
        raise FplPointsError(
            "RULESET_ACTIVATION_BUNDLE_REQUIRED",
            "production scoring requires an accepted Stage-2 activation bundle",
        )
    try:
        actual_names = {entry.name for entry in directory.iterdir() if entry.is_file()}
    except OSError as exc:
        raise FplPointsError(
            "RULESET_ACTIVATION_BUNDLE_INVALID", "activation bundle directory is unavailable"
        ) from exc
    if actual_names != expected_names:
        raise FplPointsError(
            "RULESET_ACTIVATION_BUNDLE_INVALID",
            "activation bundle must contain exactly the accepted Stage-2 children",
        )
    if approval_path is not None and approval_path.resolve() != directory / "approval.json":
        raise FplPointsError(
            "RULESET_ACTIVATION_BUNDLE_INVALID",
            "production approval must be the approval child of the activation bundle",
        )
    try:
        verified = compiler.load_compiled_ruleset(directory / "verified_ruleset.json")
        active = compiler.load_compiled_ruleset(active_path)
        approval_value, approval_bytes = _load_canonical_json(
            directory / "approval.json", code="RULESET_ACTIVATION_BUNDLE_INVALID"
        )
        receipt_value, receipt_bytes = _load_canonical_json(
            directory / "activation_receipt.json", code="RULESET_ACTIVATION_BUNDLE_INVALID"
        )
        manifest, _manifest_bytes = _load_canonical_json(
            directory / "activation_manifest.json", code="RULESET_ACTIVATION_BUNDLE_INVALID"
        )
        approval = models.ApprovalRecord.model_validate(approval_value)
        receipt = models.ActivationReceipt.model_validate(receipt_value)
        integrity.ensure_compiled_ruleset_integrity(verified)
        integrity.ensure_compiled_ruleset_integrity(active)
    except RulesError as exc:
        raise FplPointsError(exc.code, exc.message, blockers=exc.blockers) from exc
    except (ValueError, TypeError) as exc:
        raise FplPointsError(
            "RULESET_ACTIVATION_BUNDLE_INVALID", "activation bundle contains invalid metadata"
        ) from exc
    if active_path != (directory / "active_ruleset.json").resolve():
        raise FplPointsError("RULESET_ACTIVATION_BUNDLE_INVALID", "active artifact path is invalid")
    if (
        verified.status.value != "VERIFIED"
        or active.status.value != "ACTIVE"
        or not active.production_eligible
        or (verified.ruleset_id, verified.ruleset_version)
        != (active.ruleset_id, active.ruleset_version)
        or approval.ruleset_id != verified.ruleset_id
        or approval.ruleset_version != verified.ruleset_version
        or not approval.approved
        or approval.approved_at is None
        or approval.approved_by is None
        or not approval.approved_by.strip()
        or not approval.approved_at.endswith("Z")
        or _parse_approval_time(approval.approved_at) is None
        or approval.ruleset_hash != verified.ruleset_hash
        or receipt.ruleset_id != active.ruleset_id
        or receipt.ruleset_version != active.ruleset_version
        or receipt.ruleset_hash != active.ruleset_hash
        or receipt.verified_ruleset_hash != verified.ruleset_hash
        or receipt.approval_sha256 != hashlib.sha256(approval_bytes).hexdigest()
        or receipt.activated_at != approval.approved_at
        or receipt.artifact != directory.as_posix()
    ):
        raise FplPointsError(
            "RULESET_ACTIVATION_BUNDLE_INVALID",
            "activation receipt and approval are not linked to the verified and active rulesets",
        )
    children = manifest.get("children")
    if (
        manifest.get("schema_version") != "1.0"
        or manifest.get("ruleset_id") != active.ruleset_id
        or manifest.get("ruleset_version") != active.ruleset_version
        or manifest.get("active_ruleset_hash") != active.ruleset_hash
        or manifest.get("verified_ruleset_hash") != verified.ruleset_hash
        or not isinstance(children, dict)
        or set(children) != expected_names - {"activation_manifest.json"}
    ):
        raise FplPointsError(
            "RULESET_ACTIVATION_BUNDLE_INVALID", "activation manifest identity is invalid"
        )
    expected_hashes = {
        "verified_ruleset.json": verified.ruleset_hash,
        "active_ruleset.json": active.ruleset_hash,
        "approval.json": verified.ruleset_hash,
        "activation_receipt.json": active.ruleset_hash,
    }
    for filename, expected_hash in expected_hashes.items():
        child = children[filename]
        if (
            not isinstance(child, dict)
            or child.get("ruleset_id") != active.ruleset_id
            or child.get("ruleset_version") != active.ruleset_version
            or child.get("ruleset_hash") != expected_hash
            or child.get("sha256")
            != hashlib.sha256((directory / filename).read_bytes()).hexdigest()
        ):
            raise FplPointsError(
                "RULESET_ACTIVATION_BUNDLE_INVALID",
                "activation manifest child hash does not match its file",
            )
    # Keep the receipt bytes referenced so a malformed/unused child cannot be ignored.
    if hashlib.sha256(receipt_bytes).hexdigest() != children["activation_receipt.json"]["sha256"]:
        raise FplPointsError("RULESET_ACTIVATION_BUNDLE_INVALID", "receipt hash is invalid")
    return approval, True


@runtime_checkable
class RulesEngine(Protocol):
    @property
    def identity(self) -> RulesetIdentity: ...

    def assert_mode_allowed(self, mode: ProjectionMode) -> None: ...

    def score_fixture(self, scenario: FixtureEventScenario) -> dict[str, PlayerScenarioScore]: ...


class AcceptedRulesAdapter:
    """Thin runtime wrapper; all numerical FPL rules remain in ``dmf_pulse.rules``."""

    def __init__(
        self,
        compiled: Any,
        approval: Any | None = None,
        *,
        activation_bundle_verified: bool = False,
    ) -> None:
        self._compiled = compiled
        self._approval = approval
        self._activation_bundle_verified = activation_bundle_verified
        approved = bool(
            activation_bundle_verified
            or (
                approval is not None
                and getattr(approval, "approved", False)
                and getattr(approval, "ruleset_id", None) == compiled.ruleset_id
                and getattr(approval, "ruleset_version", None) == compiled.ruleset_version
                and getattr(approval, "ruleset_hash", None) == compiled.ruleset_hash
            )
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
        activation_bundle_verified = False
        if getattr(getattr(compiled, "status", None), "value", compiled.status) == "ACTIVE":
            approval, activation_bundle_verified = _load_activation_bundle(
                ruleset_path, compiler, models, approval_path
            )
        elif approval_path is not None:
            approval = _load_approval(approval_path, models)
        return cls(
            compiled,
            approval,
            activation_bundle_verified=activation_bundle_verified,
        )

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
            if not self._activation_bundle_verified:
                raise FplPointsError(
                    "RULESET_ACTIVATION_BUNDLE_REQUIRED",
                    "production projection requires an accepted Stage-2 activation bundle",
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
        minutes_by_player = {player.player_id: player.minutes for player in scenario.players}
        bps_values = {
            player_id: score.bps
            for player_id, score in result.players.items()
            if minutes_by_player.get(player_id, 0) > 0
        }
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
