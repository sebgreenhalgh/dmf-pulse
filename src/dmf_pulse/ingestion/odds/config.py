"""Strict, packaged The Odds API provider and rights configuration."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.models import RightsProfile

PROVIDER_RESOURCE = "ingestion/resources/the_odds_api.json"
RIGHTS_RESOURCE = "ingestion/resources/odds_profiles.json"


class _FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProviderTimeouts(_FrozenConfig):
    connect: int = Field(gt=0, le=60)
    read: int = Field(gt=0, le=60)
    total: int = Field(gt=0, le=120)

    @model_validator(mode="after")
    def validate_budget(self) -> ProviderTimeouts:
        if self.connect + self.read > self.total:
            raise ValueError("provider timeout budget is inconsistent")
        return self


class RetryPolicy(_FrozenConfig):
    max_attempts: int = Field(ge=1, le=3)
    default_delay_seconds: int = Field(ge=1, le=60)
    maximum_retry_after_seconds: int = Field(ge=1, le=60)

    @model_validator(mode="after")
    def validate_delay(self) -> RetryPolicy:
        if self.default_delay_seconds > self.maximum_retry_after_seconds:
            raise ValueError("retry delay policy is inconsistent")
        return self


class OddsProviderConfig(_FrozenConfig):
    provider_key: Literal["the_odds_api"]
    api_version: Literal["v4"]
    adapter_version: Literal["the-odds-api-v4-reference-v1"]
    contract_version: Literal["the-odds-api-v4-reference-v1"]
    scheme: Literal["https"]
    host: Literal["api.the-odds-api.com"]
    path: Literal["/v4/sports/soccer_epl/odds"]
    sport_keys: tuple[Literal["soccer_epl"], ...]
    regions: tuple[Literal["uk"], ...]
    markets: tuple[Literal["h2h", "totals"], ...]
    odds_format: Literal["decimal"]
    date_format: Literal["iso"]
    request_cost: int = Field(gt=0, le=10)
    max_response_bytes: int = Field(gt=0, le=16 * 1024 * 1024)
    max_json_depth: int = Field(gt=0, le=256)
    max_events: int = Field(gt=0, le=10_000)
    max_bookmakers_per_event: int = Field(gt=0, le=1000)
    max_markets_per_bookmaker: int = Field(gt=0, le=100)
    max_outcomes_per_market: int = Field(gt=0, le=1000)
    max_text_length: int = Field(gt=0, le=2000)
    timeouts_seconds: ProviderTimeouts
    retry: RetryPolicy

    @model_validator(mode="after")
    def validate_allowlists(self) -> OddsProviderConfig:
        if self.sport_keys != ("soccer_epl",):
            raise ValueError("sport allowlist drifted")
        if self.regions != ("uk",) or self.markets != ("h2h", "totals"):
            raise ValueError("market allowlist drifted")
        if self.request_cost != len(self.markets) * len(self.regions):
            raise ValueError("request cost does not match market-region coverage")
        return self


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
        return candidate.read_bytes()
    try:
        return resources.files("dmf_pulse").joinpath(name).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise IngestionError("CONFIGURATION_INVALID", "configuration is unavailable") from exc


def _json_value(data: bytes) -> object:
    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )


def load_provider_config(path: Path | None = None) -> OddsProviderConfig:
    try:
        value = _json_value(
            _resource_bytes(PROVIDER_RESOURCE, "config/providers/the_odds_api.json", path)
        )
        return OddsProviderConfig.model_validate_json(
            json.dumps(value, allow_nan=False, ensure_ascii=False), strict=True
        )
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError("CONFIGURATION_INVALID", "provider configuration is invalid") from exc


def provider_config_sha256(path: Path | None = None) -> str:
    try:
        return canonical_sha256(
            _json_value(
                _resource_bytes(PROVIDER_RESOURCE, "config/providers/the_odds_api.json", path)
            )
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise IngestionError("CONFIGURATION_INVALID", "provider configuration is invalid") from exc


def rights_config_sha256(path: Path | None = None) -> str:
    try:
        value = _json_value(
            _resource_bytes(RIGHTS_RESOURCE, "config/rights/odds_profiles.json", path)
        )
        load_rights_profiles(path)
        return canonical_sha256(value)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "odds rights configuration is invalid"
        ) from exc


def load_rights_profiles(path: Path | None = None) -> dict[str, RightsProfile]:
    try:
        value = _json_value(
            _resource_bytes(RIGHTS_RESOURCE, "config/rights/odds_profiles.json", path)
        )
        if not isinstance(value, dict) or value.get("schema_version") != "1.0.0":
            raise ValueError("invalid odds rights registry")
        raw_profiles = value.get("profiles")
        if not isinstance(raw_profiles, list):
            raise ValueError("invalid odds rights registry")
        profiles = [
            RightsProfile.model_validate_json(
                json.dumps(item, allow_nan=False, ensure_ascii=False), strict=True
            )
            for item in raw_profiles
        ]
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "odds rights configuration is invalid"
        ) from exc
    result = {profile.rights_profile_id: profile for profile in profiles}
    if len(result) != len(profiles):
        raise IngestionError("CONFIGURATION_INVALID", "odds rights profiles are duplicated")
    return result


def effective_config_sha256() -> str:
    return canonical_sha256(
        {
            "provider_config_sha256": provider_config_sha256(),
            "rights_config_sha256": rights_config_sha256(),
        }
    )
