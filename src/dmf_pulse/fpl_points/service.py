"""Application service for the bounded Stage-9 fixture vertical slice."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from dmf_pulse.fpl_points.allocation import (
    allocate_fixture_events,
    sample_participation,
    sample_scoreline,
)
from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import (
    FixturePointScenario,
    FixtureProjectionResult,
    FixtureSimulationRequest,
    MonteCarloPolicy,
    ProjectionMode,
    SimulationStatus,
)
from dmf_pulse.fpl_points.monte_carlo import monte_carlo_diagnostics
from dmf_pulse.fpl_points.rules_adapter import AcceptedRulesAdapter, RulesEngine
from dmf_pulse.fpl_points.seed import RNG_ALGORITHM, derive_seed, stable_identifier
from dmf_pulse.fpl_points.summaries import build_joint_matrix, summarize_fixture_scenarios
from dmf_pulse.fpl_points.upstream import scoreline_cells


def _source_identities(request: FixtureSimulationRequest) -> tuple[str, ...]:
    distribution = request.score_distribution
    values = {distribution.source_minutes_context_sha256}
    if distribution.source_market_sha256 is not None:
        values.add(distribution.source_market_sha256)
    return tuple(sorted(values))


def load_fixture_request(path: Path) -> FixtureSimulationRequest:
    try:
        return FixtureSimulationRequest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise FplPointsError(
            "REQUEST_INVALID", "fixture request is unavailable or invalid"
        ) from exc


def load_mc_policy(path: Path) -> MonteCarloPolicy:
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw) if path.suffix.lower() == ".json" else yaml.safe_load(raw)
        return MonteCarloPolicy.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError, ValidationError) as exc:
        raise FplPointsError(
            "MC_POLICY_INVALID", "Monte Carlo policy is unavailable or invalid"
        ) from exc


def generate_fixture_scenarios(
    request: FixtureSimulationRequest,
    rules_engine: RulesEngine,
    scenario_indices: Iterable[int],
) -> tuple[FixturePointScenario, ...]:
    identity = rules_engine.identity
    if request.projection_mode is ProjectionMode.PRODUCTION and not isinstance(
        rules_engine, AcceptedRulesAdapter
    ):
        raise FplPointsError(
            "RULESET_ACTIVATION_BUNDLE_REQUIRED",
            "production projection requires the verified Stage-2 rules adapter",
        )
    if request.fixture_readiness.value != "SCHEDULED":
        raise FplPointsError(
            "FIXTURE_NOT_PLAYABLE",
            f"fixture readiness is {request.fixture_readiness.value}; no projection is issued",
        )
    if (
        identity.ruleset_id,
        identity.ruleset_version,
        identity.ruleset_hash,
    ) != (
        request.expected_ruleset_id,
        request.expected_ruleset_version,
        request.expected_ruleset_hash,
    ):
        raise FplPointsError(
            "RULESET_REQUEST_MISMATCH", "request and loaded ruleset identities differ"
        )
    rules_engine.assert_mode_allowed(request.projection_mode)
    fixture_seed = derive_seed(request.root_seed, request.score_distribution.fixture_id)
    cells = scoreline_cells(request.score_distribution)
    scenarios: list[FixturePointScenario] = []
    weight = 1.0 / request.scenario_count
    for scenario_index in scenario_indices:
        if not 0 <= scenario_index < request.scenario_count:
            raise FplPointsError("SCENARIO_INDEX_INVALID", "scenario index is outside request")
        cell = sample_scoreline(
            cells,
            root_seed=fixture_seed,
            scenario_index=scenario_index,
        )
        participation = sample_participation(
            request.participation_scenarios,
            root_seed=fixture_seed,
            scenario_index=scenario_index,
        )
        event_scenario, degradation = allocate_fixture_events(
            cell=cell,
            participation=participation,
            profiles=request.allocation_profiles,
            config=request.allocation_config,
            ruleset=identity,
            projection_mode=request.projection_mode,
            root_seed=fixture_seed,
            scenario_index=scenario_index,
            assist_classifier=(
                rules_engine.classify_generated_assist
                if rules_engine.uses_versioned_assist_policy
                else None
            ),
        )
        player_scores = rules_engine.score_fixture(event_scenario)
        confidence: Literal["D", "E"] = (
            "E"
            if request.projection_mode is not ProjectionMode.PRODUCTION
            or identity.status != "ACTIVE"
            or not identity.production_eligible
            else "D"
        )
        scenarios.append(
            FixturePointScenario(
                scenario_id=stable_identifier(
                    "pts", fixture_seed, request.score_distribution.fixture_id, scenario_index
                ),
                outcome_draw_id=stable_identifier("draw", request.root_seed, scenario_index),
                scenario_index=scenario_index,
                weight=weight,
                upstream_score_probability=cell.probability,
                upstream_scoreline=(cell.home_goals, cell.away_goals),
                upstream_stage8_sha256=request.score_distribution.result_sha256,
                participation_scenario_id=participation.scenario_id,
                stage7_minutes_context=participation.stage7_minutes_context,
                stage7_player_projection_sha256s=(participation.stage7_player_projection_sha256s),
                fixture_id=request.score_distribution.fixture_id,
                gameweek_id=request.gameweek_id,
                players=player_scores,
                event_scenario=event_scenario,
                ruleset=identity,
                projection_mode=request.projection_mode,
                root_seed=request.root_seed,
                seed_namespace=(
                    f"fpl-points/{request.score_distribution.fixture_id}/{scenario_index}"
                ),
                rng_algorithm=RNG_ALGORITHM,
                model_version_ids=tuple(
                    sorted(
                        {
                            request.allocation_config.model_version_id,
                            request.score_distribution.model_family,
                            request.score_distribution.policy_sha256,
                            participation.stage7_minutes_context.home.model_artifact_sha256,
                            participation.stage7_minutes_context.away.model_artifact_sha256,
                        }
                    )
                ),
                dataset_version_ids=tuple(
                    sorted(
                        {
                            participation.stage7_minutes_context.home.dataset_sha256,
                            participation.stage7_minutes_context.away.dataset_sha256,
                        }
                    )
                ),
                source_bundle_ids=_source_identities(request),
                information_cutoff_utc=request.information_cutoff_utc,
                bps_completeness_mode=request.allocation_config.bps_completeness_mode,
                confidence_grade=confidence,
                degradation_reasons=degradation,
            )
        )
    return tuple(scenarios)


class FplPointsService:
    def __init__(self, rules_engine: RulesEngine, mc_policy: MonteCarloPolicy) -> None:
        self._rules_engine = rules_engine
        self._mc_policy = mc_policy

    def project(self, request: FixtureSimulationRequest) -> FixtureProjectionResult:
        try:
            scenarios = generate_fixture_scenarios(
                request, self._rules_engine, range(request.scenario_count)
            )
            diagnostics = monte_carlo_diagnostics(scenarios, self._mc_policy)
            summaries = summarize_fixture_scenarios(scenarios, diagnostics=diagnostics)
            matrix = build_joint_matrix(scenarios)
            warnings = tuple(
                sorted(
                    {reason for scenario in scenarios for reason in scenario.degradation_reasons}
                )
            )
            base = {
                "schema_version": "fpl-points-fixture-result-v1",
                "status": SimulationStatus.SUCCESS,
                "fixture_id": request.score_distribution.fixture_id,
                "gameweek_id": request.gameweek_id,
                "scenarios": scenarios,
                "player_summaries": summaries,
                "joint_matrix": matrix,
                "monte_carlo": diagnostics,
                "ruleset": self._rules_engine.identity,
                "projection_mode": request.projection_mode,
                "information_cutoff_utc": request.information_cutoff_utc,
                "simulation_request": request,
                "simulation_request_sha256": semantic_sha256(request),
                "monte_carlo_policy": self._mc_policy,
                "source_bundle_ids": _source_identities(request),
                "upstream_score_distribution": request.score_distribution,
                "upstream_stage8_sha256": request.score_distribution.result_sha256,
                "result_sha256": None,
                "warnings": warnings,
            }
            payload = FixtureProjectionResult.model_construct(
                **base  # type: ignore[arg-type]
            ).model_dump(mode="json")
            return FixtureProjectionResult.model_validate(
                {**payload, "result_sha256": semantic_sha256(payload)}
            )
        except FplPointsError as exc:
            return FixtureProjectionResult(
                schema_version="fpl-points-fixture-result-v1",
                status=SimulationStatus.BLOCKED,
                fixture_id=request.score_distribution.fixture_id,
                gameweek_id=request.gameweek_id,
                scenarios=(),
                player_summaries={},
                joint_matrix=None,
                monte_carlo=None,
                ruleset=self._rules_engine.identity,
                projection_mode=request.projection_mode,
                information_cutoff_utc=request.information_cutoff_utc,
                simulation_request=request,
                simulation_request_sha256=semantic_sha256(request),
                monte_carlo_policy=self._mc_policy,
                source_bundle_ids=_source_identities(request),
                upstream_score_distribution=request.score_distribution,
                upstream_stage8_sha256=request.score_distribution.result_sha256,
                error_code=exc.code,
                error_message=exc.message,
                warnings=(),
            )
