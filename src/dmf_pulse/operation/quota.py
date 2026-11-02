"""Separately qualified, single-attempt, zero-credit Odds account observation.

No constructor, model or import reads credentials or starts transport. A trusted
standing-policy admission callback and send guard are required at execution.
Quota counters alone never establish an account period or a reset.
"""

from __future__ import annotations

import hashlib
import math
import os
import ssl
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, field_serializer, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.credentials.providers import AutomaticOddsCredentialProvider
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import (
    CapabilityValue,
    RightsCapability,
    RightsProfile,
    RightsProfileStatus,
)
from dmf_pulse.ingestion.odds.client import (
    HttpClientOddsTransport,
    OddsHttpRequest,
    OddsHttpResponse,
)
from dmf_pulse.ingestion.odds.credentials import CredentialProvider, validate_runtime_credential
from dmf_pulse.operation.models import Metadata, MetadataTime, OperationError, Ref, Sha

QUOTA_PROFILE_ID = "the_odds_api_private_operator_quota_v1"
QUOTA_GEOGRAPHY = "private DMF Pulse analytical use from Italy and the United Kingdom (IT, GB)"
QUOTA_HOST = "api.the-odds-api.com"
QUOTA_PATH = "/v4/sports/"
QUOTA_TARGET = "https://api.the-odds-api.com/v4/sports/"
MAX_COUNTER = 2**63 - 1
Count = Annotated[int, Field(ge=0, le=MAX_COUNTER)]
Headers = Mapping[str, str] | Sequence[tuple[str, str]]
_ALLOW = frozenset(
    {
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.PRIVATE_INTERNAL_USE,
        RightsCapability.DERIVED_STORAGE,
    }
)


def _utc(value: datetime) -> datetime:
    return MetadataTime(checked_at=value).checked_at


def _profile_sha(profile: RightsProfile) -> str:
    value = profile.model_dump(mode="json", exclude={"capabilities"})
    value["capabilities"] = {key.value: item.value for key, item in profile.capabilities.items()}
    return canonical_sha256(value)


class QuotaRoute(Metadata):
    """This route cannot be substituted for, or merged into, charged EPL scope."""

    provider: Literal["ODDS"] = "ODDS"
    method: Literal["GET"] = "GET"
    scheme: Literal["https"] = "https"
    host: Literal["api.the-odds-api.com"] = "api.the-odds-api.com"
    path: Literal["/v4/sports/"] = "/v4/sports/"
    maximum_calls: Literal[1] = 1
    expected_credit_cost: Literal[0] = 0
    automatic_retries: Literal[0] = 0

    @field_validator("maximum_calls", "expected_credit_cost", "automatic_retries", mode="before")
    @classmethod
    def exact_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("quota route limits require exact integers")
        return value


class QuotaSourceQualification(Metadata):
    """Reviewed source facts; the model itself grants no execution authority."""

    schema_version: Literal["odds-quota-source-qualification-v1"] = (
        "odds-quota-source-qualification-v1"
    )
    qualification_id: Ref
    account_ref: Ref
    route: QuotaRoute = QuotaRoute()
    profile: RightsProfile
    profile_sha256: Sha
    purpose: Literal["PRIVATE_OPERATOR_FPL_RECOMMENDATIONS"] = (
        "PRIVATE_OPERATOR_FPL_RECOMMENDATIONS"
    )
    subpurpose: Literal["QUOTA_VERIFICATION"] = "QUOTA_VERIFICATION"
    permission_basis: Literal["SUPPLIER_WRITTEN_PERMISSION", "VENDOR_TERMS_AND_ACCOUNT"]
    permission_provenance: Literal["OWNER_ATTESTED_SUPPLIER_PERMISSION"] = (
        "OWNER_ATTESTED_SUPPLIER_PERMISSION"
    )
    supplier_issuer_authenticated: Literal[False] = False
    permission_evidence_sha256: Sha
    account_review_sha256: Sha
    independent_review_sha256: Sha
    decision_ref: Ref
    operator_country: Literal["IT", "GB"]
    qualified_at: datetime
    valid_until: datetime | None = None
    control_metadata_retention_approved: Literal[True]
    source_body_retention: Literal["DENIED_TRANSIENT_ONLY"] = "DENIED_TRANSIENT_ONLY"

    @field_validator(
        "supplier_issuer_authenticated", "control_metadata_retention_approved", mode="before"
    )
    @classmethod
    def exact_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("quota provenance requires explicit booleans")
        return value

    @field_serializer("profile", when_used="json")
    def serializable_profile(self, profile: RightsProfile) -> dict[str, object]:
        value = profile.model_dump(mode="json", exclude={"capabilities"})
        value["capabilities"] = {
            key.value: item.value for key, item in profile.capabilities.items()
        }
        return value

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        profile = self.profile
        if not (
            profile.rights_profile_id == QUOTA_PROFILE_ID
            and profile.provider_key == "the_odds_api"
            and profile.profile_version == "1.0.0"
            and profile.status is RightsProfileStatus.HUMAN_APPROVED
            and profile.approved_purpose == self.purpose
            and profile.geography_scope == QUOTA_GEOGRAPHY
            and profile.account_scope == f"qualified private Odds account: {self.account_ref}"
            and profile.terms_source == "https://the-odds-api.com/terms-and-conditions.html"
            and profile.retention_seconds == 0
            and profile.termination_deletion_required
            and not profile.unresolved_rights
            and not profile.attribution_required
            and profile.attribution_text is None
            and all(
                profile.capabilities[capability]
                is (CapabilityValue.ALLOW if capability in _ALLOW else CapabilityValue.DENY)
                for capability in RightsCapability
            )
            and self.profile_sha256 == _profile_sha(profile)
            and profile.approved_at <= profile.checked_at <= self.qualified_at
            and (self.valid_until is None or self.qualified_at < self.valid_until)
        ):
            raise ValueError("quota source qualification differs from its exact reviewed scope")
        return self

    def require_current(self, now: datetime) -> None:
        checked = _utc(now)
        if checked < self.qualified_at or (
            self.valid_until is not None and checked >= self.valid_until
        ):
            raise OperationError("QUOTA_SOURCE_QUALIFICATION_EXPIRED")


class VerifiedQuotaPeriod(Metadata):
    """An already verified account/ledger anchor, never derived from allowance."""

    period_started_at: datetime
    resets_at: datetime
    evidence_sha256: Sha
    provenance: Literal["VERIFIED_ACCOUNT_AND_CANONICAL_LEDGER_ANCHOR"] = (
        "VERIFIED_ACCOUNT_AND_CANONICAL_LEDGER_ANCHOR"
    )

    @model_validator(mode="after")
    def nonempty_period(self) -> Self:
        if self.period_started_at >= self.resets_at:
            raise ValueError("verified quota period is empty")
        return self


class QuotaHeaderValues(Metadata):
    remaining_credits: Count
    used_credits: Count
    last_request_cost: Count

    @model_validator(mode="after")
    def consistent_counters(self) -> Self:
        if (
            self.last_request_cost > self.used_credits
            or self.remaining_credits + self.used_credits > MAX_COUNTER
        ):
            raise ValueError("quota counters are inconsistent")
        return self


class QuotaObservation(QuotaHeaderValues):
    schema_version: Literal["odds-zero-cost-quota-observation-v1"] = (
        "odds-zero-cost-quota-observation-v1"
    )
    source: Literal["PROVIDER_RESPONSE_HEADERS_ZERO_COST_SPORTS"] = (
        "PROVIDER_RESPONSE_HEADERS_ZERO_COST_SPORTS"
    )
    account_ref: Ref
    qualification_sha256: Sha
    request_fingerprint_sha256: Sha
    request_identity_sha256: Sha
    request_started_at: datetime
    received_at: datetime
    provider_date_at: datetime | None = None
    provider_request_id_sha256: Sha | None = None
    transport_call_count: Literal[1] = 1
    automatic_retries: Literal[0] = 0
    source_body_retained: Literal[False] = False
    period_status: Literal["UNKNOWN", "VERIFIED_ANCHOR"] = "UNKNOWN"
    period_anchor: VerifiedQuotaPeriod | None = None

    @field_validator("transport_call_count", "automatic_retries", mode="before")
    @classmethod
    def exact_count(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("quota observation counts require exact integers")
        return value

    @field_validator("source_body_retained", mode="before")
    @classmethod
    def exact_body_flag(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("quota body retention requires an explicit boolean")
        return value

    @model_validator(mode="after")
    def truthful_observation(self) -> Self:
        if self.last_request_cost != 0 or self.request_started_at > self.received_at:
            raise ValueError("zero-cost quota observation is invalid")
        if (self.period_status == "VERIFIED_ANCHOR") != (self.period_anchor is not None):
            raise ValueError("quota period requires a separate verified anchor")
        if self.period_anchor is not None and not (
            self.period_anchor.period_started_at <= self.received_at < self.period_anchor.resets_at
        ):
            raise ValueError("observation lies outside the verified quota period")
        if self.request_fingerprint_sha256 != build_quota_request().request_fingerprint or (
            self.request_identity_sha256
            != canonical_sha256(
                {
                    "request_fingerprint": self.request_fingerprint_sha256,
                    "account_ref": self.account_ref,
                    "qualification_sha256": self.qualification_sha256,
                    "request_started_at": self.request_started_at.isoformat(),
                }
            )
        ):
            raise ValueError("quota observation request identity differs")
        if (
            self.provider_date_at is not None
            and abs((self.provider_date_at - self.received_at).total_seconds()) > 120
        ):
            raise ValueError("quota provider date is inconsistent")
        return self

    def require_fresh(self, now: datetime, *, maximum_age_seconds: int = 60) -> None:
        checked = _utc(now)
        if type(maximum_age_seconds) is not int or not 1 <= maximum_age_seconds <= 3600:
            raise OperationError("QUOTA_FRESHNESS_BOUND_INVALID")
        if (
            not self.received_at
            <= checked
            <= self.received_at + timedelta(seconds=maximum_age_seconds)
        ):
            raise OperationError("QUOTA_OBSERVATION_STALE")


class QuotaFailureEvidence(Metadata):
    account_ref: Ref | None = None
    qualification_sha256: Sha | None = None
    request_fingerprint_sha256: Sha
    transport_call_count: Literal[0, 1]
    request_started_at: datetime | None = None
    received_at: datetime | None = None
    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    observed_headers: QuotaHeaderValues | None = None
    automatic_retries: Literal[0] = 0
    source_body_retained: Literal[False] = False

    @field_validator("transport_call_count", "automatic_retries", mode="before")
    @classmethod
    def exact_count(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("quota attempt counts require exact integers")
        return value


class QuotaLookupError(OperationError):
    def __init__(self, code: str, evidence: QuotaFailureEvidence) -> None:
        super().__init__(code)
        self.evidence = evidence


class QuotaAdmission(Protocol):
    """Raise on denial; only a None result permits credential resolution."""

    def __call__(
        self, qualification: QuotaSourceQualification, *, checked_at: datetime
    ) -> object: ...


class QuotaSendGuard(Protocol):
    def preflight_send(
        self, provider: Literal["ODDS"], method: str, host: str, path: str
    ) -> None: ...
    def before_send(self, provider: Literal["ODDS"], method: str, host: str, path: str) -> None: ...
    def before_transport(self) -> None: ...


class QuotaTransport(Protocol):
    def send(self, request: OddsHttpRequest, credential: str) -> OddsHttpResponse: ...


def build_quota_request() -> OddsHttpRequest:
    return OddsHttpRequest("GET", "https", QUOTA_HOST, QUOTA_PATH, (), 10.0, 20.0, 30.0)


def _selected_headers(headers: Headers) -> dict[str, str]:
    pairs = list(headers.items()) if isinstance(headers, Mapping) else list(headers)
    if len(pairs) > 100:
        raise OperationError("QUOTA_HEADERS_INVALID")
    selected: dict[str, str] = {}
    allowed = {"x-requests-remaining", "x-requests-used", "x-requests-last", "date", "x-request-id"}
    for pair in pairs:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise OperationError("QUOTA_HEADERS_INVALID")
        name, value = pair
        if type(name) is not str:
            raise OperationError("QUOTA_HEADERS_INVALID")
        key = name.casefold()
        if key not in allowed:
            continue
        if (
            key in selected
            or type(value) is not str
            or len(value) > 1024
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise OperationError("QUOTA_HEADERS_INVALID")
        selected[key] = value
    return selected


def parse_quota_header_values(
    headers: Headers,
    *,
    expected_last_cost: int | None = None,
    maximum_last_cost: int | None = None,
) -> QuotaHeaderValues:
    """Strict ASCII integers; duplicate case aliases never overwrite evidence."""
    import re

    if any(
        value is not None and (type(value) is not int or not 0 <= value <= MAX_COUNTER)
        for value in (expected_last_cost, maximum_last_cost)
    ) or (
        expected_last_cost is not None
        and maximum_last_cost is not None
        and expected_last_cost > maximum_last_cost
    ):
        raise OperationError("QUOTA_COST_BOUND_INVALID")
    selected = _selected_headers(headers)
    names = ("x-requests-remaining", "x-requests-used", "x-requests-last")
    if any(
        name not in selected or re.fullmatch(r"0|[1-9][0-9]{0,18}", selected[name]) is None
        for name in names
    ):
        raise OperationError("QUOTA_HEADERS_INVALID")
    try:
        values = QuotaHeaderValues(
            **dict(
                zip(
                    ("remaining_credits", "used_credits", "last_request_cost"),
                    (int(selected[name]) for name in names),
                    strict=True,
                )
            )
        )
    except ValueError:
        raise OperationError("QUOTA_HEADERS_INCONSISTENT") from None
    if expected_last_cost is not None and values.last_request_cost != expected_last_cost:
        raise OperationError("QUOTA_UNEXPECTED_LAST_COST")
    if maximum_last_cost is not None and values.last_request_cost > maximum_last_cost:
        raise OperationError("QUOTA_LAST_COST_LIMIT_EXCEEDED")
    return values


def parse_zero_cost_quota_headers(
    headers: Headers,
    *,
    account_ref: str,
    qualification_sha256: str,
    request_started_at: datetime,
    received_at: datetime,
    checked_at: datetime,
    maximum_age_seconds: int = 60,
    period_anchor: VerifiedQuotaPeriod | None = None,
) -> QuotaObservation:
    counts = parse_quota_header_values(headers)
    if counts.last_request_cost != 0:
        raise OperationError("QUOTA_LOOKUP_UNEXPECTED_COST")
    selected = _selected_headers(headers)
    started, received = _utc(request_started_at), _utc(received_at)
    provider_date: datetime | None = None
    if "date" in selected:
        try:
            provider_date = _utc(parsedate_to_datetime(selected["date"]))
        except (TypeError, ValueError, OverflowError):
            raise OperationError("QUOTA_PROVIDER_DATE_INVALID") from None
        if abs((provider_date - received).total_seconds()) > 120:
            raise OperationError("QUOTA_PROVIDER_DATE_STALE")
    request = build_quota_request()
    provider_id = selected.get("x-request-id")
    value = QuotaObservation(
        **counts.model_dump(),
        account_ref=account_ref,
        qualification_sha256=qualification_sha256,
        request_fingerprint_sha256=request.request_fingerprint,
        request_identity_sha256=canonical_sha256(
            {
                "request_fingerprint": request.request_fingerprint,
                "account_ref": account_ref,
                "qualification_sha256": qualification_sha256,
                "request_started_at": started.isoformat(),
            }
        ),
        request_started_at=started,
        received_at=received,
        provider_date_at=provider_date,
        provider_request_id_sha256=hashlib.sha256(provider_id.encode()).hexdigest()
        if provider_id
        else None,
        period_status="VERIFIED_ANCHOR" if period_anchor is not None else "UNKNOWN",
        period_anchor=period_anchor,
    )
    value.require_fresh(checked_at, maximum_age_seconds=maximum_age_seconds)
    return value


class NativeQuotaTransport(HttpClientOddsTransport):
    """Reuse the accepted TLS/deadline/socket implementation, with a new exact route.

    The inherited charged-route sender remains unchanged. The catalog body is
    neither read nor retained: only status and selected quota headers are used.
    """

    def _unsafe_send(self, request: OddsHttpRequest, credential: str) -> OddsHttpResponse:
        if (
            request.method,
            request.scheme,
            request.host,
            request.path,
            request.safe_parameters,
        ) != (
            "GET",
            "https",
            QUOTA_HOST,
            QUOTA_PATH,
            (),
        ) or any(
            type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= bound
            for value, bound in (
                (request.connect_timeout_seconds, 10),
                (request.read_timeout_seconds, 20),
                (request.total_timeout_seconds, 30),
            )
        ):
            raise IngestionError(
                "CONFIGURATION_INVALID", "quota route differs from qualified source"
            )
        credential = validate_runtime_credential(credential)
        target = QUOTA_PATH + "?" + urllib.parse.urlencode((("apiKey", credential),))
        context = self._ssl_context_factory()
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise IngestionError("TLS_ERROR", "quota source TLS validation is unavailable")
        started = self._monotonic()
        timeout, _ = self._connect_bound(request, started_at=started)
        connection = self._connection_factory(QUOTA_HOST, timeout, context)
        try:
            configure = getattr(connection, "configure_connect_deadline", None)
            if callable(configure):
                configure(lambda: self._connect_bound(request, started_at=started)[0])
            connection.connect()
            self._install_deadline_socket(connection, request, started_at=started)
            self._apply_read_bound(connection, request, started_at=started)
            connection.request(
                "GET",
                target,
                body=None,
                headers={
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                    "User-Agent": "dmf-pulse-private/0.2.0",
                },
            )
            self._apply_read_bound(connection, request, started_at=started)
            response = connection.getresponse()
            self._remaining(request, started_at=started)
            pairs = response.getheaders()
            selected = _selected_headers(pairs)
            content_types = [value for name, value in pairs if name.casefold() == "content-type"]
            if len(content_types) != 1 or len(content_types[0]) > 200:
                raise IngestionError("CONTENT_TYPE_INVALID", "quota source content type is invalid")
            return OddsHttpResponse(
                response.status,
                content_types[0],
                selected,
                b"",
                "PRESENT" if any(name.casefold() == "location" for name, _ in pairs) else None,
            )
        finally:
            connection.close()


class _StoredOddsCredentialProvider:
    def __repr__(self) -> str:
        return "StoredOddsCredentialProvider(<protected-existing-reference>)"

    def get_credential(self) -> str:
        # Read only the systemd directory identifier here, never an environment
        # key value. Windows uses the existing Odds vault slot without fallback.
        environment = {"DMF_ODDS_CREDENTIAL_SOURCE": "auto"}
        directory = os.environ.get("CREDENTIALS_DIRECTORY")
        if directory is not None:
            environment["CREDENTIALS_DIRECTORY"] = directory
        return AutomaticOddsCredentialProvider(environment=environment).get_credential()


@dataclass(frozen=True, slots=True)
class _Outcome:
    observation: QuotaObservation | None
    code: str | None
    evidence: QuotaFailureEvidence


def _admit(
    qualification: QuotaSourceQualification,
    admission: QuotaAdmission,
    guard: QuotaSendGuard,
    clock: Callable[[], datetime],
) -> str | None:
    try:
        checked = _utc(clock())
        QuotaSourceQualification.model_validate(qualification).require_current(checked)
        if admission(qualification, checked_at=checked) is not None:
            return "QUOTA_ADMISSION_REQUIRED"
        guard.preflight_send("ODDS", "GET", QUOTA_HOST, QUOTA_PATH)
        qualification.require_current(_utc(clock()))
    except Exception:
        return "QUOTA_ADMISSION_DENIED"
    return None


def _exchange(
    qualification: QuotaSourceQualification,
    provider: CredentialProvider,
    transport: QuotaTransport,
    guard: QuotaSendGuard,
    clock: Callable[[], datetime],
    period: VerifiedQuotaPeriod | None,
    maximum_age_seconds: int,
) -> _Outcome:
    request = build_quota_request()
    evidence = QuotaFailureEvidence(
        account_ref=qualification.account_ref,
        qualification_sha256=qualification.semantic_sha256,
        request_fingerprint_sha256=request.request_fingerprint,
        transport_call_count=0,
    )
    try:
        credential = validate_runtime_credential(provider.get_credential())
    except Exception:
        return _Outcome(None, "QUOTA_CREDENTIAL_UNAVAILABLE", evidence)
    try:
        qualification.require_current(_utc(clock()))
        guard.before_send("ODDS", "GET", QUOTA_HOST, QUOTA_PATH)
        guard.before_transport()
        started = _utc(clock())
        evidence = evidence.model_copy(
            update={"request_started_at": started, "transport_call_count": 1}
        )
        try:
            response = transport.send(request, credential)
        except Exception:
            return _Outcome(None, "QUOTA_SOURCE_UNAVAILABLE", evidence)
        finally:
            del credential
        received = _utc(clock())
        evidence = evidence.model_copy(update={"received_at": received})
        if type(response.status_code) is int and 100 <= response.status_code <= 599:
            evidence = evidence.model_copy(update={"http_status": response.status_code})
        try:
            counts = parse_quota_header_values(response.headers)
        except (OperationError, ValueError):
            counts = None
        if counts is not None:
            evidence = evidence.model_copy(update={"observed_headers": counts})
        if response.redirect_location is not None or 300 <= response.status_code < 400:
            return _Outcome(None, "QUOTA_REDIRECT_BLOCKED", evidence)
        if response.status_code != 200:
            return _Outcome(None, "QUOTA_HTTP_REJECTED", evidence)
        media_type = response.content_type.partition(";")[0].strip().casefold()
        if media_type != "application/json" and not media_type.endswith("+json"):
            return _Outcome(None, "QUOTA_CONTENT_TYPE_INVALID", evidence)
        try:
            observation = parse_zero_cost_quota_headers(
                response.headers,
                account_ref=qualification.account_ref,
                qualification_sha256=qualification.semantic_sha256,
                request_started_at=started,
                received_at=received,
                checked_at=_utc(clock()),
                maximum_age_seconds=maximum_age_seconds,
                period_anchor=period,
            )
        except OperationError as error:
            return _Outcome(None, error.code, evidence)
        except ValueError:
            return _Outcome(None, "QUOTA_RESPONSE_INVALID", evidence)
        return _Outcome(observation, None, evidence)
    except Exception:
        return _Outcome(None, "QUOTA_ADMISSION_OR_CLOCK_INVALID", evidence)


class QuotaClient:
    """One separately admitted source attempt; no retries or caller-supplied URL."""

    def __init__(
        self,
        *,
        guard: QuotaSendGuard,
        credential_provider: CredentialProvider | None = None,
        transport: QuotaTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._guard = guard
        self._provider = (
            credential_provider
            if credential_provider is not None
            else _StoredOddsCredentialProvider()
        )
        self._transport = transport if transport is not None else NativeQuotaTransport()
        self._clock = clock
        self._attempted = False
        self._attempt_lock = Lock()

    def __repr__(self) -> str:
        return "QuotaClient(<separately-qualified-zero-credit-source>)"

    def fetch(
        self,
        qualification: QuotaSourceQualification,
        *,
        admission: QuotaAdmission,
        period_anchor: VerifiedQuotaPeriod | None = None,
        maximum_age_seconds: int = 60,
    ) -> QuotaObservation:
        evidence = QuotaFailureEvidence(
            request_fingerprint_sha256=build_quota_request().request_fingerprint,
            transport_call_count=0,
        )
        with self._attempt_lock:
            if self._attempted:
                raise QuotaLookupError("QUOTA_LOOKUP_ALREADY_ATTEMPTED", evidence)
            self._attempted = True
        if not isinstance(qualification, QuotaSourceQualification):
            raise QuotaLookupError("QUOTA_SOURCE_QUALIFICATION_REQUIRED", evidence)
        if type(maximum_age_seconds) is not int or not 1 <= maximum_age_seconds <= 3600:
            raise QuotaLookupError("QUOTA_FRESHNESS_BOUND_INVALID", evidence)
        denied = _admit(qualification, admission, self._guard, self._clock)
        if denied is not None:
            raise QuotaLookupError(denied, evidence) from None
        outcome = _exchange(
            qualification,
            self._provider,
            self._transport,
            self._guard,
            self._clock,
            period_anchor,
            maximum_age_seconds,
        )
        if outcome.code is not None:
            raise QuotaLookupError(outcome.code, outcome.evidence) from None
        if outcome.observation is None:
            raise QuotaLookupError("QUOTA_RESPONSE_INVALID", outcome.evidence)
        return outcome.observation
