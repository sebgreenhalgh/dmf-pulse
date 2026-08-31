from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime, timedelta

import pytest

from dmf_pulse.ingestion.openfootball.client import (
    OpenFootballHttpRequest,
    OpenFootballHttpResponse,
)
from dmf_pulse.ingestion.openfootball.config import (
    OpenFootballProviderConfig,
    OpenFootballSeasonConfig,
    load_provider_config,
)


def git_blob_sha1(body: bytes) -> str:
    header = f"blob {len(body)}\0".encode("ascii")
    return hashlib.sha1(header + body, usedforsecurity=False).hexdigest()


def resource_identity(body: bytes) -> dict[str, object]:
    return {
        "blob_sha1": git_blob_sha1(body),
        "byte_size": len(body),
        "content_sha256": hashlib.sha256(body).hexdigest(),
    }


def _fixtures() -> list[tuple[str, str, int]]:
    teams = [f"Team {index:02d}" for index in range(1, 21)]
    rotation = list(teams)
    result: list[tuple[str, str, int]] = []
    for leg in range(2):
        for round_index in range(19):
            for index in range(10):
                left = rotation[index]
                right = rotation[-index - 1]
                home, away = (left, right) if leg == 0 else (right, left)
                result.append((home, away, leg * 19 + round_index + 1))
            rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    return result


def season_body(season: OpenFootballSeasonConfig) -> bytes:
    matches: list[dict[str, object]] = []
    for index, (home_team, away_team, round_number) in enumerate(_fixtures()):
        home_score = 2 if index < season.home_goals - season.expected_matches else 1
        away_score = 2 if index < season.away_goals - season.expected_matches else 1
        full_time = [home_score, away_score]
        if index < season.object_ht_ft_count:
            score: object = {"ft": full_time, "ht": [0, 0]}
        elif index < season.object_ht_ft_count + season.object_ft_count:
            score = {"ft": full_time}
        else:
            score = full_time
        matches.append(
            {
                "date": (datetime(2023, 7, 1, tzinfo=UTC) + timedelta(days=round_number))
                .date()
                .isoformat(),
                "round": f"Round {round_number}",
                "score": score,
                "team1": home_team,
                "team2": away_team,
                "time": "15:00",
            }
        )
    return json.dumps(
        {"matches": matches, "name": season.expected_name},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def synthetic_snapshot() -> tuple[OpenFootballProviderConfig, dict[str, bytes]]:
    base = load_provider_config()
    licence_body = b"Creative Commons CC0 1.0 Universal\n"
    bodies = {season.path: season_body(season) for season in base.seasons}
    bodies[base.licence.path] = licence_body
    raw = base.model_dump()
    raw["licence"] = {**raw["licence"], **resource_identity(licence_body)}
    raw["seasons"] = tuple(
        {**season, **resource_identity(bodies[str(season["path"])])} for season in raw["seasons"]
    )
    return OpenFootballProviderConfig.model_validate(raw), bodies


class FakeTransport:
    transport_id = "test_openfootball_transport"

    def __init__(self, bodies: Mapping[str, bytes]) -> None:
        self._bodies = dict(bodies)
        self.requests: list[OpenFootballHttpRequest] = []

    def send(self, request: OpenFootballHttpRequest) -> OpenFootballHttpResponse:
        self.requests.append(request)
        # The immutable raw path has owner/repository/commit as its first three segments.
        resource_path = "/".join(request.path.lstrip("/").split("/")[3:])
        body = self._bodies[resource_path]
        content_type = "text/plain" if resource_path == "LICENSE.md" else "application/json"
        return OpenFootballHttpResponse(
            status_code=200,
            content_type=content_type,
            headers={"content-type": content_type},
            body=body,
        )


def ticking_clock(start: datetime) -> Callable[[], datetime]:
    values: Iterator[datetime] = iter(start + timedelta(seconds=index) for index in range(100))
    return lambda: next(values)


@pytest.fixture
def approved_snapshot() -> tuple[OpenFootballProviderConfig, dict[str, bytes]]:
    return synthetic_snapshot()
