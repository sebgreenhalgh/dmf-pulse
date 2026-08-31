"""Strict parsers for the immutable OpenFootball score-prior snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.openfootball.config import (
    OpenFootballProviderConfig,
    OpenFootballResourceConfig,
    OpenFootballSeasonConfig,
)

_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_MATCH_KEYS = {"date", "round", "score", "team1", "team2", "time"}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class SeasonScoreAudit(_FrozenModel):
    season_code: str
    source_path: str
    competition_name: str
    match_count: int = Field(gt=0)
    unique_fixture_count: int = Field(gt=0)
    team_count: int = Field(gt=1)
    valid_score_count: int = Field(gt=0)
    home_goals: int = Field(ge=0)
    away_goals: int = Field(ge=0)
    object_ht_ft_count: int = Field(ge=0)
    object_ft_count: int = Field(ge=0)
    direct_score_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_complete(self) -> Self:
        if (
            self.match_count != self.unique_fixture_count
            or self.match_count != self.valid_score_count
        ):
            raise ValueError("season audit is incomplete")
        if (
            self.object_ht_ft_count + self.object_ft_count + self.direct_score_count
            != self.match_count
        ):
            raise ValueError("season score-shape audit is inconsistent")
        return self


def _failure(code: str, message: str) -> IngestionError:
    return IngestionError(code, message)


def verify_resource_identity(body: bytes, resource: OpenFootballResourceConfig) -> None:
    if len(body) != resource.byte_size:
        raise _failure("VALIDATION_FAILED", "OpenFootball resource byte size differs")
    if hashlib.sha256(body).hexdigest() != resource.content_sha256:
        raise _failure("VALIDATION_FAILED", "OpenFootball resource SHA-256 differs")
    header = f"blob {len(body)}\0".encode("ascii")
    if hashlib.sha1(header + body, usedforsecurity=False).hexdigest() != resource.blob_sha1:
        raise _failure("VALIDATION_FAILED", "OpenFootball resource Git blob identity differs")


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _failure("DUPLICATE_JSON_KEY", "OpenFootball JSON contains a duplicate key")
        value[key] = item
    return value


def _reject_float(value: str) -> object:
    del value
    raise _failure("VALIDATION_FAILED", "OpenFootball JSON floating-point values are forbidden")


def _reject_constant(value: str) -> object:
    del value
    raise _failure("VALIDATION_FAILED", "OpenFootball JSON non-finite values are forbidden")


def _depth(value: object, *, limit: int) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > limit:
            raise _failure("PAYLOAD_TOO_DEEP", "OpenFootball JSON exceeds the depth limit")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _json(body: bytes, config: OpenFootballProviderConfig) -> object:
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except IngestionError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise _failure("MALFORMED_JSON", "OpenFootball JSON is malformed") from exc
    _depth(value, limit=config.max_json_depth)
    return value


def validate_licence(body: bytes, config: OpenFootballProviderConfig) -> None:
    verify_resource_identity(body, config.licence)
    try:
        text = body.decode("utf-8")
    except UnicodeError as exc:
        raise _failure("VALIDATION_FAILED", "OpenFootball licence is not UTF-8") from exc
    if "CC0 1.0 Universal" not in text or "Creative Commons" not in text:
        raise _failure("VALIDATION_FAILED", "OpenFootball licence content is unexpected")


def _text(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _failure("VALIDATION_FAILED", f"OpenFootball {label} is invalid")
    return value


def _score_pair(value: object) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise _failure("VALIDATION_FAILED", "OpenFootball full-time score is invalid")
    home, away = value
    if type(home) is not int or type(away) is not int or home < 0 or away < 0:
        raise _failure(
            "VALIDATION_FAILED", "OpenFootball score values must be nonnegative integers"
        )
    if home > 99 or away > 99:
        raise _failure("VALIDATION_FAILED", "OpenFootball score value is out of range")
    return home, away


def _reported_score(value: object) -> tuple[tuple[int, int], Literal["HT_FT", "FT", "DIRECT"]]:
    if isinstance(value, list):
        return _score_pair(value), "DIRECT"
    if not isinstance(value, dict) or set(value) not in ({"ft"}, {"ht", "ft"}):
        raise _failure("VALIDATION_FAILED", "OpenFootball score object shape is invalid")
    full_time = _score_pair(value["ft"])
    if "ht" in value:
        half_time = _score_pair(value["ht"])
        if half_time[0] > full_time[0] or half_time[1] > full_time[1]:
            raise _failure("VALIDATION_FAILED", "OpenFootball half-time score exceeds full time")
        return full_time, "HT_FT"
    return full_time, "FT"


def parse_season(
    body: bytes,
    *,
    season: OpenFootballSeasonConfig,
    config: OpenFootballProviderConfig,
) -> SeasonScoreAudit:
    verify_resource_identity(body, season)
    value = _json(body, config)
    if not isinstance(value, dict) or set(value) != {"name", "matches"}:
        raise _failure("VALIDATION_FAILED", "OpenFootball season root shape is invalid")
    competition_name = _text(
        value["name"], label="competition name", maximum=config.max_text_length
    )
    if competition_name != season.expected_name:
        raise _failure("VALIDATION_FAILED", "OpenFootball competition identity differs")
    matches = value["matches"]
    if not isinstance(matches, list) or len(matches) != season.expected_matches:
        raise _failure("QUALITY_BLOCKED", "OpenFootball season match count differs")

    fixtures: set[tuple[str, str, str]] = set()
    appearances: Counter[str] = Counter()
    home_goals = 0
    away_goals = 0
    shapes: Counter[str] = Counter()
    for match in matches:
        if not isinstance(match, dict) or set(match) != _MATCH_KEYS:
            raise _failure("VALIDATION_FAILED", "OpenFootball match shape is invalid")
        match_date = _text(match["date"], label="match date", maximum=10)
        try:
            date.fromisoformat(match_date)
        except ValueError as exc:
            raise _failure("VALIDATION_FAILED", "OpenFootball match date is invalid") from exc
        match_time = _text(match["time"], label="match time", maximum=5)
        if _TIME.fullmatch(match_time) is None:
            raise _failure("VALIDATION_FAILED", "OpenFootball match time is invalid")
        _text(match["round"], label="round", maximum=config.max_text_length)
        home_team = _text(match["team1"], label="home team", maximum=config.max_text_length)
        away_team = _text(match["team2"], label="away team", maximum=config.max_text_length)
        if home_team == away_team:
            raise _failure("VALIDATION_FAILED", "OpenFootball fixture teams are identical")
        fixture = (match_date, home_team, away_team)
        if fixture in fixtures:
            raise _failure("QUALITY_BLOCKED", "OpenFootball fixture identity is duplicated")
        fixtures.add(fixture)
        appearances.update((home_team, away_team))
        score, shape = _reported_score(match["score"])
        home_goals += score[0]
        away_goals += score[1]
        shapes[shape] += 1

    expected_shapes = {
        "HT_FT": season.object_ht_ft_count,
        "FT": season.object_ft_count,
        "DIRECT": season.direct_score_count,
    }
    if dict(shapes) != {key: count for key, count in expected_shapes.items() if count}:
        raise _failure("QUALITY_BLOCKED", "OpenFootball score-shape counts differ")
    if len(appearances) != season.expected_teams or any(
        count != season.expected_appearances_per_team for count in appearances.values()
    ):
        raise _failure("QUALITY_BLOCKED", "OpenFootball team appearance completeness differs")
    if home_goals != season.home_goals or away_goals != season.away_goals:
        raise _failure("QUALITY_BLOCKED", "OpenFootball season goal totals differ")

    return SeasonScoreAudit.model_validate(
        {
            "away_goals": away_goals,
            "competition_name": competition_name,
            "direct_score_count": shapes["DIRECT"],
            "home_goals": home_goals,
            "match_count": len(matches),
            "object_ft_count": shapes["FT"],
            "object_ht_ft_count": shapes["HT_FT"],
            "season_code": season.season_code,
            "source_path": season.path,
            "team_count": len(appearances),
            "unique_fixture_count": len(fixtures),
            "valid_score_count": sum(shapes.values()),
        }
    )


__all__ = [
    "SeasonScoreAudit",
    "parse_season",
    "validate_licence",
    "verify_resource_identity",
]
