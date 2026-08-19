"""Shared Stage-14 chip application service.

The service is the only application-layer composition path for CLI, replay and
artifacts.  Chip-specific mathematics remains in the accepted captaincy,
Bench-Boost, Free-Hit, Wildcard and scheduler modules.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ValidationError

from dmf_pulse.chips.definitions import semantic_sha256
from dmf_pulse.chips.errors import ChipError
from dmf_pulse.chips.inventory import validate_chip_inventory
from dmf_pulse.chips.schedule_models import (
    ChipScheduleOpportunity,
    ChipSchedulePolicy,
    ChipScheduleRequest,
    RootScheduleAction,
)
from dmf_pulse.chips.scheduler import optimise_chip_schedule as _optimise_schedule_core
from dmf_pulse.chips.service_models import (
    ChipCapabilityValidation,
    ChipDecision,
    ChipDecisionAction,
    ChipDecisionLineage,
    ChipDecisionSet,
    ChipOpportunityEvaluation,
    ChipProbabilityDiagnostic,
    ChipRulesValidation,
    ChipServiceRequest,
    ConfidenceGrade,
    PriceActivationStatus,
    ScenarioWeight,
)

_LIMITED_PRICE_STATUSES = {
    PriceActivationStatus.SHADOW_ONLY,
    PriceActivationStatus.TARGET_SEASON_UNCALIBRATED,
    PriceActivationStatus.RIGHTS_BLOCKED,
    PriceActivationStatus.INSUFFICIENT_EVENTS,
    PriceActivationStatus.CALIBRATION_BLOCKED,
}
_CONFIDENCE_ORDER = {
    ConfidenceGrade.A: 0,
    ConfidenceGrade.B: 1,
    ConfidenceGrade.C: 2,
    ConfidenceGrade.D: 3,
    ConfidenceGrade.E: 4,
}


def _scenario_weights(request: ChipServiceRequest) -> tuple[ScenarioWeight, ...]:
    return tuple(
        ScenarioWeight(
            scenario_id=item.scenario_id,
            outcome_draw_id=item.outcome_draw_id,
            weight=item.weight,
        )
        for item in request.schedule_request.scenario_universe
    )


def _seal_probability(value: ChipProbabilityDiagnostic) -> ChipProbabilityDiagnostic:
    payload = value.model_dump(mode="json", exclude={"diagnostic_hash"})
    return ChipProbabilityDiagnostic.model_validate(
        value.model_copy(update={"diagnostic_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def _verified_service_request(request: ChipServiceRequest) -> ChipServiceRequest:
    try:
        checked = ChipServiceRequest.model_validate(request.model_dump(mode="python"))
    except ValidationError as exc:
        raise ChipError(
            "CHIP_SERVICE_REQUEST_UNSEALED",
            "chip service requires a correctly sealed semantic request",
        ) from exc
    expected_request = semantic_sha256(
        checked.model_dump(mode="json", exclude={"service_request_hash"})
    )
    if checked.service_request_hash != expected_request:
        raise ChipError(
            "CHIP_SERVICE_REQUEST_UNSEALED",
            "chip service requires a correctly sealed semantic request",
        )
    validate_compiled_chip_bundle(checked.chip_bundle)
    for definition in checked.chip_bundle.definitions:
        if semantic_sha256(definition.definition) != definition.definition_hash:
            raise ChipError(
                "CHIP_DEFINITION_HASH_MISMATCH",
                "compiled chip definition hash does not match",
                chip_key=definition.chip_key,
            )
    bundle_payload = {
        "ruleset_id": checked.chip_bundle.ruleset_id,
        "ruleset_version": checked.chip_bundle.ruleset_version,
        "ruleset_hash": checked.chip_bundle.ruleset_hash,
        "compiler_version": checked.chip_bundle.compiler_version,
        "concurrency_limit": checked.chip_bundle.concurrency_limit,
        "definitions": [item.model_dump(mode="json") for item in checked.chip_bundle.definitions],
    }
    if semantic_sha256(bundle_payload) != checked.chip_bundle.bundle_hash:
        raise ChipError(
            "CHIP_BUNDLE_HASH_MISMATCH",
            "compiled chip bundle hash does not match",
        )
    inventory_payload = checked.inventory.model_dump(mode="json", exclude={"inventory_hash"})
    if semantic_sha256(inventory_payload) != checked.inventory.inventory_hash:
        raise ChipError(
            "CHIP_INVENTORY_HASH_MISMATCH",
            "chip inventory hash does not match",
        )
    validate_chip_inventory(checked.inventory, checked.chip_bundle)
    schedule_payload = checked.schedule_request.model_dump(mode="json", exclude={"request_hash"})
    if semantic_sha256(schedule_payload) != checked.schedule_request.request_hash:
        raise ChipError(
            "CHIP_SCHEDULE_REQUEST_HASH_MISMATCH",
            "chip schedule request hash does not match",
        )
    for opportunity in checked.schedule_request.opportunities:
        payload = opportunity.model_dump(mode="json", exclude={"opportunity_hash"})
        if semantic_sha256(payload) != opportunity.opportunity_hash:
            raise ChipError(
                "CHIP_OPPORTUNITY_HASH_MISMATCH",
                "chip schedule opportunity hash does not match",
                opportunity_id=opportunity.opportunity_id,
            )
    return checked


def seal_chip_service_request(value: ChipServiceRequest) -> ChipServiceRequest:
    """Return a validated request with its deterministic semantic hash."""

    validated = ChipServiceRequest.model_validate(value.model_dump(mode="python"))
    payload = validated.model_dump(mode="json", exclude={"service_request_hash"})
    return ChipServiceRequest.model_validate(
        validated.model_copy(update={"service_request_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def _seal_lineage(value: ChipDecisionLineage) -> ChipDecisionLineage:
    payload = value.model_dump(mode="json", exclude={"lineage_hash"})
    return ChipDecisionLineage.model_validate(
        value.model_copy(update={"lineage_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def _seal_opportunity(value: ChipOpportunityEvaluation) -> ChipOpportunityEvaluation:
    payload = value.model_dump(mode="json", exclude={"summary_hash"})
    return ChipOpportunityEvaluation.model_validate(
        value.model_copy(update={"summary_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def _seal_decision(value: ChipDecision) -> ChipDecision:
    payload = value.model_dump(mode="json", exclude={"decision_hash"})
    return ChipDecision.model_validate(
        value.model_copy(update={"decision_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def _seal_decision_set(value: ChipDecisionSet) -> ChipDecisionSet:
    payload = value.model_dump(mode="json", exclude={"decision_set_hash"})
    return ChipDecisionSet.model_validate(
        value.model_copy(update={"decision_set_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def optimise_chip_schedule(
    request: ChipServiceRequest | ChipScheduleRequest,
) -> ChipSchedulePolicy:
    """Optimise the finite-inventory schedule through the accepted core scheduler.

    Accepting the core request preserves the pre-14.07 public package contract;
    the application request additionally verifies all shared-service lineage.
    """

    if isinstance(request, ChipServiceRequest):
        checked = _verified_service_request(request)
        return _optimise_schedule_core(checked.schedule_request)
    checked_core = ChipScheduleRequest.model_validate(request.model_dump(mode="python"))
    return _optimise_schedule_core(checked_core)


def _domain_evaluation_hash(request: ChipServiceRequest, chip_key: str) -> str | None:
    evaluations = {
        "TRIPLE_CAPTAIN": request.triple_captain,
        "BENCH_BOOST": request.bench_boost,
        "FREE_HIT": request.free_hit,
        "WILDCARD": request.wildcard,
    }
    evaluation = evaluations.get(chip_key)
    return None if evaluation is None else evaluation.evaluation_hash


def _scenario_value_by_identity(
    opportunity: ChipScheduleOpportunity,
) -> dict[tuple[str, str], float]:
    return {
        (item.scenario_id, item.outcome_draw_id): (
            item.net_policy_value + item.cash_like_value + item.terminal_state_value
        )
        for item in opportunity.scenario_values
    }


def _retention_value(
    request: ChipServiceRequest,
    current: ChipScheduleOpportunity,
) -> tuple[float, dict[tuple[str, str], float]]:
    """Return best legal same-token future/terminal comparator values."""

    terminal = next(
        (
            item.expected_terminal_value + item.cash_like_value - item.robust_penalty
            for item in request.schedule_request.terminal_token_values
            if item.token_id == current.token_id
        ),
        0.0,
    )
    future = tuple(
        item
        for item in request.schedule_request.opportunities
        if item.token_id == current.token_id
        and item.activation_gameweek > current.activation_gameweek
    )
    expected = max(
        [
            terminal,
            *(
                item.expected_net_policy_value
                + item.expected_cash_like_value
                + item.expected_terminal_state_value
                - item.robust_penalty
                for item in future
            ),
        ]
    )
    identities = tuple(
        (item.scenario_id, item.outcome_draw_id)
        for item in request.schedule_request.scenario_universe
    )
    scenario_comparator = {identity: terminal for identity in identities}
    for opportunity in future:
        values = _scenario_value_by_identity(opportunity)
        for identity in identities:
            scenario_comparator[identity] = max(
                scenario_comparator[identity],
                values[identity] - opportunity.robust_penalty,
            )
    return float(expected), scenario_comparator


def _opportunity_summary(
    request: ChipServiceRequest,
    opportunity: ChipScheduleOpportunity,
) -> ChipOpportunityEvaluation:
    retention, scenario_retention = _retention_value(request, opportunity)
    current_total = (
        opportunity.expected_net_policy_value
        + opportunity.expected_cash_like_value
        + opportunity.expected_terminal_state_value
        - opportunity.robust_penalty
    )
    scenario_current = _scenario_value_by_identity(opportunity)
    probability = sum(
        item.weight
        for item in opportunity.scenario_values
        if scenario_current[(item.scenario_id, item.outcome_draw_id)] - opportunity.robust_penalty
        >= scenario_retention[(item.scenario_id, item.outcome_draw_id)] - 1e-12
    )
    denominator = sum(item.weight for item in opportunity.scenario_values)
    probability_diagnostic = _seal_probability(
        ChipProbabilityDiagnostic(
            probability_now_optimal=float(probability / denominator),
            numerator_weight=float(probability),
            denominator_weight=float(denominator),
            scenario_set_hash=request.schedule_request.scenario_set_hash,
            scenario_weights=_scenario_weights(request),
            comparison_rule=(
                "PER_SCENARIO_CURRENT_OPPORTUNITY_GTE_BEST_SAME_TOKEN_DELAY_OR_TERMINAL"
            ),
            model_version=request.continuation_model_version,
            configuration_hash=request.continuation_configuration_hash,
            exact_search=True,
            diagnostic_hash="0" * 64,
        )
    )
    value = ChipOpportunityEvaluation(
        opportunity_id=opportunity.opportunity_id,
        chip_key=opportunity.chip_key,
        token_id=opportunity.token_id,
        activation_gameweek=opportunity.activation_gameweek,
        gross_current_gain=opportunity.expected_gross_current_gain,
        continuation_value=opportunity.expected_continuation_value,
        policy_cost=opportunity.expected_policy_cost,
        net_policy_value=opportunity.expected_net_policy_value,
        opportunity_cost=max(0.0, retention - current_total),
        exercise_advantage=current_total - retention,
        probability_now_optimal=probability_diagnostic.probability_now_optimal,
        probability_diagnostic=probability_diagnostic,
        robust_penalty=opportunity.robust_penalty,
        domain_evaluation_hash=_domain_evaluation_hash(request, opportunity.chip_key),
        opportunity_hash=opportunity.opportunity_hash,
        summary_hash="0" * 64,
    )
    return _seal_opportunity(value)


def _action(policy: ChipSchedulePolicy) -> ChipDecisionAction:
    if policy.recommended_action is RootScheduleAction.ACTIVATE:
        return ChipDecisionAction.USE
    if policy.recommended_action is RootScheduleAction.EXPIRE_UNUSED:
        return ChipDecisionAction.EXPIRE_UNUSED
    has_future_activation = bool(policy.selected_schedule.activations)
    return ChipDecisionAction.WAIT if has_future_activation else ChipDecisionAction.HOLD


def _confidence(request: ChipServiceRequest) -> ConfidenceGrade:
    if not set(request.price_activation_statuses) & _LIMITED_PRICE_STATUSES:
        return request.confidence
    return max(
        (request.confidence, ConfidenceGrade.D),
        key=lambda item: _CONFIDENCE_ORDER[item],
    )


def _reason_codes(
    request: ChipServiceRequest,
    policy: ChipSchedulePolicy,
    action: ChipDecisionAction,
) -> tuple[str, ...]:
    reasons = {
        {
            ChipDecisionAction.USE: "CURRENT_CHIP_POLICY_SELECTED",
            ChipDecisionAction.WAIT: "FUTURE_CHIP_OPPORTUNITY_DOMINATES_CURRENT",
            ChipDecisionAction.HOLD: "NO_CURRENT_CHIP_CLEARS_HOLD_POLICY",
            ChipDecisionAction.EXPIRE_UNUSED: "TOKEN_EXPIRES_UNUSED",
            ChipDecisionAction.BLOCKED: "CHIP_DECISION_BLOCKED",
        }[action],
        (
            "PROBABILITY_DIAGNOSTIC_EXACT"
            if policy.probability_now_optimal.exact_search
            else "PROBABILITY_DIAGNOSTIC_APPROXIMATE"
        ),
        "PERFECT_INFORMATION_DIAGNOSTIC_NOT_EXECUTABLE",
        "FUTURE_SCHEDULE_ADVISORY_ONLY",
    }
    if policy.exercise_advantage > 0.0:
        reasons.add("POSITIVE_EXERCISE_ADVANTAGE")
    if policy.opportunity_cost > 0.0:
        reasons.add("POSITIVE_OPPORTUNITY_COST")
    for status in request.price_activation_statuses:
        if status in _LIMITED_PRICE_STATUSES:
            reasons.add(f"STAGE13_{status.value}_PROPAGATED")
    return tuple(sorted(reasons))


def _lineage(request: ChipServiceRequest) -> ChipDecisionLineage:
    value = ChipDecisionLineage(
        manager_state_id=request.manager_state_id,
        manager_state_hash=request.manager_state_hash,
        ruleset_id=request.chip_bundle.ruleset_id,
        ruleset_version=request.chip_bundle.ruleset_version,
        ruleset_hash=request.chip_bundle.ruleset_hash,
        chip_bundle_hash=request.chip_bundle.bundle_hash,
        chip_definition_hashes=tuple(
            sorted(item.definition_hash for item in request.chip_bundle.definitions)
        ),
        inventory_hash=request.inventory.inventory_hash,
        service_request_hash=request.service_request_hash,
        schedule_request_hash=request.schedule_request.request_hash,
        scenario_set_hash=request.schedule_request.scenario_set_hash,
        scenario_weights=_scenario_weights(request),
        dataset_mode=request.dataset_mode,
        feature_record_hashes=tuple(
            sorted(semantic_sha256(item) for item in request.feature_records)
        ),
        leakage_report_hash=request.leakage_report.report_sha256,
        price_input_hash=request.price_input_hash,
        price_activation_statuses=request.price_activation_statuses,
        continuation_model_version=request.continuation_model_version,
        continuation_configuration_hash=request.continuation_configuration_hash,
        forecast_origin=request.forecast_origin,
        information_cutoff=request.information_cutoff,
        code_commit=request.code_commit,
        random_seed=request.random_seed,
        lineage_hash="0" * 64,
    )
    return _seal_lineage(value)


def evaluate_chip_opportunities(request: ChipServiceRequest) -> ChipDecisionSet:
    """Compose the shared current decision, schedule and chip-specific evidence."""

    checked = _verified_service_request(request)
    policy = optimise_chip_schedule(checked)
    current = tuple(
        item
        for item in checked.schedule_request.opportunities
        if item.activation_gameweek == checked.inventory.current_gameweek
    )
    opportunities = tuple(
        sorted(
            (_opportunity_summary(checked, item) for item in current),
            key=lambda item: (item.chip_key, item.token_id, item.opportunity_id),
        )
    )
    action = _action(policy)
    selected_chips = policy.selected_chip_keys
    selected_tokens = policy.selected_token_ids
    if len(selected_chips) > 1 or len(selected_tokens) > 1:
        raise ChipError(
            "CHIP_SERVICE_ROOT_CONCURRENCY_UNSUPPORTED",
            "the public FPL chip service permits at most one root chip activation",
            selected_chip_keys=selected_chips,
            selected_token_ids=selected_tokens,
        )
    selected_chip = selected_chips[0] if selected_chips else None
    selected_token = selected_tokens[0] if selected_tokens else None
    token = None if selected_token is None else checked.inventory.token(selected_token)
    expiry_pressure = any(
        item.status.value in {"AVAILABLE", "PENDING_CANCELLABLE"}
        and item.expires_after_gameweek <= checked.inventory.current_gameweek
        for item in checked.inventory.tokens
    )
    if token is not None:
        expiry_pressure = token.expires_after_gameweek <= checked.inventory.current_gameweek

    scheduler_probability = policy.probability_now_optimal
    probability_diagnostic = _seal_probability(
        ChipProbabilityDiagnostic(
            probability_now_optimal=scheduler_probability.probability_now_optimal,
            numerator_weight=scheduler_probability.numerator_weight,
            denominator_weight=scheduler_probability.denominator_weight,
            scenario_set_hash=scheduler_probability.scenario_set_hash,
            scenario_weights=_scenario_weights(checked),
            comparison_rule=scheduler_probability.comparison_rule,
            model_version=checked.continuation_model_version,
            configuration_hash=scheduler_probability.objective_config_hash,
            exact_search=scheduler_probability.exact_search,
            diagnostic_hash="0" * 64,
        )
    )

    decision = _seal_decision(
        ChipDecision(
            decision_id=checked.decision_id,
            recommended_action=action,
            selected_chip=selected_chip,
            selected_token_id=selected_token,
            gross_current_gain=policy.gross_current_gain,
            net_policy_value=policy.net_policy_value,
            continuation_value=policy.continuation_value,
            opportunity_cost=policy.opportunity_cost,
            exercise_advantage=policy.exercise_advantage,
            robust_regret=policy.selected_schedule.robust_penalty,
            probability_now_optimal=probability_diagnostic.probability_now_optimal,
            probability_diagnostic=probability_diagnostic,
            confidence=_confidence(checked),
            expiry_pressure=expiry_pressure,
            reasons=_reason_codes(checked, policy, action),
            price_activation_statuses=checked.price_activation_statuses,
            schedule_policy_hash=policy.policy_hash,
            decision_hash="0" * 64,
        )
    )
    value = ChipDecisionSet(
        request_hash=checked.service_request_hash,
        lineage=_lineage(checked),
        decision=decision,
        opportunities=opportunities,
        captain_vice=checked.captain_vice,
        triple_captain=checked.triple_captain,
        bench_boost=checked.bench_boost,
        free_hit=checked.free_hit,
        wildcard=checked.wildcard,
        schedule_policy=policy,
        decision_set_hash="0" * 64,
    )
    return _seal_decision_set(value)


def validate_compiled_chip_bundle(bundle: object) -> ChipRulesValidation:
    """Validate compiled rules, semantic hashes and fail-closed activation state."""

    from dmf_pulse.chips.compiler import COMPILER_VERSION, compile_chip_definition
    from dmf_pulse.chips.definitions import ActivationStatus, CompiledChipBundle

    try:
        payload = bundle.model_dump(mode="python") if isinstance(bundle, BaseModel) else bundle
        checked = CompiledChipBundle.model_validate(payload)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ChipError(
            "CHIP_RULES_INVALID",
            "compiled chip rules violate the Stage-14 contract",
        ) from exc
    if checked.compiler_version != COMPILER_VERSION:
        raise ChipError(
            "CHIP_COMPILER_VERSION_MISMATCH",
            "compiled chip bundle uses an unsupported compiler version",
            expected=COMPILER_VERSION,
            observed=checked.compiler_version,
        )
    blocked = tuple(
        item for item in checked.definitions if item.activation_status is not ActivationStatus.READY
    )
    if blocked:
        raise ChipError(
            "CHIP_RULES_BLOCKED",
            "compiled chip rules contain blocked definitions",
            chip_keys=tuple(item.chip_key for item in blocked),
            blockers=tuple(blocker for item in blocked for blocker in item.blockers),
        )
    for definition in checked.definitions:
        if semantic_sha256(definition.definition) != definition.definition_hash:
            raise ChipError(
                "CHIP_DEFINITION_HASH_MISMATCH",
                "compiled chip definition hash does not match",
                chip_key=definition.chip_key,
            )
        independently_compiled = compile_chip_definition(definition.definition)
        if definition != independently_compiled:
            raise ChipError(
                "CHIP_DEFINITION_COMPILE_MISMATCH",
                "compiled chip definition differs from independent recompilation",
                chip_key=definition.chip_key,
            )
    provisional = {
        "ruleset_id": checked.ruleset_id,
        "ruleset_version": checked.ruleset_version,
        "ruleset_hash": checked.ruleset_hash,
        "compiler_version": checked.compiler_version,
        "concurrency_limit": checked.concurrency_limit,
        "definitions": [item.model_dump(mode="json") for item in checked.definitions],
    }
    if semantic_sha256(provisional) != checked.bundle_hash:
        raise ChipError(
            "CHIP_BUNDLE_HASH_MISMATCH",
            "compiled chip bundle hash does not match",
        )
    value = ChipRulesValidation(
        ruleset_id=checked.ruleset_id,
        ruleset_version=checked.ruleset_version,
        ruleset_hash=checked.ruleset_hash,
        bundle_hash=checked.bundle_hash,
        definition_count=len(checked.definitions),
        chip_keys=tuple(sorted(item.chip_key for item in checked.definitions)),
        compiler_version=checked.compiler_version,
        validation_hash="0" * 64,
    )
    payload = value.model_dump(mode="json", exclude={"validation_hash"})
    return ChipRulesValidation.model_validate(
        value.model_copy(update={"validation_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def validate_installed_chip_capability() -> ChipCapabilityValidation:
    """Report installed engineering scope without claiming target-rule activation."""

    value = ChipCapabilityValidation(
        capabilities=tuple(
            sorted(
                {
                    "ARTIFACT_TAMPER_VALIDATION",
                    "BENCH_BOOST",
                    "CAPTAIN_VICE",
                    "FINITE_INVENTORY_SCHEDULER",
                    "FREE_HIT",
                    "PUBLIC_SERVICE",
                    "ROOT_ONLY_SEQUENTIAL_REPLAY",
                    "TRIPLE_CAPTAIN",
                    "TYPER_CLI",
                    "WILDCARD",
                }
            )
        ),
        validation_hash="0" * 64,
    )
    payload = value.model_dump(mode="json", exclude={"validation_hash"})
    return ChipCapabilityValidation.model_validate(
        value.model_copy(update={"validation_hash": semantic_sha256(payload)}).model_dump(
            mode="python"
        )
    )


def validate_service_requests(requests: Iterable[ChipServiceRequest]) -> tuple[str, ...]:
    """Validate a deterministic collection and return semantic request identities."""

    checked = tuple(_verified_service_request(item) for item in requests)
    hashes = tuple(item.service_request_hash for item in checked)
    if not hashes or len(hashes) != len(set(hashes)):
        raise ChipError(
            "CHIP_SERVICE_REQUEST_SET_INVALID",
            "service request collection must be non-empty and semantically unique",
        )
    return tuple(sorted(hashes))


__all__ = [
    "evaluate_chip_opportunities",
    "optimise_chip_schedule",
    "seal_chip_service_request",
    "validate_compiled_chip_bundle",
    "validate_installed_chip_capability",
    "validate_service_requests",
]
