"""Offline approved transport, acquisition timestamps and reconstructed corpus."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.openfootball.client import (
    OpenFootballHttpRequest,
    OpenFootballHttpResponse,
)
from dmf_pulse.ingestion.openfootball.team_strength_acquisition import (
    acquire_team_strength_snapshot,
)
from dmf_pulse.ingestion.openfootball.team_strength_corpus import load_reconstructed_corpus
from tests.unit.ingestion.openfootball.test_team_strength_data import STAMP, registry, source

SYNTHETIC_LICENCE = b"SYNTHETIC LICENCE; NOT APPROVED"


@pytest.fixture
def licence_digest_double(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the licence digest is doubled; real-licence checks run in private acceptance.

    This permits branch coverage without redistributing retained provider material.
    Every source-content/blob hash remains real, and malformed licences still fail.
    """
    sha256, sha1 = hashlib.sha256, hashlib.sha1

    def digest256(body: bytes = b"", **kwargs: Any) -> Any:
        if body == SYNTHETIC_LICENCE:
            return SimpleNamespace(
                hexdigest=lambda: "36ffd9dc085d529a7e60e1276d73ae5a030b020313e6c5408593a6ae2af39673"
            )
        return sha256(body, **kwargs)

    def digest1(body: bytes = b"", **kwargs: Any) -> Any:
        if body == f"blob {len(SYNTHETIC_LICENCE)}\0".encode() + SYNTHETIC_LICENCE:
            return SimpleNamespace(hexdigest=lambda: "670154e3538863b2d9891fd5483160fbdfc89164")
        return sha1(body, **kwargs)

    monkeypatch.setattr(hashlib, "sha256", digest256)
    monkeypatch.setattr(hashlib, "sha1", digest1)


class Transport:
    transport_id = "OFFLINE_TEST"

    def __init__(self, body: bytes, *, status: int = 200, licence: bytes | None = None) -> None:
        self.body = body
        self.status = status
        self.licence = licence
        self.requests: list[OpenFootballHttpRequest] = []

    def send(self, request: OpenFootballHttpRequest) -> OpenFootballHttpResponse:
        self.requests.append(request)
        body = self.body
        if request.path.endswith("LICENSE.md"):
            body = self.licence if self.licence is not None else SYNTHETIC_LICENCE
        return OpenFootballHttpResponse(
            status_code=self.status, content_type="text/plain", headers={}, body=body
        )


def test_acquisition_uses_pinned_credential_free_boundary() -> None:
    body, lineage = source()
    fixtures = registry()
    transport = Transport(body)
    times = iter(STAMP + timedelta(seconds=i) for i in range(4))
    with pytest.raises(ValueError, match="licence"):
        acquire_team_strength_snapshot(
            resource=lineage.resource,
            expected_resource_sha256=canonical_sha256(lineage.resource),
            fixtures=fixtures,
            expected_fixture_registry_sha256=fixtures.semantic_sha256,
            transport=transport,
            clock=lambda: next(times),
        )
    assert len(transport.requests) == 1
    assert all(
        request.host == "raw.githubusercontent.com" and "/" + "a" * 40 + "/" in request.path
        for request in transport.requests
    )


def test_acquisition_success_with_synthetic_licence_double(licence_digest_double: None) -> None:
    body, lineage = source()
    fixtures = registry()
    transport = Transport(body)
    times = iter(STAMP + timedelta(seconds=i) for i in range(4))
    result = acquire_team_strength_snapshot(
        resource=lineage.resource,
        expected_resource_sha256=canonical_sha256(lineage.resource),
        fixtures=fixtures,
        expected_fixture_registry_sha256=fixtures.semantic_sha256,
        transport=transport,
        clock=lambda: next(times),
    )
    assert len(transport.requests) == 2
    assert result.raw_bytes == body and result.snapshot.lineage.usable_at == STAMP + timedelta(
        seconds=3
    )
    assert result.snapshot.matches[0].home_goals == 2


@pytest.mark.parametrize("failure", ["descriptor", "fixture", "licence", "status", "body", "clock"])
def test_acquisition_failure_is_finite_and_closed(
    failure: str, licence_digest_double: None
) -> None:
    body, lineage = source()
    fixtures = registry()
    transport = Transport(
        body + b" " if failure == "body" else body,
        status=302 if failure == "status" else 200,
        licence=b"invalid" if failure == "licence" else None,
    )
    with pytest.raises(ValueError):
        acquire_team_strength_snapshot(
            resource=lineage.resource,
            expected_resource_sha256="0" * 64
            if failure == "descriptor"
            else canonical_sha256(lineage.resource),
            fixtures=fixtures,
            expected_fixture_registry_sha256="0" * 64
            if failure == "fixture"
            else fixtures.semantic_sha256,
            transport=transport,
            clock=lambda: STAMP.replace(tzinfo=None) if failure == "clock" else STAMP,
        )
    if failure in {"descriptor", "fixture", "clock"}:
        assert transport.requests == []
    elif failure == "body":
        assert len(transport.requests) == 2
    else:
        assert len(transport.requests) == 1


def test_missing_private_corpus_cannot_be_fabricated(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        load_reconstructed_corpus(tmp_path)


@pytest.mark.parametrize("last", [STAMP - timedelta(seconds=1), STAMP.replace(tzinfo=None)])
def test_post_fetch_bad_clock_is_rejected(last: Any, licence_digest_double: None) -> None:
    body, lineage = source()
    fixtures = registry()
    transport = Transport(body)
    times = iter((STAMP, STAMP, STAMP, last))
    with pytest.raises(ValueError, match=r"order|timezone"):
        acquire_team_strength_snapshot(
            resource=lineage.resource,
            expected_resource_sha256=canonical_sha256(lineage.resource),
            fixtures=fixtures,
            expected_fixture_registry_sha256=fixtures.semantic_sha256,
            transport=transport,
            clock=lambda: next(times),
        )
    assert len(transport.requests) == 2
