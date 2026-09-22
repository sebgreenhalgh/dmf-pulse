"""Explicit two-world, provider-free 001P experiment; never a normal service factory.

No transport, filesystem writes, acquisition, model fit, player-prior resolver, or
activation exists here. D1 reads only the packaged input search policy for control
identity. Current-model Stage-7 projections are already materialised; unprepared
manual-minute inputs are rejected by this comparison route.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Literal

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.current_model import CurrentModelFixtureMinutesInput
from dmf_pulse.football_events.market_constraints import MarketFamily
from dmf_pulse.ingestion.openfootball.team_strength_data import authenticate, seal
from dmf_pulse.optimisation.multi_gameweek_models import SearchPolicy
from dmf_pulse.optimisation.multi_gameweek_policy import load_multi_gameweek_search_policy
from dmf_pulse.private_v1.one_command import _PrivateV1PreparedRollingContext
from dmf_pulse.private_v1.rolling import (
    PrivateV1RollingRecommendationService,
    PrivateV1RollingRunResult,
)
from dmf_pulse.private_v1.rolling_models import (
    PrivateV1RollingDecision,
    PrivateV1RollingExecutionInput,
)
from dmf_pulse.private_v1.shadow_comparison import (
    _candidate_screen_sha,
    _control_hashes,
    _scenario_alignment,
)
from dmf_pulse.private_v1.team_strength_comparison_models import (
    ComparisonTimings,
    DecisionSignature,
    FixturePriorComparison,
    PlayerMovement,
    PriorWorldResult,
    TeamStrengthDecisionComparison,
    World,
    action_hash,
    compare_signatures,
    summarise_coverage,
    summarise_movements,
    tactics_hash,
)
from dmf_pulse.private_v1.team_strength_diagnostics import (
    ComparisonReason as FailureReason,
)
from dmf_pulse.private_v1.team_strength_diagnostics import (
    ComparisonStage as FailureStage,
)
from dmf_pulse.private_v1.team_strength_diagnostics import (
    ComparisonTrace,
    comparison_boundary,
    note_control_divergence,
)
from dmf_pulse.private_v1.team_strength_shadow_inputs import (
    TeamStrengthShadowInput,
    TeamStrengthShadowPreparation,
    _TeamStrengthShadowResolver,
    horizon_fixtures,
)


@dataclass(frozen=True, slots=True)
class TeamStrengthComparisonRun:
    comparison: TeamStrengthDecisionComparison
    timings: ComparisonTimings


def _input_work_budget_control(
    execution: PrivateV1RollingExecutionInput, effective: SearchPolicy
) -> str:
    """Separate governed inputs from shortlist-dependent request limits (D1).

    Derived limits remain authenticated in each world's optimiser_request_sha256.
    This changes comparison identities, not any request, solve or classification.
    """
    scope = effective.transfer_action_scope
    return canonical_sha256(
        {
            "identity_version": "TEAM_STRENGTH_INPUT_WORK_BUDGET_V1",
            "input_policy": load_multi_gameweek_search_policy().model_dump(mode="json"),
            "maximum_transfers_per_deadline": execution.maximum_transfers_per_deadline,
            "search_scope_mode": execution.search_scope_mode,
            "continuation_mode": scope.continuation_mode if scope is not None else None,
            "effective_invariant_settings": effective.model_dump(
                mode="json",
                exclude={
                    "policy_sha256",
                    "max_transfers_per_node",
                    "max_actions_per_state",
                    "max_returned_root_candidates",
                    "transfer_action_scope",
                },
            ),
        }
    )


def _controls(
    execution: PrivateV1RollingExecutionInput, run: PrivateV1RollingRunResult
) -> tuple[tuple[str, str], ...]:
    lineage = run.decision.lineage
    current = execution.current_execution
    controls = _control_hashes(execution, run)
    controls.update(
        {
            "work_budget": _input_work_budget_control(
                execution, run.optimiser_request.search_policy
            ),
            "frozen_execution": execution.semantic_sha256,
            "current_source": current.current_state.semantic_sha256,
            "stage7_inputs": canonical_sha256(lineage.stage7_input_sha256_by_gameweek),
            "stage7_contexts": canonical_sha256(lineage.stage7_context_sha256_by_gameweek),
            "player_allocation": canonical_sha256(lineage.player_prior_binding_sha256_by_gameweek),
            "player_allocation_fallbacks": canonical_sha256(lineage.player_prior_fallback_ids),
            "scenario_identity": canonical_sha256(_scenario_alignment(run)),
            "draw_identity": canonical_sha256(
                tuple(
                    (
                        projection.scenario_set.gameweek_id,
                        tuple(
                            (row.scenario_id, row.outcome_draw_id, str(row.weight))
                            for row in projection.scenario_set.scenarios
                        ),
                    )
                    for projection in run.gameweek_projections
                )
            ),
            "scenario_policy": canonical_sha256(
                current.stage9_monte_carlo_policy.model_dump(mode="json")
            ),
            "ownership": current.ownership.semantic_sha256,
            "market_constraints": canonical_sha256(
                tuple(
                    (
                        row.gameweek,
                        str(row.prior.fixture_id),
                        tuple(item.model_dump(mode="json") for item in row.constraints),
                    )
                    for row in horizon_fixtures(execution)
                )
            ),
            "exact_acceleration": canonical_sha256(run.stage11_work.exact_accelerator),
            "future_price_policy": canonical_sha256(execution.future_price_mode),
            "chip_policy": canonical_sha256(execution.chip_mode),
            "scenario_tree_policy": canonical_sha256(execution.scenario_tree_mode),
            "algorithm_build": canonical_sha256(lineage.code_sha),
        }
    )
    return tuple(sorted(controls.items()))


def _world(
    world: World, execution: PrivateV1RollingExecutionInput, run: PrivateV1RollingRunResult
) -> PriorWorldResult:
    decision = PrivateV1RollingDecision.model_validate_json(run.decision.model_dump_json())
    rows = decision.by_gameweek
    with comparison_boundary(
        FailureStage.BUILD_DECISION_MATERIALITY, FailureReason.MATERIALITY_COMPARISON_FAILED
    ):
        signature = seal(
            DecisionSignature,
            by_gameweek=rows,
            action_sha256s=tuple(action_hash(row) for row in rows),
            tactical_selection_sha256s=tuple(tactics_hash(row) for row in rows),
            candidate_screen_sha256=_candidate_screen_sha(run)[0],
            utility=decision.horizon_comparison,
        )
    with comparison_boundary(
        FailureStage.RECONCILE_HARD_CONTROLS, FailureReason.HARD_CONTROL_DIVERGENCE
    ):
        controls = _controls(execution, run)
    return seal(
        PriorWorldResult,
        world=world,
        signature=signature,
        rolling_decision_sha256=decision.semantic_sha256,
        controls=controls,
        stage8_sha256s=tuple(
            (gw, fixture, digest)
            for gw, fixtures in sorted(
                decision.lineage.stage8_distribution_sha256_by_gameweek.items()
            )
            for fixture, digest in sorted(fixtures.items())
        ),
        optimiser_request_sha256=run.optimiser_request.request_sha256,
        optimiser_result_sha256=run.optimiser_result.result_sha256,
        stage11_work_sha256=run.stage11_work.semantic_sha256,
        canonical_legal_actions=run.stage11_work.cumulative_legal_actions,
    )


def _movements(
    execution: PrivateV1RollingExecutionInput,
    baseline: PrivateV1RollingRunResult,
    shadow: PrivateV1RollingRunResult,
) -> tuple[PlayerMovement, ...]:
    current = execution.current_execution
    teams = {
        row.official_fpl_team_id: str(row.canonical_team_id)
        for row in current.player_identity_map.teams
    }
    players = {str(row.canonical_player_id): row for row in current.player_identity_map.players}
    owned = {row.official_fpl_element_id for row in current.ownership.members}
    result = []
    for gw, left, right in zip(
        execution.horizon_gameweeks,
        baseline.gameweek_projections,
        shadow.gameweek_projections,
        strict=True,
    ):
        if set(left.player_summaries) != set(right.player_summaries) or not left.player_summaries:
            raise ValueError("prior worlds have different or empty player projection coverage")
        ranks = tuple(
            {
                player: index + 1
                for index, player in enumerate(
                    sorted(
                        projection.player_summaries,
                        key=lambda player: (
                            -projection.player_summaries[player].expected_points,
                            player,
                        ),
                    )
                )
            }
            for projection in (left, right)
        )
        for player in sorted(left.player_summaries):
            a = Decimal(str(left.player_summaries[player].expected_points))
            b = Decimal(str(right.player_summaries[player].expected_points))
            identity = players[player]
            result.append(
                PlayerMovement(
                    gameweek=gw,
                    player_id=player,
                    team_id=teams[identity.official_fpl_team_id],
                    in_current_squad=identity.official_fpl_element_id in owned,
                    baseline_xp=a,
                    shadow_xp=b,
                    delta=b - a,
                    baseline_rank=ranks[0][player],
                    shadow_rank=ranks[1][player],
                )
            )
    return tuple(result)


def _fixture_comparisons(
    execution: PrivateV1RollingExecutionInput,
    shadow: TeamStrengthShadowInput,
    worlds: tuple[PriorWorldResult, PriorWorldResult],
) -> tuple[FixturePriorComparison, ...]:
    outputs = tuple(
        {(gw, fixture): digest for gw, fixture, digest in world.stage8_sha256s} for world in worlds
    )
    rows = horizon_fixtures(execution)
    if any(
        set(output) != {(row.gameweek, str(row.prior.fixture_id)) for row in rows}
        for output in outputs
    ):
        raise ValueError("Stage-8 output does not cover the exact horizon")
    result = []
    for row, binding in zip(rows, shadow.fixtures, strict=True):
        families = {constraint.family for constraint in row.constraints}
        coverage: Literal["MARKET_BACKED", "PARTIAL_MARKET", "PRIOR_ONLY"]
        if not families:
            coverage = "PRIOR_ONLY"
        elif {MarketFamily.ONE_X_TWO, MarketFamily.TOTALS} <= families:
            coverage = "MARKET_BACKED"
        else:
            coverage = "PARTIAL_MARKET"
        key = (row.gameweek, str(row.prior.fixture_id))
        result.append(
            FixturePriorComparison(
                gameweek=row.gameweek,
                fixture_id=key[1],
                baseline_prior_sha256=canonical_sha256(
                    row.prior.score_prior_request.model_dump(mode="json")
                ),
                shadow_prior_sha256=canonical_sha256(
                    binding.public_bundle.score_prior.model_dump(mode="json")
                ),
                shadow_bundle_sha256=binding.public_bundle.semantic_sha256,
                market_constraints_sha256=canonical_sha256(
                    tuple(item.model_dump(mode="json") for item in row.constraints)
                ),
                baseline_stage8_sha256=outputs[0][key],
                shadow_stage8_sha256=outputs[1][key],
                market_coverage=coverage,
            )
        )
    return tuple(result)


def _compare_runs(
    prepared: _PrivateV1PreparedRollingContext,
    shadow: TeamStrengthShadowInput,
    baseline: PrivateV1RollingRunResult,
    alternative: PrivateV1RollingRunResult,
) -> TeamStrengthDecisionComparison:
    execution = prepared.rolling_execution
    with comparison_boundary(
        FailureStage.RECONCILE_WORLD_BINDINGS, FailureReason.WORLD_BINDING_MISMATCH
    ):
        if (
            baseline.decision.lineage.rolling_execution_input_sha256 != execution.semantic_sha256
            or (
                alternative.decision.lineage.rolling_execution_input_sha256
                != shadow.semantic_sha256
            )
        ):
            raise ValueError("comparison runs do not bind their exact prior worlds")
        worlds = (
            _world("LEAGUE_BASELINE", execution, baseline),
            _world("TEAM_STRENGTH_SHADOW", execution, alternative),
        )
    with comparison_boundary(
        FailureStage.RECONCILE_HARD_CONTROLS, FailureReason.HARD_CONTROL_DIVERGENCE
    ):
        if worlds[0].controls != worlds[1].controls:
            note_control_divergence(worlds[0].controls, worlds[1].controls)
            raise ValueError("prior-world hard controls diverged")
    with comparison_boundary(
        FailureStage.BUILD_PLAYER_MOVEMENT, FailureReason.PLAYER_PROJECTION_COVERAGE_MISMATCH
    ):
        rows = _movements(execution, baseline, alternative)
        movement = summarise_movements(rows)
    with comparison_boundary(
        FailureStage.BUILD_FIXTURE_PRIOR_COMPARISON, FailureReason.STAGE8_HORIZON_COVERAGE_MISMATCH
    ):
        fixtures = _fixture_comparisons(execution, shadow, worlds)
        market_coverage = summarise_coverage(fixtures)
    with comparison_boundary(
        FailureStage.BUILD_DECISION_MATERIALITY, FailureReason.MATERIALITY_COMPARISON_FAILED
    ):
        materiality = compare_signatures(worlds[0].signature, worlds[1].signature, movement)
    with comparison_boundary(FailureStage.SEAL_COMPARISON, FailureReason.COMPARISON_SEAL_FAILED):
        return seal(
            TeamStrengthDecisionComparison,
            experiment_class="SYNTHETIC_OFFLINE"
            if execution.current_execution.retention_class == "SYNTHETIC_REPLAY_ALLOWED"
            else "PRIVATE_TRANSIENT",
            information_cutoff=prepared.information_cutoff,
            horizon=execution.horizon_gameweeks,
            fpl_request_count=prepared.fpl_request_count,
            odds_request_count=prepared.odds_request_count,
            baseline_execution_sha256=execution.semantic_sha256,
            shadow_input_sha256=shadow.semantic_sha256,
            model_sha256=shadow.artifact.model.semantic_sha256,
            dataset_mode=shadow.artifact.model.dataset_mode,
            freshness=shadow.fixtures[0].public_bundle.retrieval_freshness_at_as_of,
            worlds=worlds,
            fixtures=fixtures,
            market_coverage=market_coverage,
            player_movements=rows,
            movement=movement,
            comparison=materiality,
        )


def _timing(run: PrivateV1RollingRunResult, *, projection: bool) -> Decimal:
    stages = ("stage8_9_gameweek_", "joint_scenario_assembly_gameweek_")
    solve_stages = {
        "one_gameweek_comparator",
        "action_generation",
        "tactical_batch_evaluation",
        "stage11_policy_solving",
    }
    return sum(
        (
            row.elapsed_ms
            for row in run.stage_timings
            if (row.stage.startswith(stages) if projection else row.stage in solve_stages)
        ),
        Decimal(0),
    )


def run_team_strength_shadow_comparison(
    prepared: _PrivateV1PreparedRollingContext,
    preparation: TeamStrengthShadowPreparation,
    *,
    preparation_ms: Decimal | None = None,
    _world_order: tuple[World, World] = ("LEAGUE_BASELINE", "TEAM_STRENGTH_SHADOW"),
) -> TeamStrengthComparisonRun | TeamStrengthShadowPreparation:
    """Consume one frozen provider-free preparation; no factories or transports accepted."""
    trace = ComparisonTrace()
    with (
        trace.activate(),
        comparison_boundary(
            FailureStage.VALIDATE_COMPARISON_INPUT, FailureReason.COMPARISON_INPUT_INVALID
        ),
    ):
        return _run_comparison(
            prepared,
            preparation,
            preparation_ms=preparation_ms,
            _world_order=_world_order,
            trace=trace,
        )


def _run_comparison(
    prepared: _PrivateV1PreparedRollingContext,
    preparation: TeamStrengthShadowPreparation,
    *,
    preparation_ms: Decimal | None,
    _world_order: tuple[World, World],
    trace: ComparisonTrace,
) -> TeamStrengthComparisonRun | TeamStrengthShadowPreparation:
    started = perf_counter()
    if len(set(_world_order)) != 2 or set(_world_order) != {
        "LEAGUE_BASELINE",
        "TEAM_STRENGTH_SHADOW",
    }:
        raise ValueError("comparison execution order must contain exactly both prior worlds")
    if preparation_ms is not None and (not preparation_ms.is_finite() or preparation_ms < 0):
        raise ValueError("preparation timing is invalid")
    preparation = authenticate(preparation)
    execution = PrivateV1RollingExecutionInput.model_validate_json(
        prepared.rolling_execution.model_dump_json()
    )
    if (
        prepared.information_cutoff != execution.current_execution.current_state.information_cutoff
        or (
            prepared.player_identity_map != execution.current_execution.player_identity_map
            or prepared.snapshot.fpl_input != execution.current_execution.current_state.fpl_input
        )
    ):
        raise ValueError("prepared context differs from frozen execution")
    if preparation.shadow_input is None:
        return preparation
    shadow = preparation.shadow_input
    with comparison_boundary(
        FailureStage.VALIDATE_SHADOW_RESOLVER, FailureReason.SHADOW_RESOLVER_INVALID
    ):
        _TeamStrengthShadowResolver(shadow).validate_execution(execution)
    with comparison_boundary(
        FailureStage.VALIDATE_STAGE7_CONTROL, FailureReason.STAGE7_CONTROL_INVALID
    ):
        if any(
            not isinstance(row.stage7, CurrentModelFixtureMinutesInput)
            for row in horizon_fixtures(execution)
        ):
            raise ValueError(
                "private comparison requires already prepared current-model Stage-7 projections"
            )
    frozen_bytes = execution.model_dump_json()
    runs: dict[World, PrivateV1RollingRunResult] = {}
    for world in _world_order:
        # Literal ordinary default, never an emulation through a baseline resolver.
        with comparison_boundary(
            FailureStage.RUN_LEAGUE_BASELINE_WORLD
            if world == "LEAGUE_BASELINE"
            else FailureStage.RUN_TEAM_STRENGTH_WORLD,
            FailureReason.BASELINE_WORLD_FAILED
            if world == "LEAGUE_BASELINE"
            else FailureReason.TEAM_STRENGTH_WORLD_FAILED,
        ):
            trace.start_world(world)
            service = (
                PrivateV1RollingRecommendationService()
                if world == "LEAGUE_BASELINE"
                else PrivateV1RollingRecommendationService(
                    _score_prior_resolver=_TeamStrengthShadowResolver(shadow)
                )
            )
            runs[world] = service.run(execution)
            trace.complete_world(world)
        with comparison_boundary(
            FailureStage.RECONCILE_WORLD_BINDINGS, FailureReason.WORLD_BINDING_MISMATCH
        ):
            if (
                execution.model_dump_json() != frozen_bytes
                or prepared.rolling_execution.model_dump_json() != frozen_bytes
            ):
                raise ValueError("frozen execution changed during comparison")
    baseline, alternative = runs["LEAGUE_BASELINE"], runs["TEAM_STRENGTH_SHADOW"]
    comparison = _compare_runs(prepared, shadow, baseline, alternative)
    with comparison_boundary(FailureStage.BUILD_TIMINGS, FailureReason.COMPARISON_TIMING_FAILED):
        projection_times = (
            _timing(baseline, projection=True),
            _timing(alternative, projection=True),
        )
        solve_times = (_timing(baseline, projection=False), _timing(alternative, projection=False))
        total = Decimal(str((perf_counter() - started) * 1000))
        return TeamStrengthComparisonRun(
            comparison=comparison,
            timings=ComparisonTimings(
                preparation_ms=preparation_ms,
                baseline_projection_ms=projection_times[0],
                baseline_solve_ms=solve_times[0],
                shadow_projection_ms=projection_times[1],
                shadow_solve_ms=solve_times[1],
                comparison_overhead_ms=total - sum((*projection_times, *solve_times), Decimal(0)),
            ),
        )


def safe_team_strength_summary(run: TeamStrengthComparisonRun) -> dict[str, object]:
    """Explicit allowlist; no player projection rows or raw private/provider state."""
    value = authenticate(run.comparison)
    worlds = []
    for result in value.worlds:
        signature = result.signature
        root = signature.by_gameweek[0]
        worlds.append(
            {
                "world": result.world,
                "root_transfers": tuple(
                    (row.player_out_id, row.player_in_id) for row in root.transfers
                ),
                "root_transfer_count": root.transfer_count,
                "root_hit": root.hit_points,
                "captain": root.tactics.captain,
                "vice": root.tactics.vice_captain,
                "xi_sha256": canonical_sha256(root.tactics.starting_xi),
                "utility": str(signature.utility.plan_expected_horizon_utility),
                "hold_utility": str(signature.utility.baseline_expected_horizon_utility),
                "uplift": str(signature.utility.expected_uplift),
                "gain_quantiles": (
                    signature.utility.gain_p10,
                    signature.utility.gain_median,
                    signature.utility.gain_p90,
                ),
                "probability_beats_hold": str(signature.utility.probability_plan_beats_baseline),
                "continuation_sha256s": signature.action_sha256s[1:],
                "candidate_screen_sha256": signature.candidate_screen_sha256,
                "decision_signature_sha256": signature.semantic_sha256,
            }
        )
    return {
        "status": value.status,
        "production_activation": False,
        "persistence": False,
        "comparison_sha256": value.semantic_sha256,
        "input": {
            "target_gameweek": value.horizon[0],
            "horizon": value.horizon,
            "cutoff": value.information_cutoff.isoformat(),
            "fpl_request_count": value.fpl_request_count,
            "odds_request_count": value.odds_request_count,
            "model_sha256": value.model_sha256,
            "freshness": value.freshness,
            "dataset_mode": value.dataset_mode,
            "experiment_class": value.experiment_class,
            "market_coverage": tuple(row.model_dump(mode="json") for row in value.market_coverage),
        },
        "projection_movement": value.movement.model_dump(mode="json"),
        "worlds": tuple(worlds),
        "comparison": value.comparison.model_dump(mode="json"),
        "controls": {name: True for name, _digest in value.worlds[0].controls},
        "provider_requests_during_solves": 0,
        "random_draw_disclosure": value.random_draw_disclosure,
        "timings": run.timings.model_dump(mode="json"),
    }
