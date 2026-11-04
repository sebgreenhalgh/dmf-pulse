"""Owned next-event provider shapes; no real records, credentials or transport."""

import json
from copy import deepcopy
from datetime import timedelta

from dmf_pulse.dashboard.current_sources import GuardedFplTransport
from dmf_pulse.ingestion.fpl.direct import DirectFplClient, DirectFplCredentialProvider
from dmf_pulse.operation.diagnostics import DiagnosticLog
from tests.unit.dashboard.post_gw10_support import CANARY, NOW, OwnedFpl, OwnedGuard, owned_bodies

GW11_NOW = NOW + timedelta(days=7)


def owned_gw11_bodies(repository_root, *, played=True, future_copies=True):
    bodies = {path: json.loads(body) for path, body in owned_bodies(repository_root).items()}
    bootstrap = bodies["/api/bootstrap-static/"]
    for row in bootstrap["events"]:
        gw = row["id"]
        row.update(
            finished=gw <= 10,
            data_checked=gw <= 10,
            is_previous=gw == 9,
            is_current=gw == 10,
            is_next=gw == 11,
        )
    for player in bootstrap["elements"]:
        player["minutes"] = player["minutes"] * 10 // 8
        player["starts"] = player["starts"] * 10 // 8
    for row in bodies["/api/fixtures/"]:
        row.update(finished=row["event"] <= 10, started=row["event"] <= 10)
    history = bodies["/api/entry/42/history/"]
    template = deepcopy(history["current"][0])
    history["current"] = [
        {**template, "event": gw, "points": 60, "total_points": gw * 60} for gw in range(1, 11)
    ]
    bodies["/api/entry/42/"]["summary_overall_points"] = 600
    bodies["/api/entry/42/event/10/picks/"] = bodies.pop("/api/entry/42/event/8/picks/")
    live = bodies["/api/event/1/live/"]
    for gw in (9, 10):
        bodies[f"/api/event/{gw}/live/"] = deepcopy(live)
    current = bodies["/api/my-team/42/"]
    if played:
        current["chips"][0].update(status_for_entry="played", played_by_entry=[2])
    if future_copies:
        current["chips"] = [
            copy
            for chip in current["chips"]
            for copy in (
                chip,
                {**chip, "number": 2, "status_for_entry": "unavailable", "played_by_entry": []},
            )
        ]
    return {path: json.dumps(body, separators=(",", ":")).encode() for path, body in bodies.items()}


def gw11_direct_factory(bodies, diagnostics=None):
    log = diagnostics or DiagnosticLog(clock=lambda: GW11_NOW)
    transport = OwnedFpl(bodies, None)
    guard = OwnedGuard(log, {("FPL", "GET", "fantasy.premierleague.com", path) for path in bodies})

    def factory(attestation):
        return DirectFplClient(
            attestation,
            transport=GuardedFplTransport(guard, transport),
            credential_provider=DirectFplCredentialProvider({"DMF_FPL_BEARER_TOKEN": CANARY}),
            maximum_attempts=1,
            sleeper=lambda _: None,
            pace_seconds=0,
            clock=lambda: GW11_NOW,
            before_credential=lambda method, host, path: guard.preflight_send(
                "FPL", method, host, path
            ),
        )

    return factory, guard, transport, log
