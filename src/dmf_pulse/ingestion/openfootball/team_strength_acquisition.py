"""Explicit rights-gated acquisition through the accepted OpenFootball transport."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.client import (
    HttpClientOpenFootballTransport,
    OpenFootballHttpRequest,
    OpenFootballTransport,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    MAX_BYTES,
    FixtureRegistry,
    ParsedSnapshot,
    SourceLineage,
    SourceResource,
    StrengthEvidenceError,
    authenticate,
    parse_snapshot,
    require_team_strength_rights,
    seal,
)


@dataclass(frozen=True)
class AcquiredTeamStrengthSnapshot:
    snapshot: ParsedSnapshot
    raw_bytes: bytes = field(repr=False)
    licence_bytes: bytes = field(repr=False)


def _fetch(resource: SourceResource, path: str, transport: OpenFootballTransport) -> bytes:
    if path not in {"LICENSE.md", resource.path}:
        raise StrengthEvidenceError("source path is not allowlisted")
    request = OpenFootballHttpRequest(
        method="GET",
        scheme="https",
        host="raw.githubusercontent.com",
        path=f"/openfootball/football.json/{resource.commit}/{path}",
        connect_timeout_seconds=10,
        read_timeout_seconds=20,
        total_timeout_seconds=40,
        max_response_bytes=MAX_BYTES,
    )
    try:
        response = transport.send(request)
    except (IngestionError, OSError, TimeoutError) as exc:
        raise StrengthEvidenceError("OpenFootball source acquisition failed") from exc
    if (
        response.status_code != 200
        or response.content_type
        not in {
            "application/json",
            "text/plain",
            "application/octet-stream",
        }
        or len(response.body) > MAX_BYTES
    ):
        raise StrengthEvidenceError("OpenFootball source response is invalid")
    return response.body


def acquire_team_strength_snapshot(
    *,
    resource: SourceResource,
    expected_resource_sha256: str,
    fixtures: FixtureRegistry,
    expected_fixture_registry_sha256: str,
    transport: OpenFootballTransport | None = None,
    clock: Callable[[], datetime] | None = None,
    predecessor_snapshot_sha256: str | None = None,
) -> AcquiredTeamStrengthSnapshot:
    """Fetch only an explicitly identified immutable EPL file and its pinned licence.

    No branch resolution, persistence, retries, provider credentials or fallback.
    A correction is explicitly bound to its previous immutable snapshot identity.
    """
    require_team_strength_rights()
    resource = SourceResource.model_validate(resource.model_dump(mode="python"))
    if canonical_sha256(resource) != expected_resource_sha256:
        raise StrengthEvidenceError("source descriptor differs from expected identity")
    fixtures = authenticate(fixtures, expected_fixture_registry_sha256)
    now = clock or (lambda: datetime.now(UTC))
    started = now()
    # Validate clock before any network action.
    if started.tzinfo is None or started.utcoffset() is None:
        raise StrengthEvidenceError("acquisition clock must be timezone-aware")
    active_transport = transport or HttpClientOpenFootballTransport()
    licence = _fetch(resource, "LICENSE.md", active_transport)
    if (
        hashlib.sha256(licence).hexdigest() != resource.licence_content_sha256
        or hashlib.sha1(
            f"blob {len(licence)}\0".encode() + licence,
            usedforsecurity=False,
        ).hexdigest()
        != resource.licence_blob_sha1
    ):
        raise StrengthEvidenceError("OpenFootball licence differs from approved identity")
    body = _fetch(resource, resource.path, active_transport)
    received = now()
    # Raw hash checks precede the claimed validation timestamp.
    if (
        len(body) != resource.byte_length
        or hashlib.sha256(body).hexdigest() != resource.content_sha256
    ):
        raise StrengthEvidenceError("OpenFootball source bytes differ from descriptor")
    provisional = seal(
        SourceLineage,
        resource=resource,
        retrieval_started_at=started,
        received_at=received,
        validated_at=received,
        usable_at=received,
        acquisition="COMMIT_PINNED_HTTPS",
        predecessor_snapshot_sha256=predecessor_snapshot_sha256,
    )
    # Validate the complete immutable payload and mapping before sealing real
    # validation/usable timestamps. The provisional value is never published.
    parse_snapshot(
        body,
        lineage=provisional,
        fixtures=fixtures,
        expected_fixture_registry_sha256=expected_fixture_registry_sha256,
    )
    lineage = seal(
        SourceLineage,
        resource=resource,
        retrieval_started_at=started,
        received_at=received,
        validated_at=now(),
        usable_at=now(),
        acquisition="COMMIT_PINNED_HTTPS",
        predecessor_snapshot_sha256=predecessor_snapshot_sha256,
    )
    snapshot = parse_snapshot(
        body,
        lineage=lineage,
        fixtures=fixtures,
        expected_fixture_registry_sha256=expected_fixture_registry_sha256,
    )
    return AcquiredTeamStrengthSnapshot(snapshot, body, licence)
