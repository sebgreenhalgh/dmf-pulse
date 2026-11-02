"""One admitted public bootstrap read and pure exact current-FPL route derivation."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from dmf_pulse.authorization_errors import AuthorizationError
from dmf_pulse.dashboard.authorization import RouteBudget
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.direct import (
    DIRECT_FPL_HOST,
    DirectFplClient,
    DirectFplResource,
    DirectFplRunAttestation,
    DirectHttpRequest,
    DirectHttpResponse,
    DirectTransport,
    DirectUrllibTransport,
    direct_path,
)
from dmf_pulse.ingestion.fpl.direct_payloads import _target_gameweek
from dmf_pulse.ingestion.fpl.parser import BootstrapPayload, FplResource, parse_fpl_payload
from dmf_pulse.ingestion.models import RightsProfile
from dmf_pulse.operation.models import Metadata, OperationError, Sha


class EventDiscovery(Metadata):
    target_gameweek: Annotated[int, Field(gt=0)]
    deadline_at: datetime
    history_gameweeks: Annotated[tuple[Annotated[int, Field(gt=0)], ...], Field(max_length=12)]
    request_started_at: datetime
    received_at: datetime
    bootstrap_sha256: Sha
    request_count: Literal[1]

    @field_validator("request_count", mode="before")
    @classmethod
    def actual_integer_count(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("discovery request count must be an integer")
        return value

    @model_validator(mode="after")
    def coherent_discovery(self) -> Self:
        if self.request_started_at > self.received_at or self.deadline_at <= self.received_at:
            raise ValueError("discovery chronology or official deadline is invalid")
        if self.history_gameweeks != tuple(sorted(set(self.history_gameweeks))) or any(
            value >= self.target_gameweek for value in self.history_gameweeks
        ):
            raise ValueError("discovery history identity is invalid")
        return self


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OperationError("DISCOVERY_CLOCK_INVALID")
    return value.astimezone(UTC)


class _BootstrapTransport:
    """Recheck standing admission at the actual fixed public-send boundary."""

    def __init__(
        self,
        delegate: DirectTransport,
        admission: Callable[[], None],
        before_send: Callable[[], None],
    ) -> None:
        self._delegate = delegate
        self._admission, self._before_send = admission, before_send
        self.requires_supplier_permission = (
            isinstance(delegate, DirectUrllibTransport)
            or getattr(delegate, "requires_supplier_permission", False) is True
        )

    def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
        if (
            request.method != "GET"
            or request.host != DIRECT_FPL_HOST
            or request.path != "/api/bootstrap-static/"
            or any(
                key.casefold() in {"authorization", "x-api-authorization", "cookie"}
                for key in request.headers
            )
        ):
            raise OperationError("DISCOVERY_FIXED_PUBLIC_ROUTE_REQUIRED")
        self._admission()
        self._before_send()
        return self._delegate.send(request)


@dataclass(frozen=True, slots=True)
class _DiscoveryOutcome:
    discovery: EventDiscovery | None = None
    code: str | None = None


def _discovery_scope(
    profile: RightsProfile,
    admission: Callable[[], None],
    before_send: Callable[[], None],
    clock: Callable[[], datetime],
    transport: DirectTransport | None,
) -> _DiscoveryOutcome:
    """Discard source-body/exception-bearing frames before a public error."""
    try:
        admission()
        started = _utc(clock())
        wrapped = _BootstrapTransport(
            transport if transport is not None else DirectUrllibTransport(), admission, before_send
        )
        client = DirectFplClient(
            DirectFplRunAttestation(attested_at=started),
            profile=profile,
            transport=wrapped,
            maximum_requests=1,
            maximum_attempts=1,
            before_request=admission,
            clock=clock,
        )
        body = client.fetch(DirectFplResource.BOOTSTRAP)
        received = _utc(clock())
        if received < started:
            raise OperationError("DISCOVERY_CLOCK_INVALID")
        parsed = parse_fpl_payload(FplResource.BOOTSTRAP, body)
        if not isinstance(parsed.payload, BootstrapPayload):
            raise OperationError("DISCOVERY_BOOTSTRAP_TYPE_INVALID")
        events = parsed.payload.events
        ids = tuple(event.id for event in events)
        # The existing selector uses provider order. Reject incoherent ordering;
        # never silently change that selector or the existing twelve-event history.
        if not ids or ids != tuple(sorted(set(ids))):
            raise OperationError("DISCOVERY_EVENT_IDENTITY_INVALID")
        target, history = _target_gameweek(parsed.payload, captured_at=received)
        selected = tuple(event for event in events if event.id == target)
        if len(selected) != 1 or selected[0].finished is True:
            raise OperationError("TARGET_GAMEWEEK_UNRESOLVED")
        if client.request_count != 1 or client.endpoint_classes != (DirectFplResource.BOOTSTRAP,):
            raise OperationError("DISCOVERY_REQUEST_COUNT_INVALID")
        value = EventDiscovery(
            target_gameweek=target,
            deadline_at=selected[0].deadline_time,
            history_gameweeks=history,
            request_started_at=started,
            received_at=received,
            bootstrap_sha256=parsed.payload_sha256,
            request_count=1,
        )
        return _DiscoveryOutcome(discovery=value)
    except (OperationError, IngestionError, AuthorizationError) as error:
        code = error.code
    except Exception:
        code = "DISCOVERY_SOURCE_UNAVAILABLE"
    if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,119}", code) is None:
        code = "DISCOVERY_SOURCE_UNAVAILABLE"
    return _DiscoveryOutcome(code=code)


def discover_event(
    *,
    profile: RightsProfile,
    admission: Callable[[], None],
    before_send: Callable[[], None],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    transport: DirectTransport | None = None,
) -> EventDiscovery:
    """Exactly one qualified bootstrap GET; no token or manager endpoint is used."""
    result = _discovery_scope(profile, admission, before_send, clock, transport)
    del profile, admission, before_send, clock, transport
    if result.code is not None:
        raise OperationError(result.code) from None
    if result.discovery is None:
        raise OperationError("DISCOVERY_SOURCE_UNAVAILABLE") from None
    return result.discovery


def fpl_routes(entry_id: int, discovery: EventDiscovery) -> tuple[RouteBudget, ...]:
    """Pure per-run route identities: six fixed, optional picks, at most twelve live."""
    if type(entry_id) is not int or entry_id <= 0:
        raise OperationError("DISCOVERY_ENTRY_ID_INVALID")
    discovery = EventDiscovery.model_validate(discovery)
    resources: list[tuple[DirectFplResource, int | None]] = [
        (DirectFplResource.BOOTSTRAP, None),
        (DirectFplResource.FIXTURES, None),
        (DirectFplResource.ENTRY, None),
        (DirectFplResource.HISTORY, None),
        (DirectFplResource.TRANSFERS, None),
    ]
    if discovery.history_gameweeks:
        resources.append((DirectFplResource.PICKS, discovery.history_gameweeks[-1]))
    resources.append((DirectFplResource.MY_TEAM, None))
    resources.extend((DirectFplResource.EVENT_LIVE, value) for value in discovery.history_gameweeks)
    return tuple(
        RouteBudget(
            host=DIRECT_FPL_HOST,
            path=direct_path(
                resource,
                entry_id=entry_id
                if resource
                in {
                    DirectFplResource.ENTRY,
                    DirectFplResource.HISTORY,
                    DirectFplResource.TRANSFERS,
                    DirectFplResource.PICKS,
                    DirectFplResource.MY_TEAM,
                }
                else None,
                gameweek=gameweek,
            ),
            maximum_calls=1,
        )
        for resource, gameweek in resources
    )
