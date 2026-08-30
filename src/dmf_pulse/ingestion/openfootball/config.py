"""Strict packaged authority for the approved OpenFootball score-prior source."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsProfile

PROVIDER_RESOURCE = "ingestion/resources/openfootball_score_prior.json"
RIGHTS_RESOURCE = "ingestion/resources/openfootball_profiles.json"
APPROVED_PROFILE_ID = "openfootball_football_json_score_prior_v1"
APPROVED_COMMIT_SHA = "f27dcbef681db2c3195f9def62316ce497278781"

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEASON = re.compile(r"^20\d{2}/\d{2}$")


class _FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class OpenFootballTimeouts(_FrozenConfig):
    connect: int = Field(gt=0, le=60)
    read: int = Field(gt=0, le=60)
    total: int = Field(gt=0, le=120)

    @model_validator(mode="after")
    def validate_budget(self) -> Self:
        if self.connect + self.read > self.total:
            raise ValueError("OpenFootball timeout budget is inconsistent")
        return self


class OpenFootballResourceConfig(_FrozenConfig):
    path: str = Field(min_length=1, max_length=120)
    blob_sha1: str
    content_sha256: str
    byte_size: int = Field(gt=0, le=1024 * 1024)

    @field_validator("blob_sha1")
    @classmethod
    def validate_sha1(cls, value: str) -> str:
        if _SHA1.fullmatch(value) is None:
            raise ValueError("blob_sha1 must be lowercase SHA-1")
        return value

    @field_validator("content_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("content_sha256 must be lowercase SHA-256")
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise ValueError("OpenFootball resource path is not repository-relative")
        return value


class OpenFootballSeasonConfig(OpenFootballResourceConfig):
    season_code: str
    expected_name: str = Field(min_length=1, max_length=120)
    expected_matches: int = Field(gt=0, le=1000)
    expected_teams: int = Field(gt=1, le=100)
    expected_appearances_per_team: int = Field(gt=0, le=100)
    home_goals: int = Field(ge=0, le=10_000)
    away_goals: int = Field(ge=0, le=10_000)
    object_ht_ft_count: int = Field(ge=0, le=1000)
    object_ft_count: int = Field(ge=0, le=1000)
    direct_score_count: int = Field(ge=0, le=1000)

    @field_validator("season_code")
    @classmethod
    def validate_season(cls, value: str) -> str:
        if _SEASON.fullmatch(value) is None:
            raise ValueError("season_code must use YYYY/YY")
        return value

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        shape_total = self.object_ht_ft_count + self.object_ft_count + self.direct_score_count
        if shape_total != self.expected_matches:
            raise ValueError("score-shape counts do not equal expected matches")
        if self.expected_teams * self.expected_appearances_per_team != 2 * self.expected_matches:
            raise ValueError("season appearance expectations are inconsistent")
        if self.path != f"{self.season_code.replace('/', '-')}/en.1.json":
            raise ValueError("season path does not match season_code")
        return self


class OpenFootballProviderConfig(_FrozenConfig):
    schema_version: Literal["1.0.0"]
    provider_key: Literal["openfootball_football_json"]
    repository: Literal["openfootball/football.json"]
    scheme: Literal["https"]
    host: Literal["raw.githubusercontent.com"]
    commit_sha: Literal["f27dcbef681db2c3195f9def62316ce497278781"]
    commit_timestamp: datetime
    adapter_version: Literal["openfootball-score-prior-v1"]
    contract_version: Literal["openfootball-score-prior-v1"]
    method_id: Literal["PL_LEAGUE_HOME_AWAY_MEAN_3_COMPLETE_SEASONS_V1"]
    rounding: Literal["ROUND_HALF_EVEN"]
    output_quantum: Decimal
    expected_home_goal_rate: Decimal
    expected_away_goal_rate: Decimal
    working_precision: int = Field(ge=28, le=100)
    max_response_bytes: int = Field(gt=0, le=1024 * 1024)
    max_json_depth: int = Field(gt=0, le=64)
    max_text_length: int = Field(gt=0, le=2000)
    timeouts_seconds: OpenFootballTimeouts
    licence: OpenFootballResourceConfig
    seasons: tuple[OpenFootballSeasonConfig, OpenFootballSeasonConfig, OpenFootballSeasonConfig]

    @field_validator("commit_timestamp")
    @classmethod
    def normalize_commit_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("commit_timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("output_quantum")
    @classmethod
    def validate_quantum(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value != Decimal("0.000001"):
            raise ValueError("output_quantum must be exactly 0.000001")
        return value

    @field_validator("expected_home_goal_rate", "expected_away_goal_rate")
    @classmethod
    def validate_expected_rate(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value.as_tuple().exponent != -6:
            raise ValueError("expected rates must be positive six-place Decimals")
        return value

    @model_validator(mode="after")
    def validate_approved_snapshot(self) -> Self:
        if self.licence.path != "LICENSE.md":
            raise ValueError("licence resource must be LICENSE.md")
        if tuple(item.season_code for item in self.seasons) != (
            "2023/24",
            "2024/25",
            "2025/26",
        ):
            raise ValueError("selected season window differs from human approval")
        resources = (self.licence, *self.seasons)
        if len({item.path for item in resources}) != len(resources):
            raise ValueError("OpenFootball resource paths are duplicated")
        if any(item.byte_size > self.max_response_bytes for item in resources):
            raise ValueError("configured resource exceeds response limit")
        return self

    def raw_path(self, resource_path: str) -> str:
        allowed = {self.licence.path, *(season.path for season in self.seasons)}
        if resource_path not in allowed:
            raise IngestionError("INTERNAL_INVARIANT", "OpenFootball path is not allowlisted")
        return f"/{self.repository}/{self.commit_sha}/{resource_path}"


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _resource_bytes(name: str, repository_path: str, path: Path | None) -> bytes:
    if path is not None:
        try:
            return path.read_bytes()
        except OSError as exc:
            raise IngestionError("CONFIGURATION_INVALID", "configuration is unavailable") from exc
    candidate = Path(__file__).resolve().parents[4] / repository_path
    if candidate.is_file():
        try:
            return candidate.read_bytes()
        except OSError as exc:
            raise IngestionError("CONFIGURATION_INVALID", "configuration is unavailable") from exc
    try:
        return resources.files("dmf_pulse").joinpath(name).read_bytes()
    except (OSError, ModuleNotFoundError) as exc:
        raise IngestionError("CONFIGURATION_INVALID", "configuration is unavailable") from exc


def _json_value(data: bytes) -> object:
    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )


def load_provider_config(path: Path | None = None) -> OpenFootballProviderConfig:
    try:
        value = _json_value(
            _resource_bytes(
                PROVIDER_RESOURCE,
                "config/providers/openfootball_score_prior.json",
                path,
            )
        )
        return OpenFootballProviderConfig.model_validate_json(
            json.dumps(value, allow_nan=False, ensure_ascii=False), strict=True
        )
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "OpenFootball provider configuration is invalid"
        ) from exc


def load_rights_profiles(path: Path | None = None) -> dict[str, RightsProfile]:
    try:
        value = _json_value(
            _resource_bytes(
                RIGHTS_RESOURCE,
                "config/rights/openfootball_profiles.json",
                path,
            )
        )
        if not isinstance(value, dict) or value.get("schema_version") != "1.0.0":
            raise ValueError("invalid OpenFootball rights registry")
        raw_profiles = value.get("profiles")
        if not isinstance(raw_profiles, list):
            raise ValueError("invalid OpenFootball rights registry")
        profiles = [
            RightsProfile.model_validate_json(
                json.dumps(item, allow_nan=False, ensure_ascii=False), strict=True
            )
            for item in raw_profiles
        ]
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "OpenFootball rights configuration is invalid"
        ) from exc
    result = {profile.rights_profile_id: profile for profile in profiles}
    if len(result) != len(profiles) or set(result) != {APPROVED_PROFILE_ID}:
        raise IngestionError(
            "CONFIGURATION_INVALID", "OpenFootball rights profile identity is invalid"
        )
    return result


def provider_config_sha256(path: Path | None = None) -> str:
    try:
        value = _json_value(
            _resource_bytes(
                PROVIDER_RESOURCE,
                "config/providers/openfootball_score_prior.json",
                path,
            )
        )
        load_provider_config(path)
        return canonical_sha256(value)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise IngestionError("CONFIGURATION_INVALID", "provider configuration is invalid") from exc


def rights_config_sha256(path: Path | None = None) -> str:
    try:
        value = _json_value(
            _resource_bytes(
                RIGHTS_RESOURCE,
                "config/rights/openfootball_profiles.json",
                path,
            )
        )
        load_rights_profiles(path)
        return canonical_sha256(value)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise IngestionError("CONFIGURATION_INVALID", "rights configuration is invalid") from exc


__all__ = [
    "APPROVED_COMMIT_SHA",
    "APPROVED_PROFILE_ID",
    "OpenFootballProviderConfig",
    "OpenFootballResourceConfig",
    "OpenFootballSeasonConfig",
    "load_provider_config",
    "load_rights_profiles",
    "provider_config_sha256",
    "rights_config_sha256",
]
