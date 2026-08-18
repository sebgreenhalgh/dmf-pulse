"""Credential-isolated, quota-gated HTTPS client for The Odds API v4."""

from __future__ import annotations

import hashlib
import http.client
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal, Protocol

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsCapability, RightsProfile
from dmf_pulse.ingestion.odds.config import OddsProviderConfig, load_provider_config
from dmf_pulse.ingestion.odds.credentials import (
    CredentialProvider,
    StaticCredentialProvider,
    UnavailableCredentialProvider,
    validate_runtime_credential,
)
from dmf_pulse.ingestion.odds.models import ProviderFailureCode, QuotaSource, QuotaState
from dmf_pulse.ingestion.rights import require_rights

__all__ = [
    "CredentialProvider",
    "OddsClient",
    "OddsFetchFailure",
    "OddsFetchResult",
    "OddsHttpRequest",
    "OddsHttpResponse",
    "OddsRetrievalAttempt",
    "OddsTransport",
    "StaticCredentialProvider",
    "UnavailableCredentialProvider",
    "UrllibOddsTransport",
    "build_request",
    "parse_quota_headers",
]


@dataclass(frozen=True, slots=True)
class OddsHttpRequest:
    method: str
    scheme: str
    host: str
    path: str
    safe_parameters: tuple[tuple[str, str], ...]
    credential: str = field(repr=False, compare=False)
    connect_timeout_seconds: float = 10
    read_timeout_seconds: float = 20
    total_timeout_seconds: float = 30

    @property
    def sanitized_target(self) -> str:
        query = urllib.parse.urlencode(self.safe_parameters)
        return f"{self.scheme}://{self.host}{self.path}?{query}"

    @property
    def request_fingerprint(self) -> str:
        return canonical_sha256(
            {
                "credential_present": True,
                "host": self.host,
                "method": self.method,
                "parameters": self.safe_parameters,
                "path": self.path,
                "scheme": self.scheme,
            }
        )


@dataclass(frozen=True, slots=True)
class OddsHttpResponse:
    status_code: int
    content_type: str
    headers: Mapping[str, str]
    body: bytes
    redirect_location: str | None = None


@dataclass(frozen=True, slots=True)
class OddsFetchResult:
    body: bytes
    quota: QuotaState
    request_fingerprint: str
    sanitized_target: str
    transport_call_count: int
    provider_request_id_sha256: str | None
    attempts: tuple[OddsRetrievalAttempt, ...]


@dataclass(frozen=True, slots=True)
class OddsRetrievalAttempt:
    """Secret-free evidence for exactly one invoked transport attempt."""

    attempt_number: int
    request_started_at: datetime
    received_at: datetime
    request_fingerprint: str
    sanitized_target: str
    http_status: int | None
    content_type: str | None
    body_sha256: str | None
    body_size: int | None
    body_capture_state: Literal["ABSENT", "COMPLETE", "TRUNCATED"]
    captured_prefix_sha256: str | None
    captured_prefix_size: int | None
    quota_header_state: Literal["ABSENT", "INVALID", "VALID"]
    quota: QuotaState | None
    provider_request_id_sha256: str | None
    failure_code: ProviderFailureCode | None
    requested_delay_seconds: int | None
    applied_delay_seconds: int | None
    attempt_outcome: Literal["SUCCESS", "RETRY_SCHEDULED", "TERMINAL_FAILURE"]


class OddsFetchFailure(IngestionError):
    """Terminal fetch failure carrying only bounded, secret-free attempt metadata."""

    def __init__(self, error: IngestionError, attempts: tuple[OddsRetrievalAttempt, ...]) -> None:
        super().__init__(
            error.code,
            error.message,
            retryable=error.retryable,
            details={"transport_call_count": len(attempts)},
        )
        self.attempts = attempts


class OddsTransport(Protocol):
    def send(self, request: OddsHttpRequest) -> OddsHttpResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


class UrllibOddsTransport:
    """Minimal TLS-validating transport; redirects are disabled."""

    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic

    def _read_body(self, response: object, request: OddsHttpRequest, *, started_at: float) -> bytes:
        limit = load_provider_config().max_response_bytes
        chunks: list[bytes] = []
        size = 0
        raw_socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        try:
            while size <= limit:
                remaining = request.total_timeout_seconds - (self._monotonic() - started_at)
                if remaining <= 0:
                    raise IngestionError(
                        "TOTAL_TIMEOUT", "odds provider total deadline expired", retryable=True
                    )
                if raw_socket is not None and hasattr(raw_socket, "settimeout"):
                    raw_socket.settimeout(min(request.read_timeout_seconds, remaining))
                read = getattr(response, "read", None)
                if not callable(read):
                    raise IngestionError("SOURCE_UNAVAILABLE", "odds response is invalid")
                chunk = read(min(64 * 1024, limit + 1 - size))
                if not isinstance(chunk, bytes):
                    raise IngestionError("SOURCE_UNAVAILABLE", "odds response is invalid")
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
        except IngestionError:
            raise
        except TimeoutError:
            raise IngestionError(
                "READ_TIMEOUT", "odds provider read timed out", retryable=True
            ) from None
        except ssl.SSLError:
            raise IngestionError("TLS_ERROR", "odds provider TLS validation failed") from None
        except (OSError, http.client.HTTPException):
            raise IngestionError(
                "SOURCE_UNAVAILABLE", "odds provider is unavailable", retryable=True
            ) from None
        return b"".join(chunks)

    @staticmethod
    def _safe_headers(headers: object) -> dict[str, str]:
        getter = getattr(headers, "get", None)
        if not callable(getter):
            return {}
        allowed = (
            "content-type",
            "x-requests-remaining",
            "x-requests-used",
            "x-requests-last",
            "x-request-id",
            "retry-after",
        )
        return {name: str(value) for name in allowed if (value := getter(name)) is not None}

    def send(self, request: OddsHttpRequest) -> OddsHttpResponse:
        config = load_provider_config()
        _validate_request(request, config)
        full_parameters = (("apiKey", request.credential), *request.safe_parameters)
        url = f"https://{request.host}{request.path}?{urllib.parse.urlencode(full_parameters)}"
        opener = urllib.request.build_opener(_NoRedirect())
        outbound = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "dmf-pulse-private/0.2.0",
            },
            method="GET",
        )
        started_at = self._monotonic()
        try:
            with opener.open(outbound, timeout=request.connect_timeout_seconds) as response:
                headers = self._safe_headers(response.headers)
                return OddsHttpResponse(
                    status_code=response.status,
                    content_type=str(headers.get("content-type", "")),
                    headers=headers,
                    body=self._read_body(response, request, started_at=started_at),
                )
        except urllib.error.HTTPError as exc:
            headers = self._safe_headers(exc.headers)
            return OddsHttpResponse(
                status_code=exc.code,
                content_type=str(headers.get("content-type", "")),
                headers=headers,
                body=(
                    self._read_body(exc, request, started_at=started_at)
                    if exc.fp is not None
                    else b""
                ),
                redirect_location=str(headers.get("location")) if "location" in headers else None,
            )
        except TimeoutError:
            raise IngestionError(
                "CONNECT_TIMEOUT", "odds provider connection timed out", retryable=True
            ) from None
        except ssl.SSLError:
            raise IngestionError("TLS_ERROR", "odds provider TLS validation failed") from None
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):
                raise IngestionError("TLS_ERROR", "odds provider TLS validation failed") from None
            if isinstance(reason, TimeoutError):
                raise IngestionError(
                    "CONNECT_TIMEOUT", "odds provider connection timed out", retryable=True
                ) from None
            raise IngestionError(
                "SOURCE_UNAVAILABLE", "odds provider is unavailable", retryable=True
            ) from None
        except (OSError, http.client.HTTPException):
            raise IngestionError(
                "SOURCE_UNAVAILABLE", "odds provider is unavailable", retryable=True
            ) from None


def _safe_parameters(
    config: OddsProviderConfig,
    commence_from: datetime | None,
    commence_to: datetime | None,
) -> tuple[tuple[str, str], ...]:
    parameters: list[tuple[str, str]] = [
        ("regions", config.regions[0]),
        ("markets", config.markets[0]),
        ("oddsFormat", config.odds_format),
        ("dateFormat", config.date_format),
    ]
    for name, value in (("commenceTimeFrom", commence_from), ("commenceTimeTo", commence_to)):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise IngestionError("CONFIGURATION_INVALID", "commence filter must be UTC-aware")
            parameters.append((name, value.astimezone(UTC).isoformat().replace("+00:00", "Z")))
    if commence_from is not None and commence_to is not None and commence_from >= commence_to:
        raise IngestionError("CONFIGURATION_INVALID", "commence filter range is invalid")
    return tuple(parameters)


def build_request(
    credential: str,
    *,
    commence_from: datetime | None = None,
    commence_to: datetime | None = None,
) -> OddsHttpRequest:
    config = load_provider_config()
    credential = validate_runtime_credential(credential)
    return OddsHttpRequest(
        method="GET",
        scheme=config.scheme,
        host=config.host,
        path=config.path,
        safe_parameters=_safe_parameters(config, commence_from, commence_to),
        credential=credential,
        connect_timeout_seconds=float(config.timeouts_seconds.connect),
        read_timeout_seconds=float(config.timeouts_seconds.read),
        total_timeout_seconds=float(config.timeouts_seconds.total),
    )


def _validate_request(request: OddsHttpRequest, config: OddsProviderConfig) -> None:
    approved_names = {
        "regions",
        "markets",
        "oddsFormat",
        "dateFormat",
        "commenceTimeFrom",
        "commenceTimeTo",
    }
    if (
        request.method != "GET"
        or request.scheme != "https"
        or request.host != config.host
        or request.path != config.path
        or len({name for name, _ in request.safe_parameters}) != len(request.safe_parameters)
        or any(name not in approved_names for name, _ in request.safe_parameters)
    ):
        raise IngestionError("INTERNAL_INVARIANT", "odds request is not allowlisted")
    if request.safe_parameters[:4] != (
        ("regions", "uk"),
        ("markets", "h2h"),
        ("oddsFormat", "decimal"),
        ("dateFormat", "iso"),
    ):
        raise IngestionError("INTERNAL_INVARIANT", "odds request parameters drifted")


def parse_quota_headers(headers: Mapping[str, str], observed_at: datetime) -> QuotaState:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise IngestionError("SOURCE_UNAVAILABLE", "provider quota timestamp is invalid")
    try:
        values = {
            "remaining": int(headers["x-requests-remaining"]),
            "used": int(headers["x-requests-used"]),
            "last_cost": int(headers["x-requests-last"]),
        }
        return QuotaState(
            **values,
            observed_at=observed_at.astimezone(UTC),
            source=QuotaSource.RESPONSE_HEADERS,
        )
    except (KeyError, TypeError, ValueError):
        raise IngestionError("SOURCE_UNAVAILABLE", "provider quota headers are invalid") from None


def _provider_failure_code(code: str) -> ProviderFailureCode:
    try:
        return ProviderFailureCode(code)
    except ValueError:
        return ProviderFailureCode.SOURCE_UNAVAILABLE


def _sanitized_transport_error(error: IngestionError) -> IngestionError:
    code = _provider_failure_code(error.code)
    messages = {
        ProviderFailureCode.CONNECT_TIMEOUT: "odds provider connection timed out",
        ProviderFailureCode.READ_TIMEOUT: "odds provider read timed out",
        ProviderFailureCode.TOTAL_TIMEOUT: "odds provider total deadline expired",
        ProviderFailureCode.TLS_ERROR: "odds provider TLS validation failed",
        ProviderFailureCode.CANCELLED: "odds provider request was cancelled",
        ProviderFailureCode.SOURCE_UNAVAILABLE: "odds provider is unavailable",
    }
    retryable = code in {
        ProviderFailureCode.CONNECT_TIMEOUT,
        ProviderFailureCode.READ_TIMEOUT,
        ProviderFailureCode.TOTAL_TIMEOUT,
        ProviderFailureCode.SOURCE_UNAVAILABLE,
    }
    return IngestionError(
        code.value,
        messages.get(code, "odds provider retrieval failed safely"),
        retryable=retryable,
    )


def _resolve_credential(provider: CredentialProvider) -> tuple[str | None, bool]:
    """Return only a credential value or a secret-safe resolution-failure flag."""

    try:
        value = provider.get_credential()
    except Exception:
        return None, True
    return value, False


def _construct_transport(factory: Callable[[], OddsTransport]) -> tuple[OddsTransport | None, bool]:
    """Construct a transport without retaining an unsafe factory exception."""

    try:
        return factory(), False
    except Exception:
        return None, True


def _send_transport(
    transport: OddsTransport, request: OddsHttpRequest
) -> tuple[OddsHttpResponse | None, IngestionError | None]:
    """Translate every transport exception without preserving its causal object."""

    try:
        return transport.send(request), None
    except IngestionError as exc:
        return None, _sanitized_transport_error(exc)
    except Exception:
        return None, IngestionError(
            "SOURCE_UNAVAILABLE", "odds provider is unavailable", retryable=True
        )


def _normalized_content_type(value: str) -> str | None:
    if len(value) > 200 or any(ord(character) < 32 for character in value):
        return None
    media_type = value.partition(";")[0].strip().casefold()
    return media_type or None


def _response_quota(
    response: OddsHttpResponse, observed_at: datetime
) -> tuple[QuotaState | None, Literal["ABSENT", "INVALID", "VALID"]]:
    normalized = {str(key).casefold(): value for key, value in response.headers.items()}
    required = {"x-requests-remaining", "x-requests-used", "x-requests-last"}
    present = required.intersection(normalized)
    if not present:
        return None, "ABSENT"
    if present != required:
        return None, "INVALID"
    try:
        return parse_quota_headers(normalized, observed_at), "VALID"
    except IngestionError:
        return None, "INVALID"


def _response_failure(
    response: OddsHttpResponse,
    *,
    media_type: str | None,
    quota: QuotaState | None,
) -> IngestionError | None:
    if response.redirect_location is not None or 300 <= response.status_code < 400:
        return IngestionError("REDIRECT_BLOCKED", "odds provider redirect was blocked")
    if response.status_code == 429:
        return IngestionError("HTTP_429", "odds provider rate limited the request", retryable=True)
    if 500 <= response.status_code < 600:
        return IngestionError(
            "HTTP_5XX",
            "odds provider returned a server error",
            retryable=response.status_code in {500, 502, 503, 504},
        )
    if 400 <= response.status_code < 500:
        return IngestionError("HTTP_4XX", "odds provider rejected the request")
    if response.status_code != 200:
        return IngestionError("SOURCE_UNAVAILABLE", "odds provider returned an invalid status")
    if media_type != "application/json" and not (media_type or "").endswith("+json"):
        return IngestionError("CONTENT_TYPE_INVALID", "odds provider did not return JSON")
    if len(response.body) > load_provider_config().max_response_bytes:
        return IngestionError("PAYLOAD_TOO_LARGE", "odds response exceeds the byte limit")
    if quota is None:
        return IngestionError("SOURCE_UNAVAILABLE", "provider quota headers are invalid")
    return None


def _retry_delay(response: OddsHttpResponse, config: OddsProviderConfig) -> tuple[int | None, int]:
    """Return safe requested/applied delta seconds for one 429 retry."""

    normalized = {str(key).casefold(): str(value) for key, value in response.headers.items()}
    raw = normalized.get("retry-after")
    requested: int | None = None
    if raw is not None and raw.isascii() and raw.isdecimal():
        try:
            requested = int(raw)
        except ValueError:  # pragma: no cover - guarded by isdecimal
            requested = None
    if requested is not None and 1 <= requested <= config.retry.maximum_retry_after_seconds:
        return requested, requested
    return requested, config.retry.default_delay_seconds


def _bounded_retry_request(
    request: OddsHttpRequest,
    *,
    deadline_started: float,
    observed_monotonic: float,
    minimum_elapsed_seconds: float,
    delay_seconds: int,
) -> tuple[OddsHttpRequest | None, float]:
    """Derive the next attempt's timeouts from the one total request budget."""

    if observed_monotonic < deadline_started:
        raise IngestionError("INTERNAL_INVARIANT", "odds client monotonic clock regressed")
    elapsed = max(observed_monotonic - deadline_started, minimum_elapsed_seconds)
    next_elapsed = elapsed + delay_seconds
    remaining = request.total_timeout_seconds - next_elapsed
    if remaining <= 0:
        return None, next_elapsed
    return (
        replace(
            request,
            connect_timeout_seconds=min(request.connect_timeout_seconds, remaining),
            read_timeout_seconds=min(request.read_timeout_seconds, remaining),
            total_timeout_seconds=remaining,
        ),
        next_elapsed,
    )


class OddsClient:
    """Apply config, rights, quota, and credential gates before transport."""

    def __init__(
        self,
        profile: RightsProfile,
        *,
        credential_provider: CredentialProvider | None = None,
        transport_factory: Callable[[], OddsTransport] = UrllibOddsTransport,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._profile = profile
        self._credential_provider = credential_provider or UnavailableCredentialProvider()
        self._transport_factory = transport_factory
        self._clock = clock
        self._sleeper = sleeper
        self._monotonic = monotonic
        self.transport_call_count = 0

    def fetch(
        self,
        *,
        quota: QuotaState | None = None,
        commence_from: datetime | None = None,
        commence_to: datetime | None = None,
    ) -> OddsFetchResult:
        config = load_provider_config()
        require_rights(self._profile, RightsCapability.AUTOMATED_ACCESS, checked_at=self._clock())
        if quota is not None and quota.remaining < config.request_cost:
            raise IngestionError(
                "QUOTA_EXHAUSTED",
                "provider quota is insufficient for the request",
                details={"transport_call_count": self.transport_call_count},
            )
        credential, credential_failed = _resolve_credential(self._credential_provider)
        if credential_failed or not isinstance(credential, str) or not credential:
            raise IngestionError(
                "CREDENTIAL_UNAVAILABLE",
                "approved runtime credential is unavailable",
                details={"transport_call_count": self.transport_call_count},
            )
        request = build_request(credential, commence_from=commence_from, commence_to=commence_to)
        transport, construction_failed = _construct_transport(self._transport_factory)
        if construction_failed or transport is None:
            raise IngestionError(
                "SOURCE_UNAVAILABLE",
                "odds provider transport is unavailable",
                retryable=True,
                details={"transport_call_count": self.transport_call_count},
            )
        last_error: IngestionError | None = None
        attempts: list[OddsRetrievalAttempt] = []
        deadline_started = self._monotonic()
        minimum_elapsed_seconds = 0.0
        attempt_request = request
        for attempt in range(1, config.retry.max_attempts + 1):
            if attempt > 1:
                refreshed_request, refreshed_elapsed = _bounded_retry_request(
                    request,
                    deadline_started=deadline_started,
                    observed_monotonic=self._monotonic(),
                    minimum_elapsed_seconds=minimum_elapsed_seconds,
                    delay_seconds=0,
                )
                if refreshed_request is None:
                    if last_error is None or not attempts:  # pragma: no cover - retry invariant
                        raise IngestionError(
                            "INTERNAL_INVARIANT", "odds retry deadline lacks prior evidence"
                        )
                    terminal_error = IngestionError(
                        last_error.code,
                        last_error.message,
                        retryable=False,
                    )
                    attempts[-1] = replace(
                        attempts[-1],
                        attempt_outcome="TERMINAL_FAILURE",
                    )
                    raise OddsFetchFailure(terminal_error, tuple(attempts)) from None
                attempt_request = refreshed_request
                minimum_elapsed_seconds = refreshed_elapsed
            started_at = self._clock()
            if started_at.tzinfo is None or started_at.utcoffset() is None:
                raise IngestionError(
                    "INTERNAL_INVARIANT", "odds client clock must be timezone-aware"
                )
            self.transport_call_count += 1
            response, safe_error = _send_transport(transport, attempt_request)
            transport_finished_monotonic = self._monotonic()
            if transport_finished_monotonic < deadline_started:
                raise IngestionError("INTERNAL_INVARIANT", "odds client monotonic clock regressed")
            total_deadline_expired = (
                max(
                    transport_finished_monotonic - deadline_started,
                    minimum_elapsed_seconds,
                )
                >= request.total_timeout_seconds
            )
            if safe_error is not None:
                if total_deadline_expired:
                    safe_error = IngestionError(
                        "TOTAL_TIMEOUT",
                        "odds provider total deadline expired",
                        retryable=False,
                    )
                finished_at = self._clock()
                if finished_at.tzinfo is None or finished_at.utcoffset() is None:
                    raise IngestionError(
                        "INTERNAL_INVARIANT", "odds client clock must be timezone-aware"
                    ) from None
                retry_scheduled = safe_error.retryable and attempt < config.retry.max_attempts
                next_request: OddsHttpRequest | None = None
                next_minimum_elapsed = minimum_elapsed_seconds
                if retry_scheduled:
                    next_request, next_minimum_elapsed = _bounded_retry_request(
                        request,
                        deadline_started=deadline_started,
                        observed_monotonic=transport_finished_monotonic,
                        minimum_elapsed_seconds=minimum_elapsed_seconds,
                        delay_seconds=0,
                    )
                    if next_request is None:
                        safe_error = IngestionError(
                            safe_error.code,
                            safe_error.message,
                            retryable=False,
                        )
                        retry_scheduled = False
                last_error = safe_error
                attempts.append(
                    OddsRetrievalAttempt(
                        attempt_number=attempt,
                        request_started_at=started_at.astimezone(UTC),
                        received_at=finished_at.astimezone(UTC),
                        request_fingerprint=attempt_request.request_fingerprint,
                        sanitized_target=attempt_request.sanitized_target,
                        http_status=None,
                        content_type=None,
                        body_sha256=None,
                        body_size=None,
                        body_capture_state="ABSENT",
                        captured_prefix_sha256=None,
                        captured_prefix_size=None,
                        quota_header_state="ABSENT",
                        quota=None,
                        provider_request_id_sha256=None,
                        failure_code=_provider_failure_code(safe_error.code),
                        requested_delay_seconds=None,
                        applied_delay_seconds=None,
                        attempt_outcome=(
                            "RETRY_SCHEDULED" if retry_scheduled else "TERMINAL_FAILURE"
                        ),
                    )
                )
                if not retry_scheduled:
                    raise OddsFetchFailure(safe_error, tuple(attempts)) from None
                if next_request is None:  # pragma: no cover - retry invariant
                    raise IngestionError("INTERNAL_INVARIANT", "odds retry request is unavailable")
                attempt_request = next_request
                minimum_elapsed_seconds = next_minimum_elapsed
                continue

            if response is None:  # pragma: no cover - helper invariant
                raise IngestionError("INTERNAL_INVARIANT", "odds transport result is invalid")

            finished_at = self._clock()
            if finished_at.tzinfo is None or finished_at.utcoffset() is None:
                raise IngestionError(
                    "INTERNAL_INVARIANT", "odds client clock must be timezone-aware"
                )
            media_type = _normalized_content_type(response.content_type)
            quota_value, quota_header_state = _response_quota(response, finished_at)
            response_error = _response_failure(
                response,
                media_type=media_type,
                quota=quota_value,
            )
            if total_deadline_expired:
                response_error = IngestionError(
                    "TOTAL_TIMEOUT",
                    "odds provider total deadline expired",
                    retryable=False,
                )
            if quota_header_state != "VALID" and not total_deadline_expired:
                response_error = IngestionError(
                    "SOURCE_UNAVAILABLE",
                    "provider quota headers are invalid",
                    retryable=False,
                )
            truncated = len(response.body) > config.max_response_bytes
            normalized_headers = {
                str(key).casefold(): str(value) for key, value in response.headers.items()
            }
            provider_request_id_sha256 = (
                canonical_sha256(normalized_headers["x-request-id"])
                if normalized_headers.get("x-request-id")
                else None
            )
            requested_delay: int | None = None
            applied_delay: int | None = None
            retry_scheduled = False
            next_request = None
            next_minimum_elapsed = minimum_elapsed_seconds
            if response_error is not None:
                quota_blocks_retry = (
                    quota_value is not None and quota_value.remaining < config.request_cost
                )
                if quota_blocks_retry and response_error.retryable:
                    response_error = IngestionError(
                        response_error.code,
                        response_error.message,
                        retryable=False,
                    )
                retry_scheduled = (
                    response_error.retryable
                    and not quota_blocks_retry
                    and attempt < config.retry.max_attempts
                )
                delay_seconds = 0
                if retry_scheduled and response.status_code == 429:
                    requested_delay, applied_delay = _retry_delay(response, config)
                    delay_seconds = applied_delay
                if retry_scheduled:
                    next_request, next_minimum_elapsed = _bounded_retry_request(
                        request,
                        deadline_started=deadline_started,
                        observed_monotonic=transport_finished_monotonic,
                        minimum_elapsed_seconds=minimum_elapsed_seconds,
                        delay_seconds=delay_seconds,
                    )
                    if next_request is None:
                        response_error = IngestionError(
                            response_error.code,
                            response_error.message,
                            retryable=False,
                        )
                        applied_delay = None
                        retry_scheduled = False
            retrieval = OddsRetrievalAttempt(
                attempt_number=attempt,
                request_started_at=started_at.astimezone(UTC),
                received_at=finished_at.astimezone(UTC),
                request_fingerprint=attempt_request.request_fingerprint,
                sanitized_target=attempt_request.sanitized_target,
                http_status=response.status_code,
                content_type=media_type,
                body_sha256=(None if truncated else hashlib.sha256(response.body).hexdigest()),
                body_size=None if truncated else len(response.body),
                body_capture_state="TRUNCATED" if truncated else "COMPLETE",
                captured_prefix_sha256=(
                    hashlib.sha256(response.body).hexdigest() if truncated else None
                ),
                captured_prefix_size=len(response.body) if truncated else None,
                quota_header_state=quota_header_state,
                quota=quota_value,
                provider_request_id_sha256=provider_request_id_sha256,
                failure_code=(
                    _provider_failure_code(response_error.code)
                    if response_error is not None
                    else None
                ),
                requested_delay_seconds=requested_delay,
                applied_delay_seconds=applied_delay,
                attempt_outcome=(
                    "SUCCESS"
                    if response_error is None
                    else "RETRY_SCHEDULED"
                    if retry_scheduled
                    else "TERMINAL_FAILURE"
                ),
            )
            attempts.append(retrieval)
            if response_error is not None:
                last_error = response_error
                if not retry_scheduled:
                    raise OddsFetchFailure(response_error, tuple(attempts)) from None
                if applied_delay is not None:
                    self._sleeper(float(applied_delay))
                if next_request is None:  # pragma: no cover - retry invariant
                    raise IngestionError("INTERNAL_INVARIANT", "odds retry request is unavailable")
                attempt_request = next_request
                minimum_elapsed_seconds = next_minimum_elapsed
                continue
            if quota_value is None:  # pragma: no cover - response validation invariant
                raise IngestionError("INTERNAL_INVARIANT", "validated response lacks quota")
            return OddsFetchResult(
                body=response.body,
                quota=quota_value,
                request_fingerprint=request.request_fingerprint,
                sanitized_target=request.sanitized_target,
                transport_call_count=self.transport_call_count,
                provider_request_id_sha256=provider_request_id_sha256,
                attempts=tuple(attempts),
            )
        if last_error is not None:  # pragma: no cover - loop invariant
            raise OddsFetchFailure(last_error, tuple(attempts))
        raise IngestionError("INTERNAL_INVARIANT", "odds transport loop did not execute")
