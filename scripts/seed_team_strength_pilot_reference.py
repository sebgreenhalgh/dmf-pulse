"""Authenticate original P01 read-only; freeze portable public assignment metadata."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_sha256, pretty_json, sha256_file
from dmf_pulse.evaluation.team_strength_campaign import forecast_assignment
from dmf_pulse.evaluation.team_strength_prospective_store import load_public_forecast
from dmf_pulse.evaluation.team_strength_protocol import P01_SHA, load_protocol

ROOT = Path(__file__).resolve().parents[1]
PILOT_ROOT = ROOT.parents[1] / "artifacts/public-prospective/CURRENT-TEAM-STRENGTH-001V-P01"


def deny_network(event: str, arguments: tuple[object, ...]) -> None:
    del arguments
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"}:
        raise RuntimeError("protocol ticket is offline")


def main() -> None:
    sys.addaudithook(deny_network)
    path = PILOT_ROOT / "public-team-strength-prospective" / f"{P01_SHA}.json"
    before = sha256_file(path)
    if before != "e3b7db4ef8db933a6ff5ed940bbe0a250601ad1780361fbef4195282ed27f2ee":
        raise ValueError("P01 original immutable bytes differ")
    forecast = load_public_forecast(path, expected_forecast_sha256=P01_SHA)
    assignment = forecast_assignment(forecast, cohort_id="P01", protocol=load_protocol())
    destination = ROOT / "config/evaluation/team_strength_p01_reference.json"
    body = pretty_json(assignment)
    if destination.exists():
        if destination.read_text(encoding="utf-8") != body:
            raise ValueError("P01 assignment metadata cannot be rewritten")
    else:
        with destination.open("x", encoding="utf-8", newline="\n") as output:
            output.write(body)
    assert sha256_file(path) == before
    report = {
        "status": "PASS",
        "p01_forecast_sha256": P01_SHA,
        "p01_bytes_sha256_before": before,
        "p01_bytes_sha256_after": sha256_file(path),
        "pilot_reference_sha256": canonical_sha256(assignment),
        "inspected_realized_p01_outcomes": False,
        "p01_scored": False,
        "fpl_requests": 0,
        "odds_requests": 0,
        "all_provider_requests": 0,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    evidence = ROOT / "evidence/tickets/CURRENT-TEAM-STRENGTH-001V-PROTOCOL"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "P01-PRESERVATION.json").write_text(pretty_json(report), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
