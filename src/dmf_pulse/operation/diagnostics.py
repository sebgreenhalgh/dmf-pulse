"""Bounded, code-owned execution evidence. No messages, inputs or credentials."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.operation.models import Metadata, OperationError, Sha
from dmf_pulse.operation.runtime_integrity import IntegrityReason

Stage = Literal[
    "WORKER_START",
    "FPL_ACQUISITION",
    "FPL_PARSING",
    "MANAGER_STATE",
    "RULES_BINDING",
    "MARKET_ACQUISITION",
    "SCORE_SOURCE_ACQUISITION",
    "IDENTITY_BINDING",
    "STAGE7_MINUTES",
    "SCORE_PRIOR_BINDING",
    "INPUT_SEAL",
    "STAGE8_EVENTS",
    "STAGE9_POINTS",
    "STAGE12_DECISION",
    "STAGE10_TACTICS",
    "STAGE11_POLICY",
    "RESULT_VALIDATION",
    "PUBLICATION",
    "RELEASE_INTEGRITY",
]
Provider = Literal["FPL", "ODDS", "OPENFOOTBALL"]
Category = Literal[
    "AUTHORIZATION",
    "CREDENTIAL",
    "TRANSPORT",
    "HTTP_RESPONSE",
    "RESPONSE_CONTRACT",
    "INPUT_CONTRACT",
    "MODEL_CONTRACT",
    "INTEGRITY",
    "UNRECOGNIZED_TYPED_FAILURE",
    "INTERNAL_EXCEPTION",
    "TIMEOUT",
    "WORKER_EXIT",
]
ExceptionFamily = Literal[
    "AUTHORIZATION",
    "INGESTION",
    "PRIVATE_MODEL",
    "OPERATOR",
    "VALIDATION",
    "VALUE",
    "TYPE",
    "KEY",
    "ARITHMETIC",
    "TIMEOUT",
    "OS",
    "INTEGRITY",
    "OTHER",
    "NONE",
]
HttpCategory = Literal[
    "SUCCESS", "REDIRECT", "CLIENT_ERROR", "SERVER_ERROR", "OTHER", "INVALID_STATUS"
]
EventKind = Literal[
    "STAGE_STARTED",
    "STAGE_COMPLETED",
    "ADMITTED",
    "TRANSPORT_STARTED",
    "RESPONSE_COMPLETED",
    "FAILURE",
]

# Disclosure/security bounds; these do not allocate provider authority or budgets.
MAX_EVENTS = 256
MAX_REQUESTS = 32
MAX_EVENT_BYTES = 4096

STAGE_LABELS: dict[Stage, str] = {
    "WORKER_START": "Starting reviewed worker",
    "FPL_ACQUISITION": "Acquiring current FPL state",
    "FPL_PARSING": "Validating FPL snapshot",
    "MANAGER_STATE": "Compiling authenticated manager state",
    "RULES_BINDING": "Binding accepted rules",
    "MARKET_ACQUISITION": "Acquiring current market odds",
    "SCORE_SOURCE_ACQUISITION": "Acquiring score-prior source",
    "IDENTITY_BINDING": "Resolving identities",
    "STAGE7_MINUTES": "Calculating Stage 7 minutes",
    "SCORE_PRIOR_BINDING": "Binding score priors",
    "INPUT_SEAL": "Sealing execution input",
    "STAGE8_EVENTS": "Calculating Stage 8 events",
    "STAGE9_POINTS": "Calculating Stage 9 points",
    "STAGE12_DECISION": "Calculating Stage 12 decision",
    "STAGE10_TACTICS": "Calculating Stage 10 tactics",
    "STAGE11_POLICY": "Calculating Stage 11 policy",
    "RESULT_VALIDATION": "Validating recommendation",
    "PUBLICATION": "Publishing private recommendation",
    "RELEASE_INTEGRITY": "Verifying signed executable release",
}
STARTED_STAGES: dict[str, Stage] = {
    "Acquiring current FPL state...": "FPL_ACQUISITION",
    "Acquiring current market odds...": "MARKET_ACQUISITION",
    "Acquiring current score-prior source...": "SCORE_SOURCE_ACQUISITION",
    "Resolving current identities...": "IDENTITY_BINDING",
    "Building Stage-7 minutes...": "STAGE7_MINUTES",
    "Binding current score priors...": "SCORE_PRIOR_BINDING",
    "Sealing execution input...": "INPUT_SEAL",
    "Assembling joint Gameweek scenarios...": "STAGE9_POINTS",
    "Preparing optimiser...": "STAGE11_POLICY",
    "Stage-10 tactical batch starting": "STAGE10_TACTICS",
    "Stage-11 policy selection...": "STAGE11_POLICY",
    "Verifying captain / vice-captain...": "STAGE12_DECISION",
    "Building paired comparator...": "STAGE12_DECISION",
}

# Only these static, repository-owned traceback locations may refine a stage.
# No frame locals, exception text, source values or arbitrary function names leave RAM.
_LOCATIONS: dict[tuple[str, str], Stage] = {
    ("dmf_pulse.ingestion.fpl.direct_payloads", "_parse_json"): "FPL_PARSING",
    ("dmf_pulse.ingestion.fpl.direct_payloads", "parse_direct_event_live"): "FPL_PARSING",
    ("dmf_pulse.ingestion.fpl.manager_provider", "parse_provider_current_team"): "FPL_PARSING",
    ("dmf_pulse.ingestion.fpl.parser", "parse_fpl_payload"): "FPL_PARSING",
    ("dmf_pulse.ingestion.fpl.current", "compile_direct"): "FPL_PARSING",
    ("dmf_pulse.ingestion.fpl.manager_current", "compile_provider_snapshot"): "MANAGER_STATE",
    ("dmf_pulse.private_v1.one_command", "_rules_authority"): "RULES_BINDING",
}


class SafeFailure(Metadata):
    stage: Stage
    category: Category
    exception_family: ExceptionFamily
    code: str = Field(min_length=1, max_length=100)
    typed_code_recognized: bool
    integrity_reason: IntegrityReason | None = None

    @model_validator(mode="after")
    def code_is_owned(self) -> Self:
        from dmf_pulse.current_failures import CURRENT_FAILURE_CODES

        if self.code not in CURRENT_FAILURE_CODES:
            raise ValueError("failure code is not in the fixed public catalogue")
        return self


class RequestIdentity(Metadata):
    provider: Provider
    route_sha256: Sha
    ordinal: Annotated[int, Field(ge=1, le=MAX_REQUESTS)]


class DiagnosticEvent(Metadata):
    schema_version: Literal["operator-diagnostic-event-v1"] = "operator-diagnostic-event-v1"
    sequence: Annotated[int, Field(ge=0, le=100_000)]
    at: datetime
    kind: EventKind
    stage: Stage
    request: RequestIdentity | None = None
    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    http_category: HttpCategory | None = None
    failure: SafeFailure | None = None

    @model_validator(mode="after")
    def event_is_coherent(self) -> Self:
        route_event = self.kind in {"ADMITTED", "TRANSPORT_STARTED", "RESPONSE_COMPLETED"}
        if route_event != (self.request is not None):
            raise ValueError("request identity differs from event kind")
        response = self.kind == "RESPONSE_COMPLETED"
        if response != (self.http_category is not None) or (
            not response and self.http_status is not None
        ):
            raise ValueError("HTTP evidence differs from completion kind")
        if response and self.http_status is None and self.http_category != "INVALID_STATUS":
            raise ValueError("missing status is not classified as invalid")
        if (self.kind == "FAILURE") != (self.failure is not None):
            raise ValueError("failure evidence differs from event kind")
        if (
            response
            and self.http_status is not None
            and self.http_category != http_category(self.http_status)
        ):
            raise ValueError("HTTP category differs from status")
        return self


class RequestOutcome(Metadata):
    identity: RequestIdentity
    admitted_at: datetime
    transport_started_at: datetime | None = None
    response_completed_at: datetime | None = None
    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    http_category: HttpCategory | None = None


class DiagnosticReport(Metadata):
    schema_version: Literal["operator-diagnostic-report-v1"] = "operator-diagnostic-report-v1"
    stage: Stage
    failure: SafeFailure | None
    requests: Annotated[tuple[RequestOutcome, ...], Field(max_length=MAX_REQUESTS)]
    events: Annotated[tuple[DiagnosticEvent, ...], Field(max_length=MAX_EVENTS)]
    history_truncated: bool
    chronology_complete: bool = True
    worker_terminal_received: bool = False


def http_category(status: object) -> HttpCategory:
    if type(status) is not int or not 100 <= status <= 599:
        return "INVALID_STATUS"
    if 200 <= status < 300:
        return "SUCCESS"
    if 300 <= status < 400:
        return "REDIRECT"
    if 400 <= status < 500:
        return "CLIENT_ERROR"
    if 500 <= status < 600:
        return "SERVER_ERROR"
    return "OTHER"


def route_identity(
    provider: Provider, method: str, host: str, path: str, ordinal: int
) -> RequestIdentity:
    """Call only AFTER the authoritative guard admits the exact route."""
    fpl = r"/api/(?:(?:bootstrap-static|fixtures)/|(?:entry|my-team)/[1-9][0-9]*/|entry/[1-9][0-9]*/(?:history|transfers)/|entry/[1-9][0-9]*/event/[1-9][0-9]*/picks/|event/[1-9][0-9]*/live/)"
    public = (
        r"/openfootball/football\.json/[0-9a-f]{40}/(?:LICENSE\.md|[0-9]{4}-[0-9]{2}/en\.1\.json)"
    )
    valid = method == "GET" and (
        (provider == "FPL" and host == "fantasy.premierleague.com" and re.fullmatch(fpl, path))
        or (
            provider == "ODDS"
            and host == "api.the-odds-api.com"
            and path == "/v4/sports/soccer_epl/odds"
        )
        or (
            provider == "OPENFOOTBALL"
            and host == "raw.githubusercontent.com"
            and re.fullmatch(public, path)
        )
    )
    if not valid:
        raise OperationError("DIAGNOSTIC_ROUTE_IDENTITY_INVALID")
    return RequestIdentity(
        provider=provider,
        route_sha256=canonical_sha256([provider, method, host, path]),
        ordinal=ordinal,
    )


def safe_failure(error: Exception, stage: Stage) -> SafeFailure:
    """Classify by code-owned types/constants. Never format an exception."""
    from pydantic import ValidationError

    from dmf_pulse.authorization_errors import AuthorizationError, safe_authorization_fields
    from dmf_pulse.credentials.service import CredentialError
    from dmf_pulse.current_failures import CURRENT_FAILURE_CODES, safe_current_failure_code
    from dmf_pulse.ingestion.errors import IngestionError
    from dmf_pulse.operation.runtime_integrity import RuntimeIntegrityError
    from dmf_pulse.private_v1.errors import PrivateV1Error

    family: ExceptionFamily = "OTHER"
    category: Category = "INTERNAL_EXCEPTION"
    typed = isinstance(
        error, (AuthorizationError, IngestionError, PrivateV1Error, OperationError, CredentialError)
    )
    if isinstance(error, AuthorizationError):
        family, category = "AUTHORIZATION", "AUTHORIZATION"
    elif isinstance(error, IngestionError):
        family, category = "INGESTION", "RESPONSE_CONTRACT"
    elif isinstance(error, PrivateV1Error):
        family, category = "PRIVATE_MODEL", "MODEL_CONTRACT"
    elif isinstance(error, RuntimeIntegrityError):
        family, category, stage = "INTEGRITY", "INTEGRITY", "RELEASE_INTEGRITY"
    elif isinstance(error, OperationError):
        family, category = "OPERATOR", "AUTHORIZATION"
    elif isinstance(error, CredentialError):
        family, category = "OPERATOR", "CREDENTIAL"
    elif isinstance(error, ValidationError):
        family, category = "VALIDATION", "INPUT_CONTRACT"
    elif isinstance(error, TimeoutError):
        family, category = "TIMEOUT", "TIMEOUT"
    elif isinstance(error, KeyError):
        family, category = "KEY", "INTERNAL_EXCEPTION"
    elif isinstance(error, TypeError):
        family = "TYPE"
    elif isinstance(error, ValueError):
        family = "VALUE"
    elif isinstance(error, ArithmeticError):
        family = "ARITHMETIC"
    elif isinstance(error, OSError):
        family = "OS"
        if stage in {"FPL_ACQUISITION", "MARKET_ACQUISITION", "SCORE_SOURCE_ACQUISITION"}:
            category = "TRANSPORT"

    # Read .code only on our typed boundaries; unknown text is discarded entirely.
    raw_code = getattr(error, "code", None) if typed else None
    code = safe_current_failure_code(raw_code)
    recognized = type(raw_code) is str and code != "CURRENT_SOURCE_OR_RUN_BLOCKED"
    if recognized:
        if code.startswith("CREDENTIAL_") or code == "FPL_AUTH_REQUIRED":
            category = "CREDENTIAL"
        elif raw_code in {
            "READ_TIMEOUT",
            "CONNECT_TIMEOUT",
            "TOTAL_TIMEOUT",
            "TLS_ERROR",
            "SOURCE_UNAVAILABLE",
        }:
            category = "TRANSPORT"
        elif raw_code in {"HTTP_4XX", "HTTP_5XX", "HTTP_429", "REDIRECT_BLOCKED"}:
            category = "HTTP_RESPONSE"
        elif raw_code == "ONE_COMMAND_INPUT_INVALID":
            category = "INPUT_CONTRACT"
        elif code == "RUN_TIMEOUT":
            category = "TIMEOUT"
        elif code in {
            "WORKER_STOPPED",
            "WORKER_START_FAILED",
            "RUN_OR_PUBLICATION_INVALID",
            "RECOMMENDATION_BLOCKED",
            "DIAGNOSTIC_PROTOCOL_INVALID",
        }:
            category = "INTERNAL_EXCEPTION"
        elif safe_authorization_fields(AuthorizationError(code))[0] == code:
            category = "AUTHORIZATION"
    elif typed:
        code, category = "CURRENT_TYPED_FAILURE_UNRECOGNIZED", "UNRECOGNIZED_TYPED_FAILURE"
    else:
        code = "CURRENT_INTERNAL_EXCEPTION"
        if isinstance(error, ValidationError):
            code = "CURRENT_INPUT_CONTRACT_FAILED"
        elif isinstance(error, (TimeoutError, OSError)) and stage in {
            "FPL_ACQUISITION",
            "MARKET_ACQUISITION",
            "SCORE_SOURCE_ACQUISITION",
        }:
            code = "CURRENT_TRANSPORT_FAILED"
    integrity_reason = (
        error.reason
        if isinstance(error, RuntimeIntegrityError)
        else error.integrity_reason
        if isinstance(error, OperationError)
        else None
    )
    integrity_code = (
        raw_code
        in {
            "STANDING_DEPENDENCY_TREE_CHANGED",
            "STANDING_RELEASE_RESTART_REQUIRED",
            "STANDING_PROTECTED_PACKAGE_CHANGED",
            "STANDING_INSTALLATION_INVENTORY_CHANGED",
            "STANDING_DEPENDENCY_INVENTORY_CHANGED",
            "STANDING_EXECUTION_PYTHON_CHANGED",
            "STANDING_REVIEWED_ENTRYPOINT_REQUIRED",
            "STANDING_INSTALLED_RELEASE_ORIGIN_INVALID",
        }
        if type(raw_code) is str
        else False
    )
    if isinstance(error, RuntimeIntegrityError) or integrity_reason is not None or integrity_code:
        code = "CURRENT_INTEGRITY_FAILURE"
        category, stage = "INTEGRITY", "RELEASE_INTEGRITY"
    assert code in CURRENT_FAILURE_CODES
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        module_name = frame.f_globals.get("__name__")
        if isinstance(module_name, str) and category != "INTEGRITY":
            stage = _LOCATIONS.get((module_name, frame.f_code.co_name), stage)
        traceback = traceback.tb_next
    return SafeFailure(
        stage=stage,
        category=category,
        exception_family=family,
        code=code,
        typed_code_recognized=recognized,
        integrity_reason=integrity_reason,
    )


class DiagnosticLog:
    """One run-local event reducer; transport completions never allocate authority."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        send: Callable[[DiagnosticEvent], None] | None = None,
    ) -> None:
        self.clock, self.send = clock, send
        self.stage: Stage = "WORKER_START"
        self.failure: SafeFailure | None = None
        self.events: list[DiagnosticEvent] = []
        self.requests: dict[int, RequestOutcome] = {}
        self._sequence = 0
        self._last_at: datetime | None = None
        self._truncated = False
        self._clock_valid = True
        self.worker_terminal_received = False
        self._active: RequestIdentity | None = None

    def emit(
        self,
        kind: EventKind,
        *,
        request: RequestIdentity | None = None,
        status: object = None,
        failure: SafeFailure | None = None,
        at: datetime | None = None,
    ) -> None:
        category = http_category(status) if kind == "RESPONSE_COMPLETED" else None
        safe_status = status if type(status) is int and 100 <= status <= 599 else None
        event = DiagnosticEvent(
            sequence=self._sequence,
            at=self.clock() if at is None else at,
            kind=kind,
            stage=self.stage,
            request=request,
            http_status=safe_status,
            http_category=category,
            failure=failure,
        )
        self.accept(event)
        if self.send is not None:
            self.send(event)

    def accept(self, event: DiagnosticEvent) -> None:
        if event.sequence != self._sequence or (
            self._last_at is not None and event.at < self._last_at
        ):
            raise ValueError("diagnostic chronology is invalid")
        request = event.request
        outcome = None
        if request is not None:
            previous = self.requests.get(request.ordinal)
            if event.kind == "ADMITTED":
                if previous is not None or request.ordinal != len(self.requests) + 1:
                    raise ValueError("diagnostic admission is not unique")
                outcome = RequestOutcome(identity=request, admitted_at=event.at)
            else:
                if previous is None or previous.identity != request:
                    raise ValueError("diagnostic completion has no matching admission")
                if event.kind == "TRANSPORT_STARTED":
                    if previous.transport_started_at is not None:
                        raise ValueError("transport has already started")
                    outcome = previous.model_copy(update={"transport_started_at": event.at})
                else:
                    if (
                        previous.transport_started_at is None
                        or previous.response_completed_at is not None
                    ):
                        raise ValueError("response has no unique transport start")
                    outcome = previous.model_copy(
                        update={
                            "response_completed_at": event.at,
                            "http_status": event.http_status,
                            "http_category": event.http_category,
                        }
                    )
        # Reject malformed events without partially advancing the trusted reducer.
        self._sequence += 1
        self._last_at, self.stage = event.at, event.stage
        if request is not None and outcome is not None:
            self.requests[request.ordinal] = outcome
        if event.failure is not None and self.failure is None:
            self.failure = event.failure
        if len(self.events) < MAX_EVENTS - 1 or (
            event.kind == "FAILURE" and len(self.events) < MAX_EVENTS
        ):
            self.events.append(event)
        else:
            self._truncated = True

    def enter(self, stage: Stage) -> None:
        self.stage = stage
        self.emit("STAGE_STARTED")

    def admitted(self, provider: Provider, method: str, host: str, path: str) -> None:
        self._active = route_identity(provider, method, host, path, len(self.requests) + 1)
        self.emit("ADMITTED", request=self._active)

    def transport_started(self) -> None:
        if self._active is None:
            raise ValueError("transport diagnostics have no admission")
        self.emit("TRANSPORT_STARTED", request=self._active)

    def response_completed(self, status: object) -> None:
        if self._active is None:
            raise ValueError("response diagnostics have no admission")
        self.emit("RESPONSE_COMPLETED", request=self._active, status=status)

    def failed(self, error: Exception) -> SafeFailure:
        if self.failure is None:
            failure = safe_failure(error, self.stage)
            active = self.requests.get(self._active.ordinal) if self._active is not None else None
            if (
                active is not None
                and active.http_category == "INVALID_STATUS"
                and failure.category == "TRANSPORT"
            ):
                failure = failure.model_copy(
                    update={"category": "RESPONSE_CONTRACT", "code": "SOURCE_RESPONSE_INVALID"}
                )
            self.stage = failure.stage
            now = self.clock()
            if self._last_at is not None and now < self._last_at:
                # Preserve the actual failure without inventing a replacement time.
                self._clock_valid = False
                self.failure = failure
            else:
                self.emit("FAILURE", failure=failure, at=now)
        assert self.failure is not None
        return self.failure

    def report(self) -> DiagnosticReport:
        return DiagnosticReport(
            stage=self.stage,
            failure=self.failure,
            requests=tuple(self.requests.values()),
            events=tuple(self.events),
            history_truncated=self._truncated,
            chronology_complete=self._clock_valid,
            worker_terminal_received=self.worker_terminal_received,
        )
