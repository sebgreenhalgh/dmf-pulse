"""Frozen fixture and provider-adapter contract oracles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.parser import FplResource, parse_fpl_payload
from dmf_pulse.ingestion.models import DriftClassification

pytestmark = pytest.mark.contract


def _root(repository_root: Path) -> Path:
    return repository_root / "fixtures" / "fpl" / "FPL-004"


def test_fixture_manifest_has_exact_complete_byte_oracles(repository_root: Path) -> None:
    manifest = json.loads((repository_root / "fixtures" / "manifest.json").read_text("utf-8"))
    entries = manifest["entries"]
    assert manifest["pack_id"] == "FPL-004"
    assert manifest["manifest_version"] == "1.0.0"
    assert manifest["fixture_count"] == 18 == len(entries)
    assert len({entry["path"] for entry in entries}) == len(entries)
    for entry in entries:
        path = repository_root / entry["path"]
        body = path.read_bytes()
        assert path.is_file() and not path.is_symlink()
        assert entry["synthetic"] is True
        assert entry["rights_profile"] == "synthetic_test_v1"
        assert entry["bytes"] == len(body)
        assert entry["sha256"] == hashlib.sha256(body).hexdigest()


def test_happy_and_changed_contract_semantics(repository_root: Path) -> None:
    root = _root(repository_root)
    happy_bootstrap = parse_fpl_payload(
        FplResource.BOOTSTRAP, (root / "happy_path" / "bootstrap.json").read_bytes()
    )
    changed_bootstrap = parse_fpl_payload(
        FplResource.BOOTSTRAP, (root / "changed_snapshot" / "bootstrap.json").read_bytes()
    )
    happy_fixtures = parse_fpl_payload(
        FplResource.FIXTURES, (root / "happy_path" / "fixtures.json").read_bytes()
    )
    changed_fixtures = parse_fpl_payload(
        FplResource.FIXTURES, (root / "changed_snapshot" / "fixtures.json").read_bytes()
    )

    assert happy_bootstrap.semantic_sha256 != changed_bootstrap.semantic_sha256
    assert happy_fixtures.semantic_sha256 != changed_fixtures.semantic_sha256
    assert [team.id for team in happy_bootstrap.payload.teams] == [  # type: ignore[union-attr]
        team.id
        for team in changed_bootstrap.payload.teams  # type: ignore[union-attr]
    ]
    assert [player.id for player in happy_bootstrap.payload.elements] == [  # type: ignore[union-attr]
        player.id
        for player in changed_bootstrap.payload.elements  # type: ignore[union-attr]
    ]


def test_all_frozen_drift_and_failure_oracles(repository_root: Path) -> None:
    root = _root(repository_root)
    unknown_bootstrap = parse_fpl_payload(
        FplResource.BOOTSTRAP, (root / "unknown_additive" / "bootstrap.json").read_bytes()
    )
    unknown_fixtures = parse_fpl_payload(
        FplResource.FIXTURES, (root / "unknown_additive" / "fixtures.json").read_bytes()
    )
    assert unknown_bootstrap.drift.classification is DriftClassification.ADDITIVE_UNKNOWN
    assert unknown_fixtures.drift.classification is DriftClassification.ADDITIVE_UNKNOWN

    expected = {
        "missing_required": ("VALIDATION_FAILED", "BLOCKING_MISSING_REQUIRED"),
        "wrong_type": ("VALIDATION_FAILED", "BLOCKING_TYPE_CHANGE"),
        "malformed": ("MALFORMED_JSON", "MALFORMED"),
    }
    for case, (code, classification) in expected.items():
        with pytest.raises(IngestionError) as raised:
            parse_fpl_payload(FplResource.BOOTSTRAP, (root / case / "bootstrap.json").read_bytes())
        assert raised.value.code == code
        assert raised.value.details["classification"] == classification


def test_expected_result_oracle_is_complete_and_unchanged(repository_root: Path) -> None:
    expected = json.loads((_root(repository_root) / "expected_results.json").read_text("utf-8"))
    assert set(expected) == {
        "changed_snapshot",
        "happy_path",
        "malformed",
        "missing_required",
        "post_cutoff",
        "unknown_additive",
        "wrong_type",
    }
    assert expected["happy_path"] == {
        "blocking_quality_issue_count": 0,
        "competition_count": 1,
        "fixture_count": 1,
        "gameweek_count": 2,
        "player_count": 4,
        "player_fpl_season_count": 4,
        "season_count": 1,
        "source_bundle_count": 1,
        "source_bundle_member_count": 2,
        "source_snapshot_count": 2,
        "status": "USABLE",
        "team_count": 2,
        "team_season_count": 2,
        "usable_snapshot_count": 2,
    }
    assert expected["post_cutoff"] == {
        "bundle_created": False,
        "status": "OBSERVED_NOT_BUNDLE_ELIGIBLE",
    }
