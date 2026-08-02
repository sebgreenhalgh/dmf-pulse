"""Allowlisted transport-neutral client; live access remains rights-gated."""

from __future__ import annotations

import http.client
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.config import load_provider_config
from dmf_pulse.ingestion.fpl.parser import FplResource
from dmf_pulse.ingestion.models import RightsCapability, RightsProfile
from dmf_pulse.ingestion.rights import require_rights

APPROVED_HOST = "fantasy.premierleague.com"


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    host: str
    path: str
    headers: Mapping[str, str]
    connect_timeout_seconds: float
    read_timeout_seconds: float
    total_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    content_type: str
    body: bytes
    redirect_location: str | None = None


class Transport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...


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


class UrllibTransport:
    """Minimal TLS-validating GET transport with redirects disabled."""

    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic

    def _read_bounded(
        self,
        response: object,
        request: HttpRequest,
        *,
        started_at: float,
    ) -> bytes:
        configured_limit = load_provider_config().max_response_bytes
        chunks: list[bytes] = []
        size = 0
        raw_socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        while size <= configured_limit:
            remaining = request.total_timeout_seconds - (self._monotonic() - started_at)
            if remaining <= 0:
                raise TimeoutError("total response deadline exceeded")
            if raw_socket is not None and hasattr(raw_socket, "settimeout"):
                raw_socket.settimeout(min(request.read_timeout_seconds, remaining))
            read = getattr(response, "read", None)
            if not callable(read):
                raise IngestionError("SOURCE_UNAVAILABLE", "FPL source response is invalid")
            chunk = read(min(64 * 1024, configured_limit + 1 - size))
            if not isinstance(chunk, bytes):
                raise IngestionError("SOURCE_UNAVAILABLE", "FPL source response is invalid")
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if self._monotonic() - started_at >= request.total_timeout_seconds:
                raise TimeoutError("total response deadline exceeded")
        return b"".join(chunks)

    def _read_response_body(
        self,
        response: object,
        request: HttpRequest,
        *,
        started_at: float,
    ) -> bytes:
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

    def send(self, request: HttpRequest) -> HttpResponse:
        config = load_provider_config()
        approved_host = config.resources.bootstrap.host
        approved_paths = {
            config.resources.bootstrap.path,
            config.resources.fixtures.path,
        }
        if (
            request.method != "GET"
            or request.host != approved_host
            or request.path not in approved_paths
        ):
            raise IngestionError("INTERNAL_INVARIANT", "transport request is not allowlisted")
        if (
            request.connect_timeout_seconds <= 0
            or request.read_timeout_seconds <= 0
            or request.connect_timeout_seconds + request.read_timeout_seconds
            > request.total_timeout_seconds
        ):
            raise IngestionError("CONFIGURATION_INVALID", "transport timeouts are invalid")
        url = f"https://{request.host}{request.path}"
        parsed_url = urllib.parse.urlsplit(url)
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname != approved_host
            or parsed_url.path != request.path
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise IngestionError("INTERNAL_INVARIANT", "transport URL is not allowlisted")
        opener = urllib.request.build_opener(_NoRedirect())
        outbound = urllib.request.Request(url, headers=dict(request.headers), method="GET")
        started_at = self._monotonic()
        try:
            with opener.open(outbound, timeout=request.connect_timeout_seconds) as response:
                content_type = response.headers.get_content_type()
                body = self._read_response_body(response, request, started_at=started_at)
                return HttpResponse(response.status, content_type, body)
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers else None
            body = (
                self._read_response_body(exc, request, started_at=started_at)
                if exc.fp is not None
                else b""
            )
            return HttpResponse(
                status_code=exc.code,
                content_type=(exc.headers.get_content_type() if exc.headers else ""),
                body=body,
                redirect_location=location,
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


def build_request(resource: FplResource) -> HttpRequest:
    config = load_provider_config()
    endpoint = (
        config.resources.bootstrap
        if resource is FplResource.BOOTSTRAP
        else config.resources.fixtures
    )
    return HttpRequest(
        method="GET",
        host=endpoint.host,
        path=endpoint.path,
        headers={
            "Accept": "application/json",
            "User-Agent": "dmf-pulse-private/0.2.0",
        },
        connect_timeout_seconds=float(config.timeouts_seconds.connect),
        read_timeout_seconds=float(config.timeouts_seconds.read),
        total_timeout_seconds=float(config.timeouts_seconds.total),
    )


class FplClient:
    def __init__(
        self,
        profile: RightsProfile,
        transport_factory: Callable[[], Transport] = UrllibTransport,
    ) -> None:
        self._profile = profile
        self._transport_factory = transport_factory

    def fetch(self, resource: FplResource) -> bytes:
        require_rights(self._profile, RightsCapability.AUTOMATED_ACCESS)
        request = build_request(resource)
        response = self._transport_factory().send(request)
        if response.redirect_location is not None or 300 <= response.status_code < 400:
            raise IngestionError("REDIRECT_BLOCKED", "FPL source redirect was blocked")
        if response.status_code == 429:
            raise IngestionError("HTTP_429", "FPL source rate limited the request", retryable=True)
        if 500 <= response.status_code < 600:
            raise IngestionError("HTTP_5XX", "FPL source returned a server error", retryable=True)
        if 400 <= response.status_code < 500:
            raise IngestionError("HTTP_4XX", "FPL source rejected the request")
        if response.status_code != 200:
            raise IngestionError("SOURCE_UNAVAILABLE", "FPL source returned an invalid status")
        media_type = response.content_type.partition(";")[0].strip().casefold()
        if media_type not in {
            "application/json",
            "application/problem+json",
        } and not media_type.endswith("+json"):
            raise IngestionError("CONTENT_TYPE_INVALID", "FPL source did not return JSON")
        if len(response.body) > load_provider_config().max_response_bytes:
            raise IngestionError("PAYLOAD_TOO_LARGE", "FPL response exceeds the byte limit")
        return response.body
