"""Public-only immutable current-source preflight. No FPL, Odds or private state.

Retained historical final vintages retain their original receipt timestamps. A new
LIVE_OBSERVED dataset means availability at today's forecast cutoff, never a claim
of availability at historical replay cutoffs. Existing replay objects are untouched.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator

from dmf_pulse.assurance.canonical import canonical_sha256, pretty_json
from dmf_pulse.football_events.team_strength_adapter import (
    TeamStrengthSourceAssessmentV1,
    _source_assessment,
    prepare_team_strength,
)
from dmf_pulse.football_events.team_strength_model import TeamStrengthModelArtifactV1, memberships
from dmf_pulse.football_events.team_strength_store import persist_team_strength
from dmf_pulse.ingestion.openfootball.client import (
    HttpClientOpenFootballTransport,
    OpenFootballHttpRequest,
    OpenFootballTransport,
)
from dmf_pulse.ingestion.openfootball.team_strength_acquisition import (
    AcquiredTeamStrengthSnapshot,
    acquire_team_strength_snapshot,
)
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    MAX_BYTES,
    FixtureRegistry,
    ParsedSnapshot,
    SealedEvidence,
    SourceResource,
    TeamStrengthHistoricalDatasetV1,
    authenticate,
    build_dataset,
    require_team_strength_rights,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import eligibility_not_before

CURRENT_SEASON = "2026/27"
CURRENT_PATH = "2026-27/en.1.json"


def _complete_current_registry(fixtures: FixtureRegistry) -> None:
    clubs = memberships()[CURRENT_SEASON]
    actual = {
        (row.home_team_id, row.away_team_id)
        for row in fixtures.fixtures
        if row.season == CURRENT_SEASON
    }
    if actual != {(home, away) for home in clubs for away in clubs if home != away}:
        raise ValueError("current EPL registry cannot cover an arbitrary three-GW horizon")


def discover_current_resource(
    commit: str, *, transport: OpenFootballTransport | None = None
) -> SourceResource:
    """Explicit immutable commit only; independently reacquired by the accepted API.

    Descriptor discovery is not accepted training evidence. Both licence and source
    hashes are checked again by acquire_team_strength_snapshot before parsing/use.
    """
    require_team_strength_rights()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("an explicit immutable commit is required")
    active = transport or HttpClientOpenFootballTransport()
    bodies = []
    for path in ("LICENSE.md", CURRENT_PATH):
        response = active.send(
            OpenFootballHttpRequest(
                method="GET",
                scheme="https",
                host="raw.githubusercontent.com",
                path=f"/openfootball/football.json/{commit}/{path}",
                connect_timeout_seconds=10,
                read_timeout_seconds=20,
                total_timeout_seconds=40,
                max_response_bytes=MAX_BYTES,
            )
        )
        if (
            response.status_code != 200
            or len(response.body) > MAX_BYTES
            or response.content_type
            not in {"application/json", "text/plain", "application/octet-stream"}
        ):
            raise ValueError("public discovery response invalid")
        bodies.append(response.body)
    licence, body = bodies
    if (
        hashlib.sha256(licence).hexdigest()
        != "36ffd9dc085d529a7e60e1276d73ae5a030b020313e6c5408593a6ae2af39673"
    ):
        raise ValueError("immutable licence differs")
    return SourceResource(
        commit=commit,
        path=CURRENT_PATH,
        season=CURRENT_SEASON,
        content_sha256=hashlib.sha256(body).hexdigest(),
        byte_length=len(body),
        git_blob_sha1=hashlib.sha1(
            f"blob {len(body)}\0".encode() + body, usedforsecurity=False
        ).hexdigest(),
    )


def current_dataset(
    *, sources: tuple[ParsedSnapshot, ...], fixtures: FixtureRegistry, cutoff: datetime
) -> TeamStrengthHistoricalDatasetV1:
    _complete_current_registry(authenticate(fixtures))
    current_sources = tuple(row for row in sources if row.lineage.resource.season == CURRENT_SEASON)
    if len(current_sources) != 1 or any(
        row.lineage.received_at > current_sources[0].lineage.received_at for row in sources
    ):
        # The accepted source assessment uses the latest retrieval in the corpus.
        # L1 requires that this is genuinely the current season, not newly read
        # historical bytes masking an old current snapshot. Do not alter P0/001A.
        raise ValueError("current-season retrieval must be the latest source retrieval")
    return build_dataset(
        sources=sources,
        fixtures=fixtures,
        expected_fixture_registry_sha256=fixtures.semantic_sha256,
        information_cutoff=cutoff,
        training_cutoff=cutoff,
        forecast_season=CURRENT_SEASON,
        mode="LIVE_OBSERVED",
    )


class CurrentTeamStrengthReadiness(SealedEvidence):
    schema_version: Literal["current-team-strength-live-readiness-v1"] = (
        "current-team-strength-live-readiness-v1"
    )
    artifact: TeamStrengthModelArtifactV1
    fixture_registry: FixtureRegistry
    sources: tuple[ParsedSnapshot, ...]
    source_assessment: TeamStrengthSourceAssessmentV1
    historical_origin: Literal[
        "RETAINED_FINAL_VINTAGE_OBSERVED_BEFORE_CURRENT_CUTOFF_NOT_HISTORICAL_LIVE"
    ] = "RETAINED_FINAL_VINTAGE_OBSERVED_BEFORE_CURRENT_CUTOFF_NOT_HISTORICAL_LIVE"

    @model_validator(mode="after")
    def reconcile(self) -> Self:
        dataset = current_dataset(
            sources=self.sources,
            fixtures=self.fixture_registry,
            cutoff=self.source_assessment.information_cutoff,
        )
        if _source_assessment(dataset) != self.source_assessment:
            raise ValueError("current public source assessment differs")
        model = self.artifact.model
        if (
            model.dataset_mode != "LIVE_OBSERVED"
            or model.forecast_season != CURRENT_SEASON
            or model.fixture_registry_sha256 != self.fixture_registry.semantic_sha256
            or model.information_cutoff > dataset.information_cutoff
            or dataset.freshness == "STALE_BLOCKED"
        ):
            raise ValueError("current public artifact is unavailable or mismatched")
        if tuple(row.semantic_sha256 for row in model.sources) != tuple(
            row.lineage.semantic_sha256 for row in dataset.sources
        ):
            # A retained DEGRADED artifact may predate the assessed current sources.
            if dataset.freshness != "DEGRADED":
                raise ValueError("fresh current artifact source lineage differs")
        else:
            training = current_dataset(
                sources=self.sources,
                fixtures=self.fixture_registry,
                cutoff=model.information_cutoff,
            )
            if training.semantic_sha256 != model.training_dataset_sha256:
                raise ValueError("current artifact training dataset differs")
        return self


@dataclass(frozen=True)
class PublicTeamStrengthPreflight:
    status: Literal[
        "TEAM_STRENGTH_PRIOR_READY",
        "TEAM_STRENGTH_PUBLIC_PREFLIGHT_BLOCKED",
        "TEAM_STRENGTH_WORLD_UNAVAILABLE",
    ]
    reason: Literal[
        "FRESH_FIT",
        "DEGRADED_SEALED_REUSE",
        "SOURCE_STALE",
        "EVIDENCE_INSUFFICIENT",
        "FIT_FAILURE",
        "CURRENT_ARTIFACT_UNAVAILABLE",
    ]
    assessment: TeamStrengthSourceAssessmentV1
    readiness: CurrentTeamStrengthReadiness | None


def prepare_current_public(
    *,
    sources: tuple[ParsedSnapshot, ...],
    fixtures: FixtureRegistry,
    cutoff: datetime,
    latest_artifact: TeamStrengthModelArtifactV1 | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PublicTeamStrengthPreflight:
    dataset = current_dataset(sources=sources, fixtures=fixtures, cutoff=cutoff)
    result = prepare_team_strength(dataset, latest_artifact=latest_artifact, clock=clock)
    assessment = _source_assessment(dataset)
    if result.artifact is None:
        return PublicTeamStrengthPreflight(
            "TEAM_STRENGTH_PUBLIC_PREFLIGHT_BLOCKED"
            if result.freshness == "STALE_BLOCKED"
            else "TEAM_STRENGTH_WORLD_UNAVAILABLE",
            result.reason,
            assessment,
            None,
        )
    readiness = seal(
        CurrentTeamStrengthReadiness,
        artifact=result.artifact,
        fixture_registry=fixtures,
        sources=dataset.sources,
        source_assessment=assessment,
    )
    return PublicTeamStrengthPreflight(
        "TEAM_STRENGTH_PRIOR_READY", result.reason, assessment, readiness
    )


def acquire_current_public(
    *,
    commit: str,
    historical_sources: tuple[ParsedSnapshot, ...],
    fixtures: FixtureRegistry,
    transport: OpenFootballTransport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[PublicTeamStrengthPreflight, AcquiredTeamStrengthSnapshot]:
    _complete_current_registry(authenticate(fixtures))
    if any(row.lineage.resource.season >= CURRENT_SEASON for row in historical_sources):
        raise ValueError("retained history must not replace fresh current source")
    resource = discover_current_resource(commit, transport=transport)
    acquired = acquire_team_strength_snapshot(
        resource=resource,
        expected_resource_sha256=canonical_sha256(resource),
        fixtures=fixtures,
        expected_fixture_registry_sha256=fixtures.semantic_sha256,
        transport=transport,
        clock=clock,
    )
    result = prepare_current_public(
        sources=(*historical_sources, acquired.snapshot),
        fixtures=fixtures,
        cutoff=clock(),
        clock=clock,
    )
    return result, acquired


def public_preflight_summary(result: PublicTeamStrengthPreflight) -> dict[str, object]:
    ready = result.readiness
    assessment = authenticate(result.assessment)
    summary: dict[str, object] = {
        "status": result.status,
        "reason": result.reason,
        "freshness": assessment.freshness,
        "missing_due": assessment.missing_due,
        "source_assessment_sha256": assessment.semantic_sha256,
        "private_attempt_consumed": False,
        "fpl_requests": 0,
        "odds_requests": 0,
        "production_activation": False,
    }
    if ready is not None:
        ready = authenticate(ready)
        current = next(
            row for row in ready.sources if row.lineage.resource.season == CURRENT_SEASON
        )
        due = tuple(
            row
            for row in current.matches
            if eligibility_not_before(row.source_match_date) <= assessment.information_cutoff
        )
        eligible = tuple(row for row in due if row.finality == "FULL_TIME")
        summary.update(
            source_commit=current.lineage.resource.commit,
            received_at=current.lineage.received_at.isoformat(),
            scored_rows=sum(row.finality == "FULL_TIME" for row in current.matches),
            due_rows=len(due),
            latest_eligible_result_date=max(
                (row.source_match_date.isoformat() for row in eligible), default=None
            ),
            artifact_sha256=ready.artifact.semantic_sha256,
            model_sha256=ready.artifact.model.semantic_sha256,
            dataset_mode=ready.artifact.model.dataset_mode,
            usable_at=ready.artifact.usable_at.isoformat(),
            fitted_teams=len(ready.artifact.model.effects),
            readiness_sha256=ready.semantic_sha256,
            historical_origin=ready.historical_origin,
        )
    return summary


def retain_public_readiness(ready: CurrentTeamStrengthReadiness, *, artifact_root: Path) -> Path:
    """Public OpenFootball evidence only; this function cannot accept private inputs."""
    ready = authenticate(ready)
    persist_team_strength(ready.artifact, artifact_root=artifact_root)
    root = artifact_root.resolve()
    destination = root / "current-team-strength-readiness" / f"{ready.semantic_sha256}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or not destination.resolve().is_relative_to(root):
        raise ValueError("unsafe public readiness destination")
    body = pretty_json(ready).encode()
    try:
        with destination.open("xb") as stream:
            stream.write(body)
    except FileExistsError:
        if destination.read_bytes() != body:
            raise ValueError("public readiness identity collision") from None
    return destination


def retain_public_source(acquired: AcquiredTeamStrengthSnapshot, *, artifact_root: Path) -> None:
    """Retain only hash-verified public bytes; no generic/private artifact writer."""
    source = authenticate(acquired.snapshot).lineage.resource
    for body, digest in (
        (acquired.raw_bytes, source.content_sha256),
        (acquired.licence_bytes, source.licence_content_sha256),
    ):
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("public source retention hash differs")
    root = artifact_root.resolve()
    for body, digest in (
        (acquired.raw_bytes, source.content_sha256),
        (acquired.licence_bytes, source.licence_content_sha256),
    ):
        destination = root / "openfootball-source-bytes" / digest
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or not destination.resolve().is_relative_to(root):
            raise ValueError("unsafe public source destination")
        try:
            with destination.open("xb") as stream:
                stream.write(body)
        except FileExistsError:
            if destination.read_bytes() != body:
                raise ValueError("public source identity collision") from None
