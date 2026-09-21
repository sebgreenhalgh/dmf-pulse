"""Offline temporal, rights and authenticated individual-match source checks."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability
from dmf_pulse.ingestion.openfootball.config import load_rights_profiles
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    FixtureRegistration,
    FixtureRegistry,
    SourceLineage,
    SourceResource,
    TeamStrengthHistoricalDatasetV1,
    authenticate,
    build_dataset,
    parse_snapshot,
    require_team_strength_rights,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    load_historical_team_identity,
    resolve_openfootball_team,
)

STAMP = datetime(2026, 10, 1, tzinfo=UTC)
COMPETITION = UUID("019a0100-0000-7000-8000-000000000001")
FIXTURE = UUID("019a0100-0000-7000-8000-000000000002")


def registry() -> FixtureRegistry:
    identity = load_historical_team_identity()
    registration = FixtureRegistration(
        fixture_id=FIXTURE,
        competition_id=COMPETITION,
        season="2026/27",
        home_team_id=resolve_openfootball_team(
            identity, season_code="2026/27", source_team_name="Arsenal FC"
        ),
        away_team_id=resolve_openfootball_team(
            identity, season_code="2026/27", source_team_name="Chelsea FC"
        ),
    )
    return seal(
        FixtureRegistry,
        competition_id=COMPETITION,
        registration_authority="SYNTHETIC_TEST_ONLY",
        registered_at=STAMP,
        fixtures=(registration,),
    )


def raw_match(**updates: Any) -> dict[str, Any]:
    result = {
        "team1": "Arsenal FC",
        "team2": "Chelsea FC",
        "date": "2026-09-29",
        "round": "Matchday 1",
        "time": "12:45",
        "score": {"ft": [2, 1]},
    }
    result.update(updates)
    return result


def source(
    rows: list[dict[str, Any]] | None = None,
    *,
    received: datetime | None = None,
    body: bytes | None = None,
    previous: str | None = None,
) -> tuple[bytes, SourceLineage]:
    if body is None:
        body = json.dumps(
            {"name": "English Premier League 2026/27", "matches": rows or [raw_match()]}
        ).encode()
    received = received or STAMP - timedelta(hours=1)
    descriptor = SourceResource(
        commit="a" * 40,
        path="2026-27/en.1.json",
        season="2026/27",
        git_blob_sha1=hashlib.sha1(
            f"blob {len(body)}\0".encode() + body, usedforsecurity=False
        ).hexdigest(),
        content_sha256=hashlib.sha256(body).hexdigest(),
        byte_length=len(body),
    )
    return body, seal(
        SourceLineage,
        resource=descriptor,
        retrieval_started_at=received - timedelta(seconds=1),
        received_at=received,
        validated_at=received + timedelta(microseconds=1),
        usable_at=received + timedelta(microseconds=2),
        acquisition="LOCAL_IMMUTABLE_IMPORT",
        predecessor_snapshot_sha256=previous,
    )


def dataset(
    *,
    cutoff: datetime = STAMP,
    mode: str = "LIVE_OBSERVED",
    received: datetime | None = None,
    rows: list[dict[str, Any]] | None = None,
    training_cutoff: datetime | None = None,
) -> TeamStrengthHistoricalDatasetV1:
    fixtures = registry()
    body, lineage = source(rows, received=received)
    snapshot = parse_snapshot(
        body,
        lineage=lineage,
        fixtures=fixtures,
        expected_fixture_registry_sha256=fixtures.semantic_sha256,
    )
    return build_dataset(
        sources=(snapshot,),
        fixtures=fixtures,
        expected_fixture_registry_sha256=fixtures.semantic_sha256,
        information_cutoff=cutoff,
        training_cutoff=training_cutoff or cutoff,
        forecast_season="2026/27",
        mode=mode,
    )


def test_d_plus_two_exact_boundary_and_date_precision() -> None:
    early = dataset(cutoff=STAMP - timedelta(seconds=1))
    accepted = dataset()
    assert early.matches == ()
    assert len(accepted.matches) == 1
    assert accepted.matches[0].observation.kickoff_utc is None
    assert accepted.matches[0].observation.time_precision == "DATE_ONLY"
    assert accepted.freshness.value == "FRESH"
    assert authenticate(accepted) == accepted


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(hours=24), "FRESH"),
        (timedelta(hours=24, microseconds=1), "DEGRADED"),
        (timedelta(hours=72), "DEGRADED"),
        (timedelta(hours=72, microseconds=1), "STALE_BLOCKED"),
    ],
)
def test_retrieval_age_boundaries(age: timedelta, expected: str) -> None:
    assert dataset(received=STAMP - age).freshness.value == expected


@pytest.mark.parametrize(
    "status", ["postponed", "abandoned", "cancelled", "suspended", "FT", "unknown"]
)
def test_nonfinal_and_unknown_status_are_excluded_and_block_due(status: str) -> None:
    result = dataset(rows=[raw_match(status=status)])
    assert result.matches == ()
    assert result.missing_due == 1
    assert result.freshness.value == "STALE_BLOCKED"


def test_recent_commit_cannot_mask_missing_due() -> None:
    result = dataset(rows=[raw_match(score=None)], received=STAMP - timedelta(seconds=1))
    assert result.missing_due == 1 and result.freshness.value == "STALE_BLOCKED"


@pytest.mark.parametrize("omitted", ["2025/26", "2026/27"])
def test_whole_missing_season_cannot_claim_fresh(omitted: str) -> None:
    base = registry()
    earlier = base.fixtures[0].model_copy(
        update={
            "fixture_id": UUID("019a0100-0000-7000-8000-000000000003"),
            "season": "2025/26",
        }
    )
    fixtures = seal(
        FixtureRegistry,
        **base.model_dump(mode="python", exclude={"semantic_sha256", "fixtures"}),
        fixtures=tuple(sorted((*base.fixtures, earlier), key=lambda row: row.fixture_id)),
    )
    body, lineage = source()
    if omitted == "2026/27":
        body, lineage = source(body=body.replace(b"2026/27", b"2025/26"))
        resource = lineage.resource.model_copy(
            update={"season": "2025/26", "path": "2025-26/en.1.json"}
        )
        lineage = seal(
            SourceLineage,
            **lineage.model_dump(mode="python", exclude={"semantic_sha256", "resource"}),
            resource=resource,
        )
    snapshot = parse_snapshot(
        body,
        lineage=lineage,
        fixtures=fixtures,
        expected_fixture_registry_sha256=fixtures.semantic_sha256,
    )
    with pytest.raises(ValueError, match="season coverage"):
        build_dataset(
            sources=(snapshot,),
            fixtures=fixtures,
            expected_fixture_registry_sha256=fixtures.semantic_sha256,
            information_cutoff=STAMP,
            training_cutoff=STAMP,
            forecast_season="2026/27",
            mode="LIVE_OBSERVED",
        )


def test_postponed_revised_played_date_restarts_d_plus_two() -> None:
    result = dataset(rows=[raw_match(date="2026-09-30")])
    assert not result.matches and result.missing_due == 0


@pytest.mark.parametrize(
    "score", [{"ft": {"ft": [2, 1]}}, {"ft": [2, 1], "ht": {"ft": [1, 0]}}, {"ft": None}]
)
def test_nested_or_null_full_time_score_is_not_recognized(score: object) -> None:
    with pytest.raises(ValueError, match="score"):
        dataset(rows=[raw_match(score=score)])


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(microseconds=1), timedelta(hours=1)])
def test_post_cutoff_receipt_or_usable_is_rejected(offset: timedelta) -> None:
    with pytest.raises(ValueError, match="cutoff"):
        dataset(received=STAMP + offset)


def test_reconstructed_history_preserves_actual_receipt() -> None:
    cutoff = STAMP - timedelta(days=1)
    result = dataset(
        mode="RECONSTRUCTED", training_cutoff=cutoff, rows=[raw_match(date="2026-09-27")]
    )
    assert result.matches[0].source.received_at > cutoff
    assert result.dataset_mode == "RECONSTRUCTED"
    with pytest.raises(ValueError, match="cutoffs must agree"):
        dataset(training_cutoff=cutoff)


@pytest.mark.parametrize(
    "updates",
    [
        {"team1": "arsenal fc"},
        {"team1": "Arsenal"},
        {"team1": "Blackpool FC"},
        {"team1": "Chelsea FC"},
        {"team1": "Liverpool FC"},
        {"score": [-1, 0]},
        {"score": [100, 0]},
        {"score": [True, 0]},
        {"score": [1]},
        {"score": "1-0"},
        {"score": {"ht": [1, 0]}},
        {"score": {"ht": [2, 0], "ft": [1, 0]}},
        {"score": [1.0, 0]},
        {"date": "2026-02-31"},
        {"date": "20260929"},
        {"round": "Matchday 39"},
        {"time": "25:00"},
        {"time": None},
        {"status": None},
        {"unexpected": "field"},
        {"team1": "x" * 121},
    ],
)
def test_malformed_or_unmapped_source_fails_closed(updates: dict[str, Any]) -> None:
    fixtures = registry()
    body, lineage = source([raw_match(**updates)])
    with pytest.raises(ValueError):
        parse_snapshot(
            body,
            lineage=lineage,
            fixtures=fixtures,
            expected_fixture_registry_sha256=fixtures.semantic_sha256,
        )


@pytest.mark.parametrize("score", [[2, 1], {"ft": [2, 1]}, {"ht": [1, 0], "ft": [2, 1]}])
def test_accepted_score_representations(score: object) -> None:
    assert dataset(rows=[raw_match(score=score)]).matches[0].observation.home_goals == 2


def test_duplicate_and_contradictory_fixture_fail() -> None:
    for rows in ([raw_match(), raw_match()], [raw_match(), raw_match(score=[3, 0])]):
        with pytest.raises(ValueError, match="duplicated"):
            dataset(rows=rows)


def test_corrections_create_descendants_and_do_not_mutate_original() -> None:
    fixtures = registry()
    body, first = source()
    original = parse_snapshot(
        body,
        lineage=first,
        fixtures=fixtures,
        expected_fixture_registry_sha256=fixtures.semantic_sha256,
    )
    corrected_body, descendant = source([raw_match(score=[3, 1])], previous=first.semantic_sha256)
    corrected = parse_snapshot(
        corrected_body,
        lineage=descendant,
        fixtures=fixtures,
        expected_fixture_registry_sha256=fixtures.semantic_sha256,
    )
    assert corrected.lineage.predecessor_snapshot_sha256 == original.lineage.semantic_sha256
    assert corrected.matches[0].fixture == original.matches[0].fixture
    assert corrected.semantic_sha256 != original.semantic_sha256
    assert original.matches[0].home_goals == 2


@pytest.mark.parametrize("mutation", ["score", "source", "identity", "rights", "cutoff", "fixture"])
def test_nested_tamper_invalidates_dataset(mutation: str) -> None:
    value = dataset()
    payload = value.model_dump(mode="json")
    if mutation == "score":
        payload["matches"][0]["observation"]["home_goals"] = 9
    elif mutation == "source":
        payload["sources"][0]["lineage"]["resource"]["content_sha256"] = "0" * 64
    elif mutation == "identity":
        payload["identity_registry_sha256"] = "0" * 64
    elif mutation == "rights":
        payload["sources"][0]["lineage"]["rights_config_sha256"] = "0" * 64
    elif mutation == "cutoff":
        payload["training_cutoff"] = "2026-10-02T00:00:00Z"
    else:
        payload["fixture_registry"]["fixtures"][0]["away_team_id"] = str(COMPETITION)
    with pytest.raises(ValueError):
        TeamStrengthHistoricalDatasetV1.model_validate_json(json.dumps(payload))


def test_source_descriptor_hash_and_registry_expectation_checked() -> None:
    fixtures = registry()
    body, lineage = source()
    for raw, expected in ((body + b" ", fixtures.semantic_sha256), (body, "0" * 64)):
        with pytest.raises(ValueError):
            parse_snapshot(
                raw, lineage=lineage, fixtures=fixtures, expected_fixture_registry_sha256=expected
            )


def test_rights_profile_is_purpose_exact() -> None:
    profiles = load_rights_profiles()
    require_team_strength_rights(profiles["openfootball_football_json_team_strength_v1"])
    with pytest.raises(ValueError, match="purpose"):
        require_team_strength_rights(profiles["openfootball_football_json_score_prior_v1"])


@pytest.mark.parametrize("capability", ["model_training", "public_display", "redistribution"])
def test_rights_capability_drift_fails(capability: str) -> None:
    profile = load_rights_profiles()["openfootball_football_json_team_strength_v1"]
    payload = profile.model_dump(mode="python", exclude={"capabilities"})
    payload["capabilities"] = dict(profile.capabilities)
    payload["capabilities"][RightsCapability(capability)] = (
        CapabilityValue.DENY if capability == "model_training" else CapabilityValue.ALLOW
    )
    altered = type(profile).model_validate(payload)
    with pytest.raises(ValueError):
        require_team_strength_rights(altered)


@given(days=st.integers(min_value=0, max_value=500))
def test_no_future_dated_result_enters_training(days: int) -> None:
    played = STAMP.date() + timedelta(days=days)
    result = dataset(rows=[raw_match(date=played.isoformat())])
    assert not result.matches


@pytest.mark.parametrize(
    "body",
    [b"{", b"\xff", b'{"name":"x","name":"y"}', b"[]", b'{"name":"Championship","matches":[]}'],
)
def test_malformed_json_and_competition_fail(body: bytes) -> None:
    fixtures = registry()
    raw, lineage = source(body=body)
    with pytest.raises(ValueError):
        parse_snapshot(
            raw,
            lineage=lineage,
            fixtures=fixtures,
            expected_fixture_registry_sha256=fixtures.semantic_sha256,
        )


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        dataset(cutoff=STAMP.replace(tzinfo=None))
