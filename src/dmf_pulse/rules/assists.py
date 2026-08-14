"""Pure versioned assist-eligibility classification."""

from __future__ import annotations

from typing import Any, cast

from dmf_pulse.rules.errors import RulesIntegrityError
from dmf_pulse.rules.models import (
    AssistAction,
    AssistDecisionContext,
    AssistEligibility,
    AssistGoalKind,
    AssistReboundIntervention,
    AssistReceptionZone,
    AssistSetPieceRoute,
    CompiledRuleset,
)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RulesIntegrityError("RULESET_ASSIST_CONFIG", f"compiled mapping is invalid: {label}")
    return cast(dict[str, Any], value)


def _listed(value: object, item: str, label: str) -> bool:
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise RulesIntegrityError("RULESET_ASSIST_CONFIG", f"compiled list is invalid: {label}")
    return item in value


def classify_assist(ruleset: CompiledRuleset, context: AssistDecisionContext) -> AssistEligibility:
    """Classify exact goal-chain facts using only compiled assist policy data."""

    assists = _mapping(ruleset.rules.get("assists"), "assists")
    policy = _mapping(assists.get("eligibility_policy"), "assists.eligibility_policy")
    if context.candidate_is_scorer:
        return AssistEligibility.DEFINITE_NO_ASSIST

    set_pieces = _mapping(policy.get("set_pieces"), "assists.set_pieces")
    if context.goal_kind in {AssistGoalKind.DIRECT_PENALTY, AssistGoalKind.DIRECT_FREE_KICK}:
        if context.set_piece_route is AssistSetPieceRoute.FOUL_WON:
            return AssistEligibility.DEFINITE_ASSIST
        if context.set_piece_route is AssistSetPieceRoute.CORNER_OR_THROW_IN:
            return AssistEligibility.DEFINITE_NO_ASSIST
        if context.set_piece_route is AssistSetPieceRoute.HANDBALL_AFTER_PASS_TOUCH:
            handball = _mapping(set_pieces.get("handball"), "assists.set_pieces.handball")
            pass_policy = _mapping(handball.get("pass_or_touch"), "assists.handball.pass_or_touch")
            return (
                AssistEligibility.DEFINITE_NO_ASSIST
                if context.defensive_touches > 0
                and pass_policy.get("defensive_touch_before_handball_disqualifies") is True
                else AssistEligibility.DEFINITE_ASSIST
            )
        if context.set_piece_route is AssistSetPieceRoute.HANDBALL_AFTER_SHOT:
            handball = _mapping(set_pieces.get("handball"), "assists.set_pieces.handball")
            shot_policy = _mapping(handball.get("shot"), "assists.handball.shot")
            if (
                shot_policy.get("direct_shot_required") is not True
                or shot_policy.get("on_target_before_deflection_required") is not True
                or shot_policy.get("on_target_after_deflection_required") is not True
            ):
                raise RulesIntegrityError(
                    "RULESET_ASSIST_CONFIG", "handball-shot policy is invalid"
                )
            return (
                AssistEligibility.DEFINITE_ASSIST
                if context.action in {AssistAction.SHOT, AssistAction.CROSS_SHOT}
                and context.shot_on_target_before_deflection
                and context.shot_on_target_after_deflection
                else AssistEligibility.DEFINITE_NO_ASSIST
            )
        return AssistEligibility.DEFINITE_NO_ASSIST

    if context.scorer_loses_and_regains_possession:
        return AssistEligibility.DEFINITE_NO_ASSIST
    if not _listed(policy.get("eligible_attacking_actions"), context.action.value, "actions"):
        return AssistEligibility.DEFINITE_NO_ASSIST
    if (
        context.action is AssistAction.INADVERTENT_TOUCH
        and not context.inadvertent_touch_reaches_scorer_directly
    ):
        return AssistEligibility.DEFINITE_NO_ASSIST
    if context.action in {AssistAction.PASS, AssistAction.CROSS, AssistAction.INADVERTENT_TOUCH}:
        touches = _mapping(policy.get("defensive_touches"), "assists.defensive_touches")
        if (
            context.scorer_reception_zone is AssistReceptionZone.OUTSIDE_BOX
            and not context.intended_for_scorer
        ):
            return AssistEligibility.DEFINITE_NO_ASSIST
        if context.defensive_touches >= 2:
            return AssistEligibility.DEFINITE_NO_ASSIST
        if context.defensive_touches == 1:
            if context.defensive_touch_is_pass:
                return AssistEligibility.DEFINITE_NO_ASSIST
            zone = (
                "inside_box"
                if context.scorer_reception_zone is AssistReceptionZone.INSIDE_BOX
                else "outside_box"
            )
            zone_policy = _mapping(touches.get(zone), f"assists.defensive_touches.{zone}")
            if (
                zone_policy.get("intended_destination_required") is True
                and not context.intended_for_scorer
            ):
                return AssistEligibility.DEFINITE_NO_ASSIST
        return AssistEligibility.DEFINITE_ASSIST
    if context.action in {AssistAction.SHOT, AssistAction.CROSS_SHOT}:
        rebounds = _mapping(policy.get("rebounds"), "assists.rebounds")
        if context.rebound_intervention is AssistReboundIntervention.NONE:
            return AssistEligibility.DEFINITE_NO_ASSIST
        if not _listed(
            rebounds.get("qualifying_interventions"),
            context.rebound_intervention.value,
            "assists.rebounds.qualifying_interventions",
        ):
            return AssistEligibility.DEFINITE_NO_ASSIST
        if context.defensive_touch_after_rebound or context.scorer_converts_own_rebound:
            return AssistEligibility.DEFINITE_NO_ASSIST
        return AssistEligibility.DEFINITE_ASSIST
    if (
        context.goal_kind is AssistGoalKind.OWN_GOAL
        and context.action is AssistAction.FORCED_OWN_GOAL_ACTION
    ):
        return AssistEligibility.DEFINITE_ASSIST
    return AssistEligibility.DEFINITE_NO_ASSIST
