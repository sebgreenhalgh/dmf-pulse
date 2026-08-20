"""Adapter to the accepted Stage-2 rules scorer and joint BPS/bonus engine."""

from __future__ import annotations

import hashlib
import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import (
    AssistClassification,
    FixtureEventScenario,
    PlayerScenarioScore,
    ProjectionMode,
    RulesetActivationEvidence,
    RulesetIdentity,
)
from dmf_pulse.rules.errors import RulesError
from dmf_pulse.rules.models import AssistDecisionContext


def _parse_approval_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() == UTC.utcoffset(parsed) else None


def _load_canonical_json(path: Path, *, code: str) -> tuple[dict[str, Any], bytes]:
    canonical = importlib.import_module("dmf_pulse.rules.canonical")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict) or raw != canonical.pretty_rules_json(value).encode("utf-8"):
            raise ValueError("activation child is not canonical JSON")
        return value, raw
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise FplPointsError(code, "ruleset activation bundle is unavailable or invalid") from exc


def _load_activation_bundle(
    ruleset_path: Path, compiler: Any, models: Any, approval_path: Path | None
) -> tuple[Any, RulesetActivationEvidence]:
    """Load and cryptographically cross-check the immutable Stage-2 activation bundle."""

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
        actual_names = {entry.name for entry in directory.iterdir()}
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
        manifest, manifest_bytes = _load_canonical_json(
            directory / "activation_manifest.json", code="RULESET_ACTIVATION_BUNDLE_INVALID"
        )
        approval = models.ApprovalRecord.model_validate(approval_value)
        receipt = models.ActivationReceipt.model_validate(receipt_value)
    except RulesError as exc:
        raise FplPointsError(exc.code, exc.message, blockers=exc.blockers) from exc
    except (ValueError, TypeError) as exc:
        raise FplPointsError(
            "RULESET_ACTIVATION_BUNDLE_INVALID", "activation bundle contains invalid metadata"
        ) from exc
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
        or receipt.artifact not in {directory.as_posix(), ruleset_path.parent.as_posix()}
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
    try:
        child_bytes = {
            "verified_ruleset.json": (directory / "verified_ruleset.json").read_bytes(),
            "active_ruleset.json": (directory / "active_ruleset.json").read_bytes(),
            "approval.json": approval_bytes,
            "activation_receipt.json": receipt_bytes,
        }
    except OSError as exc:
        raise FplPointsError(
            "RULESET_ACTIVATION_BUNDLE_INVALID", "activation bundle child is unavailable"
        ) from exc
    for filename, expected_hash in expected_hashes.items():
        child = children[filename]
        if (
            not isinstance(child, dict)
            or child.get("ruleset_id") != active.ruleset_id
            or child.get("ruleset_version") != active.ruleset_version
            or child.get("ruleset_hash") != expected_hash
            or child.get("sha256") != hashlib.sha256(child_bytes[filename]).hexdigest()
        ):
            raise FplPointsError(
                "RULESET_ACTIVATION_BUNDLE_INVALID",
                "activation manifest child hash does not match its file",
            )
    return active, RulesetActivationEvidence(
        ruleset_id=active.ruleset_id,
        ruleset_version=active.ruleset_version,
        verified_ruleset_hash=verified.ruleset_hash,
        active_ruleset_hash=active.ruleset_hash,
        approval_sha256=hashlib.sha256(approval_bytes).hexdigest(),
        activation_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
        activation_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )


@runtime_checkable
class RulesEngine(Protocol):
    @property
    def identity(self) -> RulesetIdentity: ...

    def assert_mode_allowed(self, mode: ProjectionMode) -> None: ...

    @property
    def uses_versioned_assist_policy(self) -> bool: ...

    def classify_generated_assist(
        self, context: AssistDecisionContext
    ) -> AssistClassification | None: ...

    def score_fixture(self, scenario: FixtureEventScenario) -> dict[str, PlayerScenarioScore]: ...


class AcceptedRulesAdapter:
    """Thin runtime wrapper; all numerical FPL rules remain in ``dmf_pulse.rules``."""

    def __init__(self, compiled: Any) -> None:
        self._compiled = compiled
        self._activation_evidence: RulesetActivationEvidence | None = None
        self._scoring_integrity_verified = False
        self._set_identity()

    def _set_identity(self) -> None:
        compiled = self._compiled
        self._identity = RulesetIdentity(
            ruleset_id=compiled.ruleset_id,
            ruleset_version=compiled.ruleset_version,
            ruleset_hash=compiled.ruleset_hash,
            status=str(
                compiled.status.value if hasattr(compiled.status, "value") else compiled.status
            ),
            production_eligible=bool(compiled.production_eligible),
            human_approval_recorded=self._activation_evidence is not None,
            unknown_blockers=tuple(compiled.unknown_blockers),
            activation_evidence=self._activation_evidence,
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
        if approval_path is not None:
            approval_path = approval_path.resolve()
        if getattr(getattr(compiled, "status", None), "value", compiled.status) == "ACTIVE":
            compiled, evidence = _load_activation_bundle(
                ruleset_path, compiler, models, approval_path
            )
            adapter = cls(compiled)
            adapter._activation_evidence = evidence
            adapter._set_identity()
            return adapter
        return cls(compiled)

    @property
    def identity(self) -> RulesetIdentity:
        return self._identity

    @property
    def uses_versioned_assist_policy(self) -> bool:
        return getattr(self._compiled, "schema_version", "1.0") == "1.1"

    def assert_mode_allowed(self, mode: ProjectionMode) -> None:
        identity = self.identity
        if mode is not ProjectionMode.PRODUCTION and self._player_points_eligible():
            return
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
            if (
                identity.activation_evidence is None
                or identity.activation_evidence.active_ruleset_hash != identity.ruleset_hash
            ):
                raise FplPointsError(
                    "RULESET_ACTIVATION_BUNDLE_REQUIRED",
                    "production projection requires an accepted Stage-2 activation bundle",
                )
        elif identity.status not in {"REFERENCE_ONLY", "VERIFIED", "ACTIVE"}:
            raise FplPointsError(
                "RULESET_SCORING_BLOCKED",
                "non-production scoring requires a complete reference, verified, or active ruleset",
            )

    def _player_points_eligible(self) -> bool:
        """Permit scoped schema-v1.1 raw scoring without global activation."""

        if getattr(self._compiled, "schema_version", "1.0") != "1.1":
            return False
        capabilities = importlib.import_module("dmf_pulse.rules.capabilities")
        models = importlib.import_module("dmf_pulse.rules.models")
        artifact = capabilities.compile_capability_artifact(
            self._compiled, models.RuleCapability.PLAYER_POINTS
        )
        return bool(artifact.production_eligible)

    def classify_generated_assist(
        self, context: AssistDecisionContext
    ) -> AssistClassification | None:
        """Resolve a generated fact pattern only through compiled schema-v1.1 policy."""

        if getattr(self._compiled, "schema_version", "1.0") != "1.1":
            return None
        assists = importlib.import_module("dmf_pulse.rules.assists")
        return AssistClassification(assists.classify_assist(self._compiled, context).value)

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
            for goal in scenario.goals:
                if goal.assist_context is None:
                    if goal.assist_classification is AssistClassification.AMBIGUOUS_ASSIST:
                        raise FplPointsError(
                            "RULESET_ASSIST_AMBIGUOUS",
                            "schema-v1.1 exact scoring rejects an unresolved assist",
                        )
                    if goal.assister_player_id is None:
                        continue
                    raise FplPointsError(
                        "RULESET_ASSIST_CONTEXT_REQUIRED",
                        "schema-v1.1 assists require a typed goal-chain context",
                    )
                resolved = self.classify_generated_assist(goal.assist_context)
                if resolved is None or resolved is AssistClassification.AMBIGUOUS_ASSIST:
                    raise FplPointsError(
                        "RULESET_ASSIST_AMBIGUOUS",
                        "schema-v1.1 exact scoring rejects an unresolved assist",
                    )
                expected_award = resolved is AssistClassification.DEFINITE_ASSIST
                if (
                    resolved is not goal.assist_classification
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
            result_players = self._score_accepted_fixture(scoring, models, accepted)
        except RulesError as exc:
            raise FplPointsError(exc.code, exc.message, blockers=exc.blockers) from exc
        minutes_by_player = {player.player_id: player.minutes for player in scenario.players}
        bps_values = {
            player_id: score.bps
            for player_id, score in result_players.items()
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
            for player_id, score in result_players.items()
        }

    def _score_accepted_fixture(self, scoring: Any, models: Any, accepted: Any) -> dict[str, Any]:
        """Score through the immutable Stage-2 compiled ruleset without rehashing it per draw."""

        # The test seam deliberately supplies a minimal scoring double. Production
        # code always follows the exact Stage-2 primitive path below.
        if not hasattr(scoring, "_components"):
            return cast(dict[str, Any], scoring.score_fixture(self._compiled, accepted).players)
        if not self._scoring_integrity_verified:
            scoring.ensure_ruleset_scoring_allowed(self._compiled)
            self._scoring_integrity_verified = True
        if self._compiled.schema_version == "1.1":
            for player in accepted.players:
                scoring.validate_v11_save_contract(player)
        scoring.validate_scenario_ruleset_identity(
            self._compiled,
            ruleset_id=accepted.ruleset_id,
            ruleset_version=accepted.ruleset_version,
            ruleset_hash=accepted.ruleset_hash,
        )
        calculated = {
            player.player_id: scoring._components(self._compiled, player)
            for player in accepted.players
        }
        eligible_bps = {
            player.player_id: calculated[player.player_id][1]
            for player in accepted.players
            if player.minutes > 0
        }
        bonus = scoring.allocate_bonus(eligible_bps, scoring._bonus_rank_awards(self._compiled))
        return {
            player.player_id: models.PlayerScore(
                **components,
                bonus=bonus.get(player.player_id, 0),
                bps=bps,
                total=sum(components.values()) + bonus.get(player.player_id, 0),
            )
            for player in sorted(accepted.players, key=lambda item: item.player_id)
            for components, bps in (calculated[player.player_id],)
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
