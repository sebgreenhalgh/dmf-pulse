"""Synthetic EPL-shaped histories: no retained provider observations."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from functools import lru_cache
from uuid import UUID

from dmf_pulse.football_events.team_strength_model import (
    TeamStrengthModelArtifactV1,
    fit_team_strength,
    memberships,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    FixtureRegistration,
    FixtureRegistry,
    SourceLineage,
    SourceResource,
    TeamStrengthHistoricalDatasetV1,
    build_dataset,
    parse_snapshot,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import load_historical_team_identity
from tests.unit.ingestion.openfootball.test_team_strength_data import COMPETITION, STAMP


@lru_cache(maxsize=1)
def synthetic_dataset() -> TeamStrengthHistoricalDatasetV1:
    membership = memberships()
    identity = load_historical_team_identity()
    names = {
        (season, record.canonical_team_id): record.source_team_name
        for record in identity.records
        for season in record.season_scope
    }
    fixtures, raw_seasons = [], []
    serial = 100
    for season in sorted(s for s in membership if s <= "2025/26"):
        raw = []
        for home in sorted(membership[season]):
            for away in sorted(membership[season]):
                if home == away:
                    continue
                serial += 1
                fixtures.append(
                    FixtureRegistration(
                        fixture_id=UUID(int=(7 << 76) | (2 << 62) | serial),
                        competition_id=COMPETITION,
                        season=season,
                        home_team_id=home,
                        away_team_id=away,
                    )
                )
                raw.append(
                    {
                        "team1": names[(season, home)],
                        "team2": names[(season, away)],
                        "date": (
                            date(int(season[:4]), 8, 1) + timedelta(days=(len(raw) // 10) * 7)
                        ).isoformat(),
                        "round": f"Matchday {len(raw) // 10 + 1}",
                        "score": {"ft": [(serial * 7) % 5, (serial * 3 + 1) % 4]},
                    }
                )
        raw_seasons.append(
            (
                season,
                json.dumps({"name": f"English Premier League {season}", "matches": raw}).encode(),
            )
        )
    registry = seal(
        FixtureRegistry,
        competition_id=COMPETITION,
        registration_authority="SYNTHETIC_TEST_ONLY",
        registered_at=STAMP,
        fixtures=tuple(fixtures),
    )
    snapshots = []
    for season, body in raw_seasons:
        resource = SourceResource(
            commit="c" * 40,
            season=season,
            path=season.replace("/", "-") + "/en.1.json",
            git_blob_sha1=hashlib.sha1(
                f"blob {len(body)}\0".encode() + body, usedforsecurity=False
            ).hexdigest(),
            content_sha256=hashlib.sha256(body).hexdigest(),
            byte_length=len(body),
        )
        lineage = seal(
            SourceLineage,
            resource=resource,
            retrieval_started_at=STAMP - timedelta(hours=1),
            received_at=STAMP - timedelta(minutes=2),
            validated_at=STAMP - timedelta(minutes=1),
            usable_at=STAMP - timedelta(seconds=1),
            acquisition="LOCAL_IMMUTABLE_IMPORT",
        )
        snapshots.append(
            parse_snapshot(
                body,
                lineage=lineage,
                fixtures=registry,
                expected_fixture_registry_sha256=registry.semantic_sha256,
            )
        )
    return build_dataset(
        sources=tuple(snapshots),
        fixtures=registry,
        expected_fixture_registry_sha256=registry.semantic_sha256,
        information_cutoff=STAMP,
        training_cutoff=STAMP.replace(month=6),
        forecast_season="2025/26",
        mode="RECONSTRUCTED",
    )


@lru_cache(maxsize=1)
def synthetic_artifact() -> TeamStrengthModelArtifactV1:
    return fit_team_strength(synthetic_dataset(), clock=lambda: STAMP + timedelta(seconds=1))
