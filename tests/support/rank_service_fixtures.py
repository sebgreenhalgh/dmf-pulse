"""Sealed synthetic Stage-15 shared-service fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

from dmf_pulse.evaluation.artifacts import canonical_json_bytes, semantic_sha256
from dmf_pulse.prices.models import ActivationStatus as PriceActivationStatus
from dmf_pulse.rank_strategy.models import SampleRightsStatus
from dmf_pulse.rank_strategy.service import bind_accepted_plan, seal_rank_service_request
from dmf_pulse.rank_strategy.service_models import (
    RankComponentIdentity,
    RankComponentKind,
    RankServiceLineage,
    RankServiceRequest,
)
from dmf_pulse.rank_strategy.utility_models import (
    RankObjectiveMode,
    RankPlanCandidate,
    RankPlanSource,
    RankTargetDefinition,
)
from tests.support.rank_utility_fixtures import (
    RAW_HASH,
    SCENARIO_HASH,
    candidate,
    context,
    policy,
)

FORECAST_ORIGIN = datetime(2026, 8, 20, 12, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 20, 11, 30, tzinfo=UTC)


def component(kind: RankComponentKind, token: str) -> RankComponentIdentity:
    return RankComponentIdentity(
        component=kind,
        identity=f"{kind.value.lower()}-{token}",
        semantic_hash=token * 64,
    )


def _candidate(
    plan_id: str,
    expected_points: float,
    pmf: dict[int, float],
    source_stage: RankPlanSource,
    *,
    confidence: str = "A",
    raw_hash: str = RAW_HASH,
    scenario_hash: str = SCENARIO_HASH,
) -> RankPlanCandidate:
    value = candidate(
        plan_id,
        expected_points,
        pmf,
        confidence=confidence,
        raw_hash=raw_hash,
        scenario_hash=scenario_hash,
    )
    return RankPlanCandidate.model_validate(
        value.model_copy(update={"source_stage": source_stage}).model_dump(mode="python")
    )


def service_request(
    *,
    objective: RankObjectiveMode = RankObjectiveMode.TARGET_RANK,
    gameweek: int = 20,
    context_confidence: str = "A",
    rank_plan_confidence: str = "A",
    rights_status: SampleRightsStatus = SampleRightsStatus.SYNTHETIC_APPROVED,
    rights_valid: bool = True,
    cohort_valid: bool = True,
    opponent_valid: bool = True,
    rules_verified: bool = True,
    target_rules_active: bool = True,
    explicit_target: bool = True,
    include_cohort: bool = True,
    include_opponent: bool = True,
    points_epsilon: float = 1.0,
    material_threshold: float = 0.5,
    minimum_confidence: str = "C",
    rank_expected_points: float = 99.4,
    rank_raw_hash: str = RAW_HASH,
    rank_scenario_hash: str = SCENARIO_HASH,
    stage13_statuses: tuple[PriceActivationStatus, ...] = (
        PriceActivationStatus.PRODUCTION_ELIGIBLE,
    ),
) -> RankServiceRequest:
    utility_policy = policy(
        points_epsilon=points_epsilon,
        material_threshold=material_threshold,
        early_through=8,
        minimum_confidence=minimum_confidence,
    )
    points_candidate = _candidate(
        "points-plan",
        100.0,
        {1: 0.2, 2: 0.8},
        RankPlanSource.STAGE_12,
    )
    rank_candidate = _candidate(
        "rank-plan",
        rank_expected_points,
        {1: 0.6, 2: 0.4},
        RankPlanSource.STAGE_14,
        confidence=rank_plan_confidence,
        raw_hash=rank_raw_hash,
        scenario_hash=rank_scenario_hash,
    )
    plans = tuple(
        sorted(
            (
                bind_accepted_plan(
                    points_candidate,
                    source_plan_hash="1" * 64,
                    source_result_hash="2" * 64,
                ),
                bind_accepted_plan(
                    rank_candidate,
                    source_plan_hash="3" * 64,
                    source_result_hash="4" * 64,
                ),
            ),
            key=lambda item: item.plan_id,
        )
    )
    activation = context(
        gameweek=gameweek,
        confidence=context_confidence,
        explicit=explicit_target,
        rights_valid=rights_valid,
        cohort_valid=cohort_valid,
        opponent_data_valid=opponent_valid,
        rules_verified=rules_verified,
        target_rules_active=target_rules_active,
    )
    lineage = RankServiceLineage(
        information_cutoff=CUTOFF,
        raw_projection_hash=RAW_HASH,
        scenario_set_hash=SCENARIO_HASH,
        stage9_scenarios=component(RankComponentKind.STAGE_9_SCENARIOS, "5"),
        stage10_tactics=component(RankComponentKind.STAGE_10_TACTICS, "6"),
        stage11_manager_state=component(RankComponentKind.STAGE_11_MANAGER_STATE, "7"),
        stage12_plans=component(RankComponentKind.STAGE_12_PLANS, "8"),
        stage13_prices=component(RankComponentKind.STAGE_13_PRICES, "9"),
        stage13_activation_statuses=tuple(sorted(stage13_statuses, key=lambda item: item.value)),
        stage14_chips=component(RankComponentKind.STAGE_14_CHIPS, "a"),
        effective_ownership_model=component(RankComponentKind.STAGE_15_EFFECTIVE_OWNERSHIP, "b"),
        cohort_model=(
            component(RankComponentKind.STAGE_15_COHORT, "c") if include_cohort else None
        ),
        opponent_model=(
            component(RankComponentKind.STAGE_15_OPPONENT_MODEL, "d") if include_opponent else None
        ),
        rights_profile_id="synthetic-rights-profile-v1",
        rights_profile_hash="e" * 64,
        rights_status=rights_status,
        ruleset_id="fpl-2026-27-reference",
        ruleset_hash="f" * 64,
        points_floor_hash=semantic_sha256(utility_policy.model_dump(mode="json")),
        code_version="rank-service-test-v1",
        config_version="rank-policy-test-v1",
        lineage_hash="0" * 64,
    )
    target = (
        None
        if objective in {RankObjectiveMode.PURE_POINTS, RankObjectiveMode.MEASURED_LEVERAGE}
        else RankTargetDefinition(target_rank=1)
    )
    value = RankServiceRequest(
        request_id="rank-service-fixture",
        forecast_origin=FORECAST_ORIGIN,
        information_cutoff=CUTOFF,
        objective=objective,
        target=target,
        context=activation,
        policy=utility_policy,
        lineage=lineage,
        plans=plans,
        service_request_hash="0" * 64,
    )
    return seal_rank_service_request(value)


def write_service_request(path, request: RankServiceRequest) -> None:
    path.write_bytes(canonical_json_bytes(request))
