"""Offline synthetic convergence and golden evidence; no provider factory."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from decimal import Decimal
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from dmf_pulse.assurance.canonical import canonical_sha256  # noqa: E402
from dmf_pulse.evaluation.team_strength_mixture_analysis import (  # noqa: E402
    compare_distributions,
    distribution_features,
)
from dmf_pulse.football_events.service import ScoreDistributionService  # noqa: E402
from dmf_pulse.football_events.team_strength_adapter import fixture_prior_bundle  # noqa: E402
from dmf_pulse.football_events.team_strength_mixture_stage8 import (  # noqa: E402
    project_parameter_mixture,
)
from dmf_pulse.football_events.team_strength_numerics import reconstruct  # noqa: E402
from dmf_pulse.football_events.team_strength_parameter_draws import (  # noqa: E402
    covariance_factor,
    draw_policy,
    joint_parameter_draws,
    unpack_triangle,
)
from tests.unit.football_events.team_strength_support import (  # noqa: E402
    synthetic_artifact,
    synthetic_dataset,
)
from tests.unit.football_events.test_team_strength_adapter import (  # noqa: E402
    bundle,
    stage8_request,
)

EVIDENCE = ROOT / "evidence/tickets/CURRENT-TEAM-STRENGTH-001U"
COUNTS = (64, 128, 256, 512, 1024, 2048, 4096, 8192)


def numerical() -> dict:
    artifact = synthetic_artifact()
    n = len(artifact.model.effects)
    p = len(artifact.model.uncertainty.parameter_order)
    covariance = unpack_triangle(artifact.model.uncertainty.covariance, p)
    information = unpack_triangle(artifact.model.uncertainty.information, p)
    factor = covariance_factor(covariance)
    draws = joint_parameter_draws(artifact, policy=draw_policy(seed=23, draw_count=2048))
    report = {
        "classification": "SYNTHETIC_LOCAL_LAPLACE_GAUSSIAN_RESEARCH_ONLY",
        "fit_sha256": artifact.semantic_sha256,
        "draw_set_sha256": draws.semantic_sha256,
        "draw_policy_sha256": draws.draw_policy_sha256,
        "dimension": p,
        "teams": n,
        "parameter_order": artifact.model.uncertainty.parameter_order,
        "covariance_sha256": draws.covariance_sha256,
        "parameter_order_sha256": draws.parameter_order_sha256,
        "minimum_cholesky_diagonal": min(factor[i][i] for i in range(p)),
        "covariance_factor_max_absolute_residual": max(
            abs(math.fsum(factor[i][k] * factor[j][k] for k in range(p)) - covariance[i][j])
            for i in range(p)
            for j in range(p)
        ),
        "information_covariance_max_identity_residual": max(
            abs(math.fsum(information[i][k] * covariance[k][j] for k in range(p)) - float(i == j))
            for i in range(p)
            for j in range(p)
        ),
        "max_draw_identifiability_residual": max(
            abs(
                math.fsum(
                    reconstruct(tuple(float(x) for x in row.free_parameters[start : start + n - 1]))
                )
            )
            for row in draws.draws
            for start in (2, n + 1)
        ),
        "accepted_fit_numerics": artifact.model.numerics.model_dump(mode="json"),
        "production_active": False,
    }
    report["semantic_sha256"] = canonical_sha256(report)
    return report


def golden() -> dict:
    artifact = synthetic_artifact()
    bound = bundle()
    draws = joint_parameter_draws(artifact, policy=draw_policy(seed=23, draw_count=16))
    result = {
        "fit_artifact": artifact.model_dump(mode="json"),
        "draw_set": draws.model_dump(mode="json"),
    }
    for market in (False, True):
        output = project_parameter_mixture(
            stage8_request(bound, market=market),
            artifact=artifact,
            draws=draws,
            fixture=bound.fixture,
            expected_artifact_sha256=artifact.semantic_sha256,
        )
        result[str(market)] = {
            name: getattr(output, name)
            for name in ("semantic_sha256", "expected_home_goals", "expected_away_goals")
        }
    return result


def convergence() -> dict:
    started = perf_counter()
    artifact = synthetic_artifact()
    fixtures = tuple(
        row
        for row in synthetic_dataset().fixture_registry.fixtures
        if row.season == artifact.model.forecast_season
    )
    # Synthetic representative pairings, frozen before measurement; no model retuning.
    selected = (fixtures[0], fixtures[190], fixtures[379])
    results = {}
    timings = []
    for seed in (23, 71):
        for count in COUNTS:
            draw_start = perf_counter()
            draws = joint_parameter_draws(artifact, policy=draw_policy(seed=seed, draw_count=count))
            draw_seconds = perf_counter() - draw_start
            fixture_start = perf_counter()
            cells = []
            for fixture in selected:
                bound = fixture_prior_bundle(
                    artifact=artifact,
                    fixture=fixture,
                    as_of=artifact.usable_at,
                    expected_artifact_sha256=artifact.semantic_sha256,
                )
                for market in (False, True):
                    request = stage8_request(bound, market=market)
                    output = project_parameter_mixture(
                        request,
                        artifact=artifact,
                        draws=draws,
                        fixture=fixture,
                        expected_artifact_sha256=artifact.semantic_sha256,
                    )
                    plugin = ScoreDistributionService().project(request).distribution
                    matrix = tuple(tuple(Decimal(x) for x in row) for row in output.probabilities)
                    plugin_matrix = tuple(
                        tuple(Decimal(x) for x in row) for row in plugin.probabilities
                    )
                    mix = output.mixture
                    cells.append(
                        {
                            "fixture": str(fixture.fixture_id),
                            "market_backed": market,
                            "features": {
                                k: str(v) for k, v in distribution_features(matrix).items()
                            },
                            "lambda_home": str(mix.weighted_lambda_home),
                            "lambda_away": str(mix.weighted_lambda_away),
                            "lambda_variance_home": str(mix.epistemic_lambda_variance_home),
                            "lambda_variance_away": str(mix.epistemic_lambda_variance_away),
                            "plugin_lambda_home": str(bound.score_prior.home_goal_rate),
                            "plugin_lambda_away": str(bound.score_prior.away_goal_rate),
                            "lambda_home_plugin_delta": str(
                                mix.weighted_lambda_home - bound.score_prior.home_goal_rate
                            ),
                            "lambda_away_plugin_delta": str(
                                mix.weighted_lambda_away - bound.score_prior.away_goal_rate
                            ),
                            "matrix": matrix,
                            "published_means": (
                                output.expected_home_goals,
                                output.expected_away_goals,
                            ),
                            "plugin_vs_mixture": compare_distributions(
                                plugin_matrix, matrix
                            ).model_dump(mode="json"),
                            "draw_policy_sha256": draws.draw_policy_sha256,
                        }
                    )
            results[(seed, count)] = cells
            timings.append(
                {
                    "seed": seed,
                    "count": count,
                    "draw_seconds": draw_seconds,
                    "six_stage8_seconds": perf_counter() - fixture_start,
                }
            )
            print(f"convergence seed={seed} count={count} completed", flush=True)
    comparisons = []
    for seed in (23, 71):
        for index, count in enumerate(COUNTS[:-2]):
            cells = []
            for current, reference, next_cell in zip(
                results[(seed, count)],
                results[(seed, 8192)],
                results[(seed, COUNTS[index + 1])],
                strict=True,
            ):
                movement = compare_distributions(reference["matrix"], current["matrix"])
                next_movement = compare_distributions(next_cell["matrix"], current["matrix"])
                passed = (
                    current["published_means"]
                    == reference["published_means"]
                    == next_cell["published_means"]
                    and movement.exact_score_total_variation * 2 <= Decimal("1e-10")
                    and next_movement.exact_score_total_variation * 2 <= Decimal("1e-10")
                )
                cells.append(
                    {
                        **{k: v for k, v in current.items() if k != "matrix"},
                        "reference_deltas": movement.model_dump(mode="json"),
                        "next_count_deltas": next_movement.model_dump(mode="json"),
                        "reference_moments": {
                            key: reference[key]
                            for key in (
                                "lambda_home",
                                "lambda_away",
                                "lambda_variance_home",
                                "lambda_variance_away",
                            )
                        },
                        "reference_moment_deltas": {
                            key: str(Decimal(current[key]) - Decimal(reference[key]))
                            for key in (
                                "lambda_home",
                                "lambda_away",
                                "lambda_variance_home",
                                "lambda_variance_away",
                            )
                        },
                        "next_count_moment_deltas": {
                            key: str(Decimal(current[key]) - Decimal(next_cell[key]))
                            for key in (
                                "lambda_home",
                                "lambda_away",
                                "lambda_variance_home",
                                "lambda_variance_away",
                            )
                        },
                        "passes_predeclared_gate": passed,
                    }
                )
            comparisons.append(
                {
                    "seed": seed,
                    "count": count,
                    "cells": cells,
                    "all_pass": all(x["passes_predeclared_gate"] for x in cells),
                }
            )
    accepted = [
        count
        for count in COUNTS[:-2]
        if all(row["all_pass"] for row in comparisons if row["count"] == count)
    ]
    report = {
        "schema_version": "team-strength-mixture-convergence-v1",
        "classification": "SYNTHETIC_OFFLINE_RESEARCH_ONLY",
        "policy_sha256": hashlib.sha256(
            (ROOT / "tickets/CURRENT-TEAM-STRENGTH-001U/CONVERGENCE-POLICY.md").read_bytes()
        ).hexdigest(),
        "fit_sha256": artifact.semantic_sha256,
        "parameter_dimension": len(artifact.model.uncertainty.parameter_order),
        "counts": COUNTS,
        "reference_count": 8192,
        "seeds": (23, 71),
        "comparisons": comparisons,
        "selected_operational_draw_count": min(accepted) if accepted else None,
        "downstream_decision_gate": "NOT_ESTABLISHED_NO_STAGE11_SOLVES",
        "production_active": False,
        "timings": timings,
        "total_seconds": perf_counter() - started,
    }
    report["semantic_sha256"] = canonical_sha256(report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("golden", "convergence", "numerical"))
    arguments = parser.parse_args()
    payload = {"golden": golden, "convergence": convergence, "numerical": numerical}[
        arguments.mode
    ]()
    destination = (
        EVIDENCE
        / {
            "golden": "STAGE8-GOLDEN.json",
            "convergence": "CONVERGENCE.json",
            "numerical": "NUMERICAL-VALIDATION.json",
        }[arguments.mode]
    )
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {destination.name}")
