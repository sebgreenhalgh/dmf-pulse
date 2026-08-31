"""Bounded credential-free HTTPS transport for immutable OpenFootball resources."""

from __future__ import annotations

import http.client
import ssl
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.config import OpenFootballProviderConfig


@dataclass(frozen=True, slots=True)
class OpenFootballHttpRequest:
    method: str
    scheme: str
    host: str
    path: str
    connect_timeout_seconds: float
    read_timeout_seconds: float
    total_timeout_seconds: float
    max_response_bytes: int

    @property
    def sanitized_target(self) -> str:
        return f"{self.scheme}://{self.host}{self.path}"


class OpenFootballHttpResponse:
    """An immutable bounded response whose representation never includes body bytes."""

    __slots__ = ("_body", "_headers", "content_type", "status_code")
    _body: bytes
    _headers: Mapping[str, str]
    content_type: str
    status_code: int

    def __init__(
        self,
        *,
        status_code: int,
        content_type: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        object.__setattr__(self, "status_code", status_code)
        object.__setattr__(self, "content_type", content_type)
        object.__setattr__(self, "_headers", MappingProxyType(dict(headers)))
        object.__setattr__(self, "_body", body)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("OpenFootballHttpResponse is immutable")

    def __repr__(self) -> str:
        return (
            "OpenFootballHttpResponse("
            f"status_code={self.status_code!r}, content_type={self.content_type!r}, "
            f"body_size={len(self._body)})"
        )

    @property
    def body(self) -> bytes:
        return self._body

    @property
    def headers(self) -> Mapping[str, str]:
        return self._headers


class OpenFootballTransport(Protocol):
    transport_id: str

    def send(self, request: OpenFootballHttpRequest) -> OpenFootballHttpResponse: ...


def build_request(
    config: OpenFootballProviderConfig, resource_path: str
) -> OpenFootballHttpRequest:
    return OpenFootballHttpRequest(
        method="GET",
        scheme=config.scheme,
        host=config.host,
        path=config.raw_path(resource_path),
        connect_timeout_seconds=config.timeouts_seconds.connect,
        read_timeout_seconds=config.timeouts_seconds.read,
        total_timeout_seconds=config.timeouts_seconds.total,
        max_response_bytes=config.max_response_bytes,
    )


def _validate_request(request: OpenFootballHttpRequest, config: OpenFootballProviderConfig) -> None:
    allowed_paths = {
        config.raw_path(config.licence.path),
        *(config.raw_path(season.path) for season in config.seasons),
    }
    if (
        request.method != "GET"
        or request.scheme != "https"
        or request.host != config.host
        or request.path not in allowed_paths
        or "?" in request.path
        or "#" in request.path
        or request.max_response_bytes != config.max_response_bytes
    ):
        raise IngestionError("INTERNAL_INVARIANT", "OpenFootball request is not allowlisted")


class HttpClientOpenFootballTransport:
    """One-attempt TLS transport with explicit redirect and response-size refusal."""

    transport_id = "stdlib_http_client"

    def __init__(
        self,
        *,
        connection_factory: Callable[..., http.client.HTTPSConnection] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._connection_factory = connection_factory or http.client.HTTPSConnection
        self._monotonic = monotonic

    def send(self, request: OpenFootballHttpRequest) -> OpenFootballHttpResponse:
        if request.scheme != "https" or request.method != "GET" or not request.path.startswith("/"):
            raise IngestionError("INTERNAL_INVARIANT", "OpenFootball request is invalid")
        started = self._monotonic()
        try:
            connection = self._connection_factory(
                request.host,
                timeout=request.connect_timeout_seconds,
                context=ssl.create_default_context(),
            )
        except TimeoutError as exc:
            raise IngestionError("CONNECT_TIMEOUT", "OpenFootball connection timed out") from exc
        except ssl.SSLError as exc:
            raise IngestionError("TLS_ERROR", "OpenFootball TLS setup failed") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise IngestionError("SOURCE_UNAVAILABLE", "OpenFootball is unavailable") from exc
        try:
            connection.request(
                "GET",
                request.path,
                headers={
                    "Accept": "application/json,text/plain;q=0.9",
                    "Connection": "close",
                    "User-Agent": "dmf-pulse/0.2.0",
                },
            )
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise IngestionError("REDIRECT_BLOCKED", "OpenFootball redirect was refused")
            if response.status != 200:
                code = "HTTP_5XX" if response.status >= 500 else "HTTP_4XX"
                raise IngestionError(code, "OpenFootball returned an unsuccessful status")
            headers = {name.lower(): value for name, value in response.getheaders()}
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in {"application/json", "text/plain", "application/octet-stream"}:
                raise IngestionError(
                    "CONTENT_TYPE_INVALID", "OpenFootball content type is unsupported"
                )
            content_length = headers.get("content-length")
            if content_length is not None:
                try:
                    length = int(content_length)
                except ValueError as exc:
                    raise IngestionError(
                        "SOURCE_UNAVAILABLE", "OpenFootball content length is invalid"
                    ) from exc
                if length < 0 or length > request.max_response_bytes:
                    raise IngestionError("PAYLOAD_TOO_LARGE", "OpenFootball response is too large")
            chunks: list[bytes] = []
            size = 0
            while True:
                elapsed = self._monotonic() - started
                remaining = request.total_timeout_seconds - elapsed
                if remaining <= 0:
                    raise IngestionError("READ_TIMEOUT", "OpenFootball total deadline expired")
                if connection.sock is not None:
                    connection.sock.settimeout(min(request.read_timeout_seconds, remaining))
                chunk = response.read(min(64 * 1024, request.max_response_bytes - size + 1))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > request.max_response_bytes:
                    raise IngestionError("PAYLOAD_TOO_LARGE", "OpenFootball response is too large")
            body = b"".join(chunks)
            if content_length is not None and len(body) != int(content_length):
                raise IngestionError("SOURCE_UNAVAILABLE", "OpenFootball response was truncated")
            return OpenFootballHttpResponse(
                status_code=response.status,
                content_type=content_type,
                headers=headers,
                body=body,
            )
        except IngestionError:
            raise
        except TimeoutError as exc:
            raise IngestionError("READ_TIMEOUT", "OpenFootball request timed out") from exc
        except ssl.SSLError as exc:
            raise IngestionError("TLS_ERROR", "OpenFootball TLS validation failed") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise IngestionError("SOURCE_UNAVAILABLE", "OpenFootball is unavailable") from exc
        finally:
            with suppress(OSError):
                connection.close()


def fetch_resource(
    *,
    config: OpenFootballProviderConfig,
    resource_path: str,
    transport: OpenFootballTransport,
) -> OpenFootballHttpResponse:
    request = build_request(config, resource_path)
    _validate_request(request, config)
    return transport.send(request)


__all__ = [
    "HttpClientOpenFootballTransport",
    "OpenFootballHttpRequest",
    "OpenFootballHttpResponse",
    "OpenFootballTransport",
    "build_request",
    "fetch_resource",
]
