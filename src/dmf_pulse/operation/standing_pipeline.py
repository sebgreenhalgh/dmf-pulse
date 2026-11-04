"""Ordinary one-GW compatibility glue around unchanged accepted numerical services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.availability.current_model import CurrentModelFixtureMinutesInput
from dmf_pulse.chips.compiler import compile_optimisation_chip_rules
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import DirectFplRunAttestation
from dmf_pulse.ingestion.fpl.direct_payloads import acquire_direct_fpl_snapshot
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorBuildRequest
from dmf_pulse.operation.analysis_optimizer import AnalysisOptimizerEvidence
from dmf_pulse.operation.chip_schema_compat import StandingSourceSchemaProof
from dmf_pulse.operation.diagnostic_pipeline import (
    assemble_diagnostic_execution,
    prepare_diagnostic_fpl,
)
from dmf_pulse.operation.diagnostics import DiagnosticEvent, DiagnosticLog
from dmf_pulse.private_v1 import one_command as accepted
from dmf_pulse.private_v1.actionability import DeadlineGuard, deadline_notice
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import PrivateV1Decision
from dmf_pulse.private_v1.one_command import (
    OneCommandRequest,
    OneCommandResult,
    PrivateV1OneCommandService,
)
from dmf_pulse.private_v1.presentation import (
    MarketQuotaReceipt,
    SourceVintage,
    build_presentation,
)
from dmf_pulse.rules.chips import build_chip_rules_view

if TYPE_CHECKING:
    from dmf_pulse.dashboard.current import CurrentLaunch


def validate_standing_source_proof(
    events: tuple[DiagnosticEvent, ...], result: OneCommandResult, launch: CurrentLaunch
) -> None:
    """Bind the one trusted derived event before the ordinary parent publishes."""
    checked = tuple(
        DiagnosticEvent.model_validate(event.model_dump(mode="python", warnings=False))
        for event in events
    )
    proofs = [event for event in checked if event.kind == "SOURCE_SCHEMA_COMPATIBILITY"]
    markets = [
        event
        for event in checked
        if event.kind == "ADMITTED"
        and event.request is not None
        and event.request.provider == "ODDS"
    ]
    if (
        len(proofs) != 1
        or len(markets) != 1
        or proofs[0].source_schema_proof is None
        or not isinstance(result.decision, PrivateV1Decision)
    ):
        raise AuthorizationError("WORKER_RESULT_BINDING_INVALID")
    event, proof = proofs[0], proofs[0].source_schema_proof
    ruleset, capability, authority = accepted._rules_authority(launch.grant.issued_at)
    chips = compile_optimisation_chip_rules(build_chip_rules_view(ruleset))
    lineage = result.decision.lineage
    if (
        launch.grant.request.horizon != 1
        or not launch.grant.request.authorization_id.startswith("OPR001-")
        or event.sequence >= markets[0].sequence
        or not launch.grant.issued_at
        <= event.at
        <= markets[0].at
        <= launch.grant.request.information_cutoff
        or proof.target_gameweek != result.decision.target_gameweek
        or proof.fpl_input_sha256 != lineage.fpl_input_sha256
        or proof.manager_state_sha256 != lineage.manager_state_sha256
        or proof.ruleset_sha256 != lineage.ruleset_sha256
        or proof.ruleset_sha256 != ruleset.ruleset_hash
        or proof.capability_sha256 != capability.capability_hash
        or proof.private_rules_authority_sha256 != authority.attestation_sha256
        or proof.private_rules_authority_sha256 != lineage.private_rules_authority_sha256
        or proof.chip_schema_proof.governed_chip_bundle_sha256
        != canonical_sha256(chips.model_dump(mode="json"))
    ):
        raise AuthorizationError("WORKER_RESULT_BINDING_INVALID")


class StandingOneGameweekService(PrivateV1OneCommandService):
    """One original FPL snapshot, real market, score prior and unchanged full kernel.

    This class grants no source access: the ordinary caller supplies the existing
    guarded factories, acquisition cutoff and run grant. No campaign authority,
    controlled gate, late-paid window or second acquisition is constructed here.
    """

    _optimizer_evidence: AnalysisOptimizerEvidence | None = None

    @property
    def optimizer_evidence(self) -> AnalysisOptimizerEvidence | None:
        return self._optimizer_evidence

    def run(self, request: OneCommandRequest) -> OneCommandResult:
        self._optimizer_evidence = None
        if (
            type(request.entry_id) is not int
            or request.entry_id <= 0
            or request.horizon_gameweeks != 1
            or request.run_at.tzinfo is None
            or request.run_at.utcoffset() is None
            or request.operator_approved_at is None
            or request.operator_approved_at.tzinfo is None
            or request.operator_approved_at.utcoffset() is None
        ):
            raise PrivateV1Error("USAGE_INVALID", "ordinary one-GW request is invalid")
        run_at = request.run_at.astimezone(UTC)
        approved_at = request.operator_approved_at.astimezone(UTC)
        if approved_at > run_at:
            raise PrivateV1Error("USAGE_INVALID", "operator approval is after the cutoff")
        diagnostics = getattr(self._progress, "diagnostics", None)
        if not isinstance(diagnostics, DiagnosticLog):
            raise AuthorizationError("WORKER_RESULT_BINDING_INVALID")
        deadline = DeadlineGuard(self._clock, not_before=approved_at)

        def observed_now() -> datetime:
            now = deadline.now()
            if now > run_at:
                raise IngestionError("POST_CUTOFF", "input acquisition exceeded its cutoff")
            return now

        def check_guard() -> None:
            if self._provider_request_guard is not None:
                self._provider_request_guard()

        self._progress.message("DMF Pulse starting")
        with self._progress.stage(
            started="Acquiring current FPL state...",
            completed="FPL state ready",
            failed="current FPL state",
        ):
            check_guard()
            client = self._direct_client_factory(DirectFplRunAttestation(attested_at=approved_at))
            snapshot = acquire_direct_fpl_snapshot(
                client, entry_id=request.entry_id, captured_at=run_at, clock=observed_now
            )
            if (
                self._expected_deadline_at is not None
                and snapshot.fpl_input.target_event.deadline_at != self._expected_deadline_at
            ):
                raise PrivateV1Error(
                    "OFFICIAL_DEADLINE_SCOPE_MISMATCH", "official deadline differs"
                )
            deadline.check(snapshot.fpl_input.target_event.deadline_at)
            diagnostics.enter("MANAGER_STATE")
            prepared = prepare_diagnostic_fpl(
                snapshot, approved_at=approved_at, observed_at=observed_now()
            )
            if prepared.chip_schema_proof is None:
                raise AuthorizationError("WORKER_RESULT_BINDING_INVALID")
            diagnostics.emit(
                "SOURCE_SCHEMA_COMPATIBILITY",
                source_schema_proof=StandingSourceSchemaProof(
                    target_gameweek=snapshot.target_gameweek,
                    snapshot_sha256=canonical_sha256(snapshot.model_dump(mode="json")),
                    fpl_input_sha256=snapshot.fpl_input.semantic_sha256,
                    manager_state_sha256=prepared.manager.semantic_sha256,
                    ruleset_sha256=prepared.ruleset.ruleset_hash,
                    capability_sha256=prepared.capability.capability_hash,
                    private_rules_authority_sha256=prepared.rules_authority.attestation_sha256,
                    chip_schema_proof=prepared.chip_schema_proof,
                ),
            )
        fixtures = tuple(
            f
            for f in snapshot.fpl_input.fixtures
            if f.event_identity == snapshot.fpl_input.target_event.identity
            and f.kickoff_at is not None
        )
        if not fixtures:
            raise IngestionError("TARGET_GAMEWEEK_UNRESOLVED", "target fixtures are absent")
        latest = max(f.kickoff_at for f in fixtures if f.kickoff_at is not None)
        with self._progress.stage(
            started="Acquiring current market odds...",
            completed="Current market odds ready",
            failed="current market odds",
        ):
            check_guard()
            odds = self._odds_service_factory(observed_now).acquire(
                information_cutoff=run_at, commence_to=latest + timedelta(seconds=1)
            )
        with self._progress.stage(
            started="Acquiring current score-prior source...",
            completed="Score-prior source ready",
            failed="current score-prior source",
        ):
            check_guard()
            prior = self._score_service_factory(observed_now).build(
                CurrentScorePriorBuildRequest(
                    information_cutoff=run_at, rights_profile_id=self._score_prior_rights_profile_id
                )
            )
        execution = assemble_diagnostic_execution(
            prepared, odds, prior, request, resolved_at=observed_now(), progress=self._progress
        )
        check_guard()
        deadline.check(snapshot.fpl_input.target_event.deadline_at)
        run = self._recommendation_service.run(execution, progress=self._progress)
        evidence = AnalysisOptimizerEvidence(
            decision_sha256=run.decision.semantic_sha256, optimiser_result=run.optimiser_result
        )
        evidence.require_bound_to(run.decision)
        report = accepted._display_report(run.decision, snapshot, execution.player_identity_map)
        report += deadline_notice(snapshot.fpl_input.target_event.deadline_at)
        presentation = None
        if self._collect_presentation:
            presentation = build_presentation(
                snapshot=snapshot,
                identities=execution.player_identity_map,
                current_squad=tuple(
                    sorted(
                        str(p.canonical_player_id)
                        for p in execution.player_identity_map.players
                        if p.official_fpl_element_id
                        in {
                            member.official_fpl_element_id for member in execution.ownership.members
                        }
                    )
                ),
                projections={snapshot.target_gameweek: run.gameweek_projection},
                fixtures=run.fixture_projections,
                minutes={
                    snapshot.target_gameweek: tuple(
                        CurrentModelFixtureMinutesInput.model_validate(value)
                        for value in execution.manual_minutes
                    )
                },
                fixture_mapping={
                    str(f.canonical_fixture_id): f.official_fpl_fixture_id
                    for f in execution.market_identity_view.fixtures
                },
                source_vintages=(
                    SourceVintage(
                        source="FPL",
                        identity_sha256=snapshot.fpl_input.semantic_sha256,
                        received_at=snapshot.fpl_input.provenance.received_at,
                        usable_at=snapshot.fpl_input.provenance.usable_at,
                        source_mode="CURRENT_TRANSIENT",
                        requests=snapshot.request_count,
                    ),
                    SourceVintage(
                        source="MARKETS",
                        identity_sha256=odds.market_semantic_sha256,
                        received_at=odds.temporal.received_at,
                        usable_at=odds.temporal.usable_at,
                        source_mode="CURRENT_TRANSIENT",
                        requests=odds.provenance.transport_call_count,
                    ),
                    SourceVintage(
                        source="TEAM_SCORE_PRIOR",
                        identity_sha256=prior.semantic_sha256,
                        received_at=prior.provenance.validation_completed_at,
                        usable_at=prior.provenance.usable_at,
                        source_mode="HISTORICAL_RECONSTRUCTED",
                        source_commit_at=prior.provenance.source_commit_timestamp,
                        requests=prior.provenance.transport_call_count,
                    ),
                ),
                market_quota_remaining=odds.quota.remaining,
                market_quota_receipt=MarketQuotaReceipt.from_odds(odds),
            )
        actionability = deadline.bind(
            deadline_at=snapshot.fpl_input.target_event.deadline_at,
            decision_sha256=run.decision.semantic_sha256,
            report=report,
        )
        result = OneCommandResult(
            status="REAL_PRIVATE_TRANSIENT_RECOMMENDATION",
            decision=run.decision,
            report=report,
            actionability=actionability,
            publication_not_before=deadline.latest_observed_at,
            fpl_request_count=snapshot.request_count,
            fpl_endpoint_classes=snapshot.endpoint_classes,
            presentation=presentation,
        )
        self._progress.message("Recommendation ready")
        self._progress.finish()
        self._optimizer_evidence = evidence
        return result
