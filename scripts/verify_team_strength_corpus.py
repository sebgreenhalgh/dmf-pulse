"""Mandatory offline real-corpus acceptance using explicit private local input.

Public CI exercises synthetic source/model boundaries. This separate mandatory
acceptance command uses retained CC0 bytes without redistributing them in git.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.openfootball.client import (
    OpenFootballHttpRequest,
    OpenFootballHttpResponse,
)
from dmf_pulse.ingestion.openfootball.team_strength_acquisition import (
    acquire_team_strength_snapshot,
)
from dmf_pulse.ingestion.openfootball.team_strength_corpus import (
    FIXTURE_REGISTRY_SHA256,
    load_reconstructed_corpus,
)


class OfflineTransport:
    transport_id = "EXPLICIT_OFFLINE_RETAINED_CORPUS"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.count = 0

    def send(self, request: OpenFootballHttpRequest) -> OpenFootballHttpResponse:
        path = "/".join(request.path.split("/")[4:])
        self.count += 1
        return OpenFootballHttpResponse(
            status_code=200,
            content_type="text/plain",
            headers={},
            body=(self.root / path).read_bytes(),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    args = parser.parse_args()
    fixtures, snapshots = load_reconstructed_corpus(args.corpus_root)
    assert len(fixtures.fixtures) == 6460
    assert len(snapshots) == 16
    assert sum(len(snapshot.matches) for snapshot in snapshots) == 6080
    assert snapshots[-1].lineage.resource.season == "2025/26"
    assert all(row.finality == "FULL_TIME" for snapshot in snapshots for row in snapshot.matches)
    transport = OfflineTransport(args.corpus_root)
    start = datetime.now(UTC)
    times = iter(start + timedelta(microseconds=i) for i in range(4))
    resource = snapshots[0].lineage.resource
    result = acquire_team_strength_snapshot(
        resource=resource,
        expected_resource_sha256=canonical_sha256(resource),
        fixtures=fixtures,
        expected_fixture_registry_sha256=FIXTURE_REGISTRY_SHA256,
        transport=transport,
        clock=lambda: next(times),
    )
    assert transport.count == 2
    assert (
        result.snapshot.lineage.received_at
        < result.snapshot.lineage.validated_at
        < result.snapshot.lineage.usable_at
    )
    assert result.raw_bytes.decode() not in repr(result)
    _, current = load_reconstructed_corpus(args.corpus_root, include_current_season=True)
    assert len(current) == 17
    print(
        json.dumps(
            {
                "status": "PASS",
                "network_calls": 0,
                "historical_matches": 6080,
                "historical_seasons": 16,
                "current_season_used_for_selection": False,
                "fixture_registry_sha256": FIXTURE_REGISTRY_SHA256,
            }
        )
    )


if __name__ == "__main__":
    main()
