"""Current public preflight with generated EPL-only source bytes, zero network."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta

import pytest

from dmf_pulse.ingestion.openfootball import team_strength_current as current
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    FixtureRegistry,
    SourceLineage,
    seal,
)
from tests.unit.ingestion.openfootball.test_team_strength_acquisition import (
    SYNTHETIC_LICENCE,
    Transport,
)
from tests.unit.ingestion.openfootball.test_team_strength_acquisition import (
    licence_digest_double as licence_digest_double,
)
from tests.unit.private_v1.team_strength_shadow_support import STAMP, synthetic_strength

pytestmark = pytest.mark.unit


def reseal(value, **changes):
    values = dict(value)
    values.pop("semantic_sha256")
    return seal(type(value), **(values | changes))


@pytest.mark.parametrize("age", [25, 75])
def test_fresh_historical_retrieval_cannot_mask_old_current_season(age):
    dataset, _ = synthetic_strength(mode="LIVE_OBSERVED")
    latest = dataset.sources[-1]
    values = dict(latest.lineage)
    values.pop("semantic_sha256")
    for key in ("retrieval_started_at", "received_at", "validated_at", "usable_at"):
        values[key] -= timedelta(hours=age)
    lineage = seal(SourceLineage, **values)
    matches = tuple(
        reseal(row, source_snapshot_sha256=lineage.semantic_sha256) for row in latest.matches
    )
    old = reseal(latest, lineage=lineage, matches=matches)
    with pytest.raises(ValueError, match="current-season retrieval"):
        current.current_dataset(
            sources=(*dataset.sources[:-1], old), fixtures=dataset.fixture_registry, cutoff=STAMP
        )
    with pytest.raises(ValueError, match="current-season retrieval"):
        current.current_dataset(
            sources=dataset.sources[:-1], fixtures=dataset.fixture_registry, cutoff=STAMP
        )


@pytest.mark.parametrize(
    "commit", ["main", "HEAD", "latest", "a" * 39, "A" * 40, "a" * 40 + "/extra"]
)
def test_discovery_requires_immutable_commit_before_transport(commit):
    transport = Transport(b"{}")
    with pytest.raises(ValueError, match="immutable"):
        current.discover_current_resource(commit, transport=transport)
    assert not transport.requests


def test_discovery_checks_licence_and_http():
    for transport in (Transport(b"{}", status=302), Transport(b"{}", licence=b"invalid")):
        with pytest.raises(ValueError):
            current.discover_current_resource("a" * 40, transport=transport)


def test_discovery_seals_hashes_before_accepted_acquisition(licence_digest_double):
    transport = Transport(b'{"public":"synthetic"}')
    result = current.discover_current_resource("b" * 40, transport=transport)
    assert result.byte_length == len(transport.body)
    assert result.content_sha256 == hashlib.sha256(transport.body).hexdigest()
    assert (
        result.git_blob_sha1
        == hashlib.sha1(f"blob {len(transport.body)}\0".encode() + transport.body).hexdigest()
    )
    assert result.path == "2026-27/en.1.json"
    assert len(transport.requests) == 2


def test_registry_covers_all_upcoming_pairs():
    dataset, _ = synthetic_strength(mode="LIVE_OBSERVED")
    incomplete = seal(
        FixtureRegistry,
        **{
            **dataset.fixture_registry.model_dump(mode="python", exclude={"semantic_sha256"}),
            "fixtures": dataset.fixture_registry.fixtures[:-1],
        },
    )
    with pytest.raises(ValueError, match="three-GW"):
        current.current_dataset(sources=dataset.sources, fixtures=incomplete, cutoff=STAMP)


@pytest.mark.parametrize("change", ["reconstructed", "training_hash", "assessment"])
def test_authenticated_readiness_rejects_wrong_current_evidence(change):
    from dmf_pulse.football_events.team_strength_adapter import _source_assessment

    dataset, artifact = synthetic_strength(mode="LIVE_OBSERVED")
    assessment = _source_assessment(dataset)
    if change == "assessment":
        assessment = reseal(assessment, dataset_sha256="0" * 64)
    else:
        model = reseal(
            artifact.model,
            **(
                {"dataset_mode": "RECONSTRUCTED"}
                if change == "reconstructed"
                else {"training_dataset_sha256": "0" * 64}
            ),
        )
        artifact = reseal(artifact, model=model)
    with pytest.raises(ValueError, match="current"):
        seal(
            current.CurrentTeamStrengthReadiness,
            artifact=artifact,
            sources=dataset.sources,
            fixture_registry=dataset.fixture_registry,
            source_assessment=assessment,
        )


def test_fresh_and_degraded_source_lineage_cannot_be_confused():
    from dmf_pulse.football_events.team_strength_adapter import _source_assessment

    dataset, artifact = synthetic_strength(mode="LIVE_OBSERVED")
    latest = dataset.sources[-1]
    lineage = reseal(latest.lineage, predecessor_snapshot_sha256="a" * 64)
    newer = reseal(
        latest,
        lineage=lineage,
        matches=tuple(
            reseal(row, source_snapshot_sha256=lineage.semantic_sha256) for row in latest.matches
        ),
    )
    sources = (*dataset.sources[:-1], newer)
    fresh = current.current_dataset(
        sources=sources, fixtures=dataset.fixture_registry, cutoff=STAMP
    )
    with pytest.raises(ValueError, match="lineage"):
        seal(
            current.CurrentTeamStrengthReadiness,
            artifact=artifact,
            sources=sources,
            fixture_registry=dataset.fixture_registry,
            source_assessment=_source_assessment(fresh),
        )
    degraded = current.prepare_current_public(
        sources=sources,
        fixtures=dataset.fixture_registry,
        cutoff=STAMP + timedelta(hours=25),
        latest_artifact=artifact,
    )
    assert degraded.reason == "DEGRADED_SEALED_REUSE" and degraded.readiness.artifact == artifact


def test_fresh_fit_degraded_reuse_stale_and_unavailable(tmp_path):
    dataset, old = synthetic_strength(mode="LIVE_OBSERVED")
    fresh = current.prepare_current_public(
        sources=dataset.sources,
        fixtures=dataset.fixture_registry,
        cutoff=STAMP,
        clock=lambda: STAMP + timedelta(seconds=1),
    )
    assert fresh.readiness.artifact == old
    assert fresh.readiness.artifact.model.dataset_mode == "LIVE_OBSERVED"
    assert fresh.readiness.sources == dataset.sources
    summary = current.public_preflight_summary(fresh)
    assert summary["private_attempt_consumed"] is False
    assert summary["fitted_teams"] == 42
    assert summary["scored_rows"] == summary["due_rows"] == 0
    path = current.retain_public_readiness(fresh.readiness, artifact_root=tmp_path)
    assert current.retain_public_readiness(fresh.readiness, artifact_root=tmp_path) == path
    assert (
        current.CurrentTeamStrengthReadiness.model_validate_json(path.read_bytes())
        == fresh.readiness
    )
    path.write_bytes(b"collision")
    with pytest.raises(ValueError, match="collision"):
        current.retain_public_readiness(fresh.readiness, artifact_root=tmp_path)
    assert path.read_bytes() == b"collision"
    for hours, artifact, status, reason in (
        (25, old, "TEAM_STRENGTH_PRIOR_READY", "DEGRADED_SEALED_REUSE"),
        (25, None, "TEAM_STRENGTH_WORLD_UNAVAILABLE", "CURRENT_ARTIFACT_UNAVAILABLE"),
        (73, old, "TEAM_STRENGTH_PUBLIC_PREFLIGHT_BLOCKED", "SOURCE_STALE"),
    ):
        result = current.prepare_current_public(
            sources=dataset.sources,
            fixtures=dataset.fixture_registry,
            cutoff=STAMP + timedelta(hours=hours),
            latest_artifact=artifact,
        )
        assert (result.status, result.reason) == (status, reason)
        assert current.public_preflight_summary(result)["private_attempt_consumed"] is False
        if result.readiness:
            assert result.readiness.artifact == old


def test_acquire_pinned_current_then_fit_and_retain_public_only(licence_digest_double, tmp_path):
    from dmf_pulse.ingestion.openfootball.team_strength_governance import (
        load_historical_team_identity,
    )

    dataset, _ = synthetic_strength(mode="LIVE_OBSERVED")
    names = {
        row.canonical_team_id: row.source_team_name
        for row in load_historical_team_identity().records
        if "2026/27" in row.season_scope
    }
    matches = [
        {
            "date": "2026-10-04",
            "team1": names[row.home_team_id],
            "team2": names[row.away_team_id],
            "round": "Matchday 1",
        }
        for row in dataset.fixture_registry.fixtures
        if row.season == "2026/27"
    ]
    body = json.dumps({"name": "English Premier League 2026/27", "matches": matches}).encode()
    transport = Transport(body)
    times = iter(STAMP + timedelta(seconds=i) for i in range(20))
    result, acquired = current.acquire_current_public(
        commit="d" * 40,
        historical_sources=dataset.sources[:-1],
        fixtures=dataset.fixture_registry,
        transport=transport,
        clock=lambda: next(times),
    )
    assert len(transport.requests) == 4
    assert result.status == "TEAM_STRENGTH_PRIOR_READY"
    assert result.readiness.sources[-1] == acquired.snapshot
    current.retain_public_source(acquired, artifact_root=tmp_path)
    current.retain_public_source(acquired, artifact_root=tmp_path)
    assert (
        tmp_path / "openfootball-source-bytes" / acquired.snapshot.lineage.resource.content_sha256
    ).read_bytes() == body
    assert acquired.licence_bytes == SYNTHETIC_LICENCE
    with pytest.raises(ValueError, match="hash"):
        current.retain_public_source(
            replace(acquired, raw_bytes=b"private input"), artifact_root=tmp_path
        )
    with pytest.raises(ValueError, match="retained history"):
        current.acquire_current_public(
            commit="d" * 40,
            historical_sources=dataset.sources,
            fixtures=dataset.fixture_registry,
            transport=transport,
        )
    assert len(transport.requests) == 4
