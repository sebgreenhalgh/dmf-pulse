"""One diagnostic session, one retained typed snapshot and two unchanged kernels.

Only fixed installed authority and the canonical journal admit acquisition.
The supervisor runs this in a bounded verified child and closes custody only
after that child and its transports have stopped. No automatic retry lives here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard.current_sources import CurrentSourceFactories, GuardedFplTransport
from dmf_pulse.dashboard.runtime import PipeProgress
from dmf_pulse.ingestion.fpl.direct import DirectFplRunAttestation, DirectUrllibTransport
from dmf_pulse.ingestion.fpl.direct_payloads import acquire_direct_fpl_snapshot
from dmf_pulse.ingestion.odds.models import QualifiedOperatorQuota
from dmf_pulse.ingestion.openfootball.service import (
    CurrentScorePriorBuildRequest,
    ScorePriorProfileId,
)
from dmf_pulse.operation.campaign import DiagnosticPaidGateProof
from dmf_pulse.operation.campaign_journal import DiagnosticJournal, DiagnosticSession
from dmf_pulse.operation.campaign_publication import build_diagnostic_publication
from dmf_pulse.operation.campaign_runtime import (
    bind_official_discovery,
    diagnostic_source_context,
    require_runtime,
)
from dmf_pulse.operation.campaign_sources import DiagnosticGuard, DiagnosticQuotaTransport
from dmf_pulse.operation.diagnostic_market import controlled_market_for_snapshot
from dmf_pulse.operation.diagnostic_pipeline import (
    assemble_diagnostic_execution,
    prepare_diagnostic_fpl,
    run_diagnostic_kernel,
)
from dmf_pulse.operation.diagnostics import STAGE_LABELS, DiagnosticLog
from dmf_pulse.operation.discovery import discover_event
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.quota import QuotaClient
from dmf_pulse.operation.standing import QuotaProof
from dmf_pulse.private_v1.one_command import OneCommandRequest


def diagnostic_run_id(key: str) -> str:
    """Preserve canonical session identity in the protected uppercase run namespace."""
    if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
        raise OperationError("DIAGNOSTIC_SESSION_NOT_FOUND")
    return "OPR003_" + key.upper()


def _quota(guard: DiagnosticGuard, *, phase: Literal["INITIAL", "PRE_PAID"]) -> QuotaProof:
    if phase not in {"INITIAL", "PRE_PAID"}:
        raise OperationError("DIAGNOSTIC_EXACT_QUOTA_PHASE_REQUIRED")
    guard.phase = phase
    guard.diagnostics.enter("QUOTA_VERIFICATION")
    runtime = require_runtime(guard.key)
    observation = QuotaClient(
        guard=guard,
        transport=DiagnosticQuotaTransport(guard),
        clock=guard.clock,
    ).fetch(runtime.authority.normal_policy.quota_qualification, admission=guard.quota_admission)
    proof = QuotaProof(
        source="ZERO_CREDIT_PROVIDER_RESPONSE_HEADERS",
        remaining_credits=observation.remaining_credits,
        used_credits=observation.used_credits,
        last_request_cost=0,
        request_started_at=observation.request_started_at,
        received_at=observation.received_at,
        qualification_sha256=observation.qualification_sha256,
        observation_sha256=observation.semantic_sha256,
    )
    guard.journal.record_quota(guard.key, guard.phase, proof, now=guard.clock())
    return proof


def execute_active_session(
    journal: DiagnosticJournal,
    key: str,
    credential_expires_at: datetime,
    *,
    clock: Callable[[], datetime],
    send: Callable[[tuple[str, object]], None],
) -> None:
    """Internal verified-worker entry; inputs contain no credential or source body."""
    log = DiagnosticLog(clock=clock)
    progress = PipeProgress(send, diagnostics=log)
    try:
        with diagnostic_source_context(journal, key) as canonical_journal:
            journal = canonical_journal
            runtime = require_runtime(key)
            authority = runtime.authority
            session: DiagnosticSession = runtime.session
            run_id = diagnostic_run_id(key)
            if credential_expires_at < session.started_at + timedelta(
                seconds=authority.proposal.limits.minimum_fpl_credential_remaining_seconds
            ):
                raise OperationError("DIAGNOSTIC_FRESH_CREDENTIAL_WINDOW_REQUIRED")
            guard = DiagnosticGuard(journal, key, diagnostics=log)
            progress.message(STAGE_LABELS["QUOTA_VERIFICATION"])
            initial = _quota(guard, phase="INITIAL")
            if session.mode == "READ_ONLY":
                journal.reconcile_initial_counter(key, initial, now=clock())
            else:
                journal.original.qualify_quota(initial, now=clock())
            profiles = {
                source.scope.provider: source.profile
                for source in authority.normal_policy.qualifications
            }
            log.enter("FPL_ACQUISITION")
            event = discover_event(
                profile=profiles["FPL"],
                admission=guard.check,
                before_send=guard.check,
                clock=clock,
                transport=GuardedFplTransport(guard, DirectUrllibTransport()),
            )
            bind_official_discovery(key, event)
            send(("phase", "OFFICIAL_GW10_DEADLINE_VERIFIED"))
            model_cutoff = min(
                session.started_at
                + timedelta(seconds=authority.proposal.limits.maximum_pre_paid_seconds),
                session.lease_until - timedelta(microseconds=1),
                event.deadline_at - timedelta(microseconds=1),
            ).replace(microsecond=0)

            def input_clock() -> datetime:
                now = clock()
                if not session.started_at <= now <= model_cutoff:
                    raise OperationError("DIAGNOSTIC_ACQUISITION_WINDOW_EXPIRED")
                return now

            def sources(quota: QuotaProof) -> CurrentSourceFactories:
                return CurrentSourceFactories(
                    guard=guard,
                    owned=False,
                    fpl_profile=profiles["FPL"],
                    odds_profile=profiles["ODDS"],
                    score_profile=profiles["OPENFOOTBALL"],
                    quota=QualifiedOperatorQuota(
                        remaining=quota.remaining_credits,
                        observed_at=quota.received_at,
                        evidence_sha256=quota.observation_sha256,
                    ),
                    clock=input_clock,
                    protected_odds_only=True,
                )

            factories = sources(initial)
            client = factories.direct(DirectFplRunAttestation(attested_at=session.started_at))
            snapshot = acquire_direct_fpl_snapshot(
                client,
                entry_id=authority.proposal.entry_id,
                captured_at=model_cutoff,
                clock=input_clock,
            )
            if (
                snapshot.target_gameweek != event.target_gameweek
                or snapshot.fpl_input.target_event.deadline_at != event.deadline_at
                or snapshot.request_count + 1 > authority.proposal.limits.fpl_gets_per_session
                or tuple(snapshot.live_by_gameweek) != event.history_gameweeks
            ):
                raise OperationError("DIAGNOSTIC_EXACT_FPL_DISCOVERY_SNAPSHOT_REQUIRED")
            log.enter("MANAGER_STATE")
            prepared = prepare_diagnostic_fpl(
                snapshot, approved_at=session.started_at, observed_at=input_clock()
            )
            validated_at = clock()
            journal.record_stage(
                key, "FPL_VALIDATION", prepared.validation_sha256, now=validated_at
            )
            log.enter("SCORE_SOURCE_ACQUISITION")
            prior = factories.score(input_clock).build(
                CurrentScorePriorBuildRequest(
                    information_cutoff=model_cutoff,
                    rights_profile_id=cast(
                        ScorePriorProfileId, profiles["OPENFOOTBALL"].rights_profile_id
                    ),
                )
            )
            controlled_market = controlled_market_for_snapshot(
                snapshot, profiles["ODDS"], assembled_at=input_clock()
            )
            request = OneCommandRequest(
                entry_id=authority.proposal.entry_id,
                code_sha=authority.normal_policy.implementation_sha,
                run_at=model_cutoff,
                operator_approved_at=session.started_at,
                run_id=run_id,
                scenario_count=256,
                root_seed=42,
            )
            controlled_input = assemble_diagnostic_execution(
                prepared,
                controlled_market.odds,
                prior,
                request,
                resolved_at=input_clock(),
                progress=progress,
            )
            controlled = run_diagnostic_kernel(controlled_input, controlled=True, progress=progress)
            controlled_proof = controlled.controlled_proof()
            controlled_sha = canonical_sha256(controlled_proof)
            controlled_at = clock()
            journal.record_stage(key, "CONTROLLED_GATE", controlled_sha, now=controlled_at)
            send(("phase", "CONTROLLED_MARKET_ENGINEERING_PASSED_NO_REAL_PUBLICATION"))
            # Controlled markets, counters and projections never leave RAM or
            # enter actual credit settlement. Keep only their derived proof.
            del controlled, controlled_input, controlled_market
            if session.mode == "READ_ONLY":
                journal.terminate(
                    key,
                    diagnostics=log.report(),
                    error_code="DIAGNOSTIC_READ_ONLY_COMPLETE",
                    now=clock(),
                )
                send(("terminal", "READ_ONLY_CONTROLLED_COMPLETE_NOT_REAL_RECOMMENDATION"))
                return
            progress.message(STAGE_LABELS["QUOTA_VERIFICATION"])
            pre_paid = _quota(guard, phase="PRE_PAID")
            journal.original.qualify_quota(pre_paid, now=clock())
            gate = DiagnosticPaidGateProof(
                campaign_sha256=authority.proposal.semantic_sha256,
                session_index=session.session_index,
                fpl_validation_sha256=prepared.validation_sha256,
                controlled_pipeline_sha256=controlled_sha,
                controlled_classification="REAL_FPL_CONTROLLED_MARKET_ENGINEERING",
                actual_fpl_contracts_passed=True,
                stage8_stage9_stage12_passed=True,
                fpl_validation_completed_at=validated_at,
                controlled_pipeline_completed_at=controlled_at,
                quota_received_at=pre_paid.received_at,
                quota_remaining_credits=pre_paid.remaining_credits,
                quota_used_credits=pre_paid.used_credits,
                quota_reconciled_with_original_account=True,
                credential_expires_at=credential_expires_at,
                official_gameweek=10,
                official_deadline_at=event.deadline_at,
            )
            grant = journal.reserve_paid(
                key, gate, pre_paid, model_cutoff=model_cutoff, now=clock()
            )
            send(("phase", "PAID_SUBGRANT_TWO_CREDITS_RESERVED_NO_RETRIES"))
            log.enter("MARKET_ACQUISITION")
            target = [
                fixture
                for fixture in snapshot.fpl_input.fixtures
                if fixture.event_identity == snapshot.fpl_input.target_event.identity
                and fixture.kickoff_at is not None
            ]
            latest = max(fixture.kickoff_at for fixture in target if fixture.kickoff_at is not None)
            odds = (
                sources(pre_paid)
                .odds(input_clock)
                .acquire(information_cutoff=model_cutoff, commence_to=latest + timedelta(seconds=1))
            )
            guard.closed = True
            real_input = assemble_diagnostic_execution(
                prepared, odds, prior, request, resolved_at=input_clock(), progress=progress
            )
            real = run_diagnostic_kernel(real_input, controlled=False, progress=progress)
            log.enter("RESULT_VALIDATION")
            publication = build_diagnostic_publication(
                authority,
                session,
                prepared,
                prior,
                real,
                grant,
                credential_expires_at=credential_expires_at,
                completed_at=clock(),
            )
            journal.publish(key, publication, log.report(), now=clock())
            send(("terminal", "GENUINE_GW10_DIAGNOSTIC_RECOMMENDATION_RECORDED"))
    except Exception as error:
        failure = log.failed(error)
        journal.terminate(key, diagnostics=log.report(), error_code=failure.code, now=clock())
        send(("terminal", failure.code))


def diagnostic_worker(
    pipe: object, horizon: int, key: str, credential_expires_at: datetime
) -> None:
    """Spawn target imported only after the signed stdlib child bootstrap check."""
    from multiprocessing.connection import _ConnectionBase

    try:
        if not isinstance(pipe, _ConnectionBase) or type(horizon) is not int or horizon != 1:
            raise OperationError("DIAGNOSTIC_INTERNAL_PIPE_REQUIRED")
        execute_active_session(
            DiagnosticJournal.production(),
            key,
            credential_expires_at,
            clock=lambda: datetime.now(UTC),
            send=pipe.send,
        )
    except BaseException:
        # A disposable child must never let multiprocessing format an implicit
        # provider/validation exception chain if custody or the pipe fails.
        raise SystemExit(2) from None
    finally:
        try:
            if isinstance(pipe, _ConnectionBase):
                pipe.close()
        except BaseException:
            raise SystemExit(2) from None
