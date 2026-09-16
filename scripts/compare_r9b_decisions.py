"""Offline synthetic Stage-10 provided-squad sensitivity; not a Stage-11 plan."""

from __future__ import annotations

from decimal import Decimal

from compare_r9b_stage9 import ablation_requests


def compare_decisions(requests, world, rules_engine, compiled_rules, candidate_squads):
    from dmf_pulse.fpl_points.artifacts import semantic_sha256
    from dmf_pulse.fpl_points.gameweek import assemble_gameweek
    from dmf_pulse.fpl_points.gameweek_summaries import build_gameweek_projection
    from dmf_pulse.fpl_points.models import MonteCarloPolicy, ProjectionMode, SimulationStatus
    from dmf_pulse.fpl_points.service import FplPointsService
    from dmf_pulse.optimisation.candidate_pool import enumerate_squads, snapshot_hash
    from dmf_pulse.optimisation.models import (
        CandidatePlayer,
        CandidatePoolSnapshot,
        CandidateSquad,
        OneGameweekOptimisationRequest,
        SearchScope,
    )
    from dmf_pulse.optimisation.policy import load_policy
    from dmf_pulse.optimisation.tactics import (
        ExactTacticalNodeKernel,
        tactical_configuration_upper_bound,
    )
    from dmf_pulse.optimisation.validation import (
        validate_plan_against_request,
        validate_request_boundary,
        validate_stage9_boundary,
    )
    from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view

    if not requests or len(candidate_squads) < 2:
        raise ValueError("decision experiment needs fixtures and at least two declared squads")
    ids = {p.player_id for request in requests for p in request.allocation_profiles}
    entries = tuple(e for e in world.posterior.entries if e.binding.current_player_id in ids)
    cutoff = requests[0].information_cutoff_utc
    pool = CandidatePoolSnapshot(
        information_cutoff_utc=cutoff,
        players=tuple(
            sorted(
                (
                    CandidatePlayer(
                        player_id=e.binding.current_player_id,
                        position=e.binding.position,
                        club_id=e.binding.current_team_id,
                    )
                    for e in entries
                ),
                key=lambda p: p.player_id,
            )
        ),
        snapshot_sha256="0" * 64,
    )
    pool = pool.model_copy(update={"snapshot_sha256": snapshot_hash(pool)})
    request = OneGameweekOptimisationRequest(
        request_id="r9b-synthetic-provided-squads",
        projection_mode=ProjectionMode.TEST,
        gameweek_id=requests[0].gameweek_id,
        information_cutoff_utc=cutoff,
        search_scope=SearchScope.PROVIDED_SQUADS,
        candidate_pool=pool,
        provided_candidate_squads=tuple(
            CandidateSquad(player_ids=squad) for squad in candidate_squads
        ),
        request_sha256="0" * 64,
    )
    request = request.model_copy(
        update={
            "request_sha256": semantic_sha256(
                request.model_dump(mode="json") | {"request_sha256": None}
            )
        }
    )
    # Test-only MC policy allows finite-scenario movement measurement; this is not
    # production convergence or predictive acceptance.
    mc = MonteCarloPolicy(
        minimum_effective_scenarios=1,
        maximum_mean_mcse=1000,
        maximum_probability_se=1000,
        maximum_quantile_span=1000,
        quantiles=(0.5,),
        thresholds=(1,),
        batch_count=2,
    )
    results = []
    policy = load_policy()
    view = build_one_gameweek_rules_view(compiled_rules, projection_mode=ProjectionMode.TEST)
    players = {p.player_id: p for p in pool.players}
    validate_request_boundary(request)
    squads = tuple(enumerate_squads(request, view, policy)[0])
    if len(squads) != len(candidate_squads):
        raise ValueError("declared decision experiment includes an illegal squad")
    upper = sum(tactical_configuration_upper_bound(s, players, view) for s in squads)
    if (
        upper > policy.max_tactical_configurations
        or upper * requests[0].scenario_count > policy.max_scenario_score_operations
    ):
        raise ValueError("sealed cumulative Stage-10 work limit exceeded")
    for component in ("STALE", "ALL_SUPPORTED"):
        fixture_results = tuple(
            FplPointsService(rules_engine, mc).project(dict(ablation_requests(r, world))[component])
            for r in requests
        )
        if any(r.status is not SimulationStatus.SUCCESS for r in fixture_results):
            raise ValueError("synthetic Stage-9 decision projection blocked")
        projection = build_gameweek_projection(assemble_gameweek(fixture_results), mc)
        validate_stage9_boundary(request, projection, ruleset_hash=compiled_rules.ruleset_hash)
        kernel = ExactTacticalNodeKernel(
            scenarios=projection.scenario_set.scenarios, players=players, rules=view
        )
        candidates = tuple(kernel.optimise(squad, policy) for squad in squads)
        plan = min(candidates, key=lambda item: (-item[1], item[0].signature))[0]
        if not validate_plan_against_request(request, projection, compiled_rules, plan).legal:
            raise ValueError("canonical Stage-10 final verification failed")
        results.append(plan)
    stale, shadow = results
    before, after = stale.tactical_configuration, shadow.tactical_configuration
    if tuple((s.scenario_id, s.outcome_draw_id) for s in stale.scenario_scores) != tuple(
        (s.scenario_id, s.outcome_draw_id) for s in shadow.scenario_scores
    ):
        raise ValueError("decision scenarios are not paired")
    paired = tuple(
        b.manager_points - a.manager_points
        for a, b in zip(stale.scenario_scores, shadow.scenario_scores, strict=True)
    )
    return {
        "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "interpretation": "MODEL_MOVEMENT_NOT_MODEL_ACCURACY",
        "decision_scope": "EXACT_R7_STAGE10_KERNEL_DECLARED_SQUADS_NOT_STAGE11_TRANSFER_OPTIMALITY",
        "squad_choice_changed": stale.squad != shadow.squad,
        "captain_changed": before.captain != after.captain,
        "starting_xi_changed": set(before.starting_xi) != set(after.starting_xi),
        "expected_manager_utility_delta": str(
            shadow.expected_manager_points - stale.expected_manager_points
        ),
        "paired_manager_gain_mean": str(sum(paired, Decimal(0)) / len(paired)),
        "provided_squad_count": len(candidate_squads),
        "fixture_count": len(requests),
        "upstream_rules_and_scenarios_held_fixed": True,
        "price_hit_ft_scope": "NOT_MODELLED_IN_PROVIDED_SQUAD_EXPERIMENT",
        "rolling_action_changed": None,
        "stage11_not_executed": True,
        "world_sha256": world.semantic_sha256,
    }
