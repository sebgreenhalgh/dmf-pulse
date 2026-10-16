"""Bounded HTTP diagnostics exercised only with explicitly injected fake connections."""

from __future__ import annotations

import hashlib
import http.client
import ssl
import time
from collections.abc import Callable
from datetime import UTC, datetime

from dmf_pulse.evaluation.p01_fallback_context import ROUTES, require_openligadb_rights
from dmf_pulse.ingestion.p01_fallback_diagnostics import (
    ContentTypeClass,
    DiagnosticProgress,
    FailureReason,
    ReasonFailure,
    RouteClass,
)


class HttpOpenLigaTransport:
    """No default live connection: D1 grants no provider execution authority."""

    def __init__(
        self, *, connection_factory: Callable[..., http.client.HTTPSConnection] | None = None
    ) -> None:
        self._connection_factory = connection_factory

    def get(
        self,
        url: str,
        *,
        progress: DiagnosticProgress | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> bytes:
        if url not in ROUTES:
            raise ReasonFailure(FailureReason.TRANSPORT_ROUTE_REFUSED)
        require_openligadb_rights()
        if self._connection_factory is None:
            raise ReasonFailure(FailureReason.ONE_ATTEMPT_ALREADY_CONSUMED)
        state = progress or DiagnosticProgress()
        if progress is None:
            state.begin(tuple(RouteClass)[ROUTES.index(url)], clock())
        started = time.monotonic()
        connection: http.client.HTTPSConnection | None = None
        digest = hashlib.sha256()
        count = 0
        try:
            connection = self._connection_factory(
                "api.openligadb.de", timeout=8, context=ssl.create_default_context()
            )
            connection.request(
                "GET",
                url.removeprefix("https://api.openligadb.de"),
                headers={
                    "Accept": "application/json",
                    "Connection": "close",
                    "User-Agent": "dmf-pulse/0.2.0",
                },
            )
            response = connection.getresponse()
            status = response.status
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].lower()
            kinds = {
                "application/json": ContentTypeClass.JSON,
                "text/json": ContentTypeClass.TEXT_JSON,
                "text/plain": ContentTypeClass.TEXT_PLAIN,
                "": ContentTypeClass.MISSING,
            }
            kind = kinds.get(content_type, ContentTypeClass.OTHER)
            state.receipt(
                response_received_at=clock(),
                http_status_code=status if type(status) is int and 100 <= status <= 599 else None,
                content_type_class=kind,
            )
            if status != 200 or kind not in {
                ContentTypeClass.JSON,
                ContentTypeClass.TEXT_JSON,
                ContentTypeClass.TEXT_PLAIN,
            }:
                raise ReasonFailure(FailureReason.TRANSPORT_STATUS_OR_CONTENT_TYPE_REFUSED)
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > 524288):
                raise ReasonFailure(FailureReason.TRANSPORT_RESPONSE_TOO_LARGE)
            chunks: list[bytes] = []
            while True:
                remaining = 20 - (time.monotonic() - started)
                if remaining <= 0:
                    raise ReasonFailure(FailureReason.TRANSPORT_TIMEOUT)
                if connection.sock is not None:
                    connection.sock.settimeout(min(8, remaining))
                part = response.read1(min(32768, 524289 - count))
                if not part:
                    break
                count += len(part)
                digest.update(part)
                state.receipt(response_bytes=count, response_sha256=digest.hexdigest())
                if count > 524288:
                    raise ReasonFailure(FailureReason.TRANSPORT_RESPONSE_TOO_LARGE)
                chunks.append(part)
            if length is not None and count != int(length):
                raise ReasonFailure(FailureReason.TRANSPORT_TRUNCATED)
            state.receipt(
                response_bytes=count,
                response_sha256=digest.hexdigest(),
                response_complete=True,
                response_received_at=clock(),
            )
            return b"".join(chunks)
        except TimeoutError:
            raise ReasonFailure(FailureReason.TRANSPORT_TIMEOUT) from None
        except (OSError, http.client.HTTPException):
            raise ReasonFailure(FailureReason.TRANSPORT_UNAVAILABLE) from None
        finally:
            if connection is not None:
                connection.close()
