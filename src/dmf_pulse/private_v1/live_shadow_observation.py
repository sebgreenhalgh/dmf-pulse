"""One-shot, zero-retention R9C-A2 live shadow decision observation.

This module has no route from the ordinary CLI or service factory.  It prepares
through the existing one-command path once, then runs four isolated canonical
rolling services without retaining provider or posterior data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, cast

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.current_player_posterior import (
    CurrentPlayerAllocationShadow,
    load_historical_rate_resource,
)
from dmf_pulse.fpl_points.current_player_shadow import compile_current_player_shadow
from dmf_pulse.fpl_points.player_prior import (
    build_current_gw_player_prior_binding,
    load_packaged_player_prior,
)
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current_player_history import (
    CurrentPlayerHistoryEvidence,
    build_current_player_history_evidence,
)
from dmf_pulse.ingestion.fpl.direct import DirectFplClient, DirectFplRunAttestation
from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability, RightsProfileStatus
from dmf_pulse.ingestion.odds.config import load_rights_profiles as load_odds_rights
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
from dmf_pulse.ingestion.odds.transient import CurrentOddsTransientService
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorResult,
    CurrentScorePriorService,
)
from dmf_pulse.ingestion.rights import load_rights_profiles as load_fpl_rights
from dmf_pulse.ingestion.rights import require_rights
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.one_command import (
    OneCommandRequest,
    PrivateV1OneCommandService,
    _PrivateV1PreparedRollingContext,
)
from dmf_pulse.private_v1.progress import NullProgress, ProgressSink
from dmf_pulse.private_v1.rolling import (
    PrivateV1RollingRecommendationService,
    PrivateV1RollingRunResult,
)
from dmf_pulse.private_v1.shadow_adapter import ShadowFixtureAllocationProfileResolver
from dmf_pulse.private_v1.shadow_comparison import (
    ComparisonWorld,
    ShadowComparisonWorldResult,
    _pair,
    _world_result,
)

A2_APPROVAL_REFERENCE = "DMF-R9C-A2-PRIVATE-RIGHTS-2026-09-17"
A2_EXECUTION_ATTESTATION = "PRIVATE-V1-ONE-COMMAND-001N-R9C-A2#ONE-SHOT-2026-09-17"
FPL_APPROVAL_REFERENCE = (
    "PRIVATE-V1-ONE-COMMAND-001A#fpl_official_private_operator_initiated_read_v1"
)
FPL_PROFILE_ID = "fpl_official_private_operator_initiated_read_v1"
ODDS_PROFILE_ID = "the_odds_api_private_analytics_v1"
_ODDS_TERMS_DATE = date(2026, 8, 31)
_ODDS_CHECKED_AT = datetime(2026, 9, 11, 21, 21, 31, tzinfo=UTC)
_ODDS_APPROVED_AT = datetime(2026, 9, 17, 14, 43, 36, tzinfo=UTC)
_CANONICAL_WORLDS: tuple[ComparisonWorld, ...] = (
    "STALE",
    "CENTRAL_TEMPORARY",
    "LOW_SHRINKAGE",
    "HIGH_SHRINKAGE",
)


class A2FailureStage(StrEnum):
    VALIDATE_RUNTIME_INPUT = "VALIDATE_RUNTIME_INPUT"
    VALIDATE_PROVIDER_AUTHORITY = "VALIDATE_PROVIDER_AUTHORITY"
    PREPARE_FROZEN_CONTEXT = "PREPARE_FROZEN_CONTEXT"
    BUILD_CURRENT_HISTORY = "BUILD_CURRENT_HISTORY"
    COMPILE_FIXED_SHADOW = "COMPILE_FIXED_SHADOW"
    RUN_FOUR_WORLD_COMPARISON = "RUN_FOUR_WORLD_COMPARISON"
    BUILD_SAFE_SUMMARY = "BUILD_SAFE_SUMMARY"
    INTERNAL = "INTERNAL"


class A2FailureReason(StrEnum):
    RUNTIME_INPUT_INVALID = "RUNTIME_INPUT_INVALID"
    PROVIDER_AUTHORITY_INVALID = "PROVIDER_AUTHORITY_INVALID"
    FROZEN_CONTEXT_PREPARATION_FAILED = "FROZEN_CONTEXT_PREPARATION_FAILED"
    CURRENT_HISTORY_INVALID = "CURRENT_HISTORY_INVALID"
    FIXED_SHADOW_COMPILE_FAILED = "FIXED_SHADOW_COMPILE_FAILED"
    FOUR_WORLD_COMPARISON_FAILED = "FOUR_WORLD_COMPARISON_FAILED"
    SAFE_SUMMARY_FAILED = "SAFE_SUMMARY_FAILED"
    UNEXPECTED_INTERNAL_FAILURE = "UNEXPECTED_INTERNAL_FAILURE"


LiveClassification = Literal[
    "LIVE_EXACT_PLAN_ROBUST",
    "LIVE_UTILITY_ONLY_MOVEMENT",
    "LIVE_ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE",
    "LIVE_ROOT_ACTION_ROBUST_TACTICS_SENSITIVE",
    "LIVE_WORLD_SENSITIVE_ROOT_ACTION",
    "LIVE_ROOT_ACTION_DIFFERENCE_CANDIDATE_SCREEN_CONFOUNDED",
]


@dataclass(frozen=True, slots=True)
class A2OperatorRequest:
    entry_id: int
    code_sha: str
    operator_approved_at: datetime
    acquisition_cutoff: datetime
    provider_approval_reference: str
    execution_attestation: str
    root_seed: int = 20260901
    scenario_count: int = 256


@dataclass(frozen=True, slots=True)
class LiveA2BlockedResult:
    schema_version: Literal["r9c-a2-live-shadow-blocked-v1"]
    status: Literal["BLOCKED"]
    reason_code: A2FailureReason
    failure_stage: A2FailureStage
    fpl_request_attempt_count: int
    fpl_endpoint_classes: tuple[str, ...]
    odds_acquisition_attempt_count: int
    retry_performed: Literal[False] = False
    persistence_performed: Literal[False] = False
    model_training_performed: Literal[False] = False
    production_activation: Literal[False] = False

    def public_dict(self) -> dict[str, object]:
        return _json_value(asdict(self))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class LiveShadowComparisonPair:
    left: ComparisonWorld
    right: ComparisonWorld
    root_action_changed: bool
    full_plan_changed: bool
    starting_xi_changed: bool
    captain_changed: bool
    vice_captain_changed: bool
    continuation_changed: bool
    candidate_screen_equal: bool
    optimal_utility_delta: Decimal
    hold_utility_delta: Decimal
    uplift_delta: Decimal
    classification: LiveClassification
    semantic_sha256: str

    def __post_init__(self) -> None:
        if self.left == self.right or self.semantic_sha256 != _hash_dataclass(self):
            raise ValueError("live pair is unsealed or compares one world to itself")


@dataclass(frozen=True, slots=True)
class LiveFourWorldShadowDecisionObservation:
    schema_version: Literal["r9c-a2-live-four-world-shadow-observation-v1"]
    status: Literal["LIVE_TRANSIENT_OBSERVATION_COMPLETE"]
    rolling_execution_input_sha256: str
    target_gameweek: int
    finalized_history_gameweeks: tuple[int, ...]
    horizon_gameweeks: tuple[int, int, int]
    information_cutoff_utc: str
    fpl_request_count: int
    fpl_endpoint_classes: tuple[str, ...]
    odds_request_count: int
    odds_endpoint_classes: tuple[str, ...]
    market_coverage_by_gameweek: tuple[tuple[int, int, int, int], ...]
    exact_donor_assignment_count: int
    fallback_assignment_count: int
    complete_history_reconciliation_count: int
    partial_history_reconciliation_count: int
    failed_history_reconciliation_count: int
    shadow_semantic_sha256: str
    results: tuple[
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
    ]
    pairs: tuple[LiveShadowComparisonPair, ...]
    stage7_identical_across_worlds: bool
    stage8_identical_across_worlds: bool
    root_randomness_aligned: bool
    scenario_identity_aligned: bool
    prices_identical_across_worlds: bool
    manager_state_identical_across_worlds: bool
    rules_identical_across_worlds: bool
    work_budget_semantics_identical_across_worlds: bool
    fixture_order_identical_across_worlds: bool
    terminal_policy_identical_across_worlds: bool
    candidate_policy_identical_across_worlds: bool
    candidate_universe_same_across_worlds: bool
    root_action_same_across_all_worlds: bool
    full_plan_same_across_all_worlds: bool
    starting_xi_same_across_all_worlds: bool
    captain_same_across_all_worlds: bool
    vice_same_across_all_worlds: bool
    model_input_status: Literal["SHADOW_NOT_MODEL_INPUT"]
    production_activation: Literal[False]
    persistence_performed: Literal[False]
    model_training_performed: Literal[False]
    new_network_requests_during_world_comparison: Literal[0]
    semantic_sha256: str

    def __post_init__(self) -> None:
        worlds = tuple(item.world for item in self.results)
        if worlds != _CANONICAL_WORLDS:
            raise ValueError("live comparison worlds are incomplete or noncanonical")
        expected_pairs = tuple(
            (worlds[left], worlds[right]) for left in range(4) for right in range(left + 1, 4)
        )
        if tuple((item.left, item.right) for item in self.pairs) != expected_pairs:
            raise ValueError("live comparison does not contain the canonical six pairs")
        if self.finalized_history_gameweeks != tuple(range(1, self.target_gameweek)):
            raise ValueError("live history window is incomplete")
        if self.horizon_gameweeks != (
            self.target_gameweek,
            self.target_gameweek + 1,
            self.target_gameweek + 2,
        ):
            raise ValueError("live rolling horizon is incoherent")
        controls = (
            self.stage7_identical_across_worlds,
            self.stage8_identical_across_worlds,
            self.root_randomness_aligned,
            self.scenario_identity_aligned,
            self.prices_identical_across_worlds,
            self.manager_state_identical_across_worlds,
            self.rules_identical_across_worlds,
            self.work_budget_semantics_identical_across_worlds,
            self.fixture_order_identical_across_worlds,
            self.terminal_policy_identical_across_worlds,
            self.candidate_policy_identical_across_worlds,
        )
        if not all(controls):
            raise ValueError("live comparison control divergence is blocking")
        if self.semantic_sha256 != _hash_dataclass(self):
            raise ValueError("live comparison semantic hash does not match")


def _canonical_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_value(asdict(value))
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in value.items()
            if key not in {"semantic_sha256", "timing_ms_by_stage"}
        }
    if isinstance(value, (list, tuple)):
        return tuple(_canonical_value(item) for item in value)
    return value


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _hash_dataclass(value: object) -> str:
    return canonical_sha256(_canonical_value(value))


def _sealed_pair(**payload: Any) -> LiveShadowComparisonPair:
    return LiveShadowComparisonPair(
        **payload,
        semantic_sha256=canonical_sha256(_canonical_value(payload)),
    )


def _sealed_observation(**payload: Any) -> LiveFourWorldShadowDecisionObservation:
    return LiveFourWorldShadowDecisionObservation(
        **payload,
        semantic_sha256=canonical_sha256(_canonical_value(payload)),
    )


def _validate_provider_authority(
    request: A2OperatorRequest,
    *,
    checked_at: datetime,
) -> None:
    if (
        request.provider_approval_reference != A2_APPROVAL_REFERENCE
        or request.execution_attestation != A2_EXECUTION_ATTESTATION
    ):
        raise ValueError("A2 provider-purpose authority references differ")
    fpl = load_fpl_rights()[FPL_PROFILE_ID]
    odds = load_odds_rights()[ODDS_PROFILE_ID]
    if (
        fpl.rights_profile_id != FPL_PROFILE_ID
        or fpl.profile_version != "1.0.0"
        or fpl.provider_key != "official_fpl"
        or fpl.status is not RightsProfileStatus.HUMAN_APPROVED
        or fpl.human_approval_id != FPL_APPROVAL_REFERENCE
        or fpl.approved_by != "PRIVATE-V1-ONE-COMMAND-001A operator approval"
        or fpl.approved_purpose
        != "low-volume operator-initiated read-only private recommendation; no production service"
        or fpl.account_scope != "One operator-supplied FPL entry in Sebastian's private context"
        or fpl.geography_scope != "private operator use only"
        or fpl.terms_source
        != "Premier League Terms and Conditions and current FPL application transport observed 2026-09-01"
        or fpl.terms_version != "checked-2026-09-01"
        or fpl.checked_at != datetime(2026, 9, 1, tzinfo=UTC)
        or fpl.approved_at != datetime(2026, 9, 1, tzinfo=UTC)
        or fpl.retention_seconds != 0
        or fpl.termination_deletion_required is not False
        or fpl.unresolved_rights != ()
        or fpl.approved_at > checked_at
    ):
        raise ValueError("official-FPL authority identity, purpose or review metadata differs")
    for capability in (
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.PRIVATE_INTERNAL_USE,
    ):
        require_rights(fpl, capability, checked_at=checked_at)
    for capability in (
        RightsCapability.MANUAL_IMPORT,
        RightsCapability.RAW_STORAGE,
        RightsCapability.DERIVED_STORAGE,
        RightsCapability.CACHE,
        RightsCapability.BACKUP,
        RightsCapability.MODEL_TRAINING,
        RightsCapability.PUBLIC_DISPLAY,
        RightsCapability.REDISTRIBUTION,
    ):
        if fpl.capabilities[capability] is not CapabilityValue.DENY:
            raise ValueError("official-FPL denied capability differs")
    if (
        odds.rights_profile_id != ODDS_PROFILE_ID
        or odds.profile_version != "1.0.0"
        or odds.provider_key != "the_odds_api"
        or odds.status is not RightsProfileStatus.HUMAN_APPROVED
        or odds.human_approval_id != A2_APPROVAL_REFERENCE
        or odds.approved_by != "Sebastian"
        or odds.account_scope != "Sebastian-owned and authorized private The Odds API account"
        or odds.geography_scope != "United Kingdom private use"
        or odds.approved_purpose
        != (
            "one private operator-initiated R9C-A2 live transient four-world decision "
            "observation using one frozen current information set through the existing "
            "three-Gameweek decision pipeline"
        )
        or odds.terms_source != "The Odds API Terms and Conditions"
        or odds.terms_version != f"checked-{_ODDS_TERMS_DATE.isoformat()}"
        or odds.checked_at != _ODDS_CHECKED_AT
        or odds.approved_at != _ODDS_APPROVED_AT
        or odds.approved_at > checked_at
        or request.operator_approved_at.astimezone(UTC) < odds.approved_at
        or odds.retention_seconds != 0
        or odds.termination_deletion_required is not True
        or odds.unresolved_rights
        != (
            "raw historical retention requires explicit review",
            "model training and backup require explicit review",
            "public product is a new purpose",
        )
    ):
        raise ValueError("Odds A2 authority identity, purpose or review metadata differs")
    expected_odds = {
        RightsCapability.AUTOMATED_ACCESS: "ALLOW",
        RightsCapability.MANUAL_IMPORT: "ALLOW",
        RightsCapability.TRANSIENT_PROCESSING: "ALLOW",
        RightsCapability.CACHE: "ALLOW",
        RightsCapability.RAW_STORAGE: "UNKNOWN",
        RightsCapability.DERIVED_STORAGE: "ALLOW",
        RightsCapability.MODEL_TRAINING: "UNKNOWN",
        RightsCapability.PRIVATE_INTERNAL_USE: "ALLOW",
        RightsCapability.PUBLIC_DISPLAY: "DENY",
        RightsCapability.REDISTRIBUTION: "DENY",
        RightsCapability.BACKUP: "UNKNOWN",
    }
    if any(odds.capabilities[key].value != value for key, value in expected_odds.items()):
        raise ValueError("Odds capability matrix differs from the approved existing matrix")
    for capability in (
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.PRIVATE_INTERNAL_USE,
    ):
        require_rights(odds, capability, checked_at=checked_at)


def _build_current_history(
    prepared: _PrivateV1PreparedRollingContext,
) -> CurrentPlayerHistoryEvidence:
    snapshot = prepared.snapshot
    identity_map = prepared.player_identity_map
    history = build_current_player_history_evidence(
        snapshot,
        canonical_player_ids={
            item.official_fpl_element_id: item.canonical_player_id for item in identity_map.players
        },
    )
    target = prepared.rolling_execution.horizon_gameweeks[0]
    if (
        history.target_gameweek != target
        or history.coverage.observed_gameweeks != tuple(range(1, target))
        or history.information_cutoff != prepared.information_cutoff
        or prepared.rolling_execution.current_execution.current_state.information_cutoff
        != prepared.information_cutoff
    ):
        raise ValueError("current history, target or cutoff differs from the rolling input")
    return history


def _compile_fixed_shadow(
    prepared: _PrivateV1PreparedRollingContext,
    history: CurrentPlayerHistoryEvidence,
) -> CurrentPlayerAllocationShadow:
    snapshot = prepared.snapshot
    identity_map = prepared.player_identity_map
    prior = load_packaged_player_prior()
    policy = prepared.rolling_execution.current_execution.player_prior_carry_forward_policy
    if policy is None:
        raise ValueError("current stale prior policy is unavailable")
    binding = build_current_gw_player_prior_binding(
        prior,
        snapshot.fpl_input,
        policy,
        canonical_player_ids_by_source_id={
            item.official_fpl_element_id: str(item.canonical_player_id)
            for item in identity_map.players
        },
        canonical_team_ids_by_source_id={
            item.official_fpl_team_id: str(item.canonical_team_id) for item in identity_map.teams
        },
    )
    shadow = compile_current_player_shadow(
        history=history,
        current_fpl=snapshot.fpl_input,
        binding=binding,
        policy=policy,
        prior=prior,
        historical=load_historical_rate_resource(),
    )
    if shadow.persistence_performed or shadow.model_training_performed:
        raise ValueError("compiled shadow performed persistence or training")
    return shadow


def _compile_shadow(
    prepared: _PrivateV1PreparedRollingContext,
) -> tuple[CurrentPlayerHistoryEvidence, CurrentPlayerAllocationShadow]:
    history = _build_current_history(prepared)
    shadow = _compile_fixed_shadow(prepared, history)
    return history, shadow


def _live_pair(
    left: ShadowComparisonWorldResult,
    right: ShadowComparisonWorldResult,
) -> LiveShadowComparisonPair:
    pair = _pair(left, right)
    classification: LiveClassification
    if pair.root_action_changed and not pair.candidate_screen_equal:
        classification = "LIVE_ROOT_ACTION_DIFFERENCE_CANDIDATE_SCREEN_CONFOUNDED"
    else:
        classification = cast(
            LiveClassification,
            {
                "EXACT_PLAN_ROBUST": "LIVE_EXACT_PLAN_ROBUST",
                "UTILITY_ONLY_MOVEMENT": "LIVE_UTILITY_ONLY_MOVEMENT",
                "ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE": (
                    "LIVE_ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE"
                ),
                "ROOT_ACTION_ROBUST_TACTICS_SENSITIVE": (
                    "LIVE_ROOT_ACTION_ROBUST_TACTICS_SENSITIVE"
                ),
                "WORLD_SENSITIVE_ROOT_ACTION": "LIVE_WORLD_SENSITIVE_ROOT_ACTION",
            }[pair.classification],
        )
    return _sealed_pair(
        left=pair.left,
        right=pair.right,
        root_action_changed=pair.root_action_changed,
        full_plan_changed=pair.full_plan_changed,
        starting_xi_changed=pair.starting_xi_changed,
        captain_changed=pair.captain_changed,
        vice_captain_changed=pair.vice_captain_changed,
        continuation_changed=pair.continuation_changed,
        candidate_screen_equal=pair.candidate_screen_equal,
        optimal_utility_delta=pair.optimal_utility_delta,
        hold_utility_delta=pair.hold_utility_delta,
        uplift_delta=pair.uplift_delta,
        classification=classification,
    )


def _all_equal(values: tuple[object, ...]) -> bool:
    return all(item == values[0] for item in values[1:])


def _validated_control_alignment(
    results: tuple[
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
    ],
) -> tuple[bool, bool, bool, bool, bool, bool, bool, bool, bool, bool, bool]:
    controls = (
        _all_equal(tuple(item.stage7_context_sha256_by_gameweek for item in results)),
        _all_equal(tuple(item.stage8_distribution_sha256_by_gameweek for item in results)),
        _all_equal(tuple(item.scenario_alignment_sha256_by_gameweek for item in results)),
        _all_equal(tuple(item.root_randomness_sha256 for item in results)),
        _all_equal(tuple(item.prices_sha256 for item in results)),
        _all_equal(tuple(item.manager_state_sha256 for item in results)),
        _all_equal(tuple(item.rules_sha256 for item in results)),
        _all_equal(tuple(item.work_budget_semantics_sha256 for item in results)),
        _all_equal(tuple(item.fixture_order_sha256 for item in results)),
        _all_equal(tuple(item.terminal_policy_sha256 for item in results)),
        _all_equal(tuple(item.candidate_policy_sha256 for item in results)),
    )
    if not all(controls):
        raise ValueError("live comparison controls diverged")
    return controls


def _network_request_delta(before: tuple[int, int, int], after: tuple[int, int, int]) -> int:
    deltas = tuple(end - start for start, end in zip(before, after, strict=True))
    if any(item < 0 for item in deltas):
        raise ValueError("provider request counters moved backwards")
    return sum(deltas)


def _run_live_comparison(
    prepared: _PrivateV1PreparedRollingContext,
    history: CurrentPlayerHistoryEvidence,
    shadow: CurrentPlayerAllocationShadow,
    *,
    progress: ProgressSink,
    network_state: Callable[[], tuple[int, int, int]],
) -> tuple[LiveFourWorldShadowDecisionObservation, PrivateV1RollingRunResult]:
    execution = prepared.rolling_execution
    network_before = network_state()
    run_by_world: dict[ComparisonWorld, PrivateV1RollingRunResult] = {}
    for world in _CANONICAL_WORLDS:
        service = (
            PrivateV1RollingRecommendationService()
            if world == "STALE"
            else PrivateV1RollingRecommendationService(
                _allocation_profile_resolver=ShadowFixtureAllocationProfileResolver(
                    shadow=shadow,
                    world=world,
                )
            )
        )
        run_by_world[world] = service.run(execution, progress=progress)
    results = cast(
        tuple[
            ShadowComparisonWorldResult,
            ShadowComparisonWorldResult,
            ShadowComparisonWorldResult,
            ShadowComparisonWorldResult,
        ],
        tuple(_world_result(world, run_by_world[world], execution) for world in _CANONICAL_WORLDS),
    )
    (
        stage7,
        stage8,
        scenarios,
        root_randomness,
        prices,
        manager,
        rules,
        budgets,
        fixture_order,
        terminal_policy,
        candidate_policy,
    ) = _validated_control_alignment(results)
    network_delta = _network_request_delta(network_before, network_state())
    if network_delta != 0:
        raise ValueError("provider access occurred during the four-world comparison")
    candidate_same = _all_equal(tuple(item.candidate_screen_sha256 for item in results))
    pairs = tuple(
        _live_pair(results[left], results[right])
        for left in range(4)
        for right in range(left + 1, 4)
    )
    signatures = tuple(item.decision_signature for item in results)
    root_same = _all_equal(tuple(item.root_action_signature for item in signatures))
    full_same = _all_equal(
        tuple(
            (item.by_gameweek_action_signatures, item.tactical_selection_signatures)
            for item in signatures
        )
    )
    xi_same = _all_equal(tuple(item.starting_xi for item in signatures))
    captain_same = _all_equal(tuple(item.captain for item in signatures))
    vice_same = _all_equal(tuple(item.vice_captain for item in signatures))
    central = shadow.worlds[0].posterior
    exact = sum(item.binding.assignment_level == "INDIVIDUAL_SAME_TEAM" for item in central.entries)
    complete = sum(
        item.reconciliation_minutes == item.reconciliation_starts == "MATCH"
        for item in history.entries
    )
    failed = sum(
        "FAILED" in (item.reconciliation_minutes, item.reconciliation_starts)
        for item in history.entries
    )
    stale = run_by_world["STALE"]
    gameweeks = (stale.decision.do_now, *stale.decision.future_plan)
    coverage = tuple(
        (
            item.gameweek,
            item.fixture_coverage.market_backed_fixtures,
            item.fixture_coverage.score_prior_only_fixtures,
            item.fixture_coverage.blocked_fixtures,
        )
        for item in gameweeks
    )
    observation = _sealed_observation(
        schema_version="r9c-a2-live-four-world-shadow-observation-v1",
        status="LIVE_TRANSIENT_OBSERVATION_COMPLETE",
        rolling_execution_input_sha256=execution.semantic_sha256,
        target_gameweek=execution.horizon_gameweeks[0],
        finalized_history_gameweeks=history.coverage.observed_gameweeks,
        horizon_gameweeks=execution.horizon_gameweeks,
        information_cutoff_utc=prepared.information_cutoff.isoformat().replace("+00:00", "Z"),
        fpl_request_count=prepared.fpl_request_count,
        fpl_endpoint_classes=prepared.fpl_endpoint_classes,
        odds_request_count=prepared.odds_request_count,
        odds_endpoint_classes=prepared.odds_endpoint_classes,
        market_coverage_by_gameweek=coverage,
        exact_donor_assignment_count=exact,
        fallback_assignment_count=len(central.entries) - exact,
        complete_history_reconciliation_count=complete,
        partial_history_reconciliation_count=len(history.entries) - complete - failed,
        failed_history_reconciliation_count=failed,
        shadow_semantic_sha256=shadow.semantic_sha256,
        results=results,
        pairs=pairs,
        stage7_identical_across_worlds=stage7,
        stage8_identical_across_worlds=stage8,
        root_randomness_aligned=root_randomness,
        scenario_identity_aligned=scenarios,
        prices_identical_across_worlds=prices,
        manager_state_identical_across_worlds=manager,
        rules_identical_across_worlds=rules,
        work_budget_semantics_identical_across_worlds=budgets,
        fixture_order_identical_across_worlds=fixture_order,
        terminal_policy_identical_across_worlds=terminal_policy,
        candidate_policy_identical_across_worlds=candidate_policy,
        candidate_universe_same_across_worlds=candidate_same,
        root_action_same_across_all_worlds=root_same,
        full_plan_same_across_all_worlds=full_same,
        starting_xi_same_across_all_worlds=xi_same,
        captain_same_across_all_worlds=captain_same,
        vice_same_across_all_worlds=vice_same,
        model_input_status="SHADOW_NOT_MODEL_INPUT",
        production_activation=False,
        persistence_performed=False,
        model_training_performed=False,
        new_network_requests_during_world_comparison=cast(Literal[0], network_delta),
    )
    return observation, stale


class _A2PreparedRunner:
    def __init__(self, network_state: Callable[[], tuple[int, int, int]]) -> None:
        self.observation: LiveFourWorldShadowDecisionObservation | None = None
        self.prepared: _PrivateV1PreparedRollingContext | None = None
        self.failure_stage = A2FailureStage.BUILD_CURRENT_HISTORY
        self._network_state = network_state

    def __call__(
        self,
        prepared: _PrivateV1PreparedRollingContext,
        *,
        progress: ProgressSink,
    ) -> PrivateV1RollingRunResult:
        self.prepared = prepared
        sealed_network_state = self._network_state()
        self.failure_stage = A2FailureStage.BUILD_CURRENT_HISTORY
        history = _build_current_history(prepared)
        self.failure_stage = A2FailureStage.COMPILE_FIXED_SHADOW
        shadow = _compile_fixed_shadow(prepared, history)
        self.failure_stage = A2FailureStage.RUN_FOUR_WORLD_COMPARISON
        self.observation, stale = _run_live_comparison(
            prepared,
            history,
            shadow,
            progress=progress,
            network_state=self._network_state,
        )
        if self._network_state() != sealed_network_state:
            raise ValueError("provider access occurred during the four-world comparison")
        return stale


class _CountingOddsService(CurrentOddsTransientService):
    def __init__(self, delegate: CurrentOddsTransientService) -> None:
        self._delegate = delegate
        self.acquire_count = 0

    def acquire(
        self,
        *,
        information_cutoff: datetime,
        commence_to: datetime,
        required_h2h_commence_times: tuple[datetime, ...] | None = None,
    ) -> OddsProviderCurrentInput:
        self.acquire_count += 1
        return self._delegate.acquire(
            information_cutoff=information_cutoff,
            commence_to=commence_to,
            required_h2h_commence_times=required_h2h_commence_times,
        )


class _CountingScoreService(CurrentScorePriorService):
    def __init__(self, delegate: CurrentScorePriorService) -> None:
        self._delegate = delegate
        self.build_count = 0

    def build(self, request: CurrentScorePriorBuildRequest) -> CurrentScorePriorResult:
        self.build_count += 1
        return self._delegate.build(request)


def _blocked(
    reason: A2FailureReason,
    stage: A2FailureStage,
    direct: DirectFplClient | None,
    odds_attempts: int,
) -> LiveA2BlockedResult:
    return LiveA2BlockedResult(
        schema_version="r9c-a2-live-shadow-blocked-v1",
        status="BLOCKED",
        reason_code=reason,
        failure_stage=stage,
        fpl_request_attempt_count=0 if direct is None else direct.request_count,
        fpl_endpoint_classes=() if direct is None else direct.endpoint_classes,
        odds_acquisition_attempt_count=odds_attempts,
    )


def _safe_summary_blocked(
    observation: LiveFourWorldShadowDecisionObservation,
) -> LiveA2BlockedResult:
    return LiveA2BlockedResult(
        schema_version="r9c-a2-live-shadow-blocked-v1",
        status="BLOCKED",
        reason_code=A2FailureReason.SAFE_SUMMARY_FAILED,
        failure_stage=A2FailureStage.BUILD_SAFE_SUMMARY,
        fpl_request_attempt_count=observation.fpl_request_count,
        fpl_endpoint_classes=observation.fpl_endpoint_classes,
        odds_acquisition_attempt_count=observation.odds_request_count,
    )


class R9CA2LiveShadowObservationService:
    """One invocation, one preparation, four offline-after-preparation solves."""

    def __init__(
        self,
        *,
        direct_client_factory: Callable[
            [DirectFplRunAttestation, Callable[[], None]], DirectFplClient
        ]
        | None = None,
        odds_service_factory: Callable[[Callable[[], datetime]], CurrentOddsTransientService]
        | None = None,
        score_service_factory: Callable[
            [Callable[[], datetime], Callable[[], None]], CurrentScorePriorService
        ]
        | None = None,
        progress: ProgressSink | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._direct_client_factory = direct_client_factory
        self._odds_service_factory = odds_service_factory
        self._score_service_factory = score_service_factory
        self._progress = progress or NullProgress()
        self._clock = clock
        self._prepared_for_safe_summary: _PrivateV1PreparedRollingContext | None = None

    def run(
        self, request: A2OperatorRequest
    ) -> LiveFourWorldShadowDecisionObservation | LiveA2BlockedResult:
        direct: DirectFplClient | None = None
        odds_attempts = 0
        odds_service: _CountingOddsService | None = None
        score_service: _CountingScoreService | None = None

        def network_state() -> tuple[int, int, int]:
            return (
                0 if direct is None else direct.request_count,
                0 if odds_service is None else odds_service.acquire_count,
                0 if score_service is None else score_service.build_count,
            )

        def acquisition_time() -> datetime:
            value = self._clock()
            if value.tzinfo is None or value.utcoffset() is None:
                raise IngestionError("INTERNAL_INVARIANT", "A2 clock must be timezone-aware")
            value = value.astimezone(UTC)
            if value < request.operator_approved_at.astimezone(UTC):
                raise IngestionError("PRE_APPROVAL", "A2 acquisition window is not yet open")
            if value > request.acquisition_cutoff.astimezone(UTC):
                raise IngestionError("POST_CUTOFF", "A2 acquisition window expired")
            return value

        def acquisition_guard() -> None:
            acquisition_time()

        runner = _A2PreparedRunner(network_state)
        try:
            times = (request.operator_approved_at, request.acquisition_cutoff)
            if (
                type(request.entry_id) is not int
                or request.entry_id <= 0
                or len(request.code_sha) != 40
                or any(character not in "0123456789abcdef" for character in request.code_sha)
                or any(value.tzinfo is None or value.utcoffset() is None for value in times)
                or request.acquisition_cutoff <= request.operator_approved_at
                or request.acquisition_cutoff - request.operator_approved_at > timedelta(minutes=5)
                or request.scenario_count <= 0
            ):
                return _blocked(
                    A2FailureReason.RUNTIME_INPUT_INVALID,
                    A2FailureStage.VALIDATE_RUNTIME_INPUT,
                    direct,
                    odds_attempts,
                )
            try:
                checked_at = acquisition_time()
            except IngestionError:
                return _blocked(
                    A2FailureReason.FROZEN_CONTEXT_PREPARATION_FAILED,
                    A2FailureStage.PREPARE_FROZEN_CONTEXT,
                    direct,
                    odds_attempts,
                )
            _validate_provider_authority(request, checked_at=checked_at)

            def direct_factory(attestation: DirectFplRunAttestation) -> DirectFplClient:
                nonlocal direct
                direct = (
                    DirectFplClient(attestation, before_request=acquisition_guard)
                    if self._direct_client_factory is None
                    else self._direct_client_factory(attestation, acquisition_guard)
                )
                return direct

            def odds_factory(clock: Callable[[], datetime]) -> CurrentOddsTransientService:
                nonlocal odds_attempts, odds_service
                delegate = (
                    CurrentOddsTransientService(clock=clock)
                    if self._odds_service_factory is None
                    else self._odds_service_factory(clock)
                )
                odds_service = _CountingOddsService(delegate)
                odds_attempts += 1
                return odds_service

            def score_factory(clock: Callable[[], datetime]) -> CurrentScorePriorService:
                nonlocal score_service
                delegate = (
                    CurrentScorePriorService(clock=clock, before_request=acquisition_guard)
                    if self._score_service_factory is None
                    else self._score_service_factory(clock, acquisition_guard)
                )
                score_service = _CountingScoreService(delegate)
                return score_service

            service = PrivateV1OneCommandService(
                direct_client_factory=direct_factory,
                odds_service_factory=odds_factory,
                score_service_factory=score_factory,
                _prepared_rolling_runner=runner,
                _provider_request_guard=acquisition_guard,
                progress=self._progress,
                clock=self._clock,
            )
            service.run(
                OneCommandRequest(
                    entry_id=request.entry_id,
                    code_sha=request.code_sha,
                    run_at=request.acquisition_cutoff.astimezone(UTC),
                    operator_approved_at=request.operator_approved_at.astimezone(UTC),
                    run_id="PRIVATE_V1_R9C_A2_ONE_SHOT",
                    root_seed=request.root_seed,
                    scenario_count=request.scenario_count,
                    horizon_gameweeks=3,
                )
            )
            if runner.observation is None:
                return _blocked(
                    A2FailureReason.FOUR_WORLD_COMPARISON_FAILED,
                    runner.failure_stage,
                    direct,
                    odds_attempts,
                )
            self._prepared_for_safe_summary = runner.prepared
            return runner.observation
        except (PrivateV1Error, IngestionError, ValueError, ArithmeticError, KeyError, TypeError):
            reason = (
                A2FailureReason.PROVIDER_AUTHORITY_INVALID
                if runner.prepared is None and direct is None and odds_attempts == 0
                else A2FailureReason.FROZEN_CONTEXT_PREPARATION_FAILED
                if runner.prepared is None
                else A2FailureReason.CURRENT_HISTORY_INVALID
                if runner.failure_stage == A2FailureStage.BUILD_CURRENT_HISTORY
                else A2FailureReason.FIXED_SHADOW_COMPILE_FAILED
                if runner.failure_stage == A2FailureStage.COMPILE_FIXED_SHADOW
                else A2FailureReason.FOUR_WORLD_COMPARISON_FAILED
            )
            stage = (
                A2FailureStage.VALIDATE_PROVIDER_AUTHORITY
                if reason == A2FailureReason.PROVIDER_AUTHORITY_INVALID
                else A2FailureStage.PREPARE_FROZEN_CONTEXT
                if runner.prepared is None
                else runner.failure_stage
            )
            return _blocked(reason, stage, direct, odds_attempts)
        except Exception:
            return _blocked(
                A2FailureReason.UNEXPECTED_INTERNAL_FAILURE,
                A2FailureStage.INTERNAL,
                direct,
                odds_attempts,
            )

    def take_safe_summary(
        self, observation: LiveFourWorldShadowDecisionObservation
    ) -> dict[str, object] | LiveA2BlockedResult:
        """Render once, then release the source-bearing prepared context reference."""

        prepared = self._prepared_for_safe_summary
        self._prepared_for_safe_summary = None
        if prepared is None:
            return _safe_summary_blocked(observation)
        try:
            return safe_live_observation_summary(observation, prepared)
        except (KeyError, TypeError, ValueError):
            return _safe_summary_blocked(observation)


def safe_live_observation_summary(
    observation: LiveFourWorldShadowDecisionObservation,
    prepared: _PrivateV1PreparedRollingContext,
) -> dict[str, object]:
    """Render only approved private decision-level fields; never posterior rows."""

    player_by_element = {
        item.provider_element_id: item.web_name for item in prepared.snapshot.fpl_input.players
    }
    element_by_player = {
        str(item.canonical_player_id): item.official_fpl_element_id
        for item in prepared.player_identity_map.players
    }

    def label(player_id: str) -> str:
        return player_by_element[element_by_player[player_id]]

    worlds: list[dict[str, object]] = []
    for result in observation.results:
        signature = result.decision_signature
        worlds.append(
            {
                "world": result.world,
                "root_transfers": tuple(
                    {"out": label(out_id), "in": label(in_id)}
                    for out_id, in_id in signature.root_transfers
                ),
                "root_transfer_count": len(signature.root_transfers),
                "root_hit_points": signature.root_hit_points,
                "captain": label(signature.captain),
                "vice_captain": label(signature.vice_captain),
                "root_xi_semantic_sha256": canonical_sha256(signature.starting_xi),
                "continuation_action_signatures": signature.by_gameweek_action_signatures[1:],
                "continuation_transfer_counts": tuple(
                    len(item) for item in signature.by_gameweek_transfers[1:]
                ),
                "optimal_horizon_utility": str(result.plan_expected_horizon_utility),
                "hold_horizon_utility": str(result.baseline_expected_horizon_utility),
                "uplift_versus_hold": str(result.expected_uplift),
                "gain_p10": result.gain_p10,
                "gain_median": result.gain_median,
                "gain_p90": result.gain_p90,
                "decision_signature_sha256": signature.semantic_sha256,
            }
        )
    return {
        "schema_version": observation.schema_version,
        "status": observation.status,
        "target_gameweek": observation.target_gameweek,
        "finalized_history_gameweeks": observation.finalized_history_gameweeks,
        "horizon_gameweeks": observation.horizon_gameweeks,
        "information_cutoff_utc": observation.information_cutoff_utc,
        "fpl_request_count": observation.fpl_request_count,
        "fpl_endpoint_classes": observation.fpl_endpoint_classes,
        "odds_request_count": observation.odds_request_count,
        "odds_endpoint_classes": observation.odds_endpoint_classes,
        "market_coverage_by_gameweek": observation.market_coverage_by_gameweek,
        "exact_donor_assignment_count": observation.exact_donor_assignment_count,
        "fallback_assignment_count": observation.fallback_assignment_count,
        "complete_history_reconciliation_count": (
            observation.complete_history_reconciliation_count
        ),
        "partial_history_reconciliation_count": (observation.partial_history_reconciliation_count),
        "failed_history_reconciliation_count": observation.failed_history_reconciliation_count,
        "shadow_semantic_sha256": observation.shadow_semantic_sha256,
        "controls": {
            "stage7_identical_across_worlds": observation.stage7_identical_across_worlds,
            "stage8_identical_across_worlds": observation.stage8_identical_across_worlds,
            "root_randomness_aligned": observation.root_randomness_aligned,
            "scenario_identity_aligned": observation.scenario_identity_aligned,
            "prices_identical_across_worlds": observation.prices_identical_across_worlds,
            "manager_state_identical_across_worlds": observation.manager_state_identical_across_worlds,
            "rules_identical_across_worlds": observation.rules_identical_across_worlds,
            "work_budget_semantics_identical_across_worlds": (
                observation.work_budget_semantics_identical_across_worlds
            ),
            "fixture_order_identical_across_worlds": (
                observation.fixture_order_identical_across_worlds
            ),
            "terminal_policy_identical_across_worlds": (
                observation.terminal_policy_identical_across_worlds
            ),
            "candidate_policy_identical_across_worlds": (
                observation.candidate_policy_identical_across_worlds
            ),
            "candidate_universe_same_across_worlds": (
                observation.candidate_universe_same_across_worlds
            ),
        },
        "worlds": tuple(worlds),
        "robustness": {
            "root_action_same_across_all_worlds": observation.root_action_same_across_all_worlds,
            "full_plan_same_across_all_worlds": observation.full_plan_same_across_all_worlds,
            "starting_xi_same_across_all_worlds": (observation.starting_xi_same_across_all_worlds),
            "captain_same_across_all_worlds": observation.captain_same_across_all_worlds,
            "vice_same_across_all_worlds": observation.vice_same_across_all_worlds,
            "pair_classifications": tuple(
                {"left": item.left, "right": item.right, "classification": item.classification}
                for item in observation.pairs
            ),
            "candidate_screen_attribution": (
                "COMMON_CANDIDATE_UNIVERSE_VALUATION_COMPARISON"
                if observation.candidate_universe_same_across_worlds
                else "CANONICAL_PER_WORLD_SCREEN_CONTRIBUTES"
            ),
        },
        "model_input_status": observation.model_input_status,
        "persistence_performed": False,
        "model_training_performed": False,
        "production_activation": False,
        "new_network_requests_during_world_comparison": (
            observation.new_network_requests_during_world_comparison
        ),
        "interpretation": "MODEL_MOVEMENT_NOT_MODEL_ACCURACY",
        "semantic_sha256": observation.semantic_sha256,
    }


__all__ = [
    "A2_APPROVAL_REFERENCE",
    "A2_EXECUTION_ATTESTATION",
    "A2FailureReason",
    "A2FailureStage",
    "A2OperatorRequest",
    "LiveA2BlockedResult",
    "LiveFourWorldShadowDecisionObservation",
    "LiveShadowComparisonPair",
    "R9CA2LiveShadowObservationService",
    "safe_live_observation_summary",
]
