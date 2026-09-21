"""Import P0-pinned public research blobs offline, preserving registered fixtures.

An explicit first registration creates nondeterministic UUIDv7 fixture/competition
IDs. Subsequent executions reuse that registry and refuse to overwrite evidence.
No network or FPL/Odds access. Not invoked by ordinary tests or package imports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.ingestion.openfootball.team_strength_corpus import load_reconstructed_corpus
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    FixtureRegistration,
    FixtureRegistry,
    SourceLineage,
    SourceResource,
    parse_snapshot,
    require_team_strength_rights,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    load_historical_team_identity,
    resolve_openfootball_team,
)


def uuid7(registered_at: datetime) -> UUID:
    millis = int(registered_at.timestamp() * 1000)
    random = secrets.randbits(74)
    return UUID(
        int=(millis << 80)
        | (7 << 76)
        | ((random >> 62) << 64)
        | (2 << 62)
        | (random & ((1 << 62) - 1))
    )


def write_once(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise ValueError("immutable corpus artifact already exists with different bytes")
        return
    with path.open("xb") as handle:
        handle.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", type=Path, required=True)
    parser.add_argument("--initial-registration", action="store_true")
    args = parser.parse_args()
    require_team_strength_rights()
    root = Path(__file__).resolve().parents[1]
    # Source rights permit private retention, not redistribution in this public repository.
    destination = root / "review_pack/private_openfootball_corpus"
    if (destination / "corpus.json").exists():
        # Authenticate prior receipt/mapping/resource identities before doing any writes.
        # Legitimate reuse retains those timestamps; corrupt manifests never look successful.
        load_reconstructed_corpus(destination, include_current_season=True)
    identity = load_historical_team_identity()
    registry_path = destination / "fixture_registry.json"
    existing = (
        FixtureRegistry.model_validate_json(registry_path.read_bytes())
        if registry_path.exists()
        else None
    )
    if existing is None and not args.initial_registration:
        parser.error("first creation requires --initial-registration")
    started = datetime.now(UTC)
    registered_at = started.replace(microsecond=(started.microsecond // 1000) * 1000)
    competition = existing.competition_id if existing else uuid7(registered_at)

    def read_blob(path: str) -> bytes:
        return subprocess.check_output(
            [
                "git",
                "-C",
                str(args.source_repository),
                "show",
                f"{identity.source_commit_sha}:{path}",
            ],
            timeout=30,
        )

    licence = read_blob("LICENSE.md")
    if (
        hashlib.sha256(licence).hexdigest()
        != "36ffd9dc085d529a7e60e1276d73ae5a030b020313e6c5408593a6ae2af39673"
    ):
        raise ValueError("licence content differs from approval")
    bodies: dict[str, bytes] = {}
    registrations = []
    lineages = []
    for snapshot in identity.source_snapshots:
        body = read_blob(snapshot.path)
        received = datetime.now(UTC)
        if hashlib.sha256(body).hexdigest() != snapshot.content_sha256:
            raise ValueError("source hash differs from P0")
        payload = json.loads(body)
        if existing is None:
            for row in payload["matches"]:
                registrations.append(
                    FixtureRegistration(
                        fixture_id=uuid7(registered_at),
                        competition_id=competition,
                        season=snapshot.season_code,
                        home_team_id=resolve_openfootball_team(
                            identity,
                            season_code=snapshot.season_code,
                            source_team_name=row["team1"],
                        ),
                        away_team_id=resolve_openfootball_team(
                            identity,
                            season_code=snapshot.season_code,
                            source_team_name=row["team2"],
                        ),
                    )
                )
        resource = SourceResource(
            commit=snapshot.commit_sha,
            path=snapshot.path,
            season=snapshot.season_code,
            content_sha256=snapshot.content_sha256,
            byte_length=len(body),
            git_blob_sha1=hashlib.sha1(
                f"blob {len(body)}\0".encode() + body, usedforsecurity=False
            ).hexdigest(),
        )
        # A later complete parser check precedes the final published validation timestamp.
        lineages.append(
            seal(
                SourceLineage,
                resource=resource,
                retrieval_started_at=started,
                received_at=received,
                validated_at=received,
                usable_at=received,
                acquisition="LOCAL_IMMUTABLE_IMPORT",
            )
        )
        bodies[snapshot.path] = body
    fixtures = existing or seal(
        FixtureRegistry,
        competition_id=competition,
        registration_authority="CURRENT-TEAM-STRENGTH-001A#fixture-registration-v1",
        registered_at=registered_at,
        fixtures=tuple(sorted(registrations, key=lambda row: row.fixture_id)),
    )
    for lineage in lineages:
        parse_snapshot(
            bodies[lineage.resource.path],
            lineage=lineage,
            fixtures=fixtures,
            expected_fixture_registry_sha256=fixtures.semantic_sha256,
        )
    validated_at = datetime.now(UTC)
    usable_at = datetime.now(UTC)
    manifest = {
        "schema_version": "team-strength-offline-corpus-v1",
        "dataset_mode": "RECONSTRUCTED",
        "historical_availability_claimed": False,
        "fixture_registry_sha256": fixtures.semantic_sha256,
        "sources": [
            seal(
                SourceLineage,
                resource=lineage.resource,
                retrieval_started_at=started,
                received_at=lineage.received_at,
                validated_at=validated_at,
                usable_at=usable_at,
                acquisition="LOCAL_IMMUTABLE_IMPORT",
            ).model_dump(mode="json")
            for lineage in lineages
        ],
    }
    for path, body in bodies.items():
        write_once(destination / path, body)
    write_once(destination / "LICENSE.md", licence)
    write_once(registry_path, pretty_json(fixtures).encode())
    manifest_path = destination / "corpus.json"
    if not manifest_path.exists():
        write_once(manifest_path, pretty_json(manifest).encode())
    print(
        json.dumps(
            {
                "source_files": len(bodies),
                "fixtures": len(fixtures.fixtures),
                "fixture_registry_sha256": fixtures.semantic_sha256,
                "corpus_content_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
