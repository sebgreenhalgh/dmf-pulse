#!/usr/bin/env python3
"""Recompute Stage-9 invariants and, when supplied, exact rules scoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dmf_pulse.football_events import JointScoreDistribution
from dmf_pulse.fpl_points.artifacts import (
    load_verified_model,
    verify_embedded_semantic_hash,
)
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import FixtureProjectionResult, ProjectionMode, SimulationStatus
from dmf_pulse.fpl_points.monte_carlo import monte_carlo_diagnostics
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter, RulesEngine
from dmf_pulse.fpl_points.summaries import (
    build_joint_matrix,
    normalize_weights,
    summarize_fixture_scenarios,
)
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
        if result.result_sha256 is None:
            errors.append("RESULT_SEMANTIC_HASH_REQUIRED")
        try:
            JointScoreDistribution.model_validate(
                result.upstream_score_distribution.model_dump(mode="python")
            )
        except ValueError:
            errors.append("UPSTREAM_STAGE8_IDENTITY_INVALID")
        if rules_engine is None:
            errors.append("RULESET_RECOMPUTE_REQUIRED")
        elif rules_engine.identity != result.ruleset:
            errors.append("RULESET_IDENTITY_MISMATCH")
        if result.joint_matrix is None:
            errors.append("JOINT_MATRIX_MISSING")
        else:
            scenario_map = {scenario.scenario_id: scenario for scenario in result.scenarios}
            normalized_weights = normalize_weights(tuple(item.weight for item in result.scenarios))
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
                if result.joint_matrix.weights[row_index] != normalized_weights[row_index]:
                    errors.append(f"JOINT_WEIGHT_MISMATCH:{scenario_id}")
        if result.monte_carlo_policy is None:
            errors.append("MONTE_CARLO_POLICY_RECOMPUTE_REQUIRED")
        else:
            try:
                diagnostics = monte_carlo_diagnostics(result.scenarios, result.monte_carlo_policy)
                matrix = build_joint_matrix(result.scenarios)
                summaries = summarize_fixture_scenarios(result.scenarios, diagnostics=diagnostics)
            except (FplPointsError, ValueError) as exc:
                errors.append(f"DERIVED_RECOMPUTE_FAILED:{type(exc).__name__}")
            else:
                if result.monte_carlo != diagnostics:
                    errors.append("MONTE_CARLO_DIAGNOSTICS_TAMPERED")
                if result.joint_matrix != matrix:
                    errors.append("JOINT_MATRIX_TAMPERED")
                if result.player_summaries != summaries:
                    errors.append("PLAYER_SUMMARIES_TAMPERED")
        for scenario in result.scenarios:
            event_ids = {player.player_id for player in scenario.event_scenario.players}
            score_ids = set(scenario.players)
            stage7_ids = set(scenario.stage7_player_projection_sha256s)
            if event_ids != score_ids or stage7_ids != score_ids:
                errors.append(f"PARTICIPANT_UNIVERSE_MISMATCH:{scenario.scenario_id}")
            if scenario.upstream_stage8_sha256 != result.upstream_stage8_sha256:
                errors.append(f"UPSTREAM_IDENTITY_MISMATCH:{scenario.scenario_id}")
            if (
                scenario.stage7_minutes_context.semantic_sha256
                != result.upstream_score_distribution.source_minutes_context_sha256
            ):
                errors.append(f"STAGE7_IDENTITY_MISMATCH:{scenario.scenario_id}")
            if rules_engine is not None:
                try:
                    recomputed = rules_engine.score_fixture(scenario.event_scenario)
                except (FplPointsError, RulesError) as exc:
                    errors.append(f"RULES_RECOMPUTE_FAILED:{scenario.scenario_id}:{exc.code}")
                else:
                    if recomputed != scenario.players:
                        errors.append(f"BPS_OR_SCORE_TAMPERED:{scenario.scenario_id}")
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
