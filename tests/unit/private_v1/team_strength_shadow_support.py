"""Synthetic source construction only; all forecast/optimiser services stay real."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache, partial
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from dmf_pulse.football_events.team_strength_model import fit_team_strength, memberships
from dmf_pulse.ingestion.fpl.direct_payloads import DirectFplSnapshot, parse_direct_event_live
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    FixtureRegistration,
    FixtureRegistry,
    SourceLineage,
    SourceResource,
    build_dataset,
    parse_snapshot,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import load_historical_team_identity
from dmf_pulse.private_v1.automatic_inputs import (
    _AutomaticFixtureTarget,
    _build_automatic_model_minutes_for_targets,
)
from dmf_pulse.private_v1.models import seal_execution_input
from dmf_pulse.private_v1.one_command import _PrivateV1PreparedRollingContext
from dmf_pulse.private_v1.rolling_models import (
    seal_rolling_execution_input,
    seal_rolling_fixture_input,
    seal_rolling_gameweek_input,
)
from dmf_pulse.private_v1.team_strength_shadow_inputs import horizon_fixtures
from tests.unit.private_v1 import e2e_test_support as support

STAMP = datetime(2026, 10, 1, tzinfo=UTC)
CUTOFF = STAMP + timedelta(hours=2)
CAPTURED = STAMP + timedelta(minutes=30)
COMPETITION = UUID("30000000-0000-7000-8000-000000000001")
PAIRS = (((1, 2), (3, 4), (5, 6)), ((1, 4), (3, 6), (5, 2)), ((1, 6), (3, 2), (5, 4)))


@lru_cache(maxsize=4)
def synthetic_strength(variant: int = 0, mode: str = "RECONSTRUCTED"):
    """Fit a complete synthetic corpus through the unchanged accepted 001A kernel."""
    identity = load_historical_team_identity()
    membership = memberships()
    names = {
        (season, row.canonical_team_id): row.source_team_name
        for row in identity.records
        for season in row.season_scope
    }
    fixtures, bodies = [], []
    serial = 100
    clubs = tuple(club.canonical_team_id for club in identity.canonical_clubs)
    for season, teams in sorted(membership.items()):
        matches = []
        for home in sorted(teams):
            for away in sorted(teams):
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
                start = date(2026, 10, 4) if season == "2026/27" else date(int(season[:4]), 8, 1)
                row = {
                    "team1": names[(season, home)],
                    "team2": names[(season, away)],
                    "date": (start + timedelta(days=(len(matches) // 10) * 7)).isoformat(),
                    "round": f"Matchday {len(matches) // 10 + 1}",
                }
                if season != "2026/27":
                    h = 1 + serial % 3
                    a = serial % 3
                    if variant == 2:
                        # A separate, legitimate near-league synthetic data-generating
                        # process, not a model-policy change or historical retuning.
                        raw = hashlib.sha256(f"001P|{season}|{home}|{away}".encode()).digest()
                        u, v = (
                            int.from_bytes(raw[:4], "big") % 10,
                            int.from_bytes(raw[4:8], "big") % 10,
                        )
                        h = (0, 0, 1, 1, 1, 2, 2, 2, 3, 4)[u]
                        a = (0, 0, 0, 1, 1, 1, 2, 2, 3, 3)[v]
                    elif variant:
                        h += (clubs.index(home) + variant) % 2
                        a += (clubs.index(away) + variant) % 2
                    row["score"] = {"ft": [h, a]}
                matches.append(row)
        bodies.append(
            (
                season,
                json.dumps(
                    {"name": f"English Premier League {season}", "matches": matches}
                ).encode(),
            )
        )
    registry = seal(
        FixtureRegistry,
        competition_id=COMPETITION,
        registration_authority="REPOSITORY_SYNTHETIC_001P_ONLY",
        registered_at=STAMP,
        fixtures=tuple(fixtures),
    )
    sources = []
    for season, body in bodies:
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
        sources.append(
            parse_snapshot(
                body,
                lineage=lineage,
                fixtures=registry,
                expected_fixture_registry_sha256=registry.semantic_sha256,
            )
        )
    dataset = build_dataset(
        sources=tuple(sources),
        fixtures=registry,
        expected_fixture_registry_sha256=registry.semantic_sha256,
        information_cutoff=STAMP,
        training_cutoff=STAMP,
        forecast_season="2026/27",
        mode=mode,
    )
    return dataset, fit_team_strength(dataset, clock=lambda: STAMP + timedelta(seconds=1))


def synthetic_prepared(root: Path, working: Path, *, low_current_minutes: bool = False):
    """Move only synthetic source construction to a post-P0 cutoff and unique schedule.

    Patches are confined to fixture builders. No stage, optimiser, result, model,
    allocation binding, or decision is mocked or replaced.
    """
    with (
        patch.object(support, "_CAPTURED", CAPTURED),
        patch.object(support, "_CUTOFF", CUTOFF),
        patch.object(
            support,
            "_unified_context",
            partial(support._unified_context, captured_at=CAPTURED, information_cutoff=CUTOFF),
        ),
        patch.object(
            support,
            "_identity_map",
            partial(support._identity_map, captured_at=CAPTURED, information_cutoff=CUTOFF),
        ),
        patch.object(
            support,
            "_manual_inputs",
            partial(support._manual_inputs, captured_at=CAPTURED, information_cutoff=CUTOFF),
        ),
        patch.object(
            support,
            "_build_fpl_input",
            partial(support._build_fpl_input, horizon_fixture_pairs=PAIRS),
        ),
    ):
        execution = support.build_rolling_execution_input(
            root,
            working,
            target_gameweek=5,
            historical_gameweeks=4,
            force_candidate_low_current_minutes=low_current_minutes,
        )
    fpl = execution.current_execution.current_state.fpl_input
    snapshot = DirectFplSnapshot.model_construct(
        captured_at=CAPTURED,
        target_gameweek=5,
        fpl_input=fpl,
        request_count=0,
        endpoint_classes=(),
    )
    return _PrivateV1PreparedRollingContext(
        snapshot=snapshot,
        rolling_execution=execution,
        player_identity_map=execution.current_execution.player_identity_map,
        fpl_request_count=0,
        fpl_endpoint_classes=(),
        odds_request_count=0,
        odds_endpoint_classes=(),
        score_prior_acquisition_count=1,
        fpl_rights_profile_id="fpl_official_private_manual_v1",
        odds_rights_profile_id="the_odds_api_private_analytics_v1",
        information_cutoff=CUTOFF,
    )


def synthetic_model_prepared(root: Path, working: Path):
    """Fit/predict real Stage 7 once before either prior world exists."""
    prepared = synthetic_prepared(root, working)
    execution = prepared.rolling_execution
    current = execution.current_execution
    fpl = current.current_state.fpl_input
    live = {}
    for gw in range(1, 5):
        live[gw] = parse_direct_event_live(
            json.dumps(
                {
                    "elements": [
                        {
                            "id": player.provider_element_id,
                            "stats": {
                                "minutes": 80 if player.provider_element_id % 23 < 11 else 15,
                                "starts": int(player.provider_element_id % 23 < 11),
                            },
                        }
                        for player in fpl.players
                    ]
                },
                sort_keys=True,
            ).encode()
        )
    snapshot = DirectFplSnapshot.model_construct(
        **(dict(prepared.snapshot) | {"live_by_gameweek": live})
    )
    targets = tuple(
        _AutomaticFixtureTarget(
            gameweek=row.gameweek,
            fixture=row.official,
            canonical_fixture_id=row.prior.fixture_id,
            scenario="private-one-command-current"
            if row.gameweek == 5
            else "private-one-command-current-cutoff-future",
        )
        for row in horizon_fixtures(execution)
    )
    minutes = _build_automatic_model_minutes_for_targets(
        snapshot, prepared.player_identity_map, targets, progress=None
    )
    current = seal_execution_input(
        type(current).model_construct(
            **(dict(current) | {"manual_minutes": minutes.minutes_by_gameweek[5]})
        )
    )
    future = []
    for gw in execution.future_gameweeks:
        by_id = {row.fixture_id: row for row in minutes.minutes_by_gameweek[gw.gameweek]}
        fixtures = tuple(
            seal_rolling_fixture_input(
                type(row).model_construct(
                    **(dict(row) | {"stage7": by_id[str(row.canonical_fixture_id)]})
                )
            )
            for row in gw.fixtures
        )
        future.append(
            seal_rolling_gameweek_input(
                type(gw).model_construct(**(dict(gw) | {"fixtures": fixtures}))
            )
        )
    execution = seal_rolling_execution_input(
        type(execution).model_construct(
            **(dict(execution) | {"current_execution": current, "future_gameweeks": tuple(future)})
        )
    )
    return replace(prepared, snapshot=snapshot, rolling_execution=execution)
