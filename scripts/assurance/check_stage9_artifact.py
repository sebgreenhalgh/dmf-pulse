#!/usr/bin/env python3
"""Recompute Stage-9 invariants and, when supplied, exact rules scoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dmf_pulse.football_events import JointScoreDistribution
from dmf_pulse.fpl_points.artifacts import (
    load_verified_model,
    semantic_sha256,
    verify_embedded_semantic_hash,
)
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import FixtureProjectionResult, ProjectionMode, SimulationStatus
from dmf_pulse.fpl_points.monte_carlo import monte_carlo_diagnostics
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter, RulesEngine
from dmf_pulse.fpl_points.service import generate_fixture_scenarios
from dmf_pulse.fpl_points.summaries import build_joint_matrix, summarize_fixture_scenarios
from dmf_pulse.rules.errors import RulesError


def validate_projection(
    result: FixtureProjectionResult, rules_engine: RulesEngine | None = None
) -> list[str]:
    errors: list[str] = []
    try:
        verify_embedded_semantic_hash(result)
    except FplPointsError as exc:
        errors.append(exc.code)
    if result.status is SimulationStatus.SUCCESS:
        try:
            JointScoreDistribution.model_validate(
                result.upstream_score_distribution.model_dump(mode="python")
            )
        except ValueError:
            errors.append("UPSTREAM_STAGE8_IDENTITY_INVALID")
        if rules_engine is None:
            errors.append("RULESET_RECOMPUTE_REQUIRED")
        elif not isinstance(rules_engine, AcceptedRulesAdapter):
            errors.append("RULESET_RECOMPUTE_ENGINE_INVALID")
        elif rules_engine.identity != result.ruleset:
            errors.append("RULESET_IDENTITY_MISMATCH")
        if semantic_sha256(result.simulation_request) != result.simulation_request_sha256:
            errors.append("SIMULATION_REQUEST_HASH_MISMATCH")
        request = result.simulation_request
        if (
            request.score_distribution != result.upstream_score_distribution
            or request.score_distribution.result_sha256 != result.upstream_stage8_sha256
            or request.projection_mode is not result.projection_mode
        ):
            errors.append("SIMULATION_REQUEST_IDENTITY_MISMATCH")
        if result.joint_matrix is None:
            errors.append("JOINT_MATRIX_MISSING")
        else:
            scenario_map = {scenario.scenario_id: scenario for scenario in result.scenarios}
            for row_index, scenario_id in enumerate(result.joint_matrix.scenario_ids):
                scenario = scenario_map.get(scenario_id)
                if scenario is None:
                    errors.append(f"JOINT_SCENARIO_UNKNOWN:{scenario_id}")
                    continue
                expected = tuple(
                    scenario.players[player_id].total
                    for player_id in result.joint_matrix.player_ids
                )
                if result.joint_matrix.points[row_index] != expected:
                    errors.append(f"JOINT_ROW_MISMATCH:{scenario_id}")
                if result.joint_matrix.outcome_draw_ids[row_index] != scenario.outcome_draw_id:
                    errors.append(f"JOINT_DRAW_MISMATCH:{scenario_id}")
        if (
            isinstance(rules_engine, AcceptedRulesAdapter)
            and rules_engine.identity == result.ruleset
        ):
            for scenario in result.scenarios:
                try:
                    recomputed_scores = rules_engine.score_fixture(scenario.event_scenario)
                except (FplPointsError, RulesError) as exc:
                    errors.append(f"RULES_RECOMPUTE_FAILED:{scenario.scenario_id}:{exc.code}")
                else:
                    if recomputed_scores != scenario.players:
                        errors.append(f"BPS_OR_SCORE_TAMPERED:{scenario.scenario_id}")
            try:
                regenerated = generate_fixture_scenarios(
                    request, rules_engine, range(request.scenario_count)
                )
            except (FplPointsError, RulesError) as exc:
                errors.append(f"SCENARIO_REGENERATION_FAILED:{exc.code}")
            else:
                if regenerated != result.scenarios:
                    errors.append("SCENARIO_REGENERATION_MISMATCH")
                diagnostics = monte_carlo_diagnostics(regenerated, result.monte_carlo_policy)
                summaries = summarize_fixture_scenarios(regenerated, diagnostics=diagnostics)
                matrix = build_joint_matrix(regenerated)
                if result.joint_matrix != matrix:
                    errors.append("JOINT_MATRIX_RECOMPUTE_MISMATCH")
                if result.player_summaries != summaries:
                    errors.append("SUMMARY_RECOMPUTE_MISMATCH")
                if result.monte_carlo != diagnostics:
                    errors.append("MONTE_CARLO_RECOMPUTE_MISMATCH")
    if (
        result.projection_mode is ProjectionMode.PRODUCTION
        and result.status is SimulationStatus.SUCCESS
    ):
        identity = result.ruleset
        if (
            identity.status != "ACTIVE"
            or not identity.production_eligible
            or not identity.human_approval_recorded
            or identity.unknown_blockers
        ):
            errors.append("PRODUCTION_RULESET_GATE_BYPASSED")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--ruleset", type=Path, required=True)
    parser.add_argument("--approval", type=Path)
    args = parser.parse_args()
    try:
        result = load_verified_model(args.artifact, FixtureProjectionResult)
        engine = AcceptedRulesAdapter.from_paths(args.ruleset, args.approval)
        errors = validate_projection(result, engine)
    except FplPointsError as exc:
        errors = [exc.code]
    print(
        json.dumps(
            {
                "schema_version": "pts-009-artifact-assurance-v1",
                "status": "PASS" if not errors else "FAIL",
                "errors": errors,
            },
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
