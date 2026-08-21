"""Property-level traceback regressions for LIVE-ODDS-001 remediation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from dmf_pulse.ingestion.odds.client import (
    OddsClient,
    OddsHttpRequest,
    OddsHttpResponse,
    StaticCredentialProvider,
)
from dmf_pulse.ingestion.odds.config import load_provider_config, load_rights_profiles
from dmf_pulse.ingestion.odds.parser import parse_odds_payload

pytestmark = pytest.mark.security

CANARY_A = "traceback-credential-" + "canary-913579"
CANARY_B = "traceback-provider-" + "canary-246802"
CANARIES = (CANARY_A, CANARY_B)


def _contains_canary(value: object, *, seen: set[int] | None = None) -> bool:
    visited = set() if seen is None else seen
    if id(value) in visited:
        return False
    visited.add(id(value))
    if isinstance(value, str):
        return any(canary in value for canary in CANARIES)
    if isinstance(value, bytes):
        return any(canary.encode() in value for canary in CANARIES)
    if isinstance(value, Mapping):
        return any(
            _contains_canary(key, seen=visited) or _contains_canary(item, seen=visited)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_canary(item, seen=visited) for item in value)
    if isinstance(value, OddsHttpRequest):
        return _contains_canary(value.credential, seen=visited)
    if isinstance(value, OddsHttpResponse):
        return _contains_canary(value.body, seen=visited) or _contains_canary(
            value.headers, seen=visited
        )
    return False


def _production_traceback_hits(error: BaseException) -> tuple[tuple[str, str], ...]:
    hits: set[tuple[str, str]] = set()
    pending: list[BaseException] = [error]
    seen_errors: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen_errors:
            continue
        seen_errors.add(id(current))
        for nested in (current.__cause__, current.__context__):
            if nested is not None:
                pending.append(nested)
        traceback = current.__traceback__
        while traceback is not None:
            frame = traceback.tb_frame
            filename = frame.f_code.co_filename.replace("\\", "/")
            if "/src/dmf_pulse/" in filename:
                for name, value in frame.f_locals.items():
                    if _contains_canary(value):
                        hits.add((frame.f_code.co_name, name))
            traceback = traceback.tb_next
    return tuple(sorted(hits))


class _EchoFailureTransport:
    transport_id = "traceback-reproduction"

    def send(self, _request: OddsHttpRequest) -> OddsHttpResponse:
        body = json.dumps({"api" + "Key": CANARY_A, "provider_note": CANARY_B}).encode()
        return OddsHttpResponse(
            500,
            "application/json",
            {
                "x-requests-remaining": "498",
                "x-requests-used": "2",
                "x-requests-last": "2",
                "x-request-id": CANARY_B,
            },
            body,
            None,
        )


def test_sec_tb_fetch_failure_has_no_secret_bearing_production_locals() -> None:
    client = OddsClient(
        load_rights_profiles()["the_odds_api_private_analytics_v1"],
        credential_provider=StaticCredentialProvider(CANARY_A),
        transport_factory=_EchoFailureTransport,
        clock=lambda: datetime(2026, 8, 20, 12, tzinfo=UTC),
        sleeper=lambda _seconds: None,
        monotonic=lambda: 0.0,
    )

    with pytest.raises(Exception) as raised:
        client.fetch()

    assert _production_traceback_hits(raised.value) == ()
    assert all(canary not in str(raised.value) for canary in CANARIES)


def test_sec_tb_parser_redacts_before_early_structured_validation() -> None:
    oversized = CANARY_B + ("x" * (load_provider_config().max_text_length + 1))
    body = json.dumps([{"api" + "Key": oversized}]).encode()

    with pytest.raises(Exception) as raised:
        parse_odds_payload(body)

    assert _production_traceback_hits(raised.value) == ()
    assert all(canary not in str(raised.value) for canary in CANARIES)
