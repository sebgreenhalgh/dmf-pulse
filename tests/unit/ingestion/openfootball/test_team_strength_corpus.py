"""Offline loader branch tests with explicit synthetic trust roots, never real raw data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dmf_pulse.ingestion.openfootball import team_strength_corpus as corpus
from tests.unit.ingestion.openfootball.test_team_strength_data import registry, source


def test_explicit_corpus_integrity_scope_and_missing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixtures = registry()
    raw, lineage = source()
    (tmp_path / "fixture_registry.json").write_text(fixtures.model_dump_json(), encoding="utf-8")
    body = json.dumps({"sources": [lineage.model_dump(mode="json")]}).encode()
    (tmp_path / "corpus.json").write_bytes(body)
    path = tmp_path / lineage.resource.path
    path.parent.mkdir()
    path.write_bytes(raw)
    # A synthetic fixture must never impersonate the pinned real research corpus.
    with pytest.raises(ValueError, match="identity"):
        corpus.load_fixture_registry(tmp_path)
    monkeypatch.setattr(corpus, "FIXTURE_REGISTRY_SHA256", fixtures.semantic_sha256)
    with pytest.raises(ValueError, match="identity"):
        corpus.load_reconstructed_corpus(tmp_path)
    monkeypatch.setattr(corpus, "CORPUS_CONTENT_SHA256", hashlib.sha256(body).hexdigest())
    loaded, snapshots = corpus.load_reconstructed_corpus(tmp_path)
    assert loaded == fixtures and snapshots == ()  # 2026/27 is excluded by default.
    loaded, snapshots = corpus.load_reconstructed_corpus(tmp_path, include_current_season=True)
    assert loaded == fixtures and len(snapshots) == 1
    path.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="identity"):
        corpus.load_reconstructed_corpus(tmp_path, include_current_season=True)
    with pytest.raises(FileNotFoundError):
        corpus.load_reconstructed_corpus(tmp_path / "missing")
