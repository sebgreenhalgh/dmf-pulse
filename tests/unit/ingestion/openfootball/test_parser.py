from __future__ import annotations

import json

import pytest

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.config import OpenFootballProviderConfig
from dmf_pulse.ingestion.openfootball.parser import parse_season

from .conftest import resource_identity, season_body


def _config_for_body(config: OpenFootballProviderConfig, body: bytes) -> OpenFootballProviderConfig:
    raw = config.model_dump()
    seasons = list(raw["seasons"])
    seasons[0] = {**seasons[0], **resource_identity(body)}
    raw["seasons"] = tuple(seasons)
    return OpenFootballProviderConfig.model_validate(raw)


@pytest.mark.unit
def test_all_approved_score_shapes_are_parsed_exactly(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, bodies = approved_snapshot

    audits = tuple(
        parse_season(bodies[season.path], season=season, config=config) for season in config.seasons
    )

    assert tuple(audit.object_ht_ft_count for audit in audits) == (369, 364, 353)
    assert tuple(audit.object_ft_count for audit in audits) == (11, 16, 0)
    assert tuple(audit.direct_score_count for audit in audits) == (0, 0, 27)
    assert all(audit.match_count == 380 for audit in audits)
    assert all(audit.team_count == 20 for audit in audits)


@pytest.mark.parametrize("invalid_score", [["1", 0], [True, 0], [1.0, 0], [-1, 0]])
def test_non_exact_score_values_are_rejected(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
    invalid_score: object,
) -> None:
    config, _ = approved_snapshot
    original = json.loads(season_body(config.seasons[0]))
    original["matches"][0]["score"] = {"ft": invalid_score}
    body = json.dumps(original, separators=(",", ":"), sort_keys=True).encode()
    adjusted = _config_for_body(config, body)

    with pytest.raises(IngestionError) as caught:
        parse_season(body, season=adjusted.seasons[0], config=adjusted)

    assert caught.value.code == "VALIDATION_FAILED"


@pytest.mark.security
def test_duplicate_json_key_is_rejected_after_exact_identity_validation(
    approved_snapshot: tuple[OpenFootballProviderConfig, dict[str, bytes]],
) -> None:
    config, _ = approved_snapshot
    body = b'{"name":"x","name":"y","matches":[]}'
    adjusted = _config_for_body(config, body)

    with pytest.raises(IngestionError) as caught:
        parse_season(body, season=adjusted.seasons[0], config=adjusted)

    assert caught.value.code == "DUPLICATE_JSON_KEY"
