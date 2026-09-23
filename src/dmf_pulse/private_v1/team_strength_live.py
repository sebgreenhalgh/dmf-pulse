"""Historical L1/L2/L3 operator experiment, never selected by ordinary dmf pulse.

All three live authorities are consumed. Legacy L1 names and the historical run
identity remain for offline regression only; D3 repairs diagnostic transport.

Only an allowlisted summary escapes. The prepared-context callback completes via
a private exception carrying that summary, because the inherited callback return
contract is a single rolling run. This avoids a third solve, a fake rolling result,
or modifications to accepted 001P comparison mathematics.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from statistics import median
from typing import Never, cast

from dmf_pulse.football_events.team_strength_adapter import _source_assessment
from dmf_pulse.ingestion.fpl.direct import (
    DirectFplClient,
    DirectFplCredentialProvider,
    DirectFplRunAttestation,
    DirectTransport,
    DirectUrllibTransport,
)
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.ingestion.odds.client import HttpClientOddsTransport, OddsClient, OddsTransport
from dmf_pulse.ingestion.odds.credentials import (
    CredentialProvider,
    EnvironmentOddsCredentialProvider,
)
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
from dmf_pulse.ingestion.odds.transient import CurrentOddsTransientService
from dmf_pulse.ingestion.openfootball.client import (
    HttpClientOpenFootballTransport,
    OpenFootballTransport,
)
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    CurrentScorePriorResult,
    CurrentScorePriorService,
)
from dmf_pulse.ingestion.openfootball.team_strength_current import (
    CurrentTeamStrengthReadiness,
    current_dataset,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import authenticate
from dmf_pulse.private_v1.one_command import (
    OneCommandRequest,
    PrivateV1OneCommandService,
    _PrivateV1PreparedRollingContext,
)
from dmf_pulse.private_v1.prepared_control import PreparedRollingControlFlow
from dmf_pulse.private_v1.progress import ProgressSink
from dmf_pulse.private_v1.team_strength_comparison import (
    TeamStrengthComparisonRun,
    run_team_strength_shadow_comparison,
    safe_team_strength_summary,
)
from dmf_pulse.private_v1.team_strength_diagnostics import (
    TeamStrengthComparisonFailure,
    safe_comparison_failure,
)
from dmf_pulse.private_v1.team_strength_live_authority import (
    APPROVAL,
    ATTESTATION,
    ConsumedL1ApprovalError,
    validate_l1_authority,
)
from dmf_pulse.private_v1.team_strength_live_network import (
    GuardedFplTransport,
    GuardedOddsTransport,
    GuardedOpenFootballTransport,
    OneShotNetworkGate,
)
from dmf_pulse.private_v1.team_strength_shadow_inputs import (
    TeamStrengthShadowInput,
    TeamStrengthShadowPreparation,
    prepare_team_strength_shadow,
)


class L1Stage(StrEnum):
    VALIDATE_RUNTIME_INPUT = "VALIDATE_RUNTIME_INPUT"
    VALIDATE_RIGHTS = "VALIDATE_RIGHTS"
    ASSESS_TEAM_STRENGTH_SOURCE = "ASSESS_TEAM_STRENGTH_SOURCE"
    PREPARE_PRIVATE_FROZEN_CONTEXT = "PREPARE_PRIVATE_FROZEN_CONTEXT"
    PREPARE_TEAM_STRENGTH_SHADOW = "PREPARE_TEAM_STRENGTH_SHADOW"
    RUN_TWO_WORLD_COMPARISON = "RUN_TWO_WORLD_COMPARISON"
    BUILD_SAFE_SUMMARY = "BUILD_SAFE_SUMMARY"
    INVOKE_TWO_WORLD_COMPARISON = "INVOKE_TWO_WORLD_COMPARISON"
    RECONCILE_POST_COMPARISON_PROVIDER_COUNTERS = "RECONCILE_POST_COMPARISON_PROVIDER_COUNTERS"
    VALIDATE_COMPARISON_RESULT_TYPE = "VALIDATE_COMPARISON_RESULT_TYPE"
    SERIALIZE_COMPARISON_DIAGNOSTIC = "SERIALIZE_COMPARISON_DIAGNOSTIC"
    BUILD_SAFE_SUCCESS_SUMMARY = "BUILD_SAFE_SUCCESS_SUMMARY"


class L1Reason(StrEnum):
    RUNTIME_INPUT_INVALID = "RUNTIME_INPUT_INVALID"
    AUTHORITY_INVALID = "AUTHORITY_INVALID"
    AUTHORITY_CONSUMED = "AUTHORITY_CONSUMED"
    PUBLIC_READINESS_INVALID = "PUBLIC_READINESS_INVALID"
    SOURCE_STALE = "SOURCE_STALE"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
    FROZEN_CONTEXT_FAILED = "FROZEN_CONTEXT_FAILED"
    SHADOW_UNAVAILABLE = "SHADOW_UNAVAILABLE"
    CURRENT_ARTIFACT_UNAVAILABLE = "CURRENT_ARTIFACT_UNAVAILABLE"
    CURRENT_SOURCE_ASSESSMENT_UNAVAILABLE = "CURRENT_SOURCE_ASSESSMENT_UNAVAILABLE"
    INCOMPLETE_FIXTURE_COVERAGE = "INCOMPLETE_FIXTURE_COVERAGE"
    TWO_WORLD_COMPARISON_FAILED = "TWO_WORLD_COMPARISON_FAILED"
    SAFE_SUMMARY_FAILED = "SAFE_SUMMARY_FAILED"
    COMPARISON_INVOCATION_FAILED = "COMPARISON_INVOCATION_FAILED"
    PROVIDER_COUNTER_RECONCILIATION_FAILED = "PROVIDER_COUNTER_RECONCILIATION_FAILED"
    PROVIDER_COUNTER_DIVERGENCE_DURING_COMPARISON = "PROVIDER_COUNTER_DIVERGENCE_DURING_COMPARISON"
    COMPARISON_RESULT_TYPE_INVALID = "COMPARISON_RESULT_TYPE_INVALID"
    SAFE_COMPARISON_DIAGNOSTIC_INVALID = "SAFE_COMPARISON_DIAGNOSTIC_INVALID"
    SAFE_SUCCESS_SUMMARY_FAILED = "SAFE_SUCCESS_SUMMARY_FAILED"
    ALREADY_INVOKED = "ALREADY_INVOKED"


@dataclass(frozen=True, repr=False)
class L1OperatorRequest:
    entry_id: int
    code_sha: str
    approval: str
    attestation: str
    readiness_sha256: str


class _ObservationComplete(PreparedRollingControlFlow):
    def __init__(self, summary: dict[str, object]) -> None:
        super().__init__("safe observation complete")
        self.summary = summary


class _LiveWrapperFailure(PreparedRollingControlFlow):
    """Closed wrapper failure; no nested exception text is retained or emitted."""

    def __init__(self, stage: L1Stage, reason: L1Reason) -> None:
        self.stage = stage
        self.reason = reason
        super().__init__("closed live wrapper failure")


_PROVIDER_COUNTER_ORDER = (
    "FPL_SENDS",
    "ODDS_SENDS",
    "OPENFOOTBALL_SENDS",
    "FPL_SESSIONS",
    "ODDS_ACQUISITIONS",
    "LEAGUE_ACQUISITIONS",
    "DENIED_SENDS",
)

_SHADOW_PREPARATION_FAILURES = {
    "SOURCE_STALE": L1Reason.SOURCE_STALE,
    "CURRENT_ARTIFACT_UNAVAILABLE": L1Reason.CURRENT_ARTIFACT_UNAVAILABLE,
    "CURRENT_SOURCE_ASSESSMENT_UNAVAILABLE": L1Reason.CURRENT_SOURCE_ASSESSMENT_UNAVAILABLE,
    "INCOMPLETE_FIXTURE_COVERAGE": L1Reason.INCOMPLETE_FIXTURE_COVERAGE,
}


def _counter_deltas(before: tuple[int, ...], after: tuple[int, ...]) -> dict[str, int]:
    if (
        len(before) != len(_PROVIDER_COUNTER_ORDER)
        or len(after) != len(_PROVIDER_COUNTER_ORDER)
        or any(type(value) is not int for value in (*before, *after))
    ):
        raise ValueError("provider counter shape invalid")
    deltas = {
        name: right - left
        for name, left, right in zip(_PROVIDER_COUNTER_ORDER, before, after, strict=True)
    }
    if any(value < 0 for value in deltas.values()):
        raise ValueError("provider counter moved backwards")
    return deltas


def _prior_movement(
    run: TeamStrengthComparisonRun, shadow: TeamStrengthShadowInput
) -> tuple[dict[str, object], ...]:
    result = []
    for gw in run.comparison.horizon:
        bindings = tuple(row for row in shadow.fixtures if row.gameweek == gw)
        home = tuple(
            abs(
                row.public_bundle.score_prior.home_goal_rate
                - row.baseline_prior.score_prior_request.home_goal_rate
            )
            for row in bindings
        )
        away = tuple(
            abs(
                row.public_bundle.score_prior.away_goal_rate
                - row.baseline_prior.score_prior_request.away_goal_rate
            )
            for row in bindings
        )
        coverage = next(row for row in run.comparison.market_coverage if row.gameweek == gw)
        result.append(
            {
                **coverage.model_dump(mode="json"),
                "median_absolute_home_lambda_movement": str(median(home)),
                "median_absolute_away_lambda_movement": str(median(away)),
                "maximum_lambda_movement": str(max(*home, *away)),
                "changed_stage8_outputs": sum(
                    row.baseline_stage8_sha256 != row.shadow_stage8_sha256
                    for row in run.comparison.fixtures
                    if row.gameweek == gw
                ),
            }
        )
    return tuple(result)


def json_safe(value: object) -> object:
    """Closed serialization: never fall back to repr/str of arbitrary objects."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal) and value.is_finite():
        return str(value)
    if isinstance(value, (tuple, list)):
        return [json_safe(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: json_safe(item) for key, item in value.items()}
    raise ValueError("non-allowlisted summary value")


class TeamStrengthL1ObservationService:
    """One invocation, one preparation, exactly the accepted two-world comparison."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        fpl_transport: DirectTransport | None = None,
        odds_transport: OddsTransport | None = None,
        public_transport: OpenFootballTransport | None = None,
        fpl_credentials: DirectFplCredentialProvider | None = None,
        odds_credentials: EnvironmentOddsCredentialProvider | None = None,
    ) -> None:
        self._clock = clock
        self._fpl_transport = fpl_transport
        self._odds_transport = odds_transport
        self._public_transport = public_transport
        self._fpl_credentials = fpl_credentials or DirectFplCredentialProvider()
        self._odds_credentials = odds_credentials or EnvironmentOddsCredentialProvider()
        self._invoked = False
        self._gate: OneShotNetworkGate | None = None
        self._comparison_invocation_started = False
        self._comparison_invocation_returned = False
        self._provider_counter_deltas: dict[str, int] | None = None

    def guard_network_event(self) -> None:
        """Standalone operator audit hook: deny uninstrumented post-freeze I/O."""
        if self._gate is None or self._gate.closed:
            if self._gate is not None:
                self._gate.denied += 1
            raise ValueError("network outside private acquisition")
        self._gate.window()

    def _blocked(self, stage: L1Stage, reason: L1Reason) -> dict[str, object]:
        gate = self._gate
        result: dict[str, object] = {
            "status": "TEAM_STRENGTH_PUBLIC_PREFLIGHT_BLOCKED"
            if stage == L1Stage.ASSESS_TEAM_STRENGTH_SOURCE
            and reason != L1Reason.CREDENTIAL_UNAVAILABLE
            else "CURRENT_TEAM_STRENGTH_001P_L3_LIVE_EXECUTION_NOT_COMPLETED",
            "stage": stage.value,
            "reason": reason.value,
            "private_attempt_consumed": gate.consumed if gate else False,
            "fpl_requests": gate.counts["FPL"] if gate else 0,
            "fpl_endpoint_classes": tuple(gate.fpl_endpoints) if gate else (),
            "odds_requests": gate.counts["ODDS"] if gate else 0,
            "odds_acquisitions": gate.odds_acquisitions if gate else 0,
            "retry_performed": False,
            "persistence": False,
            "production_activation": False,
            "comparison_invocation_started": self._comparison_invocation_started,
            "comparison_invocation_returned": self._comparison_invocation_returned,
        }
        if self._provider_counter_deltas is not None:
            result["provider_counter_deltas"] = dict(self._provider_counter_deltas)
        return result

    def _invoke_two_world_comparison(
        self,
        prepared: _PrivateV1PreparedRollingContext,
        preparation: TeamStrengthShadowPreparation,
        gate: OneShotNetworkGate,
    ) -> tuple[TeamStrengthComparisonRun, tuple[int, ...], tuple[int, ...]]:
        try:
            before = gate.counters()
        except (Exception, KeyboardInterrupt):
            raise _LiveWrapperFailure(
                L1Stage.RECONCILE_POST_COMPARISON_PROVIDER_COUNTERS,
                L1Reason.PROVIDER_COUNTER_RECONCILIATION_FAILED,
            ) from None
        self._comparison_invocation_started = True
        try:
            run = run_team_strength_shadow_comparison(prepared, preparation)
        except TeamStrengthComparisonFailure:
            raise
        except (Exception, KeyboardInterrupt):
            raise _LiveWrapperFailure(
                L1Stage.INVOKE_TWO_WORLD_COMPARISON,
                L1Reason.COMPARISON_INVOCATION_FAILED,
            ) from None
        self._comparison_invocation_returned = True
        try:
            after = gate.counters()
            deltas = _counter_deltas(before, after)
        except (Exception, KeyboardInterrupt):
            raise _LiveWrapperFailure(
                L1Stage.RECONCILE_POST_COMPARISON_PROVIDER_COUNTERS,
                L1Reason.PROVIDER_COUNTER_RECONCILIATION_FAILED,
            ) from None
        if before != after:
            self._provider_counter_deltas = deltas
            raise _LiveWrapperFailure(
                L1Stage.RECONCILE_POST_COMPARISON_PROVIDER_COUNTERS,
                L1Reason.PROVIDER_COUNTER_DIVERGENCE_DURING_COMPARISON,
            )
        if not isinstance(run, TeamStrengthComparisonRun):
            raise _LiveWrapperFailure(
                L1Stage.VALIDATE_COMPARISON_RESULT_TYPE,
                L1Reason.COMPARISON_RESULT_TYPE_INVALID,
            )
        return run, before, after

    def _build_safe_success_summary(
        self,
        *,
        run: TeamStrengthComparisonRun,
        shadow: TeamStrengthShadowInput,
        gate: OneShotNetworkGate,
        prepared: _PrivateV1PreparedRollingContext,
        before: tuple[int, ...],
        after: tuple[int, ...],
        request: L1OperatorRequest,
        ready: CurrentTeamStrengthReadiness,
    ) -> dict[str, object]:
        try:
            summary = safe_team_strength_summary(run)
            worlds = cast(tuple[dict[str, object], ...], summary["worlds"])
            for world, result in zip(worlds, run.comparison.worlds, strict=True):
                world["continuation_transfer_counts"] = tuple(
                    row.transfer_count for row in result.signature.by_gameweek[1:]
                )
            summary.update(
                status="CURRENT_TEAM_STRENGTH_001P_L3_LIVE_OBSERVATION_COMPLETE",
                private_attempt_consumed=gate.consumed,
                retry_performed=False,
                approval=APPROVAL,
                attestation=ATTESTATION,
                code_sha=request.code_sha,
                interpretation="DECISION_MATERIALITY_NOT_MODEL_ACCURACY",
                fpl_endpoint_classes=prepared.fpl_endpoint_classes,
                odds_endpoint_classes=prepared.odds_endpoint_classes,
                acquisition_counts={
                    "FPL": gate.fpl_sessions,
                    "ODDS": gate.odds_acquisitions,
                    "LEAGUE_PRIOR": gate.league_acquisitions,
                },
                provider_counters_before=before,
                provider_counters_after=after,
                provider_counter_order=_PROVIDER_COUNTER_ORDER,
                comparison_invocation_started=True,
                comparison_invocation_returned=True,
                prior_movement_by_gameweek=_prior_movement(run, shadow),
                public_artifact_sha256=ready.artifact.semantic_sha256,
                parameter_mixture_active=False,
                ordinary_path_changed=False,
            )
            return cast(dict[str, object], json_safe(summary))
        except (Exception, KeyboardInterrupt):
            raise _LiveWrapperFailure(
                L1Stage.BUILD_SAFE_SUCCESS_SUMMARY,
                L1Reason.SAFE_SUCCESS_SUMMARY_FAILED,
            ) from None

    def _comparison_failure_result(
        self, failure: TeamStrengthComparisonFailure
    ) -> dict[str, object]:
        try:
            diagnostic = safe_comparison_failure(failure)
        except (Exception, KeyboardInterrupt):
            return self._blocked(
                L1Stage.SERIALIZE_COMPARISON_DIAGNOSTIC,
                L1Reason.SAFE_COMPARISON_DIAGNOSTIC_INVALID,
            )
        # D1's exact stage/reason and all existing safe fields intentionally
        # override the invocation wrapper's generic location.
        return {
            **self._blocked(
                L1Stage.INVOKE_TWO_WORLD_COMPARISON,
                L1Reason.COMPARISON_INVOCATION_FAILED,
            ),
            **diagnostic,
        }

    def run(
        self, request: L1OperatorRequest, ready: CurrentTeamStrengthReadiness
    ) -> dict[str, object]:
        if self._invoked:
            return self._blocked(L1Stage.VALIDATE_RUNTIME_INPUT, L1Reason.ALREADY_INVOKED)
        self._invoked = True
        stage, reason = L1Stage.VALIDATE_RUNTIME_INPUT, L1Reason.RUNTIME_INPUT_INVALID
        try:
            started = self._clock()
            if (
                started.tzinfo is None
                or started.utcoffset() is None
                or type(request.entry_id) is not int
                or request.entry_id <= 0
                or re.fullmatch(r"[0-9a-f]{40}", request.code_sha) is None
            ):
                raise ValueError("invalid operator input")
            # Existing Odds commence filters require whole-second UTC precision.
            # Round the window end down, never beyond the five-minute ceiling.
            cutoff = (started.astimezone(UTC) + timedelta(minutes=5)).replace(microsecond=0)
            stage, reason = L1Stage.VALIDATE_RIGHTS, L1Reason.AUTHORITY_INVALID
            validate_l1_authority(
                approval=request.approval, attestation=request.attestation, checked_at=started
            )
            stage, reason = L1Stage.ASSESS_TEAM_STRENGTH_SOURCE, L1Reason.PUBLIC_READINESS_INVALID
            ready = authenticate(ready, request.readiness_sha256)
            if ready.artifact.usable_at > cutoff:
                raise ValueError("post-cutoff public model")
            assessment = _source_assessment(
                current_dataset(
                    sources=ready.sources, fixtures=ready.fixture_registry, cutoff=cutoff
                )
            )
            if assessment.freshness == "STALE_BLOCKED":
                return self._blocked(stage, L1Reason.SOURCE_STALE)
            # Check runtime credentials without ever emitting or storing values.
            reason = L1Reason.CREDENTIAL_UNAVAILABLE
            self._fpl_credentials.get()
            self._odds_credentials.get_credential()
            gate = OneShotNetworkGate(started, cutoff, self._clock)
            self._gate = gate
            stage, reason = L1Stage.PREPARE_PRIVATE_FROZEN_CONTEXT, L1Reason.FROZEN_CONTEXT_FAILED

            def direct_factory(attestation: DirectFplRunAttestation) -> DirectFplClient:
                gate.window()
                gate.fpl_sessions += 1
                if gate.fpl_sessions != 1:
                    raise ValueError("repeated FPL session")
                return DirectFplClient(
                    attestation,
                    credential_provider=self._fpl_credentials,
                    maximum_attempts=1,
                    before_request=gate.preparation_guard,
                    transport=GuardedFplTransport(
                        gate, self._fpl_transport or DirectUrllibTransport()
                    ),
                )

            def odds_factory(clock: Callable[[], datetime]) -> CurrentOddsTransientService:
                def client_factory(
                    profile: RightsProfile,
                    *,
                    credential_provider: CredentialProvider,
                    clock: Callable[[], datetime],
                ) -> OddsClient:
                    return OddsClient(
                        profile,
                        credential_provider=credential_provider,
                        clock=clock,
                        maximum_attempts=1,
                        transport_factory=lambda: GuardedOddsTransport(
                            gate, self._odds_transport or HttpClientOddsTransport()
                        ),
                    )

                class OneOddsAcquisition(CurrentOddsTransientService):
                    def acquire(
                        self,
                        *,
                        information_cutoff: datetime,
                        commence_to: datetime,
                        required_h2h_commence_times: tuple[datetime, ...] | None = None,
                    ) -> OddsProviderCurrentInput:
                        gate.window()
                        gate.odds_acquisitions += 1
                        if gate.odds_acquisitions != 1:
                            raise ValueError("repeated Odds acquisition")
                        return super().acquire(
                            information_cutoff=information_cutoff,
                            commence_to=commence_to,
                            required_h2h_commence_times=required_h2h_commence_times,
                        )

                return OneOddsAcquisition(
                    credential_provider=self._odds_credentials,
                    client_factory=client_factory,
                    clock=clock,
                )

            def score_factory(clock: Callable[[], datetime]) -> CurrentScorePriorService:
                class OneLeagueAcquisition(CurrentScorePriorService):
                    def build(
                        self, request: CurrentScorePriorBuildRequest
                    ) -> CurrentScorePriorResult:
                        gate.window()
                        gate.league_acquisitions += 1
                        if gate.league_acquisitions != 1:
                            raise ValueError("repeated league acquisition")
                        result = super().build(request)
                        gate.closed = True
                        return result

                return OneLeagueAcquisition(
                    clock=clock,
                    transport=GuardedOpenFootballTransport(
                        gate, self._public_transport or HttpClientOpenFootballTransport()
                    ),
                )

            def prepared_runner(
                prepared: _PrivateV1PreparedRollingContext, *, progress: ProgressSink
            ) -> Never:
                del progress
                nonlocal stage, reason
                if (
                    not gate.closed
                    or gate.denied
                    or (gate.fpl_sessions, gate.odds_acquisitions, gate.league_acquisitions)
                    != (1, 1, 1)
                    or gate.counts["FPL"] != prepared.fpl_request_count
                    or gate.counts["ODDS"] != prepared.odds_request_count
                    or prepared.score_prior_acquisition_count != 1
                ):
                    raise ValueError("acquisition accounting differs")
                stage, reason = L1Stage.PREPARE_TEAM_STRENGTH_SHADOW, L1Reason.SHADOW_UNAVAILABLE
                preparation = prepare_team_strength_shadow(
                    prepared.rolling_execution,
                    artifact=ready.artifact,
                    expected_artifact_sha256=ready.artifact.semantic_sha256,
                    fixture_registry=ready.fixture_registry,
                    source_assessment=assessment,
                )
                if preparation.shadow_input is None:
                    raise _LiveWrapperFailure(
                        L1Stage.PREPARE_TEAM_STRENGTH_SHADOW,
                        _SHADOW_PREPARATION_FAILURES.get(
                            preparation.reason, L1Reason.SHADOW_UNAVAILABLE
                        ),
                    )
                stage, reason = (
                    L1Stage.INVOKE_TWO_WORLD_COMPARISON,
                    L1Reason.COMPARISON_INVOCATION_FAILED,
                )
                run, before, after = self._invoke_two_world_comparison(prepared, preparation, gate)
                stage, reason = (
                    L1Stage.BUILD_SAFE_SUCCESS_SUMMARY,
                    L1Reason.SAFE_SUCCESS_SUMMARY_FAILED,
                )
                raise _ObservationComplete(
                    self._build_safe_success_summary(
                        run=run,
                        shadow=preparation.shadow_input,
                        gate=gate,
                        prepared=prepared,
                        before=before,
                        after=after,
                        request=request,
                        ready=ready,
                    )
                )

            PrivateV1OneCommandService(
                direct_client_factory=direct_factory,
                odds_service_factory=odds_factory,
                score_service_factory=score_factory,
                _prepared_rolling_runner=prepared_runner,
                _provider_request_guard=gate.preparation_guard,
                clock=self._clock,
            ).run(
                OneCommandRequest(
                    entry_id=request.entry_id,
                    code_sha=request.code_sha,
                    run_at=cutoff,
                    operator_approved_at=started,
                    horizon_gameweeks=3,
                    run_id="CURRENT-TEAM-STRENGTH-001P-L3",
                )
            )
        except _ObservationComplete as completed:
            return completed.summary
        except _LiveWrapperFailure as failure:
            return self._blocked(failure.stage, failure.reason)
        except ConsumedL1ApprovalError:
            return {
                **self._blocked(L1Stage.VALIDATE_RIGHTS, L1Reason.AUTHORITY_CONSUMED),
                "prior_l1_one_shot_consumed": True,
                "prior_l2_one_shot_consumed": True,
                "prior_l3_one_shot_consumed": True,
                "fresh_live_authorization_required": True,
            }
        except TeamStrengthComparisonFailure as failure:
            return self._comparison_failure_result(failure)
        except (Exception, KeyboardInterrupt):
            # No exception text, chained traceback, provider payload or entry ID
            # escapes this terminal boundary, including unexpected failures.
            return self._blocked(stage, reason)
        finally:
            if self._gate is not None:
                self._gate.closed = True
        return self._blocked(stage, reason)
