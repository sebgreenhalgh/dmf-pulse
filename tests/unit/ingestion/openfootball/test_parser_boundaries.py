from __future__ import annotations

import json

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.config import OpenFootballProviderConfig
from dmf_pulse.ingestion.openfootball.parser import (
    parse_season,
    validate_licence,
    verify_resource_identity,
)

from .conftest import resource_identity, season_body


def _adjust(config: OpenFootballProviderConfig, body: bytes) -> OpenFootballProviderConfig:
    raw = config.model_dump()
    seasons = list(raw["seasons"])
    seasons[0] = {**seasons[0], **resource_identity(body)}
    raw["seasons"] = tuple(seasons)
    return OpenFootballProviderConfig.model_validate(raw)


def _mutated_body(config: OpenFootballProviderConfig, mutate: object) -> bytes:
    value = json.loads(season_body(config.seasons[0]))
    mutate(value)  # type: ignore[operator]
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("byte_size", 1),
        ("content_sha256", "0" * 64),
        ("blob_sha1", "0" * 40),
    ],
)
def test_resource_identity_rejects_each_mismatch(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
    field: str,
    value: object,
) -> None:
    config, bodies = approved_snapshot
    season = config.seasons[0].model_copy(update={field: value})

    with pytest.raises(IngestionError) as caught:
        verify_resource_identity(bodies[config.seasons[0].path], season)

    assert caught.value.code == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"\xff", "MALFORMED_JSON"),
        (b"{", "MALFORMED_JSON"),
        (b'{"name":"x","matches":[],"extra":[[[[[[[[[[[[[0]]]]]]]]]]]]]}', "PAYLOAD_TOO_DEEP"),
    ],
)
def test_json_envelope_rejects_malformed_or_deep_payload(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
    body: bytes,
    code: str,
) -> None:
    config, _ = approved_snapshot
    adjusted = _adjust(config, body)

    with pytest.raises(IngestionError) as caught:
        parse_season(body, season=adjusted.seasons[0], config=adjusted)

    assert caught.value.code == code


@pytest.mark.parametrize("body", [b"\xff", b"not the approved licence"])
def test_licence_content_is_validated_not_only_hashed(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]], body: bytes
) -> None:
    config, _ = approved_snapshot
    adjusted = config.model_copy(
        update={"licence": config.licence.model_copy(update=resource_identity(body))}
    )

    with pytest.raises(IngestionError) as caught:
        validate_licence(body, adjusted)

    assert caught.value.code == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"extra": 1}),
        lambda value: value.update({"name": "Another Competition"}),
        lambda value: value["matches"].pop(),
        lambda value: value["matches"][0].pop("round"),
        lambda value: value["matches"][0].update({"date": "not-a-date"}),
        lambda value: value["matches"][0].update({"time": "25:00"}),
        lambda value: value["matches"][0].update({"round": ""}),
        lambda value: value["matches"][0].update({"team2": value["matches"][0]["team1"]}),
        lambda value: value["matches"][0].update({"score": {"ht": [0, 0]}}),
        lambda value: value["matches"][0].update({"score": {"ft": [1, 0], "ht": [2, 0]}}),
        lambda value: value["matches"][0].update({"score": {"ft": [100, 0]}}),
        lambda value: value["matches"][1].update(
            {
                "date": value["matches"][0]["date"],
                "team1": value["matches"][0]["team1"],
                "team2": value["matches"][0]["team2"],
            }
        ),
        lambda value: value["matches"][0].update({"team2": "Team 03"}),
        lambda value: value["matches"][0].update({"score": {"ft": [3, 1]}}),
    ],
)
def test_season_semantic_drift_is_fail_closed(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]], mutate: object
) -> None:
    config, _ = approved_snapshot
    body = _mutated_body(config, mutate)
    adjusted = _adjust(config, body)

    with pytest.raises(IngestionError):
        parse_season(body, season=adjusted.seasons[0], config=adjusted)
