from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.config import (
    OpenFootballProviderConfig,
    OpenFootballResourceConfig,
    OpenFootballSeasonConfig,
    OpenFootballTimeouts,
    load_provider_config,
    load_rights_profiles,
    provider_config_sha256,
    rights_config_sha256,
)


@pytest.mark.parametrize(
    ("model", "update"),
    [
        (OpenFootballTimeouts, {"connect": 10, "read": 20, "total": 15}),
        (
            OpenFootballResourceConfig,
            {
                "blob_sha1": "x" * 40,
                "byte_size": 1,
                "content_sha256": "a" * 64,
                "path": "LICENSE.md",
            },
        ),
        (
            OpenFootballResourceConfig,
            {
                "blob_sha1": "a" * 40,
                "byte_size": 1,
                "content_sha256": "x" * 64,
                "path": "LICENSE.md",
            },
        ),
        (
            OpenFootballResourceConfig,
            {
                "blob_sha1": "a" * 40,
                "byte_size": 1,
                "content_sha256": "b" * 64,
                "path": "../LICENSE.md",
            },
        ),
    ],
)
def test_strict_config_components_refuse_invalid_authority(
    model: object, update: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(update)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "update",
    [
        {"season_code": "2023-24"},
        {"object_ht_ft_count": 0},
        {"expected_appearances_per_team": 37},
        {"path": "2024-25/en.1.json"},
    ],
)
def test_season_config_refuses_inconsistent_completeness(update: dict[str, object]) -> None:
    season = load_provider_config().seasons[0]

    with pytest.raises(ValidationError):
        OpenFootballSeasonConfig.model_validate({**season.model_dump(), **update})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.update({"commit_timestamp": "naive"}),
        lambda raw: raw.update({"output_quantum": "0.001"}),
        lambda raw: raw.update({"expected_home_goal_rate": "0"}),
        lambda raw: raw.update({"licence": {**raw["licence"], "path": "COPYING"}}),
        lambda raw: raw.update({"seasons": tuple(reversed(raw["seasons"]))}),
        lambda raw: raw.update(
            {"seasons": (raw["seasons"][0], raw["seasons"][0], raw["seasons"][2])}
        ),
        lambda raw: raw.update({"max_response_bytes": 10}),
    ],
)
def test_provider_config_refuses_snapshot_drift(mutate: object) -> None:
    raw = load_provider_config().model_dump()
    mutate(raw)  # type: ignore[operator]

    with pytest.raises(ValidationError):
        OpenFootballProviderConfig.model_validate(raw)


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"schema_version":"1.0.0","schema_version":"1.0.0"}',
        b'{"working_precision":NaN}',
    ],
)
def test_provider_loader_fails_closed_for_invalid_json(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / "provider.json"
    path.write_bytes(payload)

    with pytest.raises(IngestionError) as caught:
        load_provider_config(path)

    assert caught.value.code == "CONFIGURATION_INVALID"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": "2.0.0", "profiles": []},
        {"schema_version": "1.0.0", "profiles": {}},
        {"schema_version": "1.0.0", "profiles": []},
    ],
)
def test_rights_loader_fails_closed_for_registry_drift(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    path = tmp_path / "rights.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(IngestionError) as caught:
        load_rights_profiles(path)

    assert caught.value.code == "CONFIGURATION_INVALID"


@pytest.mark.parametrize(
    ("loader", "name"),
    [(provider_config_sha256, "provider"), (rights_config_sha256, "rights")],
)
def test_config_hash_refuses_invalid_input(tmp_path: Path, loader: object, name: str) -> None:
    path = tmp_path / f"{name}.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(IngestionError):
        loader(path)  # type: ignore[operator]


def test_config_loader_refuses_unreadable_path(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="unavailable"):
        load_provider_config(tmp_path)
