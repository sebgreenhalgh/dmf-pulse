"""Independent plan validation entry point."""

from __future__ import annotations

from dmf_pulse.fpl_points.models import GameweekProjectionResult
from dmf_pulse.optimisation.legality import validate_squad_legality, validate_tactical_configuration
from dmf_pulse.optimisation.models import (
    LegalityReport,
    OneGameweekOptimisationRequest,
    OneGameweekPlan,
)
from dmf_pulse.rules.models import CapabilityArtifact, CompiledRuleset
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view


def validate_plan_against_request(
    request: OneGameweekOptimisationRequest,
    projection: GameweekProjectionResult,
    rules: CompiledRuleset,
    plan: OneGameweekPlan,
    *,
    capability: CapabilityArtifact | None = None,
) -> LegalityReport:
    view = build_one_gameweek_rules_view(
        rules, projection_mode=request.projection_mode, capability=capability
    )
    players = {item.player_id: item for item in request.candidate_pool.candidates}
    squad_report = validate_squad_legality(plan.candidate_squad, players, view)
    tactic_report = validate_tactical_configuration(
        plan.candidate_squad, plan.tactical_configuration, players, view
    )
    return LegalityReport(
        legal=squad_report.legal and tactic_report.legal,
        issues=squad_report.issues + tactic_report.issues,
    )
