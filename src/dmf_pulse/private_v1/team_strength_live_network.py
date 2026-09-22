"""One-shot transport accounting and closure; no data retention or retry loop."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from dmf_pulse.ingestion.fpl.direct import (
    DirectHttpRequest,
    DirectHttpResponse,
    DirectTransport,
)
from dmf_pulse.ingestion.odds.client import OddsHttpRequest, OddsHttpResponse, OddsTransport
from dmf_pulse.ingestion.openfootball.client import (
    OpenFootballHttpRequest,
    OpenFootballHttpResponse,
    OpenFootballTransport,
)

Provider = Literal["FPL", "ODDS", "OPENFOOTBALL"]


def fpl_endpoint(path: str) -> str:
    patterns = (
        (r"/api/bootstrap-static/", "BOOTSTRAP"),
        (r"/api/fixtures/", "FIXTURES"),
        (r"/api/event/[1-9][0-9]*/live/", "EVENT_LIVE"),
        (r"/api/entry/[1-9][0-9]*/", "ENTRY"),
        (r"/api/entry/[1-9][0-9]*/history/", "HISTORY"),
        (r"/api/entry/[1-9][0-9]*/event/[1-9][0-9]*/picks/", "PICKS"),
        (r"/api/entry/[1-9][0-9]*/transfers/", "TRANSFERS"),
        (r"/api/my-team/[1-9][0-9]*/", "MY_TEAM"),
    )
    for pattern, endpoint in patterns:
        if re.fullmatch(pattern, path):
            return endpoint
    raise ValueError("unrecognized FPL endpoint")


@dataclass
class OneShotNetworkGate:
    started_at: datetime
    cutoff: datetime
    clock: Callable[[], datetime] = field(repr=False)
    closed: bool = False
    consumed: bool = False
    denied: int = 0
    counts: dict[Provider, int] = field(
        default_factory=lambda: {"FPL": 0, "ODDS": 0, "OPENFOOTBALL": 0}
    )
    fpl_endpoints: list[str] = field(default_factory=list)
    fpl_sessions: int = 0
    odds_acquisitions: int = 0
    league_acquisitions: int = 0

    def window(self) -> None:
        now = self.clock()
        if (
            now.tzinfo is None
            or now.utcoffset() is None
            or not self.started_at <= now <= self.cutoff
        ):
            raise ValueError("provider acquisition window unavailable")

    def preparation_guard(self) -> None:
        # The accepted one-command seam calls this again after Stage 7. Its
        # deterministic work may outlive the network window, but sends may not.
        if not self.closed:
            self.window()

    def attempt(self, provider: Provider, endpoint: str = "") -> None:
        if self.closed:
            self.denied += 1
            raise ValueError("provider access is closed")
        self.window()
        if provider == "ODDS" and self.counts[provider] != 0:
            self.denied += 1
            raise ValueError("one-shot Odds attempt already consumed")
        self.counts[provider] += 1
        if provider in {"FPL", "ODDS"}:
            # This boundary is immediately before transport.send, including a
            # failed send. Factory/credential/preflight failures do not consume.
            self.consumed = True
        if provider == "FPL":
            self.fpl_endpoints.append(endpoint)

    def counters(self) -> tuple[int, ...]:
        return (
            *self.counts.values(),
            self.fpl_sessions,
            self.odds_acquisitions,
            self.league_acquisitions,
            self.denied,
        )


@dataclass(repr=False)
class GuardedFplTransport:
    gate: OneShotNetworkGate
    delegate: DirectTransport

    def send(self, request: DirectHttpRequest) -> DirectHttpResponse:
        endpoint = fpl_endpoint(request.path)
        self.gate.attempt("FPL", endpoint)
        return self.delegate.send(request)


@dataclass(repr=False)
class GuardedOddsTransport:
    gate: OneShotNetworkGate
    delegate: OddsTransport
    transport_id: Literal["injected"] = "injected"

    def send(self, request: OddsHttpRequest, credential: str) -> OddsHttpResponse:
        self.gate.attempt("ODDS")
        return self.delegate.send(request, credential)


@dataclass(repr=False)
class GuardedOpenFootballTransport:
    gate: OneShotNetworkGate
    delegate: OpenFootballTransport
    transport_id: str = "injected"

    def send(self, request: OpenFootballHttpRequest) -> OpenFootballHttpResponse:
        self.gate.attempt("OPENFOOTBALL")
        return self.delegate.send(request)
