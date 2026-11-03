"""Exact single-attempt transports under canonical GW10 diagnostic custody."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Literal

from dmf_pulse.dashboard.current_sources import Provider
from dmf_pulse.ingestion.odds.client import OddsHttpRequest, OddsHttpResponse
from dmf_pulse.operation.campaign_journal import DiagnosticJournal
from dmf_pulse.operation.campaign_runtime import require_runtime
from dmf_pulse.operation.diagnostics import DiagnosticLog
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.quota import (
    QUOTA_PATH,
    NativeQuotaTransport,
    QuotaSourceQualification,
    QuotaTransport,
)


class DiagnosticGuard:
    def __init__(
        self,
        journal: DiagnosticJournal,
        key: str,
        *,
        diagnostics: DiagnosticLog,
    ) -> None:
        runtime = require_runtime(key)
        if runtime.journal is not journal:
            raise OperationError("DIAGNOSTIC_VERIFIED_PROCESS_SCOPE_REQUIRED")
        self.journal, self.key, self.clock, self.diagnostics = (
            journal,
            key,
            runtime.clock,
            diagnostics,
        )
        self.phase: Literal["INITIAL", "PRE_PAID"] = "INITIAL"
        self.pending: str | None = None
        self.closed = False
        self._odds_headers_observed = False

    def check(self) -> None:
        if self.closed:
            raise OperationError("DIAGNOSTIC_ACQUISITION_CLOSED")
        runtime = require_runtime(self.key)
        current = self.journal.check(self.key, now=self.clock())
        if current != runtime.session:
            raise OperationError("DIAGNOSTIC_VERIFIED_PROCESS_SCOPE_REQUIRED")
        ceiling = (
            runtime.paid_cutoff
            if runtime.paid_cutoff is not None
            else current.started_at
            + timedelta(seconds=runtime.authority.proposal.limits.maximum_pre_paid_seconds)
        )
        if self.clock() >= ceiling:
            raise OperationError("DIAGNOSTIC_ACQUISITION_WINDOW_EXPIRED")

    def quota_admission(
        self, qualification: QuotaSourceQualification, *, checked_at: datetime
    ) -> None:
        self.check()
        runtime = require_runtime(self.key)
        if (
            qualification != runtime.authority.normal_policy.quota_qualification
            or checked_at > self.clock()
        ):
            raise OperationError("QUOTA_SOURCE_NOT_ENROLLED")

    def _provider(
        self, provider: Provider, path: str
    ) -> Literal["FPL", "OPENFOOTBALL", "ODDS_PAID", "QUOTA"]:
        return (
            "QUOTA"
            if provider == "ODDS" and path == QUOTA_PATH
            else "ODDS_PAID"
            if provider == "ODDS"
            else provider
        )

    def preflight_send(self, provider: Provider, method: str, host: str, path: str) -> None:
        self.check()
        source = self._provider(provider, path)
        self.journal.admit_provider(
            self.key,
            source,
            method,
            host,
            path,
            phase=self.phase if source == "QUOTA" else None,
            now=self.clock(),
            consume=False,
        )
        self.check()

    def before_send(self, provider: Provider, method: str, host: str, path: str) -> None:
        self.check()
        source = self._provider(provider, path)
        self.pending = self.journal.admit_provider(
            self.key,
            source,
            method,
            host,
            path,
            phase=self.phase if source == "QUOTA" else None,
            now=self.clock(),
        )
        self.diagnostics.admitted(provider, method, host, path)

    def before_transport(self) -> None:
        self.check()

    def transport_started(self) -> None:
        if self.pending is None:
            raise OperationError("DIAGNOSTIC_TRANSPORT_ADMISSION_REQUIRED")
        self.check()
        self.journal.record_transport(self.key, self.pending, "TRANSPORT_STARTED", now=self.clock())
        self.check()
        self.diagnostics.transport_started()

    def response_completed(self, status: int) -> None:
        if self.pending is None:
            raise OperationError("DIAGNOSTIC_TRANSPORT_ADMISSION_REQUIRED")
        self.journal.record_transport(
            self.key, self.pending, "RESPONSE_COMPLETED", now=self.clock(), http_status=status
        )
        self.diagnostics.response_completed(status)

    def transport_failed(self, error: Exception) -> None:
        self.diagnostics.failed(error)

    def credential_failed(self, code: object) -> None:
        del code
        self.diagnostics.failed(OperationError("CREDENTIAL_UNAVAILABLE"))

    def finish_acquisition(self) -> None:
        # The score service closes its own phase before controlled computation;
        # the later paid phase remains separately gated. The controller closes
        # the complete guard explicitly after its sole paid acquisition.
        self.check()

    def observe_odds_headers(self, status: int, headers: Mapping[str, str]) -> None:
        self.journal.settle_headers(self.key, headers, status, now=self.clock())
        self._odds_headers_observed = True

    def observe_odds_response(self, response: object) -> None:
        if not isinstance(response, OddsHttpResponse):
            raise OperationError("DIAGNOSTIC_ACTUAL_ODDS_RESPONSE_REQUIRED")
        # Native header observation precedes body completion. Check duplicate
        # values too; a wrapper cannot silently replace a settled response.
        self.observe_odds_headers(response.status_code, response.headers)


class DiagnosticQuotaTransport:
    """QuotaClient supplies the secret only to the existing native transport."""

    def __init__(self, guard: DiagnosticGuard, delegate: QuotaTransport | None = None) -> None:
        self.guard, self.delegate = (
            guard,
            delegate if delegate is not None else NativeQuotaTransport(),
        )

    def send(self, request: OddsHttpRequest, credential: str) -> OddsHttpResponse:
        try:
            self.guard.transport_started()
            response = self.delegate.send(request, credential)
            self.guard.response_completed(response.status_code)
            return response
        except Exception as error:
            self.guard.transport_failed(error)
            raise
