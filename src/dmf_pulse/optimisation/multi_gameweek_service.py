"""Application service for Stage-11 optimise/execute/observe/re-optimise workflows."""

from __future__ import annotations

from decimal import Decimal

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.multi_gameweek_errors import (
    CapabilityBlockedError,
    MultiGameweekError,
    ResourceLimitReached,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    AlternativeAvailability,
    BackendStatus,
    HorizonTransferCountFrontier,
    HorizonTransferCountFrontierPoint,
    MultiGameweekLineage,
    MultiGameweekOptimisationRequest,
    MultiGameweekOptimisationResult,
    MultiGameweekResultStatus,
    ObjectiveMode,
    OptimalityGuarantee,
    PlanAlternative,
    PlanKind,
    ResultConfidence,
    ScenarioTree,
    ScenarioTreeNode,
    SolverDiagnostics,
    StateAdvanceResult,
    TransferCountFrontier,
    TransferCountFrontierPoint,
    seal_advance,
    seal_horizon_transfer_count_frontier,
    seal_request,
    seal_result,
    seal_scenario_tree,
    seal_transfer_count_frontier,
    verify_advance_hash,
    verify_result_hash,
    verify_transfer_count_frontier_hash,
)
from dmf_pulse.optimisation.multi_gameweek_solver import (
    FrontierResult,
    PolicyCandidate,
    apply_transfer_action,
    build_move_attribution,
    build_plan,
    children_by_parent,
    information_set_key,
    observe_node,
    root_node,
    select_candidate,
    select_horizon_transfer_count_frontier,
    select_materially_distinct_candidate,
    select_transfer_count_frontier,
    solve_frontier,
    validate_plan,
    validate_request,
)
from dmf_pulse.optimisation.stage10_adapter import StaticTacticalEvaluator, TacticalEvaluator

STAGE10_PARENT_SHA = "49103e03bb1e7500aff5c15b90b136f2cc476405"


def _configuration_hash(request: MultiGameweekOptimisationRequest) -> str:
    return semantic_sha256(
        {
            "rules": request.rules.model_dump(mode="json"),
            "scenario_tree": request.scenario_tree.model_dump(mode="json"),
            "search_policy": request.search_policy.model_dump(mode="json"),
            "terminal_policy": request.terminal_policy.model_dump(mode="json"),
        }
    )


def _lineage(request: MultiGameweekOptimisationRequest) -> MultiGameweekLineage:
    input_hash = semantic_sha256(
        {
            "stage10_parent_sha": STAGE10_PARENT_SHA,
            "request_sha256": request.request_sha256,
            "manager_state_sha256": request.initial_state.state_sha256,
            "scenario_tree_sha256": request.scenario_tree.tree_sha256,
            "search_policy_sha256": request.search_policy.policy_sha256,
            "terminal_policy_sha256": request.terminal_policy.policy_sha256,
            "ruleset_hash": request.rules.ruleset_hash,
        }
    )
    return MultiGameweekLineage(
        stage10_parent_sha=STAGE10_PARENT_SHA,
        request_sha256=request.request_sha256,
        manager_state_sha256=request.initial_state.state_sha256,
        scenario_tree_sha256=request.scenario_tree.tree_sha256,
        search_policy_sha256=request.search_policy.policy_sha256,
        terminal_policy_sha256=request.terminal_policy.policy_sha256,
        ruleset_hash=request.rules.ruleset_hash,
        input_sha256=input_hash,
    )


def _empty_alternative(reason: str) -> PlanAlternative:
    return PlanAlternative(
        availability=AlternativeAvailability.UNAVAILABLE,
        plan=None,
        reason=reason,
    )


def _failure_result(
    request: MultiGameweekOptimisationRequest,
    *,
    status: MultiGameweekResultStatus,
    backend_status: BackendStatus,
    code: str,
    message: str,
    counters: object | None = None,
) -> MultiGameweekOptimisationResult:
    diagnostics = SolverDiagnostics(
        status=backend_status,
        termination_reason=message,
        optimality_guarantee=OptimalityGuarantee.NONE,
        state_expansions=int(getattr(counters, "state_expansions", 0)),
        action_candidates=int(getattr(counters, "action_candidates", 0)),
        policy_candidates=int(getattr(counters, "policy_candidates", 0)),
        pareto_candidates=int(getattr(counters, "pareto_candidates", 0)),
        memo_entries=0,
        configuration_sha256=_configuration_hash(request),
    )
    value = MultiGameweekOptimisationResult(
        status=status,
        request_id=request.request_id,
        conservative_plan=_empty_alternative(message),
        high_upside_plan=_empty_alternative(message),
        solver_status=diagnostics,
        confidence=ResultConfidence.BLOCKED,
        assumptions=tuple(sorted(request.assumptions)),
        lineage=_lineage(request),
        error_code=code,
        error_message=message,
        result_sha256="0" * 64,
    )
    return seal_result(value)


def _standard_assumptions(request: MultiGameweekOptimisationRequest) -> tuple[str, ...]:
    values = set(request.assumptions)
    values.update(
        {
            "Exactness is limited to the declared candidate pool, action scope and scenario tree.",
            "Future decisions use only canonical node information available at that deadline.",
            "Only the current root action is executable; future policy is contingent recourse.",
            "Conservative and upside selection use separately reported Stage-10 p10/p90 proxies.",
            f"Terminal policy {request.terminal_policy.policy_id} is separately attributed.",
        }
    )
    if request.terminal_policy.liquidation_points_per_tenth != Decimal(0):
        values.add("Terminal liquidation value is explicitly enabled as a team-value proxy.")
    return tuple(sorted(values))


def _build_alternative(
    request: MultiGameweekOptimisationRequest,
    frontier: FrontierResult,
    recommended: PolicyCandidate,
    *,
    mode: ObjectiveMode,
    kind: PlanKind,
    evaluator: TacticalEvaluator,
    assumptions: tuple[str, ...],
) -> PlanAlternative:
    floor = recommended.expected_score - request.search_policy.alternative_expected_sacrifice_points
    candidate = select_materially_distinct_candidate(
        frontier.candidates,
        recommended=recommended,
        mode=mode,
        expected_floor=floor,
        material_difference=request.search_policy.material_difference_points,
    )
    if candidate is None:
        return PlanAlternative(
            availability=AlternativeAvailability.NO_MATERIALLY_DISTINCT_PLAN,
            plan=None,
            reason=(
                "No policy in the exact declared frontier is materially distinct while satisfying "
                "the configured expected-utility floor."
            ),
        )
    plan = build_plan(
        request,
        candidate,
        plan_kind=kind,
        objective_mode=mode,
        diagnostics=frontier.diagnostics,
        assumptions=assumptions,
    )
    validate_plan(request, plan, evaluator=evaluator)
    return PlanAlternative(
        availability=AlternativeAvailability.DISTINCT,
        plan=plan,
        reason=f"Best materially distinct {mode.value.lower()} policy within expected floor.",
    )


def _build_transfer_count_frontier(
    request: MultiGameweekOptimisationRequest,
    frontier: FrontierResult,
    *,
    assumptions: tuple[str, ...],
) -> TransferCountFrontier | HorizonTransferCountFrontier:
    horizon_gameweeks = tuple(sorted({item.gameweek for item in request.scenario_tree.nodes}))
    if "HORIZON_TRANSFER_COUNT_FRONTIER_V1" in request.assumptions:
        if len(horizon_gameweeks) <= 1:
            raise ValueError("horizon transfer-count frontier requires multiple Gameweeks")
        horizon_points: list[HorizonTransferCountFrontierPoint] = []
        for candidate in select_horizon_transfer_count_frontier(frontier.candidates):
            plan = build_plan(
                request,
                candidate,
                plan_kind=PlanKind.TRANSFER_COUNT_FRONTIER,
                objective_mode=ObjectiveMode.EXPECTED,
                diagnostics=frontier.diagnostics,
                assumptions=assumptions,
            )
            root = candidate.root_decision
            horizon_points.append(
                HorizonTransferCountFrontierPoint(
                    transfer_count=root.action.transfer_count,
                    plan=plan,
                    immediate_expected_points_before_hit=(root.tactical_evaluation.expected_points),
                    transfer_hit_points=root.hit_points,
                    current_gameweek_objective=(
                        root.tactical_evaluation.expected_points - Decimal(root.hit_points)
                    ),
                    expected_horizon_utility=plan.utility.expected_horizon_utility,
                )
            )
        return seal_horizon_transfer_count_frontier(
            HorizonTransferCountFrontier.model_construct(
                horizon_gameweeks=horizon_gameweeks,
                points=tuple(horizon_points),
                frontier_sha256="0" * 64,
            )
        )
    points: list[TransferCountFrontierPoint] = []
    for candidate in select_transfer_count_frontier(frontier.candidates):
        plan = build_plan(
            request,
            candidate,
            plan_kind=PlanKind.TRANSFER_COUNT_FRONTIER,
            objective_mode=ObjectiveMode.EXPECTED,
            diagnostics=frontier.diagnostics,
            assumptions=assumptions,
        )
        root = candidate.root_decision
        points.append(
            TransferCountFrontierPoint(
                transfer_count=root.action.transfer_count,
                plan=plan,
                immediate_expected_points_before_hit=(root.tactical_evaluation.expected_points),
                transfer_hit_points=root.hit_points,
                current_gameweek_objective=(
                    root.tactical_evaluation.expected_points - Decimal(root.hit_points)
                ),
            )
        )
    value = seal_transfer_count_frontier(
        TransferCountFrontier.model_construct(
            points=tuple(points),
            frontier_sha256="0" * 64,
        )
    )
    verify_transfer_count_frontier_hash(value)
    return value


def optimise_multi_gameweek(
    request: MultiGameweekOptimisationRequest,
    *,
    evaluator: TacticalEvaluator | None = None,
) -> MultiGameweekOptimisationResult:
    """Optimise a policy; expose only its root transition as executable."""

    evaluator = evaluator or StaticTacticalEvaluator()
    try:
        validate_request(request)
        if request.projection_mode is ProjectionMode.PRODUCTION:
            raise CapabilityBlockedError(
                "MULTI_GAMEWEEK_PRODUCTION_BACKEND_UNAVAILABLE",
                "the bounded exact enumerator is authorised for TEST/REPLAY only; no approved "
                "unrestricted production solver/capability is present",
            )
        frontier = solve_frontier(request, evaluator)
    except CapabilityBlockedError as exc:
        return _failure_result(
            request,
            status=MultiGameweekResultStatus.BLOCKED,
            backend_status=BackendStatus.INPUT_CAPABILITY_BLOCKED,
            code=exc.code,
            message=exc.message,
        )
    except ResourceLimitReached as exc:
        return _failure_result(
            request,
            status=MultiGameweekResultStatus.RESOURCE_LIMIT,
            backend_status=BackendStatus.TIME_RESOURCE_LIMIT_NO_INCUMBENT,
            code=exc.code,
            message=exc.message,
            counters=exc.counters,
        )
    except MultiGameweekError as exc:
        infeasible = exc.status == "INFEASIBLE"
        return _failure_result(
            request,
            status=(
                MultiGameweekResultStatus.INFEASIBLE
                if infeasible
                else MultiGameweekResultStatus.BLOCKED
            ),
            backend_status=(
                BackendStatus.INFEASIBLE if infeasible else BackendStatus.INPUT_CAPABILITY_BLOCKED
            ),
            code=exc.code,
            message=exc.message,
        )
    except ValueError as exc:
        return _failure_result(
            request,
            status=MultiGameweekResultStatus.BLOCKED,
            backend_status=BackendStatus.INPUT_CAPABILITY_BLOCKED,
            code="MULTI_GAMEWEEK_INPUT_INVALID",
            message=str(exc),
        )

    assumptions = _standard_assumptions(request)
    try:
        recommended_candidate = select_candidate(frontier.candidates, mode=ObjectiveMode.EXPECTED)
        recommended = build_plan(
            request,
            recommended_candidate,
            plan_kind=PlanKind.RECOMMENDED,
            objective_mode=ObjectiveMode.EXPECTED,
            diagnostics=frontier.diagnostics,
            assumptions=assumptions,
        )
    except (MultiGameweekError, ValueError) as exc:
        code = (
            exc.code if isinstance(exc, MultiGameweekError) else "OPTIMISER_EMITTED_INVALID_POLICY"
        )
        message = exc.message if isinstance(exc, MultiGameweekError) else str(exc)
        return _failure_result(
            request,
            status=MultiGameweekResultStatus.ERROR,
            backend_status=BackendStatus.SOLVER_BACKEND_ERROR,
            code=code,
            message=message,
        )
    warnings: list[str] = []
    if not frontier.complete:
        warnings.append(
            "A complete incumbent policy is returned, but a configured resource cap prevented "
            "an optimality proof."
        )
    transfer_count_frontier = (
        _build_transfer_count_frontier(request, frontier, assumptions=assumptions)
        if frontier.complete
        else None
    )
    baseline_candidate = None
    baseline = None
    try:
        baseline_frontier = solve_frontier(request, evaluator, root_no_transfer_only=True)
        baseline_candidate = select_candidate(
            baseline_frontier.candidates,
            mode=ObjectiveMode.EXPECTED,
        )
        baseline = build_plan(
            request,
            baseline_candidate,
            plan_kind=PlanKind.NO_TRANSFER_BASELINE,
            objective_mode=ObjectiveMode.EXPECTED,
            diagnostics=baseline_frontier.diagnostics,
            assumptions=assumptions,
        )
        validate_plan(request, baseline, evaluator=evaluator)
    except (MultiGameweekError, ValueError) as exc:
        code = exc.code if isinstance(exc, MultiGameweekError) else "BASELINE_REPLAY_INVALID"
        message = exc.message if isinstance(exc, MultiGameweekError) else str(exc)
        warnings.append(f"No-transfer baseline unavailable: {code}: {message}")
    if frontier.complete and (baseline_candidate is None or baseline is None):
        return _failure_result(
            request,
            status=MultiGameweekResultStatus.ERROR,
            backend_status=BackendStatus.SOLVER_BACKEND_ERROR,
            code="NO_TRANSFER_BASELINE_UNAVAILABLE",
            message=warnings[-1],
        )
    try:
        validate_plan(request, recommended, evaluator=evaluator)
        if frontier.complete:
            conservative = _build_alternative(
                request,
                frontier,
                recommended_candidate,
                mode=ObjectiveMode.CONSERVATIVE,
                kind=PlanKind.CONSERVATIVE,
                evaluator=evaluator,
                assumptions=assumptions,
            )
            upside = _build_alternative(
                request,
                frontier,
                recommended_candidate,
                mode=ObjectiveMode.HIGH_UPSIDE,
                kind=PlanKind.HIGH_UPSIDE,
                evaluator=evaluator,
                assumptions=assumptions,
            )
        else:
            reason = (
                "Alternative plans are unavailable because the configured resource limit "
                "prevented complete frontier exhaustion."
            )
            conservative = _empty_alternative(reason)
            upside = _empty_alternative(reason)
    except (MultiGameweekError, ValueError) as exc:
        code = (
            exc.code if isinstance(exc, MultiGameweekError) else "OPTIMISER_EMITTED_INVALID_POLICY"
        )
        message = exc.message if isinstance(exc, MultiGameweekError) else str(exc)
        return _failure_result(
            request,
            status=MultiGameweekResultStatus.ERROR,
            backend_status=BackendStatus.SOLVER_BACKEND_ERROR,
            code=code,
            message=message,
        )
    try:
        attribution = (
            build_move_attribution(
                request,
                recommended=recommended_candidate,
                no_transfer=baseline_candidate,
                candidates=frontier.candidates,
            )
            if frontier.complete and baseline_candidate is not None
            else None
        )
    except ValueError as exc:
        return _failure_result(
            request,
            status=MultiGameweekResultStatus.ERROR,
            backend_status=BackendStatus.SOLVER_BACKEND_ERROR,
            code="MOVE_ATTRIBUTION_INVALID",
            message=str(exc),
        )
    all_exact = all(
        item.tactical_evaluation.exact_stage10_evaluation
        for item in (recommended.current_action, *recommended.future_policy)
    )
    status = (
        MultiGameweekResultStatus.SUCCESS
        if frontier.complete
        else MultiGameweekResultStatus.RESOURCE_LIMIT
    )
    value = MultiGameweekOptimisationResult(
        status=status,
        request_id=request.request_id,
        recommended_plan=recommended,
        conservative_plan=conservative,
        high_upside_plan=upside,
        no_transfer_baseline=baseline,
        transfer_count_frontier=transfer_count_frontier,
        marginal_value_of_each_move=attribution,
        current_action=recommended.current_action.action,
        future_policy=recommended.future_policy,
        solver_status=frontier.diagnostics,
        confidence=(
            ResultConfidence.HIGH if frontier.complete and all_exact else ResultConfidence.MEDIUM
        ),
        assumptions=assumptions,
        warnings=tuple(sorted(warnings)),
        lineage=_lineage(request),
        result_sha256="0" * 64,
    )
    value = seal_result(value)
    verify_result_hash(value)
    return value


def advance_current_action(
    request: MultiGameweekOptimisationRequest,
    result: MultiGameweekOptimisationResult,
    *,
    observed_node_id: str | None = None,
) -> StateAdvanceResult:
    """Execute only the current action, then optionally observe one immediate child."""

    validate_request(request)
    verify_result_hash(result)
    if result.status not in {
        MultiGameweekResultStatus.SUCCESS,
        MultiGameweekResultStatus.RESOURCE_LIMIT,
    }:
        raise ValueError("only a successful or incumbent resource-limit result is executable")
    if result.request_id != request.request_id or result.recommended_plan is None:
        raise ValueError("result does not contain an executable plan for this request")
    if result.lineage != _lineage(request):
        raise ValueError("result lineage does not match the request being advanced")
    root = root_node(request.scenario_tree)
    action = result.recommended_plan.current_action.action
    transition = apply_transfer_action(
        request.initial_state,
        action,
        node=root,
        candidate_pool=request.candidate_pool,
        rules=request.rules,
    )
    if transition.state != result.recommended_plan.current_action.state_after:
        raise ValueError("recommended current transition does not replay exactly")
    state = transition.state
    if observed_node_id is not None:
        children = {
            item.node_id: item
            for item in children_by_parent(request.scenario_tree).get(root.node_id, ())
        }
        observed = children.get(observed_node_id)
        if observed is None:
            raise ValueError("observed node must be an immediate child of the executed root")
        state = observe_node(state, node=observed)
    value = StateAdvanceResult(
        request_id=request.request_id,
        executed_action=action,
        observed_node_id=observed_node_id,
        manager_state=state,
        advance_sha256="0" * 64,
    )
    return seal_advance(value)


def reroot_request_after_observation(
    request: MultiGameweekOptimisationRequest,
    advance: StateAdvanceResult,
    *,
    request_id: str | None = None,
) -> MultiGameweekOptimisationRequest:
    """Create the next rolling-horizon request at one observed child node.

    The helper independently replays the executed root action, verifies the observed state,
    removes elapsed nodes, recomputes information-set lineage, and seals a new canonical
    request.  It does not reuse the previously planned future action.
    """

    validate_request(request)
    verify_advance_hash(advance)
    if advance.request_id != request.request_id:
        raise ValueError("state advance belongs to a different optimisation request")
    if advance.observed_node_id is None:
        raise ValueError("rolling re-root requires an observed child node")
    root = root_node(request.scenario_tree)
    children = {
        item.node_id: item
        for item in children_by_parent(request.scenario_tree).get(root.node_id, ())
    }
    observed = children.get(advance.observed_node_id)
    if observed is None:
        raise ValueError("rolling re-root node must be an immediate child of the old root")
    replay = apply_transfer_action(
        request.initial_state,
        advance.executed_action,
        node=root,
        candidate_pool=request.candidate_pool,
        rules=request.rules,
    )
    expected_state = observe_node(replay.state, node=observed)
    if expected_state != advance.manager_state:
        raise ValueError("state advance does not replay against the original request")

    descendants: set[str] = set()
    stack = [observed]
    child_index = children_by_parent(request.scenario_tree)
    while stack:
        node = stack.pop()
        if node.node_id in descendants:
            continue
        descendants.add(node.node_id)
        stack.extend(reversed(child_index.get(node.node_id, ())))

    rebuilt: dict[str, ScenarioTreeNode] = {}
    new_nodes = []
    for node in request.scenario_tree.nodes:
        if node.node_id not in descendants:
            continue
        parent_id = None if node.node_id == observed.node_id else node.parent_id
        conditional_probability = (
            Decimal(1) if node.node_id == observed.node_id else node.conditional_probability
        )
        provisional = node.model_copy(
            update={
                "parent_id": parent_id,
                "conditional_probability": conditional_probability,
                "information_set_key": "pending",
            }
        )
        parent_key = None
        if parent_id is not None:
            parent = rebuilt.get(parent_id)
            if parent is None:
                raise ValueError("rolling subtree order does not contain its parent")
            parent_key = parent.information_set_key
        rebuilt_node = provisional.model_copy(
            update={"information_set_key": information_set_key(provisional, parent_key=parent_key)}
        )
        rebuilt[node.node_id] = rebuilt_node
        new_nodes.append(rebuilt_node)
    if set(rebuilt) != descendants:
        raise ValueError("rolling subtree reconstruction is incomplete")
    tree = seal_scenario_tree(
        ScenarioTree(
            tree_id=f"{request.scenario_tree.tree_id}-from-{observed.node_id}",
            nodes=tuple(new_nodes),
            tree_sha256="0" * 64,
        )
    )
    next_request = request.model_copy(
        update={
            "request_id": request_id or f"{request.request_id}-from-{observed.node_id}",
            "initial_state": advance.manager_state,
            "scenario_tree": tree,
            "request_sha256": "0" * 64,
        }
    )
    next_request = seal_request(next_request)
    validate_request(next_request)
    return next_request
