"""Diagnostic custody appended to the original journal, without standing ENROLL."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Connection, select

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.dashboard.authorization import RefreshAuthorizer, RefreshGrant, RefreshRequest
from dmf_pulse.data_model.tables import refresh_control_event
from dmf_pulse.operation.campaign import (
    DiagnosticBudgetPreview,
    DiagnosticCampaignProposal,
    DiagnosticPaidGateProof,
    DiagnosticSessionSummary,
    SessionMode,
    preview_diagnostic_budget,
    preview_diagnostic_paid_reservation,
)
from dmf_pulse.operation.campaign_authority import (
    CAMPAIGN_POLICY_SHA,
    VerifiedCampaignAuthority,
    load_verified_campaign,
)
from dmf_pulse.operation.campaign_publication import LABEL, DiagnosticPublication
from dmf_pulse.operation.chip_schema_compat import ChipSchemaProof
from dmf_pulse.operation.diagnostics import DiagnosticReport
from dmf_pulse.operation.discovery import EventDiscovery
from dmf_pulse.operation.journal import OperationJournal
from dmf_pulse.operation.models import MetadataTime, OperationError
from dmf_pulse.operation.standing import QuotaProof, verify_period
from dmf_pulse.private_v1.models import PrivateV1Decision

EXECUTION_CLASS = "GW10_DIAGNOSTIC"
ORIGINAL_CONTROL_PREFIX_LENGTH = 18
ORIGINAL_CONTROL_PREFIX_SHA = "d1d83ca544ffc488d19292d0f95f2435d2d09c7afc0f869761198b3551d82efa"
ORIGINAL_OPERATOR_PREFIX_LENGTH = 6
ORIGINAL_OPERATOR_PREFIX_SHA = "6e711db1edca99e389df9dd22a4beb35f933e7e96b1f01f5c169cc1e941628e2"


def is_diagnostic_settlement(row: Mapping[str, Any]) -> bool:
    value = row["payload"]["value"]
    return (
        row["kind"] == "LAUNCH"
        and value.get("execution_class") == EXECUTION_CLASS
        and value.get("campaign_id") == "GW10-DIAGNOSTIC-CAMPAIGN-001"
        and value.get("campaign_policy_sha256") == CAMPAIGN_POLICY_SHA
        and value.get("subtype") in {"ACTUAL_QUOTA", "COUNTER_RECONCILIATION"}
    )


def _is_terminal(row: Mapping[str, Any]) -> bool:
    value = row["payload"]["value"]
    return bool(
        value.get("subtype") == "TERMINAL"
        and (
            row["kind"] == "FAILURE"
            or (
                row["kind"] == "LAUNCH"
                and value.get("outcome") in {"REAL_PUBLICATION", "CONTROLLED_ENGINEERING_COMPLETE"}
            )
        )
    )


def _is_publication(row: Mapping[str, Any]) -> bool:
    return _is_terminal(row) and row["payload"]["value"].get("outcome") == "REAL_PUBLICATION"


@dataclass(frozen=True, slots=True)
class DiagnosticSession:
    session_index: int
    session_key: str
    launch_id: str
    mode: SessionMode
    started_at: datetime
    lease_until: datetime
    authority_sha256: str


class DiagnosticJournal:
    """No database initialization, alternate ledger, migration or prior-row write."""

    def __init__(self, journal: OperationJournal) -> None:
        self.original = journal

    @classmethod
    def production(cls) -> DiagnosticJournal:
        authority = load_verified_campaign()
        return cls(OperationJournal.production(authority.normal_policy))

    @contextmanager
    def _transaction(
        self,
    ) -> Iterator[tuple[VerifiedCampaignAuthority, Connection, list[dict[str, Any]]]]:
        authority = load_verified_campaign()
        if (
            authority.normal_policy != self.original.policy
            or authority.proposal.original_ledger_id != self.original.policy.ledger_id
            or authority.proposal.odds_account_ref != self.original.policy.odds_account_ref
        ):
            raise OperationError("DIAGNOSTIC_ORIGINAL_CONTROL_BINDING_CHANGED")
        with self.original._transaction() as (connection, rows):
            yield authority, connection, rows

    @staticmethod
    def _tagged(
        rows: list[dict[str, Any]], proposal: DiagnosticCampaignProposal
    ) -> list[dict[str, Any]]:
        selected = []
        for row in rows:
            value = row["payload"]["value"]
            if value.get("execution_class") != EXECUTION_CLASS:
                continue
            if value.get("campaign_id") != proposal.campaign_id:
                continue
            if value.get("campaign_policy_sha256") != proposal.semantic_sha256:
                raise OperationError("DIAGNOSTIC_CAMPAIGN_HISTORY_COLLISION")
            selected.append(row)
        return selected

    @staticmethod
    def _starts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            row
            for row in rows
            if row["kind"] == "LAUNCH" and row["payload"]["value"]["subtype"] == "SESSION"
        ]

    def _summaries(
        self, rows: list[dict[str, Any]], proposal: DiagnosticCampaignProposal
    ) -> tuple[DiagnosticSessionSummary, ...]:
        result = []
        for start in self._starts(rows):
            value = start["payload"]["value"]
            key = start["execution_key"]
            related = [row for row in rows if row["execution_key"] == key]
            terminal = [row for row in related if _is_terminal(row)]
            inspections = [
                row
                for row in related
                if row["kind"] == "CLOSE" and row["payload"]["value"]["subtype"] == "INSPECTION"
            ]
            paid = [
                row
                for row in related
                if row["kind"] == "LAUNCH"
                and row["payload"]["value"]["subtype"] == "PAID_RESERVATION"
            ]
            settlements = [row for row in related if is_diagnostic_settlement(row)]
            paid_admissions = [
                row
                for row in related
                if row["kind"] == "LAUNCH"
                and row["payload"]["value"]["subtype"] == "PROVIDER_ADMISSION"
                and row["payload"]["value"]["provider"] == "ODDS_PAID"
            ]
            if (
                len(terminal) > 1
                or len(paid) > 1
                or len(settlements) > 1
                or len(paid_admissions) > 1
            ):
                raise OperationError("DIAGNOSTIC_SESSION_HISTORY_INVALID")
            inspected = bool(
                terminal
                and inspections
                and inspections[-1]["payload"]["value"]["terminal_sha256"] == terminal[-1]["sha256"]
            )
            settled = bool(settlements and settlements[0]["payload"]["value"]["consistent"] is True)
            result.append(
                DiagnosticSessionSummary(
                    campaign_sha256=proposal.semantic_sha256,
                    session_index=value["session_index"],
                    mode=value["mode"],
                    started_at=start["at"],
                    terminal=bool(terminal),
                    inspected=inspected,
                    paid_credits_reserved=bool(paid),
                    unresolved_paid_consumption=bool(paid_admissions) and not settled,
                    successful_real_recommendation=bool(terminal and _is_publication(terminal[0])),
                    terminal_diagnostics_sha256=terminal[0]["sha256"] if terminal else None,
                    real_publication_sha256=terminal[0]["sha256"]
                    if terminal and _is_publication(terminal[0])
                    else None,
                )
            )
        return tuple(result)

    @staticmethod
    def _session(start: Mapping[str, Any]) -> DiagnosticSession:
        value = start["payload"]["value"]
        return DiagnosticSession(
            value["session_index"],
            start["execution_key"],
            value["launch_id"],
            value["mode"],
            start["at"],
            datetime.fromisoformat(value["lease_until"]),
            value["authority_sha256"],
        )

    def _append(
        self,
        authority: VerifiedCampaignAuthority,
        connection: Connection,
        rows: list[dict[str, Any]],
        session: DiagnosticSession,
        kind: str,
        subtype: str,
        data: Mapping[str, Any],
        *,
        now: datetime,
    ) -> str:
        common = {
            "execution_class": EXECUTION_CLASS,
            "campaign_id": authority.proposal.campaign_id,
            "campaign_policy_sha256": authority.proposal.semantic_sha256,
            "session_index": session.session_index,
            "launch_id": session.launch_id,
            "lease_until": session.lease_until.isoformat(),
            "subtype": subtype,
            "authority_sha256": session.authority_sha256,
        }
        if set(common) & set(data):
            raise OperationError("DIAGNOSTIC_EVENT_ENVELOPE_COLLISION")
        return self.original._append(
            connection, rows, kind, {**common, **data}, now=now, key=session.session_key
        )

    def begin_session(self, mode: SessionMode, *, now: datetime) -> DiagnosticSession:
        now = MetadataTime(checked_at=now).checked_at
        with self._transaction() as (authority, connection, rows):
            proposal = authority.proposal
            selected = self._tagged(rows, proposal)
            summaries = self._summaries(selected, proposal)
            # Budget-only preparation uses the retained deadline ceiling. It does
            # not assert fresh discovery or authorize any snapshot/paid route.
            preview = preview_diagnostic_budget(
                proposal,
                summaries,
                mode=mode,
                now=now,
                fresh_official_gameweek=proposal.gameweek,
                fresh_official_deadline=proposal.deadline_not_after,
            )
            closed = {
                row["payload"]["value"]["launch_id"] for row in rows if row["kind"] == "CLOSE"
            }
            for row in rows:
                value = row["payload"]["value"]
                if (
                    row["kind"] == "LAUNCH"
                    and value["launch_id"] not in closed
                    and now < datetime.fromisoformat(value["lease_until"])
                ):
                    raise OperationError("ANOTHER_OPERATOR_LAUNCH_IS_RUNNING")
            key = preview.session_key
            session = DiagnosticSession(
                preview.session_index,
                key,
                key,
                mode,
                now,
                min(
                    now + timedelta(seconds=proposal.limits.maximum_session_seconds),
                    proposal.deadline_not_after,
                ),
                authority.signed_campaign.semantic_sha256,
            )
            self._append(
                authority,
                connection,
                rows,
                session,
                "LAUNCH",
                "SESSION",
                {
                    "mode": mode,
                    "policy_sha256": self.original.policy.semantic_sha256,
                    "original_consumed_execution_key": proposal.original_consumed_execution_key,
                    "official_discovery_pending": True,
                    "reserved_credits": 0,
                },
                now=now,
            )
            return session

    def preflight_session(self, mode: SessionMode, *, now: datetime) -> DiagnosticBudgetPreview:
        """No slot or source authority: reject exhausted/uninspected runs before a prompt."""
        now = MetadataTime(checked_at=now).checked_at
        with self._transaction() as (authority, _, rows):
            proposal = authority.proposal
            selected = self._tagged(rows, proposal)
            return preview_diagnostic_budget(
                proposal,
                self._summaries(selected, proposal),
                mode=mode,
                now=now,
                fresh_official_gameweek=proposal.gameweek,
                fresh_official_deadline=proposal.deadline_not_after,
            )

    def verify_original_custody(self) -> dict[str, object]:
        """Retain both original chain prefixes, independent of appended sessions."""
        with (
            self._transaction() as (authority, connection, rows),
            self.original.ledger.participate_in_transaction(connection),
            self.original.ledger._sql_transaction() as original,
        ):
            if (
                len(original) < ORIGINAL_CONTROL_PREFIX_LENGTH
                or original[ORIGINAL_CONTROL_PREFIX_LENGTH - 1]["sha256"]
                != ORIGINAL_CONTROL_PREFIX_SHA
                or len(rows) < ORIGINAL_OPERATOR_PREFIX_LENGTH
                or rows[ORIGINAL_OPERATOR_PREFIX_LENGTH - 1]["sha256"]
                != ORIGINAL_OPERATOR_PREFIX_SHA
                or not any(
                    row["kind"] == "ENROLL"
                    and row["execution_key"] == authority.proposal.original_consumed_execution_key
                    for row in rows[:ORIGINAL_OPERATOR_PREFIX_LENGTH]
                )
            ):
                raise OperationError("DIAGNOSTIC_ORIGINAL_CONSUMPTION_PREFIX_CHANGED")
            return {
                "ledger_id": self.original.policy.ledger_id,
                "original_control_prefix_rows": ORIGINAL_CONTROL_PREFIX_LENGTH,
                "original_control_prefix_sha256": ORIGINAL_CONTROL_PREFIX_SHA,
                "original_operator_prefix_rows": ORIGINAL_OPERATOR_PREFIX_LENGTH,
                "original_operator_prefix_sha256": ORIGINAL_OPERATOR_PREFIX_SHA,
                "original_consumed_execution_key": authority.proposal.original_consumed_execution_key,
                "original_marker_manifest_sha256": authority.proposal.original_marker_manifest_sha256,
            }

    def session_receipt(self, key: str) -> dict[str, Any]:
        """Read canonical control/derived facts; never grant source access."""
        with self._transaction() as (authority, _, rows):
            selected = self._tagged(rows, authority.proposal)
            starts = [row for row in self._starts(selected) if row["execution_key"] == key]
            if len(starts) != 1:
                raise OperationError("DIAGNOSTIC_SESSION_NOT_FOUND")
            related = [row for row in selected if row["execution_key"] == key]
            terminal = [row for row in related if _is_terminal(row)]
            return {
                "schema_version": "gw10-diagnostic-private-receipt-v1",
                "campaign_id": authority.proposal.campaign_id,
                "campaign_policy_sha256": authority.proposal.semantic_sha256,
                "session_key": key,
                "classification": LABEL,
                "ledger_id": self.original.policy.ledger_id,
                "canonical_head_sha256": rows[-1]["sha256"],
                "records": [{**row, "at": row["at"].isoformat()} for row in related],
                "terminal_sha256": terminal[0]["sha256"] if len(terminal) == 1 else None,
                "terminal": terminal[0]["payload"]["value"] if len(terminal) == 1 else None,
            }

    def execution_ceiling(self, key: str) -> datetime:
        """Authenticated custody time, never a new approval or source context."""
        with self._transaction() as (authority, _, rows):
            selected = self._tagged(rows, authority.proposal)
            starts = [row for row in self._starts(selected) if row["execution_key"] == key]
            if len(starts) != 1:
                raise OperationError("DIAGNOSTIC_SESSION_NOT_FOUND")
            ceiling = self._session(starts[0]).lease_until
            for row in selected:
                if row["execution_key"] != key:
                    continue
                value = row["payload"]["value"]
                if value["subtype"] == "OFFICIAL_DISCOVERY":
                    ceiling = min(ceiling, datetime.fromisoformat(value["deadline_at"]))
                elif value["subtype"] == "PAID_RESERVATION":
                    ceiling = min(ceiling, datetime.fromisoformat(value["grant"]["expires_at"]))
            return ceiling

    def check(self, session_key: str, *, now: datetime) -> DiagnosticSession:
        now = MetadataTime(checked_at=now).checked_at
        with self._transaction() as (authority, _, rows):
            selected = self._tagged(rows, authority.proposal)
            return self._active(authority, selected, session_key, now)

    def _active(
        self,
        authority: VerifiedCampaignAuthority,
        rows: list[dict[str, Any]],
        key: str,
        now: datetime,
    ) -> DiagnosticSession:
        starts = [row for row in self._starts(rows) if row["execution_key"] == key]
        if len(starts) != 1:
            raise OperationError("DIAGNOSTIC_SESSION_NOT_FOUND")
        session = self._session(starts[0])
        closed = any(row["kind"] == "CLOSE" and row["execution_key"] == key for row in rows)
        terminal = any(_is_terminal(row) and row["execution_key"] == key for row in rows)
        discoveries = [
            row
            for row in rows
            if row["execution_key"] == key
            and row["payload"]["value"]["subtype"] == "OFFICIAL_DISCOVERY"
        ]
        if len(discoveries) > 1:
            raise OperationError("DIAGNOSTIC_SESSION_HISTORY_INVALID")
        ceiling = min(
            session.lease_until,
            datetime.fromisoformat(discoveries[0]["payload"]["value"]["deadline_at"])
            if discoveries
            else session.lease_until,
        )
        if (
            closed
            or terminal
            or session.authority_sha256 != authority.signed_campaign.semantic_sha256
            or not session.started_at <= now < ceiling
        ):
            raise OperationError("DIAGNOSTIC_SESSION_CLOSED_CHANGED_OR_EXPIRED")
        return session

    def record_discovery(self, key: str, event: EventDiscovery, *, now: datetime) -> None:
        with self._transaction() as (authority, connection, rows):
            selected = self._tagged(rows, authority.proposal)
            session = self._active(authority, selected, key, now)
            bootstrap_sha = canonical_sha256(
                ["FPL", "GET", "fantasy.premierleague.com", "/api/bootstrap-static/"]
            )
            admissions = [
                row
                for row in selected
                if row["execution_key"] == key
                and row["payload"]["value"]["subtype"] == "PROVIDER_ADMISSION"
                and row["payload"]["value"].get("route_sha256") == bootstrap_sha
            ]
            complete = [
                row
                for row in selected
                if row["execution_key"] == key
                and row["payload"]["value"]["subtype"] == "RESPONSE_COMPLETED"
                and admissions
                and row["payload"]["value"].get("request_id")
                == admissions[0]["payload"]["value"]["request_id"]
                and row["payload"]["value"]["http_status"] == 200
            ]
            if (
                len(admissions) != 1
                or len(complete) != 1
                or event.target_gameweek != authority.proposal.gameweek
                or not session.started_at <= event.request_started_at <= event.received_at <= now
                or now >= min(session.lease_until, event.deadline_at)
                or any(
                    row["execution_key"] == key
                    and row["payload"]["value"]["subtype"] == "OFFICIAL_DISCOVERY"
                    for row in selected
                )
            ):
                raise OperationError("DIAGNOSTIC_FRESH_GW10_DISCOVERY_REQUIRED")
            self._append(
                authority,
                connection,
                rows,
                session,
                "LAUNCH",
                "OFFICIAL_DISCOVERY",
                {
                    "proof_sha256": event.semantic_sha256,
                    "deadline_at": event.deadline_at.isoformat(),
                    "event": event.model_dump(mode="json"),
                },
                now=now,
            )

    def record_stage(
        self,
        key: str,
        stage: Literal["FPL_VALIDATION", "CONTROLLED_GATE"],
        value_sha256: str,
        *,
        now: datetime,
        source_schema_proof: ChipSchemaProof | None = None,
    ) -> None:
        if len(value_sha256) != 64 or any(c not in "0123456789abcdef" for c in value_sha256):
            raise OperationError("DIAGNOSTIC_STAGE_PROOF_INVALID")
        proof_value: dict[str, object] = {"proof_sha256": value_sha256}
        if source_schema_proof is not None:
            if stage != "FPL_VALIDATION":
                raise OperationError("DIAGNOSTIC_STAGE_PROOF_INVALID")
            proof_value["source_schema_proof"] = ChipSchemaProof.model_validate(
                source_schema_proof
            ).model_dump(mode="json")
        with self._transaction() as (authority, connection, rows):
            selected = self._tagged(rows, authority.proposal)
            session = self._active(authority, selected, key, now)
            existing = [
                row
                for row in selected
                if row["execution_key"] == key and row["payload"]["value"]["subtype"] == stage
            ]
            if existing:
                raise OperationError("DIAGNOSTIC_STAGE_ALREADY_RECORDED")
            self._append(
                authority,
                connection,
                rows,
                session,
                "LAUNCH",
                stage,
                proof_value,
                now=now,
            )

    def record_quota(
        self,
        key: str,
        phase: Literal["INITIAL", "PRE_PAID"],
        proof: QuotaProof,
        *,
        now: datetime,
    ) -> None:
        with self._transaction() as (authority, connection, rows):
            selected = self._tagged(rows, authority.proposal)
            session = self._active(authority, selected, key, now)
            quotas = [row for row in selected if row["kind"] == "QUOTA"]
            admissions = [
                row
                for row in selected
                if row["execution_key"] == key
                and row["payload"]["value"]["subtype"] == "PROVIDER_ADMISSION"
                and row["payload"]["value"].get("provider") == "QUOTA"
                and row["payload"]["value"].get("phase") == phase
            ]
            if (
                len(admissions) != 1
                or len(quotas) >= authority.proposal.limits.quota_gets_campaign_total
                or any(
                    row["execution_key"] == key and row["payload"]["value"]["phase"] == phase
                    for row in quotas
                )
                or (phase == "PRE_PAID" and session.mode != "PAID_ELIGIBLE")
            ):
                raise OperationError("DIAGNOSTIC_QUOTA_PHASE_EXHAUSTED")
            request_id = admissions[0]["payload"]["value"]["request_id"]
            completions = [
                row
                for row in selected
                if row["payload"]["value"]["subtype"] == "RESPONSE_COMPLETED"
                and row["payload"]["value"].get("request_id") == request_id
                and row["payload"]["value"].get("http_status") == 200
            ]
            if (
                len(completions) != 1
                or proof.qualification_sha256
                != self.original.policy.quota_qualification.semantic_sha256
                or not session.started_at <= proof.request_started_at <= proof.received_at <= now
            ):
                raise OperationError("DIAGNOSTIC_ACTUAL_QUOTA_COMPLETION_REQUIRED")
            self._append(
                authority,
                connection,
                rows,
                session,
                "QUOTA",
                "QUOTA",
                {"phase": phase, "proof": proof.model_dump(mode="json")},
                now=now,
            )

    def reserve_paid(
        self,
        key: str,
        gate: DiagnosticPaidGateProof,
        quota: QuotaProof,
        *,
        model_cutoff: datetime,
        now: datetime,
    ) -> RefreshGrant:
        from dmf_pulse.operation.campaign_runtime import paid_enrollment, require_runtime

        runtime = require_runtime(key)
        if runtime.journal is not self:
            raise OperationError("DIAGNOSTIC_VERIFIED_PROCESS_SCOPE_REQUIRED")
        previous_registry = runtime.registry
        previous_cutoff = runtime.paid_cutoff
        grant = None
        # Catch outside the outer transaction: a tag failure must roll back the
        # financial reservation/claim as well, never leave an orphan or refund.
        try:
            with self._transaction() as (authority, connection, rows):
                selected = self._tagged(rows, authority.proposal)
                session = self._active(authority, selected, key, now)
                if runtime.authority != authority or runtime.session != session:
                    raise OperationError("DIAGNOSTIC_VERIFIED_PROCESS_SCOPE_REQUIRED")
                preview = preview_diagnostic_paid_reservation(
                    authority.proposal, self._summaries(selected, authority.proposal), gate, now=now
                )
                for stage, digest, completed_at in (
                    (
                        "FPL_VALIDATION",
                        gate.fpl_validation_sha256,
                        gate.fpl_validation_completed_at,
                    ),
                    (
                        "CONTROLLED_GATE",
                        gate.controlled_pipeline_sha256,
                        gate.controlled_pipeline_completed_at,
                    ),
                ):
                    matches = [
                        row
                        for row in selected
                        if row["execution_key"] == key
                        and row["payload"]["value"]["subtype"] == stage
                    ]
                    if (
                        len(matches) != 1
                        or matches[0]["payload"]["value"]["proof_sha256"] != digest
                        or matches[0]["at"] != completed_at
                    ):
                        raise OperationError("DIAGNOSTIC_CANONICAL_GATE_PROOF_REQUIRED")
                observed = [
                    row
                    for row in selected
                    if row["execution_key"] == key
                    and row["kind"] == "QUOTA"
                    and row["payload"]["value"]["phase"] == "PRE_PAID"
                    and row["payload"]["value"]["proof"] == quota.model_dump(mode="json")
                ]
                if len(observed) != 1:
                    raise OperationError("DIAGNOSTIC_CANONICAL_PRE_PAID_QUOTA_REQUIRED")
                start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                used, unresolved = self.original._paid_state(
                    connection, rows, self.original.policy, start
                )
                period = verify_period(
                    self.original.policy,
                    quota,
                    now=now,
                    settled_credits=used,
                    unresolved_paid_attempts=unresolved,
                )
                if (
                    not now
                    <= model_cutoff
                    <= session.started_at
                    + timedelta(seconds=authority.proposal.limits.maximum_pre_paid_seconds)
                ):
                    raise OperationError("DIAGNOSTIC_MODEL_CUTOFF_INVALID")
                registry = paid_enrollment(
                    runtime, gate, quota, period, now=now, expires_at=preview.expires_at
                )
                runtime.registry = registry
                approval = registry.approvals[0]
                request = RefreshRequest(
                    **{
                        name: getattr(approval, name)
                        for name in (
                            "authorization_id",
                            "implementation_sha",
                            "review_sha256",
                            "operator_ref",
                            "purpose",
                            "season_code",
                            "mode",
                            "source_scopes",
                        )
                    },
                    horizon=1,
                    information_cutoff=min(model_cutoff, preview.acquisition_ends_at),
                    deadline_at=gate.official_deadline_at,
                )
                runtime.paid_cutoff = request.information_cutoff
                with self.original.ledger.participate_in_transaction(connection):
                    grant = RefreshAuthorizer(self.original.ledger, clock=lambda: now).authorize(
                        request
                    )
                    self.original.ledger.claim(grant, key, now=now)
                    self._append(
                        authority,
                        connection,
                        rows,
                        session,
                        "LAUNCH",
                        "PAID_RESERVATION",
                        {
                            "reservation_id": grant.reservation_id,
                            "reserved_credits": 2,
                            "paid_issued_at": now.isoformat(),
                            "gate_sha256": gate.semantic_sha256,
                            "gate": gate.model_dump(mode="json"),
                            "grant": grant.model_dump(mode="json"),
                            "model_cutoff": model_cutoff.isoformat(),
                            "quota": quota.model_dump(mode="json"),
                            "period": period.model_dump(mode="json"),
                        },
                        now=now,
                    )
        except BaseException:
            runtime.registry = previous_registry
            runtime.paid_cutoff = previous_cutoff
            raise
        return grant

    def admit_provider(
        self,
        key: str,
        provider: Literal["FPL", "OPENFOOTBALL", "ODDS_PAID", "QUOTA"],
        method: str,
        host: str,
        path: str,
        *,
        phase: Literal["INITIAL", "PRE_PAID"] | None = None,
        now: datetime,
        consume: bool = True,
    ) -> str:
        """Durable admission precedes invocation, including failed free checks."""
        from dmf_pulse.operation.campaign_runtime import require_runtime
        from dmf_pulse.operation.quota import QUOTA_HOST, QUOTA_PATH

        runtime = require_runtime(key)
        if runtime.journal is not self:
            raise OperationError("DIAGNOSTIC_VERIFIED_PROCESS_SCOPE_REQUIRED")
        with self._transaction() as (authority, connection, rows):
            selected = self._tagged(rows, authority.proposal)
            session = self._active(authority, selected, key, now)
            admissions = [
                row
                for row in selected
                if row["payload"]["value"]["subtype"] == "PROVIDER_ADMISSION"
            ]
            related = [row for row in admissions if row["execution_key"] == key]
            quotas = [row for row in related if row["payload"]["value"]["provider"] == "QUOTA"]
            completions = [
                row for row in selected if row["execution_key"] == key and row["kind"] == "QUOTA"
            ]
            if method != "GET":
                raise OperationError("DIAGNOSTIC_EXACT_READ_ONLY_ROUTE_REQUIRED")
            if provider == "QUOTA":
                if (host, path) != (QUOTA_HOST, QUOTA_PATH) or phase not in {"INITIAL", "PRE_PAID"}:
                    raise OperationError("DIAGNOSTIC_EXACT_QUOTA_ROUTE_REQUIRED")
                if (
                    any(row["payload"]["value"]["phase"] == phase for row in quotas)
                    or sum(row["payload"]["value"]["provider"] == "QUOTA" for row in admissions)
                    >= authority.proposal.limits.quota_gets_campaign_total
                ):
                    raise OperationError("DIAGNOSTIC_QUOTA_PHASE_EXHAUSTED")
                if phase == "PRE_PAID" and (
                    session.mode != "PAID_ELIGIBLE"
                    or not any(row["payload"]["value"]["phase"] == "INITIAL" for row in completions)
                    or not any(
                        row["execution_key"] == key
                        and row["payload"]["value"]["subtype"] == "CONTROLLED_GATE"
                        for row in selected
                    )
                ):
                    raise OperationError("DIAGNOSTIC_PRE_PAID_GATE_REQUIRED")
            else:
                if phase is not None or not any(
                    row["payload"]["value"]["phase"] == "INITIAL" for row in completions
                ):
                    raise OperationError("DIAGNOSTIC_INITIAL_QUOTA_REQUIRED")
                source = "ODDS" if provider == "ODDS_PAID" else provider
                routes = [
                    route
                    for q in runtime.registry.qualifications
                    if q.scope.provider == source
                    for route in q.scope.routes
                    if (route.method, route.host, route.path) == (method, host, path)
                ]
                if len(routes) != 1:
                    raise OperationError("DIAGNOSTIC_EXACT_SOURCE_ROUTE_REQUIRED")
                maximum = {"FPL": 20, "OPENFOOTBALL": 4, "ODDS_PAID": 1}[provider]
                if (
                    sum(row["payload"]["value"]["provider"] == provider for row in related)
                    >= maximum
                ):
                    raise OperationError("DIAGNOSTIC_PROVIDER_BUDGET_EXHAUSTED")
                path_max = (
                    2
                    if provider == "FPL" and path == "/api/bootstrap-static/"
                    else routes[0].maximum_calls
                )
                route_sha = canonical_sha256([provider, method, host, path])
                if (
                    sum(row["payload"]["value"].get("route_sha256") == route_sha for row in related)
                    >= path_max
                ):
                    raise OperationError("DIAGNOSTIC_SOURCE_ROUTE_ALREADY_ATTEMPTED")
                if provider == "ODDS_PAID":
                    paid = [
                        row
                        for row in selected
                        if row["execution_key"] == key
                        and row["payload"]["value"]["subtype"] == "PAID_RESERVATION"
                    ]
                    if len(paid) != 1:
                        raise OperationError("DIAGNOSTIC_LATE_PAID_GRANT_REQUIRED")
                    import json

                    grant = RefreshGrant.model_validate_json(
                        json.dumps(paid[0]["payload"]["value"]["grant"])
                    )
                    with self.original.ledger.participate_in_transaction(connection):
                        if consume:
                            self.original.ledger.attempt(
                                grant,
                                key,
                                provider="ODDS",
                                method=method,
                                host=host,
                                path=path,
                                now=now,
                            )
                        else:
                            self.original.ledger.preflight_attempt(
                                grant,
                                key,
                                provider="ODDS",
                                method=method,
                                host=host,
                                path=path,
                                now=now,
                            )
            route_sha = canonical_sha256([provider, method, host, path])
            request_id = canonical_sha256([key, len(related) + 1, route_sha, phase])
            if consume:
                self._append(
                    authority,
                    connection,
                    rows,
                    session,
                    "LAUNCH",
                    "PROVIDER_ADMISSION",
                    {
                        "request_id": request_id,
                        "provider": provider,
                        "route_sha256": route_sha,
                        "phase": phase,
                    },
                    now=now,
                )
            return request_id

    def record_transport(
        self,
        key: str,
        request_id: str,
        kind: Literal["TRANSPORT_STARTED", "RESPONSE_COMPLETED"],
        *,
        now: datetime,
        http_status: int | None = None,
    ) -> None:
        with self._transaction() as (authority, connection, rows):
            selected = self._tagged(rows, authority.proposal)
            session = (
                self._active(authority, selected, key, now)
                if kind == "TRANSPORT_STARTED"
                else self._facts_session(selected, key)
            )
            related = [
                row
                for row in selected
                if row["execution_key"] == key
                and row["payload"]["value"].get("request_id") == request_id
            ]
            subtypes = [row["payload"]["value"]["subtype"] for row in related]
            expected = (
                ["PROVIDER_ADMISSION"]
                if kind == "TRANSPORT_STARTED"
                else ["PROVIDER_ADMISSION", "TRANSPORT_STARTED"]
            )
            if subtypes != expected or (
                kind == "RESPONSE_COMPLETED"
                and (type(http_status) is not int or not 100 <= http_status <= 599)
            ):
                raise OperationError("DIAGNOSTIC_TRANSPORT_CHRONOLOGY_INVALID")
            self._append(
                authority,
                connection,
                rows,
                session,
                "LAUNCH",
                kind,
                {"request_id": request_id, "http_status": http_status},
                now=now,
            )

    def _facts_session(self, rows: list[dict[str, Any]], key: str) -> DiagnosticSession:
        """Authenticate an existing request's receipt after expiry; grant nothing."""
        starts = [row for row in self._starts(rows) if row["execution_key"] == key]
        if len(starts) != 1 or any(
            row["execution_key"] == key
            and row["kind"] == "CLOSE"
            and row["payload"]["value"]["subtype"] == "QUIESCENT_CLOSE"
            for row in rows
        ):
            raise OperationError("DIAGNOSTIC_SESSION_NOT_FOUND_OR_ALREADY_QUIESCENT")
        return self._session(starts[0])

    def settle_headers(
        self, key: str, headers: Mapping[str, str], status: int, *, now: datetime
    ) -> None:
        from dmf_pulse.operation.quota import parse_quota_header_values

        values = parse_quota_header_values(headers)
        if type(status) is not int or not 100 <= status <= 599:
            raise OperationError("DIAGNOSTIC_ACTUAL_HTTP_STATUS_REQUIRED")
        with self._transaction() as (authority, connection, rows):
            selected = self._tagged(rows, authority.proposal)
            session = self._facts_session(selected, key)
            paid = [
                row
                for row in selected
                if row["execution_key"] == key
                and row["payload"]["value"]["subtype"] == "PAID_RESERVATION"
            ]
            admissions = [
                row
                for row in selected
                if row["execution_key"] == key
                and row["payload"]["value"]["subtype"] == "PROVIDER_ADMISSION"
                and row["payload"]["value"]["provider"] == "ODDS_PAID"
            ]
            if (
                len(paid) != 1
                or len(admissions) != 1
                or not any(
                    row["payload"]["value"]["subtype"] == "TRANSPORT_STARTED"
                    and row["payload"]["value"].get("request_id")
                    == admissions[0]["payload"]["value"]["request_id"]
                    for row in selected
                )
            ):
                raise OperationError("DIAGNOSTIC_ACTUAL_PAID_INVOCATION_REQUIRED")
            value = paid[0]["payload"]["value"]
            import json

            before = QuotaProof.model_validate_json(json.dumps(value["quota"]))
            period = value["period"]
            consistent = (
                values.remaining_credits + values.used_credits
                == authority.proposal.plan_credit_allowance
                and values.last_request_cost <= 2
                and values.used_credits == before.used_credits + values.last_request_cost
                and values.remaining_credits == before.remaining_credits - values.last_request_cost
                and datetime.fromisoformat(period["started_at"])
                <= now
                < datetime.fromisoformat(period["resets_at"])
            )
            receipt = {
                "reservation_id": value["reservation_id"],
                "period_started_at": datetime.fromisoformat(period["started_at"]).isoformat(),
                "reserved_credits": 2,
                "remaining_credits": values.remaining_credits,
                "used_credits": values.used_credits,
                "last_request_cost": values.last_request_cost,
                "provider_status": status,
                "source": "ACTUAL_CHARGED_RESPONSE_HEADERS",
                "consistent": consistent,
            }
            previous = [
                row
                for row in selected
                if row["execution_key"] == key and is_diagnostic_settlement(row)
            ]
            if previous:
                if len(previous) != 1 or any(
                    previous[0]["payload"]["value"].get(name) != item
                    for name, item in receipt.items()
                ):
                    raise OperationError("DIAGNOSTIC_CONTRADICTORY_RESPONSE_QUOTA")
            else:
                self._append(
                    authority,
                    connection,
                    rows,
                    session,
                    "LAUNCH",
                    "ACTUAL_QUOTA",
                    receipt,
                    now=now,
                )
        if not consistent:
            raise OperationError("CHARGED_QUOTA_HEADERS_CONTRADICT_LEDGER")

    def reconcile_initial_counter(self, key: str, quota: QuotaProof, *, now: datetime) -> None:
        """A fresh read-only session may attribute ONE exact full-cost delta.

        Zero/partial deltas never prove non-charge after possible invocation.
        No reservation is refunded and no failed session slot is restored.
        """
        from dmf_pulse.operation.journal import PAID_ROUTE_SHA

        with self._transaction() as (authority, connection, rows):
            selected = self._tagged(rows, authority.proposal)
            session = self._active(authority, selected, key, now)
            observations = [
                row
                for row in selected
                if row["kind"] == "QUOTA"
                and row["execution_key"] == key
                and row["payload"]["value"]["phase"] == "INITIAL"
                and row["payload"]["value"]["proof"] == quota.model_dump(mode="json")
            ]
            if session.mode != "READ_ONLY" or len(observations) != 1:
                raise OperationError("DIAGNOSTIC_READ_ONLY_INITIAL_RECONCILIATION_REQUIRED")
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            used, unresolved = self.original._paid_state(
                connection, rows, self.original.policy, start
            )
            if unresolved == 0:
                verify_period(
                    self.original.policy,
                    quota,
                    now=now,
                    settled_credits=used,
                    unresolved_paid_attempts=0,
                )
                return
            anchor = (
                self.original.policy.calendar_anchor_used_credits
                if start == self.original.policy.calendar_anchor_at
                else 0
            )
            if (
                unresolved != 1
                or quota.used_credits - used - anchor != 2
                or quota.remaining_credits + quota.used_credits
                != authority.proposal.plan_credit_allowance
                or not start <= quota.request_started_at <= quota.received_at <= now
                or now - quota.received_at
                > timedelta(seconds=authority.proposal.limits.quota_max_age_seconds)
            ):
                raise OperationError("DIAGNOSTIC_PAID_CONSUMPTION_UNRESOLVED")
            original = [
                dict(row["payload"])
                for row in connection.execute(
                    select(refresh_control_event).where(
                        refresh_control_event.c.ledger_id == self.original.policy.ledger_id
                    )
                ).mappings()
            ]
            settled = {
                row["payload"]["value"]["reservation_id"]
                for row in rows
                if (row["kind"] == "SETTLEMENT" or is_diagnostic_settlement(row))
                and row["payload"]["value"]["consistent"] is True
            }
            missing = [
                row
                for row in original
                if row["kind"] == "ATTEMPT"
                and row["route_sha256"] == PAID_ROUTE_SHA
                and row["reservation_id"] not in settled
            ]
            if len(missing) != 1:
                raise OperationError("DIAGNOSTIC_PAID_CONSUMPTION_UNRESOLVED")
            attempts = missing[0]
            paid = [
                row
                for row in selected
                if row["payload"]["value"]["subtype"] == "PAID_RESERVATION"
                and row["payload"]["value"]["reservation_id"] == attempts["reservation_id"]
            ]
            if (
                len(paid) != 1
                or not start <= datetime.fromisoformat(attempts["at"]) <= quota.request_started_at
            ):
                raise OperationError("DIAGNOSTIC_EXACT_PRIOR_PAID_IDENTITY_REQUIRED")
            prior_key = paid[0]["execution_key"]
            admissions = [
                row
                for row in selected
                if row["execution_key"] == prior_key
                and row["payload"]["value"]["subtype"] == "PROVIDER_ADMISSION"
                and row["payload"]["value"]["provider"] == "ODDS_PAID"
            ]
            if (
                len(admissions) != 1
                or any(
                    row["execution_key"] == prior_key and is_diagnostic_settlement(row)
                    for row in selected
                )
                or not any(
                    row["execution_key"] == prior_key
                    and row["payload"]["value"]["subtype"] == "TRANSPORT_STARTED"
                    and row["payload"]["value"].get("request_id")
                    == admissions[0]["payload"]["value"]["request_id"]
                    for row in selected
                )
            ):
                raise OperationError("DIAGNOSTIC_EXACT_UNSETTLED_PRIOR_INVOCATION_REQUIRED")
            prior = [row for row in self._starts(selected) if row["execution_key"] == prior_key]
            if len(prior) != 1 or not any(
                row["execution_key"] == prior_key
                and row["kind"] == "CLOSE"
                and row["payload"]["value"]["subtype"] == "QUIESCENT_CLOSE"
                for row in selected
            ):
                raise OperationError("DIAGNOSTIC_PRIOR_TRANSPORT_QUIESCENCE_REQUIRED")
            self._append(
                authority,
                connection,
                rows,
                self._session(prior[0]),
                "LAUNCH",
                "COUNTER_RECONCILIATION",
                {
                    "reservation_id": attempts["reservation_id"],
                    "period_started_at": start.isoformat(),
                    "reserved_credits": 2,
                    "remaining_credits": quota.remaining_credits,
                    "used_credits": quota.used_credits,
                    "last_request_cost": 2,
                    "provider_status": None,
                    "source": "EXCLUSIVE_ACCOUNT_FRESH_COUNTER_EXACT_FULL_RESERVATION_DELTA",
                    "consistent": True,
                    "reconciliation_session_key": key,
                    "reconciliation_quota_sha256": quota.semantic_sha256,
                },
                now=now,
            )

    def publish(
        self,
        key: str,
        publication: DiagnosticPublication,
        diagnostics: DiagnosticReport,
        *,
        now: datetime,
    ) -> None:
        import json

        with self._transaction() as (authority, connection, rows):
            selected = self._tagged(rows, authority.proposal)
            session = self._active(authority, selected, key, now)
            proof, view = publication.proof, publication.view
            if not isinstance(view.team.decision, PrivateV1Decision):
                raise OperationError("DIAGNOSTIC_ONE_GAMEWEEK_REQUIRED")
            related = [row for row in selected if row["execution_key"] == key]
            paid = [
                row for row in related if row["payload"]["value"]["subtype"] == "PAID_RESERVATION"
            ]
            settled = [row for row in related if is_diagnostic_settlement(row)]
            if len(paid) != 1 or len(settled) != 1:
                raise OperationError("DIAGNOSTIC_ACTUAL_PAID_SETTLEMENT_REQUIRED")
            value, settlement = paid[0]["payload"]["value"], settled[0]["payload"]["value"]
            grant = RefreshGrant.model_validate_json(json.dumps(value["grant"]))
            gate = DiagnosticPaidGateProof.model_validate_json(json.dumps(value["gate"]))
            receipt = view.market_quota_receipt
            ceiling = min(
                session.lease_until,
                grant.expires_at,
                gate.credential_expires_at,
                grant.request.deadline_at,
                authority.proposal.deadline_not_after,
            )
            if (
                proof.session_key != key
                or view.job_id != key
                or proof.campaign_sha256 != authority.proposal.semantic_sha256
                or proof.signed_authority_sha256 != session.authority_sha256
                or proof.grant_sha256 != grant.semantic_sha256
                or proof.fpl_validation_sha256 != gate.fpl_validation_sha256
                or proof.credential_expires_at != gate.credential_expires_at
                or proof.model_cutoff != datetime.fromisoformat(value["model_cutoff"])
                or view.information_cutoff != proof.model_cutoff
                or proof.decision_sha256 != view.team.decision.semantic_sha256
                or view.team.decision.lineage.execution_input_sha256 != proof.execution_input_sha256
                or view.team.decision.lineage.fpl_input_sha256 != proof.fpl_input_sha256
                or view.team.decision.lineage.odds_market_sha256 != proof.odds_input_sha256
                or view.team.decision.lineage.code_sha != authority.normal_policy.implementation_sha
                or view.team.decision.scenario_count != 256
                or view.team.decision.stage9_monte_carlo_status != "PASS"
                or canonical_sha256(view.model_dump(mode="json")) != proof.view_sha256
                or view.dataset_mode != "PRIVATE_TRANSIENT"
                or LABEL not in view.restrictions
                or view.gameweeks != (authority.proposal.gameweek,)
                or view.deadline_at != grant.request.deadline_at
                or not proof.completed_at == view.generated_at <= now < ceiling
                or view.expires_at != ceiling
                or not session.started_at
                <= proof.fpl_usable_at
                <= gate.fpl_validation_completed_at
                <= gate.controlled_pipeline_completed_at
                <= grant.issued_at
                or not session.started_at
                <= proof.prior_usable_at
                <= gate.controlled_pipeline_completed_at
                or not grant.issued_at
                <= proof.odds_request_started_at
                <= proof.odds_received_at
                <= proof.odds_usable_at
                <= grant.request.information_cutoff
                <= proof.model_cutoff
                or proof.odds_usable_at > proof.completed_at
                or settlement["consistent"] is not True
                or settlement["source"] != "ACTUAL_CHARGED_RESPONSE_HEADERS"
                or settlement["provider_status"] != 200
                or settlement["reservation_id"] != grant.reservation_id
                or receipt is None
            ):
                raise OperationError("DIAGNOSTIC_REAL_PUBLICATION_PROOF_INVALID")
            if (
                any(
                    (getattr(receipt, name) != settlement[field])
                    for name, field in (
                        ("remaining_credits", "remaining_credits"),
                        ("used_credits", "used_credits"),
                        ("last_request_cost", "last_request_cost"),
                    )
                )
                or receipt.received_at != proof.odds_received_at
                or receipt.transport_call_count != 1
            ):
                raise OperationError("DIAGNOSTIC_REAL_QUOTA_RECEIPT_INVALID")
            vintages = {vintage.source: vintage for vintage in view.source_vintages}
            if len(vintages) != len(view.source_vintages) or set(vintages) != {
                "FPL",
                "MARKETS",
                "TEAM_SCORE_PRIOR",
            }:
                raise OperationError("DIAGNOSTIC_REAL_SOURCE_VINTAGES_INVALID")
            for source, digest in (
                ("FPL", proof.fpl_input_sha256),
                ("MARKETS", proof.odds_input_sha256),
                ("TEAM_SCORE_PRIOR", proof.prior_input_sha256),
            ):
                if vintages[source].identity_sha256 != digest:
                    raise OperationError("DIAGNOSTIC_REAL_SOURCE_VINTAGES_INVALID")
            admissions = [
                row for row in related if row["payload"]["value"]["subtype"] == "PROVIDER_ADMISSION"
            ]
            completions: dict[str, list[datetime]] = {}
            for admission in admissions:
                request = admission["payload"]["value"]
                sequence = [
                    row
                    for row in related
                    if row["payload"]["value"].get("request_id") == request["request_id"]
                ]
                if [row["payload"]["value"]["subtype"] for row in sequence] != [
                    "PROVIDER_ADMISSION",
                    "TRANSPORT_STARTED",
                    "RESPONSE_COMPLETED",
                ] or sequence[-1]["payload"]["value"]["http_status"] != 200:
                    raise OperationError("DIAGNOSTIC_COMPLETE_ACTUAL_HTTP_RESPONSES_REQUIRED")
                completions.setdefault(request["provider"], []).append(sequence[-1]["at"])
            if (
                set(completions) != {"FPL", "QUOTA", "OPENFOOTBALL", "ODDS_PAID"}
                or len(completions["FPL"]) != vintages["FPL"].requests + 1
                or len(completions["FPL"]) > authority.proposal.limits.fpl_gets_per_session
                or max(completions["FPL"]) > gate.fpl_validation_completed_at
                or len(completions["OPENFOOTBALL"]) != 4
                or max(completions["OPENFOOTBALL"]) > proof.prior_usable_at
                or len(completions["QUOTA"]) != 2
                or len(completions["ODDS_PAID"]) != 1
                or completions["ODDS_PAID"][0] > proof.odds_received_at
                or diagnostics.failure is not None
                or diagnostics.chronology_complete is not True
            ):
                raise OperationError("DIAGNOSTIC_COMPLETE_ACTUAL_HTTP_RESPONSES_REQUIRED")
            self._append(
                authority,
                connection,
                rows,
                session,
                "LAUNCH",
                "TERMINAL",
                {
                    "outcome": "REAL_PUBLICATION",
                    "view": view.model_dump(mode="json"),
                    "publication_proof": proof.model_dump(mode="json"),
                    "diagnostics": diagnostics.model_dump(mode="json"),
                    "classification": LABEL,
                    "unvalidated": True,
                    "retention": "PRIVATE_DERIVED_AS_OF_SOURCE_BODIES_TRANSIENT",
                },
                now=now,
            )

    def terminate(
        self,
        key: str,
        *,
        diagnostics: DiagnosticReport,
        error_code: str,
        now: datetime,
    ) -> None:
        with self._transaction() as (authority, connection, rows):
            selected = self._tagged(rows, authority.proposal)
            starts = [row for row in self._starts(selected) if row["execution_key"] == key]
            if len(starts) != 1:
                raise OperationError("DIAGNOSTIC_SESSION_NOT_FOUND")
            session = self._session(starts[0])
            if any(_is_terminal(row) and row["execution_key"] == key for row in selected):
                raise OperationError("DIAGNOSTIC_SESSION_ALREADY_TERMINAL")
            from dmf_pulse.current_failures import CURRENT_FAILURE_CODES

            safe = (
                error_code
                if type(error_code) is str and error_code in CURRENT_FAILURE_CODES
                else "CURRENT_TYPED_FAILURE_UNRECOGNIZED"
            )
            controlled_complete = safe == "DIAGNOSTIC_READ_ONLY_COMPLETE"
            if controlled_complete and (
                session.mode != "READ_ONLY"
                or not any(
                    row["execution_key"] == key
                    and row["payload"]["value"]["subtype"] == "CONTROLLED_GATE"
                    for row in selected
                )
            ):
                raise OperationError("DIAGNOSTIC_CANONICAL_GATE_PROOF_REQUIRED")
            self._append(
                authority,
                connection,
                rows,
                session,
                "LAUNCH" if controlled_complete else "FAILURE",
                "TERMINAL",
                {
                    "outcome": "CONTROLLED_ENGINEERING_COMPLETE"
                    if controlled_complete
                    else "FAILED",
                    "diagnostics": diagnostics.model_dump(mode="json"),
                    "error_code": safe,
                    "view": None,
                    "classification": "GW10 diagnostic / forecasts unvalidated",
                },
                now=now,
            )

    def close(self, key: str, *, worker_and_transports_quiescent: bool, now: datetime) -> None:
        if worker_and_transports_quiescent is not True:
            raise OperationError("DIAGNOSTIC_QUIESCENCE_REQUIRED")
        with self._transaction() as (authority, connection, rows):
            selected = self._tagged(rows, authority.proposal)
            starts = [row for row in self._starts(selected) if row["execution_key"] == key]
            terminal = [
                row for row in selected if row["execution_key"] == key and _is_terminal(row)
            ]
            if len(starts) != 1 or len(terminal) != 1:
                raise OperationError("DIAGNOSTIC_TERMINAL_RESULT_REQUIRED")
            session = self._session(starts[0])
            self._append(
                authority,
                connection,
                rows,
                session,
                "CLOSE",
                "QUIESCENT_CLOSE",
                {"worker_and_transports_quiescent": True},
                now=now,
            )

    def inspect_previous(self, key: str, terminal_sha256: str, *, now: datetime) -> None:
        with self._transaction() as (authority, connection, rows):
            selected = self._tagged(rows, authority.proposal)
            starts = [row for row in self._starts(selected) if row["execution_key"] == key]
            matches = [
                row
                for row in selected
                if row["execution_key"] == key
                and row["sha256"] == terminal_sha256
                and _is_terminal(row)
            ]
            closed = any(row["kind"] == "CLOSE" and row["execution_key"] == key for row in selected)
            if len(starts) != 1 or len(matches) != 1 or not closed:
                raise OperationError("DIAGNOSTIC_CLOSED_TERMINAL_INSPECTION_REQUIRED")
            self._append(
                authority,
                connection,
                rows,
                self._session(starts[0]),
                "CLOSE",
                "INSPECTION",
                {"terminal_sha256": terminal_sha256},
                now=now,
            )
