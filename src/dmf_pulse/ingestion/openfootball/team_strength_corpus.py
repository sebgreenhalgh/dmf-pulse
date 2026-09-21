"""Explicit offline loading of the immutable, reconstructed research corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dmf_pulse.ingestion.openfootball.team_strength_data import (
    FixtureRegistry,
    ParsedSnapshot,
    SourceLineage,
    StrengthEvidenceError,
    authenticate,
    parse_snapshot,
    require_team_strength_rights,
)

FIXTURE_REGISTRY_SHA256 = "de447eb368a807d4edf701a75c094a8b3f4925aa3e87cbff9b9f4fadd63eba18"
CORPUS_CONTENT_SHA256 = "5a3882ee17da73deaf0f175dcce28999edd95aa5506911eea2274cefcaa59cc8"


def load_fixture_registry(corpus_root: Path) -> FixtureRegistry:
    body = (corpus_root / "fixture_registry.json").read_bytes()
    return authenticate(FixtureRegistry.model_validate_json(body), FIXTURE_REGISTRY_SHA256)


def load_reconstructed_corpus(
    corpus_root: Path,
    *,
    include_current_season: bool = False,
) -> tuple[FixtureRegistry, tuple[ParsedSnapshot, ...]]:
    """Load final-vintage evidence; never relabel its receipts LIVE_OBSERVED."""
    require_team_strength_rights()
    fixtures = load_fixture_registry(corpus_root)
    directory = corpus_root
    body = directory.joinpath("corpus.json").read_bytes()
    if hashlib.sha256(body).hexdigest() != CORPUS_CONTENT_SHA256:
        raise StrengthEvidenceError("reconstructed corpus identity differs")
    payload = json.loads(body)
    snapshots = []
    for raw_lineage in payload["sources"]:
        lineage = SourceLineage.model_validate_json(json.dumps(raw_lineage))
        if lineage.resource.season == "2026/27" and not include_current_season:
            continue
        snapshots.append(
            parse_snapshot(
                directory.joinpath(lineage.resource.path).read_bytes(),
                lineage=lineage,
                fixtures=fixtures,
                expected_fixture_registry_sha256=FIXTURE_REGISTRY_SHA256,
            )
        )
    return fixtures, tuple(snapshots)
