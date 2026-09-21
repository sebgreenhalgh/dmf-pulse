from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    CanonicalClubRegistration,
    OpenFootballAliasMapping,
    OpenFootballHistoricalTeamIdentityV1,
    SourceSnapshotIdentity,
    load_current_team_strength_governance,
    load_historical_team_identity,
)

ROOT = Path(__file__).resolve().parents[4]
IDENTITY_PATH = ROOT / "config/providers/openfootball_historical_team_identity.json"
POLICY_PATH = ROOT / "config/models/current_team_strength_governance.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _rehash_record(record: dict[str, Any]) -> None:
    body = {key: value for key, value in record.items() if key != "semantic_sha256"}
    record["semantic_sha256"] = canonical_sha256(body)


def _rehash_identity(value: dict[str, Any]) -> None:
    body = {key: item for key, item in value.items() if key != "root_semantic_sha256"}
    value["root_semantic_sha256"] = canonical_sha256(body)


def _rehash_club(club: dict[str, Any]) -> None:
    identity = {
        "canonical_team_id": club["canonical_team_id"],
        "entity_type": club["entity_type"],
        "id_generation_method": club["id_generation_method"],
        "registered_at": club["registered_at"],
        "registration_authority": club["registration_authority"],
    }
    club["canonical_team_identity_sha256"] = canonical_sha256(identity)
    body = {key: item for key, item in club.items() if key != "semantic_sha256"}
    club["semantic_sha256"] = canonical_sha256(body)


def _validate_json(model: type[Any], value: object) -> None:
    model.model_validate_json(json.dumps(value, allow_nan=False, ensure_ascii=False), strict=True)


def _rehash_policy(value: dict[str, Any]) -> None:
    body = {key: item for key, item in value.items() if key != "semantic_sha256"}
    value["semantic_sha256"] = canonical_sha256(body)


@pytest.mark.parametrize(
    ("source", "loader", "mutate"),
    [
        (
            IDENTITY_PATH,
            load_historical_team_identity,
            lambda value: value.update({"canonical_club_count": 41}),
        ),
        (
            IDENTITY_PATH,
            load_historical_team_identity,
            lambda value: value["canonical_clubs"][0].update({"canonical_name": "Tampered Club"}),
        ),
        (
            POLICY_PATH,
            load_current_team_strength_governance,
            lambda value: value["materiality_policy"].update(
                {"calibration_relative_harm_limit": "0.02"}
            ),
        ),
        (
            POLICY_PATH,
            load_current_team_strength_governance,
            lambda value: value.update({"production_active": True}),
        ),
    ],
)
def test_stale_semantic_hash_blocks_tamper(
    tmp_path: Path,
    source: Path,
    loader: Callable[[Path | None], object],
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    value = _load(source)
    mutate(value)
    target = tmp_path / source.name
    _write(target, value)

    with pytest.raises(IngestionError) as caught:
        loader(target)
    assert caught.value.code == "CONFIGURATION_INVALID"


def test_rehashed_materiality_drift_still_fails_closed(tmp_path: Path) -> None:
    value = _load(POLICY_PATH)
    value["materiality_policy"]["player_xp_materiality_per_gw"] = "0.16"
    _rehash_policy(value)
    target = tmp_path / "policy.json"
    _write(target, value)

    with pytest.raises(IngestionError, match="invalid"):
        load_current_team_strength_governance(target)


def test_approved_policy_hash_is_an_external_trust_anchor(tmp_path: Path) -> None:
    value = _load(POLICY_PATH)
    value["human_approval"]["approved_at"] = "2026-09-21T17:14:40Z"
    _rehash_policy(value)
    target = tmp_path / "policy.json"
    _write(target, value)

    with pytest.raises(IngestionError, match="invalid"):
        load_current_team_strength_governance(target)


def test_approved_identity_hash_is_an_external_trust_anchor(tmp_path: Path) -> None:
    value = _load(IDENTITY_PATH)
    club = value["canonical_clubs"][0]
    club["continuity_note"] = "A different but structurally valid note."
    _rehash_club(club)
    _rehash_identity(value)
    target = tmp_path / "identity.json"
    _write(target, value)

    with pytest.raises(IngestionError, match="invalid"):
        load_historical_team_identity(target)


@pytest.mark.parametrize(
    ("mutate", "rehash"),
    [
        (lambda item: item.update({"path": "2020-21/en.1.json"}), True),
        (lambda item: item.update({"content_sha256": "0" * 64}), False),
    ],
)
def test_source_snapshot_invariants_fail_closed(
    mutate: Callable[[dict[str, Any]], None],
    rehash: bool,
) -> None:
    item = copy.deepcopy(_load(IDENTITY_PATH)["source_snapshots"][0])
    mutate(item)
    if rehash:
        body = {key: value for key, value in item.items() if key != "semantic_sha256"}
        item["semantic_sha256"] = canonical_sha256(body)

    with pytest.raises(ValidationError):
        _validate_json(SourceSnapshotIdentity, item)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item.update({"canonical_team_id": "00000000-0000-4000-8000-000000000001"}),
        lambda item: item.update(
            {"openfootball_aliases": list(reversed(item["openfootball_aliases"]))}
        ),
        lambda item: item.update(
            {"season_membership": [*item["season_membership"], item["season_membership"][0]]}
        ),
    ],
)
def test_canonical_registration_invariants_fail_closed(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    clubs = _load(IDENTITY_PATH)["canonical_clubs"]
    item = copy.deepcopy(next(club for club in clubs if len(club["openfootball_aliases"]) > 1))
    mutate(item)
    _rehash_club(item)

    with pytest.raises(ValidationError):
        _validate_json(CanonicalClubRegistration, item)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item.update({"canonical_team_id": "00000000-0000-4000-8000-000000000001"}),
        lambda item: item.update({"source_team_name": f" {item['source_team_name']}"}),
        lambda item: item.update(
            {"season_scope": [*item["season_scope"], item["season_scope"][0]]}
        ),
        lambda item: item.update({"source_identity_sha256": "0" * 64}),
        lambda item: item.update({"semantic_sha256": "0" * 64}),
    ],
)
def test_alias_mapping_invariants_fail_closed(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    item = copy.deepcopy(_load(IDENTITY_PATH)["records"][0])
    mutate(item)
    if item["semantic_sha256"] != "0" * 64:
        _rehash_record(item)

    with pytest.raises(ValidationError):
        _validate_json(OpenFootballAliasMapping, item)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["canonical_clubs"].pop(),
        lambda value: value["records"].pop(),
        lambda value: value["source_snapshots"].pop(),
        lambda value: value.update(
            {"seasons_covered": [value["seasons_covered"][0], *value["seasons_covered"][:-1]]}
        ),
        lambda value: value.update({"source_snapshots": list(reversed(value["source_snapshots"]))}),
        lambda value: value.update({"canonical_clubs": list(reversed(value["canonical_clubs"]))}),
        lambda value: value.update({"records": list(reversed(value["records"]))}),
    ],
)
def test_registry_shape_and_order_invariants_fail_closed(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    value = _load(IDENTITY_PATH)
    mutate(value)
    _rehash_identity(value)

    with pytest.raises(ValidationError):
        _validate_json(OpenFootballHistoricalTeamIdentityV1, value)


def test_mapping_to_unregistered_club_fails_closed() -> None:
    value = _load(IDENTITY_PATH)
    record = value["records"][0]
    record["canonical_team_id"] = "00000000-0000-7000-8000-000000000099"
    record["canonical_team_identity_sha256"] = "0" * 64
    _rehash_record(record)
    value["records"] = sorted(
        value["records"],
        key=lambda item: (
            item["canonical_team_id"],
            item["source_team_name"],
            item["season_scope"],
        ),
    )
    _rehash_identity(value)

    with pytest.raises(ValidationError):
        _validate_json(OpenFootballHistoricalTeamIdentityV1, value)


def test_duplicate_mapping_fails_even_when_hashes_are_recomputed(tmp_path: Path) -> None:
    value = _load(IDENTITY_PATH)
    first = copy.deepcopy(value["records"][0])
    second = value["records"][1]
    first["canonical_team_id"] = second["canonical_team_id"]
    first["canonical_team_identity_sha256"] = second["canonical_team_identity_sha256"]
    first["source_team_name"] = second["source_team_name"]
    first["season_scope"] = copy.deepcopy(second["season_scope"])
    first["source_identity_sha256"] = second["source_identity_sha256"]
    first["source_snapshot_identity"] = second["source_snapshot_identity"]
    _rehash_record(first)
    value["records"][0] = first
    value["records"] = sorted(
        value["records"],
        key=lambda item: (
            item["canonical_team_id"],
            item["source_team_name"],
            item["season_scope"],
        ),
    )
    _rehash_identity(value)
    target = tmp_path / "identity.json"
    _write(target, value)

    with pytest.raises(IngestionError, match="invalid"):
        load_historical_team_identity(target)


def test_ambiguous_target_fails_even_when_hashes_are_recomputed(tmp_path: Path) -> None:
    value = _load(IDENTITY_PATH)
    record = value["records"][0]
    other = next(
        item
        for item in value["canonical_clubs"]
        if item["canonical_team_id"] != record["canonical_team_id"]
    )
    record["canonical_team_id"] = other["canonical_team_id"]
    record["canonical_team_identity_sha256"] = other["canonical_team_identity_sha256"]
    _rehash_record(record)
    value["records"] = sorted(
        value["records"],
        key=lambda item: (
            item["canonical_team_id"],
            item["source_team_name"],
            item["season_scope"],
        ),
    )
    _rehash_identity(value)
    target = tmp_path / "identity.json"
    _write(target, value)

    with pytest.raises(IngestionError, match="invalid"):
        load_historical_team_identity(target)


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b'{"schema_version":"x","schema_version":"x"}',
        b'{"semantic_sha256":NaN}',
        b"\xff",
    ],
)
def test_artifact_loaders_reject_invalid_json(tmp_path: Path, payload: bytes) -> None:
    target = tmp_path / "artifact.json"
    target.write_bytes(payload)

    with pytest.raises(IngestionError) as identity_error:
        load_historical_team_identity(target)
    with pytest.raises(IngestionError) as policy_error:
        load_current_team_strength_governance(target)
    assert identity_error.value.code == "CONFIGURATION_INVALID"
    assert policy_error.value.code == "CONFIGURATION_INVALID"


def test_identity_loader_refuses_unreadable_path(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="unavailable"):
        load_historical_team_identity(tmp_path)
