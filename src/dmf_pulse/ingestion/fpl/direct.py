"""Bounded operator-initiated, read-only access to current official FPL JSON.

This is deliberately separate from the legacy FPL client.  It has no write method, no
generic URL method, no cookie support, and no persistence boundary.  Response bodies are
returned only to the caller in memory.
"""

from __future__ import annotations

import http.client
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import Message
from enum import StrEnum
from typing import Literal, Protocol, Self

from pydantic import SecretStr, field_validator, model_validator

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.config import load_provider_config
from dmf_pulse.ingestion.models import (
    CapabilityValue,
    FrozenModel,
    RightsCapability,
    RightsProfile,
    RightsProfileStatus,
)
from dmf_pulse.ingestion.rights import load_rights_profiles, require_rights

DIRECT_FPL_PROFILE_ID: Literal["fpl_official_private_operator_initiated_read_v1"] = (
    "fpl_official_private_operator_initiated_read_v1"
)
DIRECT_FPL_HOST: Literal["fantasy.premierleague.com"] = "fantasy.premierleague.com"
DIRECT_FPL_TOKEN_ENV: Literal["DMF_FPL_BEARER_TOKEN"] = "DMF_FPL_BEARER_TOKEN"
DIRECT_FPL_USER_AGENT = "dmf-pulse-private-operator-read/0.2.0"

_PATH_PATTERN = re.compile(
    r"^(?:"
    r"/api/bootstrap-static/|"
    r"/api/fixtures/|"
    r"/api/event/[1-9][0-9]*/live/|"
    r"/api/entry/[1-9][0-9]*/|"
    r"/api/entry/[1-9][0-9]*/history/|"
    r"/api/entry/[1-9][0-9]*/event/[1-9][0-9]*/picks/|"
    r"/api/entry/[1-9][0-9]*/transfers/|"
    r"/api/my-team/[1-9][0-9]*/"
    r")$"
)
_MY_TEAM_PATTERN = re.compile(r"^/api/my-team/[1-9][0-9]*/$")


class DirectFplResource(StrEnum):
    BOOTSTRAP = "BOOTSTRAP"
    FIXTURES = "FIXTURES"
    EVENT_LIVE = "EVENT_LIVE"
    ENTRY = "ENTRY"
    HISTORY = "HISTORY"
    PICKS = "PICKS"
    TRANSFERS = "TRANSFERS"
    MY_TEAM = "MY_TEAM"


class DirectFplRunAttestation(FrozenModel):
    """Per-run authority; it is never written by this module."""

    operator_initiated: Literal[True] = True
    private_use: Literal[True] = True
    read_only: Literal[True] = True
    non_commercial: Literal[True] = True
    production_service: Literal[False] = False
    accepted_contractual_risk: Literal[True] = True
    attested_at: datetime

    @field_validator("attested_at")
    @classmethod
    def normalise_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("direct FPL attestation time must be timezone-aware")
        return value.astimezone(UTC)


class DirectFplCredential(FrozenModel):
    source: Literal["ENVIRONMENT", "HIDDEN_PROMPT"]
    bearer_token: SecretStr

    @model_validator(mode="after")
    def token_is_bounded(self) -> Self:
        value = self.bearer_token.get_secret_value()
        if not value or value != value.strip() or len(value) > 16_384 or "\x00" in value:
            raise ValueError("FPL bearer token is invalid")
        return self


class DirectFplCredentialProvider:
    """Read one bearer token without accepting it as a command-line value."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ

    def get(self) -> DirectFplCredential:
        token = self._environ.get(DIRECT_FPL_TOKEN_ENV)
        if token is None or not token.strip():
            raise IngestionError(
                "CREDENTIAL_MISSING",
                f"{DIRECT_FPL_TOKEN_ENV} is missing.",
            )
        try:
            return DirectFplCredential(source="ENVIRONMENT", bearer_token=SecretStr(token))
        except ValueError:
            raise IngestionError("CREDENTIAL_INVALID", "FPL bearer token is invalid.") from None


@dataclass(frozen=True, slots=True, repr=False)
class DirectHttpRequest:
    method: Literal["GET"]
    host: Literal["fantasy.premierleague.com"]
    path: str
    headers: Mapping[str, str] = field(repr=False)
    connect_timeout_seconds: float
    read_timeout_seconds: float
    total_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class DirectHttpResponse:
    status_code: int
    content_type: str
    body: bytes = field(repr=False)
    redirect_location: str | None = None
    retry_after: str | None = None


class DirectTransport(Protocol):
    def send(self, request: DirectHttpRequest) -> DirectHttpResponse: ...


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
        del req, fp, code, msg, headers, newurl
        return None


def _retry_after(headers: Message | None) -> str | None:
    return None if headers is None else headers.get("Retry-After")


class DirectUrllibTransport:
    """TLS-validating bounded transport for the closed direct-read path grammar."""

    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic

    @staticmethod
    def _set_read_timeout(response: object, timeout_seconds: float) -> None:
        """Adjust the live socket while allowing CPython's post-body detached state."""

        raw_socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        set_timeout = getattr(raw_socket, "settimeout", None)
        if not callable(set_timeout):
            return
        try:
            set_timeout(timeout_seconds)
        except OSError:
            fileno = getattr(raw_socket, "fileno", None)
            if not callable(fileno):
                raise
            try:
                descriptor = fileno()
            except OSError:
                return
            if not isinstance(descriptor, int) or descriptor >= 0:
                raise
            # HTTPResponse can close the socket after consuming Content-Length while its
            # stable read() interface still has one authoritative EOF result to return.

    @staticmethod
    def _declared_content_length(response: object) -> int | None:
        headers = getattr(response, "headers", None)
        get_header = getattr(headers, "get", None)
        if not callable(get_header):
            return None
        raw_length = get_header("Content-Length")
        if raw_length is None:
            return None
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            raise IngestionError("SOURCE_UNAVAILABLE", "FPL source response is invalid") from None
        if length < 0:
            raise IngestionError("SOURCE_UNAVAILABLE", "FPL source response is invalid")
        return length

    def _read_bounded(
        self, response: object, request: DirectHttpRequest, *, started_at: float
    ) -> bytes:
        limit = load_provider_config().max_response_bytes
        declared_length = self._declared_content_length(response)
        chunks: list[bytes] = []
        size = 0
        while size <= limit:
            remaining = request.total_timeout_seconds - (self._monotonic() - started_at)
            if remaining <= 0:
                raise TimeoutError
            self._set_read_timeout(response, min(request.read_timeout_seconds, remaining))
            reader = getattr(response, "read", None)
            if not callable(reader):
                raise IngestionError("SOURCE_UNAVAILABLE", "FPL source response is invalid")
            chunk = reader(min(64 * 1024, limit + 1 - size))
            if not isinstance(chunk, bytes):
                raise IngestionError("SOURCE_UNAVAILABLE", "FPL source response is invalid")
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        body = b"".join(chunks)
        if len(body) > limit:
            raise IngestionError("PAYLOAD_TOO_LARGE", "FPL response exceeds the byte limit")
        if declared_length is not None and len(body) != declared_length:
            raise IngestionError("SOURCE_UNAVAILABLE", "FPL source response is incomplete")
        return body

    def _body(self, response: object, request: DirectHttpRequest, *, started_at: float) -> bytes:
        try:
            return self._read_bounded(response, request, started_at=started_at)
        except IngestionError:
            raise
        except TimeoutError:
            raise IngestionError("READ_TIMEOUT", "FPL source timed out", retryable=True) from None
        except ssl.SSLError:
            raise IngestionError("TLS_ERROR", "FPL source TLS validation failed") from None
        except (OSError, http.client.HTTPException):
            raise IngestionError(
                "SOURCE_UNAVAILABLE", "FPL source is unavailable", retryable=True
            ) from None

    def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
        if (
            request.method != "GET"
            or request.host != DIRECT_FPL_HOST
            or _PATH_PATTERN.fullmatch(request.path) is None
            or request.connect_timeout_seconds <= 0
            or request.read_timeout_seconds <= 0
            or request.connect_timeout_seconds + request.read_timeout_seconds
            > request.total_timeout_seconds
        ):
            raise IngestionError("INTERNAL_INVARIANT", "direct FPL request is not allowlisted")
        url = f"https://{request.host}{request.path}"
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != DIRECT_FPL_HOST
            or parsed.path != request.path
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise IngestionError("INTERNAL_INVARIANT", "direct FPL URL is not allowlisted")
        started_at = self._monotonic()
        opener = urllib.request.build_opener(_NoRedirect())
        outbound = urllib.request.Request(url, headers=dict(request.headers), method="GET")
        try:
            with opener.open(outbound, timeout=request.connect_timeout_seconds) as response:
                return DirectHttpResponse(
                    status_code=response.status,
                    content_type=response.headers.get_content_type(),
                    body=self._body(response, request, started_at=started_at),
                    retry_after=_retry_after(response.headers),
                )
        except urllib.error.HTTPError as exc:
            return DirectHttpResponse(
                status_code=exc.code,
                content_type=exc.headers.get_content_type() if exc.headers else "",
                body=(self._body(exc, request, started_at=started_at) if exc.fp else b""),
                redirect_location=exc.headers.get("Location") if exc.headers else None,
                retry_after=_retry_after(exc.headers),
            )
        except TimeoutError:
            raise IngestionError("READ_TIMEOUT", "FPL source timed out", retryable=True) from None
        except ssl.SSLError:
            raise IngestionError("TLS_ERROR", "FPL source TLS validation failed") from None
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):
                raise IngestionError("TLS_ERROR", "FPL source TLS validation failed") from None
            code = "CONNECT_TIMEOUT" if isinstance(reason, TimeoutError) else "SOURCE_UNAVAILABLE"
            raise IngestionError(code, "FPL source is unavailable", retryable=True) from None
        except (OSError, http.client.HTTPException):
            raise IngestionError(
                "SOURCE_UNAVAILABLE", "FPL source is unavailable", retryable=True
            ) from None


def direct_path(
    resource: DirectFplResource, *, entry_id: int | None = None, gameweek: int | None = None
) -> str:
    if entry_id is not None and (isinstance(entry_id, bool) or entry_id <= 0):
        raise IngestionError("USAGE_INVALID", "entry ID must be a positive integer")
    if gameweek is not None and (isinstance(gameweek, bool) or gameweek <= 0):
        raise IngestionError("USAGE_INVALID", "Gameweek must be a positive integer")
    if resource is DirectFplResource.BOOTSTRAP:
        path = "/api/bootstrap-static/"
    elif resource is DirectFplResource.FIXTURES:
        path = "/api/fixtures/"
    elif resource is DirectFplResource.EVENT_LIVE and gameweek is not None:
        path = f"/api/event/{gameweek}/live/"
    elif resource is DirectFplResource.ENTRY and entry_id is not None:
        path = f"/api/entry/{entry_id}/"
    elif resource is DirectFplResource.HISTORY and entry_id is not None:
        path = f"/api/entry/{entry_id}/history/"
    elif resource is DirectFplResource.PICKS and entry_id is not None and gameweek is not None:
        path = f"/api/entry/{entry_id}/event/{gameweek}/picks/"
    elif resource is DirectFplResource.TRANSFERS and entry_id is not None:
        path = f"/api/entry/{entry_id}/transfers/"
    elif resource is DirectFplResource.MY_TEAM and entry_id is not None:
        path = f"/api/my-team/{entry_id}/"
    else:
        raise IngestionError("USAGE_INVALID", "direct FPL endpoint arguments are incomplete")
    if _PATH_PATTERN.fullmatch(path) is None:
        raise IngestionError("INTERNAL_INVARIANT", "direct FPL path is not allowlisted")
    return path


def _profile_is_exact(profile: RightsProfile) -> bool:
    expected = {
        RightsCapability.AUTOMATED_ACCESS: CapabilityValue.ALLOW,
        RightsCapability.TRANSIENT_PROCESSING: CapabilityValue.ALLOW,
        RightsCapability.PRIVATE_INTERNAL_USE: CapabilityValue.ALLOW,
        RightsCapability.MANUAL_IMPORT: CapabilityValue.DENY,
        RightsCapability.RAW_STORAGE: CapabilityValue.DENY,
        RightsCapability.DERIVED_STORAGE: CapabilityValue.DENY,
        RightsCapability.CACHE: CapabilityValue.DENY,
        RightsCapability.BACKUP: CapabilityValue.DENY,
        RightsCapability.MODEL_TRAINING: CapabilityValue.DENY,
        RightsCapability.PUBLIC_DISPLAY: CapabilityValue.DENY,
        RightsCapability.REDISTRIBUTION: CapabilityValue.DENY,
    }
    return (
        profile.rights_profile_id == DIRECT_FPL_PROFILE_ID
        and profile.profile_version == "1.0.0"
        and profile.provider_key == "official_fpl"
        and profile.status is RightsProfileStatus.HUMAN_APPROVED
        and profile.retention_seconds == 0
        and all(profile.capabilities[key] is value for key, value in expected.items())
    )


class DirectFplClient:
    """One sequential session with a finite request and retry budget."""

    def __init__(
        self,
        attestation: DirectFplRunAttestation,
        *,
        profile: RightsProfile | None = None,
        transport: DirectTransport | None = None,
        credential_provider: DirectFplCredentialProvider | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        maximum_requests: int = 24,
        maximum_attempts: int = 3,
        pace_seconds: float = 0.25,
    ) -> None:
        self._attestation = attestation
        self._profile = profile or load_rights_profiles()[DIRECT_FPL_PROFILE_ID]
        self._transport = transport or DirectUrllibTransport()
        self._credential_provider = credential_provider or DirectFplCredentialProvider()
        self._sleeper = sleeper
        if maximum_requests < 1 or maximum_requests > 24 or maximum_attempts not in {1, 2, 3}:
            raise ValueError("direct FPL budgets are invalid")
        if pace_seconds < 0 or pace_seconds > 2:
            raise ValueError("direct FPL pacing is invalid")
        self._maximum_requests = maximum_requests
        self._maximum_attempts = maximum_attempts
        self._pace_seconds = pace_seconds
        self._request_count = 0
        self._endpoint_classes: list[DirectFplResource] = []
        if not _profile_is_exact(self._profile):
            raise IngestionError("RIGHTS_BLOCKED", "direct FPL rights profile is not exact")
        for capability in (
            RightsCapability.AUTOMATED_ACCESS,
            RightsCapability.TRANSIENT_PROCESSING,
            RightsCapability.PRIVATE_INTERNAL_USE,
        ):
            require_rights(self._profile, capability, checked_at=attestation.attested_at)

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def endpoint_classes(self) -> tuple[DirectFplResource, ...]:
        return tuple(self._endpoint_classes)

    def _request(
        self, resource: DirectFplResource, path: str, credential: DirectFplCredential | None
    ) -> DirectHttpRequest:
        config = load_provider_config()
        authenticated = _MY_TEAM_PATTERN.fullmatch(path) is not None
        if authenticated != (credential is not None):
            raise IngestionError("INTERNAL_INVARIANT", "FPL authentication boundary is invalid")
        headers = {"Accept": "application/json", "User-Agent": DIRECT_FPL_USER_AGENT}
        if credential is not None:
            headers["X-API-Authorization"] = f"Bearer {credential.bearer_token.get_secret_value()}"
        return DirectHttpRequest(
            method="GET",
            host=DIRECT_FPL_HOST,
            path=path,
            headers=headers,
            connect_timeout_seconds=float(config.timeouts_seconds.connect),
            read_timeout_seconds=float(config.timeouts_seconds.read),
            total_timeout_seconds=float(config.timeouts_seconds.total),
        )

    @staticmethod
    def _retry_delay(response: DirectHttpResponse, attempt: int) -> float:
        if response.status_code == 429 and response.retry_after is not None:
            try:
                delay = float(response.retry_after)
            except ValueError:
                delay = float(attempt)
            return min(max(delay, 0.0), 10.0)
        return min(float(2 ** (attempt - 1)), 4.0)

    def fetch(
        self,
        resource: DirectFplResource,
        *,
        entry_id: int | None = None,
        gameweek: int | None = None,
    ) -> bytes:
        path = direct_path(resource, entry_id=entry_id, gameweek=gameweek)
        credential = (
            self._credential_provider.get() if resource is DirectFplResource.MY_TEAM else None
        )
        request = self._request(resource, path, credential)
        for attempt in range(1, self._maximum_attempts + 1):
            if self._request_count >= self._maximum_requests:
                raise IngestionError("REQUEST_BUDGET_EXHAUSTED", "FPL request budget exhausted")
            if self._request_count:
                self._sleeper(self._pace_seconds)
            self._request_count += 1
            self._endpoint_classes.append(resource)
            response = self._transport.send(request)
            if response.redirect_location is not None or 300 <= response.status_code < 400:
                raise IngestionError("REDIRECT_BLOCKED", "FPL source redirect was blocked")
            if response.status_code == 200:
                media_type = response.content_type.partition(";")[0].strip().casefold()
                if media_type != "application/json" and not media_type.endswith("+json"):
                    raise IngestionError("CONTENT_TYPE_INVALID", "FPL source did not return JSON")
                return response.body
            retryable = response.status_code == 429 or 500 <= response.status_code < 600
            if retryable and attempt < self._maximum_attempts:
                self._sleeper(self._retry_delay(response, attempt))
                continue
            if response.status_code == 401 or response.status_code == 403:
                raise IngestionError(
                    "FPL_AUTH_REQUIRED", "authenticated current FPL team access was rejected"
                )
            if response.status_code == 429:
                raise IngestionError(
                    "HTTP_429", "FPL source rate limited the request", retryable=True
                )
            if 500 <= response.status_code < 600:
                raise IngestionError(
                    "HTTP_5XX", "FPL source returned a server error", retryable=True
                )
            if 400 <= response.status_code < 500:
                raise IngestionError("HTTP_4XX", "FPL source rejected the request")
            raise IngestionError("SOURCE_UNAVAILABLE", "FPL source returned an invalid status")
        raise IngestionError("INTERNAL_INVARIANT", "FPL request loop did not terminate")


__all__ = [
    "DIRECT_FPL_HOST",
    "DIRECT_FPL_PROFILE_ID",
    "DIRECT_FPL_TOKEN_ENV",
    "DirectFplClient",
    "DirectFplCredential",
    "DirectFplCredentialProvider",
    "DirectFplResource",
    "DirectFplRunAttestation",
    "DirectHttpRequest",
    "DirectHttpResponse",
    "DirectTransport",
    "DirectUrllibTransport",
    "direct_path",
]
