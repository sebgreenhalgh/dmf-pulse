"""Bind a genuine diagnostic result to early source and late paid authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.current_model import CurrentModelFixtureMinutesInput
from dmf_pulse.dashboard.authorization import RefreshGrant
from dmf_pulse.dashboard.views import DeskView, desk_view
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorResult
from dmf_pulse.operation.diagnostic_pipeline import DiagnosticKernelResult, PreparedDiagnosticFpl
from dmf_pulse.operation.models import Metadata, OperationError, Sha
from dmf_pulse.private_v1.actionability import DeadlineGuard, deadline_notice
from dmf_pulse.private_v1.one_command import OneCommandResult, _display_report
from dmf_pulse.private_v1.presentation import MarketQuotaReceipt, SourceVintage, build_presentation

if TYPE_CHECKING:
    from dmf_pulse.operation.campaign_authority import VerifiedCampaignAuthority
    from dmf_pulse.operation.campaign_journal import DiagnosticSession

LABEL = "GW10 diagnostic / forecasts unvalidated"


class DiagnosticPublicationProof(Metadata):
    execution_class: Literal["GW10_DIAGNOSTIC"] = "GW10_DIAGNOSTIC"
    campaign_sha256: Sha
    session_key: Sha
    signed_authority_sha256: Sha
    grant_sha256: Sha
    fpl_validation_sha256: Sha
    execution_input_sha256: Sha
    decision_sha256: Sha
    fpl_input_sha256: Sha
    odds_input_sha256: Sha
    prior_input_sha256: Sha
    model_cutoff: datetime
    fpl_usable_at: datetime
    prior_usable_at: datetime
    odds_request_started_at: datetime
    odds_received_at: datetime
    odds_usable_at: datetime
    completed_at: datetime
    credential_expires_at: datetime
    view_sha256: Sha


@dataclass(frozen=True, slots=True, repr=False)
class DiagnosticPublication:
    view: DeskView
    proof: DiagnosticPublicationProof


def build_diagnostic_publication(
    authority: VerifiedCampaignAuthority,
    session: DiagnosticSession,
    prepared: PreparedDiagnosticFpl,
    prior: CurrentScorePriorResult,
    kernel: DiagnosticKernelResult,
    grant: RefreshGrant,
    *,
    credential_expires_at: datetime,
    completed_at: datetime,
) -> DiagnosticPublication:
    """Same accepted presentation, with an independent two-phase provenance check."""
    snapshot, execution = prepared.snapshot, kernel.execution
    fpl, odds = execution.current_state.fpl_input, execution.current_state.odds_input
    ceiling = min(
        session.lease_until,
        grant.expires_at,
        credential_expires_at,
        authority.proposal.deadline_not_after,
        fpl.target_event.deadline_at,
    )
    if (
        kernel.classification != "REAL_MARKET_KERNEL_NOT_PUBLICATION"
        or odds.provenance.transport_id not in {"stdlib_http_client", "stdlib_urllib"}
        or not fpl.provenance.transport_called
        or fpl.provenance.acquisition_mode != "OPERATOR_INITIATED_DIRECT_READ"
        or fpl != snapshot.fpl_input
        or snapshot.entry.id != authority.proposal.entry_id
        or snapshot.entry.id != authority.normal_policy.entry_id
        or prepared.manager.source_class != "PROVIDER_OBSERVED"
        or prepared.manager.provider_verification != "PROVIDER_VERIFIED"
        or execution.code_sha != authority.normal_policy.implementation_sha
        or execution.scenario_count != 256
        or execution.root_seed != 42
        or execution.require_stage9_mc_pass is not True
        or kernel.result.decision.lineage.execution_input_sha256 != execution.semantic_sha256
        or kernel.result.decision.lineage.code_sha != execution.code_sha
        or kernel.result.decision.lineage.current_state_sha256
        != execution.current_state.semantic_sha256
        or kernel.result.decision.lineage.fpl_input_sha256 != fpl.semantic_sha256
        or kernel.result.decision.lineage.odds_market_sha256 != odds.market_semantic_sha256
        or kernel.result.decision.scenario_count != execution.scenario_count
        or kernel.result.decision.stage9_monte_carlo_status != "PASS"
        or session.mode != "PAID_ELIGIBLE"
        or session.authority_sha256 != authority.signed_campaign.semantic_sha256
        or grant.request.authorization_id != f"OPR003-{session.session_key}"
        or grant.classification != "PRIVATE_CURRENT"
        or grant.ledger_id != authority.proposal.original_ledger_id
        or grant.request.implementation_sha != authority.normal_policy.implementation_sha
        or snapshot.target_gameweek != authority.proposal.gameweek
        or fpl.target_event.deadline_at != grant.request.deadline_at
        or execution.current_state.manager_state != prepared.manager
    ):
        raise OperationError("DIAGNOSTIC_REAL_SOURCE_AND_KERNEL_BINDING_REQUIRED")
    cutoff = fpl.provenance.information_cutoff
    if (
        cutoff != odds.temporal.information_cutoff
        or cutoff != prior.provenance.information_cutoff
        or cutoff != kernel.result.decision.information_cutoff
        or not session.started_at
        <= snapshot.captured_at
        <= fpl.provenance.usable_at
        <= grant.issued_at
        or not session.started_at
        <= prior.provenance.request_started_at
        <= prior.provenance.usable_at
        <= grant.issued_at
        or not grant.issued_at
        <= odds.temporal.request_started_at
        <= odds.temporal.received_at
        <= odds.temporal.usable_at
        <= grant.request.information_cutoff
        <= cutoff
        or not odds.temporal.usable_at <= completed_at < ceiling
    ):
        raise OperationError("DIAGNOSTIC_REAL_PUBLICATION_CHRONOLOGY_INVALID")
    decision = kernel.result.decision
    minutes = tuple(
        CurrentModelFixtureMinutesInput.model_validate(value) for value in execution.manual_minutes
    )
    report = _display_report(decision, snapshot, execution.player_identity_map)
    report = LABEL + "\n" + report + deadline_notice(fpl.target_event.deadline_at)
    presentation = build_presentation(
        snapshot=snapshot,
        identities=execution.player_identity_map,
        current_squad=tuple(
            sorted(
                str(player.canonical_player_id)
                for player in execution.player_identity_map.players
                if player.official_fpl_element_id
                in {member.official_fpl_element_id for member in execution.ownership.members}
            )
        ),
        projections={snapshot.target_gameweek: kernel.result.gameweek_projection},
        fixtures=kernel.result.fixture_projections,
        minutes={snapshot.target_gameweek: minutes},
        fixture_mapping={
            str(fixture.canonical_fixture_id): fixture.official_fpl_fixture_id
            for fixture in execution.market_identity_view.fixtures
        },
        source_vintages=(
            SourceVintage(
                source="FPL",
                identity_sha256=fpl.semantic_sha256,
                received_at=fpl.provenance.received_at,
                usable_at=fpl.provenance.usable_at,
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
    actionability = DeadlineGuard(lambda: completed_at, not_before=session.started_at).bind(
        deadline_at=fpl.target_event.deadline_at,
        decision_sha256=decision.semantic_sha256,
        report=report,
    )
    result = OneCommandResult(
        status="REAL_PRIVATE_TRANSIENT_RECOMMENDATION",
        decision=decision,
        report=report,
        actionability=actionability,
        publication_not_before=completed_at,
        fpl_request_count=snapshot.request_count,
        fpl_endpoint_classes=snapshot.endpoint_classes,
        presentation=presentation,
    )
    view = desk_view(
        result,
        job_id=session.session_key,
        mode="PRIVATE_TRANSIENT",
        generated_at=completed_at,
        expires_at=ceiling,
    )
    view = view.model_copy(update={"restrictions": (*view.restrictions, LABEL)})
    proof = DiagnosticPublicationProof(
        campaign_sha256=authority.proposal.semantic_sha256,
        session_key=session.session_key,
        signed_authority_sha256=session.authority_sha256,
        grant_sha256=grant.semantic_sha256,
        fpl_validation_sha256=prepared.validation_sha256,
        execution_input_sha256=execution.semantic_sha256,
        decision_sha256=decision.semantic_sha256,
        fpl_input_sha256=fpl.semantic_sha256,
        odds_input_sha256=odds.market_semantic_sha256,
        prior_input_sha256=prior.semantic_sha256,
        model_cutoff=cutoff,
        fpl_usable_at=fpl.provenance.usable_at,
        prior_usable_at=prior.provenance.usable_at,
        odds_request_started_at=odds.temporal.request_started_at,
        odds_received_at=odds.temporal.received_at,
        odds_usable_at=odds.temporal.usable_at,
        completed_at=completed_at,
        credential_expires_at=credential_expires_at,
        view_sha256=canonical_sha256(view.model_dump(mode="json")),
    )
    return DiagnosticPublication(view, proof)
