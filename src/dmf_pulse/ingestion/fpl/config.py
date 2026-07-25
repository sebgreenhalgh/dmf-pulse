"""Strict runtime loading for the packaged FPL provider configuration."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.rights import rights_config_sha256

PROVIDER_RESOURCE = "ingestion/resources/fpl.json"


class _FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderEndpoint(_FrozenConfig):
    host: Literal["fantasy.premierleague.com"]
    path: str = Field(min_length=2, max_length=128)


class ProviderResources(_FrozenConfig):
    bootstrap: ProviderEndpoint
    fixtures: ProviderEndpoint


class ProviderTimeouts(_FrozenConfig):
    connect: int = Field(gt=0, le=60)
    read: int = Field(gt=0, le=60)
    total: int = Field(gt=0, le=120)

    @model_validator(mode="after")
    def validate_deadline(self) -> ProviderTimeouts:
        if self.connect + self.read > self.total:
            raise ValueError("provider timeout budget is inconsistent")
        return self


class FplProviderConfig(_FrozenConfig):
    provider_key: Literal["official_fpl"]
    adapter_version: Literal["fpl-reference-v1"]
    contract_version: Literal["fpl-reference-v1"]
    max_json_depth: int = Field(gt=0, le=256)
    max_response_bytes: int = Field(gt=0, le=16 * 1024 * 1024)
    resources: ProviderResources
    timeouts_seconds: ProviderTimeouts

    @model_validator(mode="after")
    def validate_endpoints(self) -> FplProviderConfig:
        endpoints = (self.resources.bootstrap, self.resources.fixtures)
        if any(
            not endpoint.path.startswith("/")
            or endpoint.path.startswith("//")
            or "?" in endpoint.path
            or "#" in endpoint.path
            or "@" in endpoint.path
            for endpoint in endpoints
        ):
            raise ValueError("provider endpoint path is not allowlisted")
        if self.resources.bootstrap.path == self.resources.fixtures.path:
            raise ValueError("provider endpoint paths must differ")
        return self


def _provider_bytes(path: Path | None = None) -> bytes:
    if path is not None:
        try:
            return path.read_bytes()
        except OSError as exc:
            raise IngestionError(
                "CONFIGURATION_INVALID", "FPL provider configuration is unavailable"
            ) from exc
    repository_candidate = Path(__file__).resolve().parents[4] / "config/providers/fpl.json"
    if repository_candidate.is_file():
        return repository_candidate.read_bytes()
    try:
        return resources.files("dmf_pulse").joinpath(PROVIDER_RESOURCE).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "FPL provider configuration is unavailable"
        ) from exc


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate provider configuration key")
        value[key] = item
    return value


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _provider_value(path: Path | None = None) -> dict[str, object]:
    value = json.loads(
        _provider_bytes(path).decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("invalid FPL provider configuration")
    return value


def load_provider_config(path: Path | None = None) -> FplProviderConfig:
    try:
        return FplProviderConfig.model_validate(_provider_value(path), strict=False)
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "FPL provider configuration is invalid"
        ) from exc


def provider_config_sha256(path: Path | None = None) -> str:
    try:
        value = _provider_value(path)
        FplProviderConfig.model_validate(value, strict=False)
        return canonical_sha256(value)
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise IngestionError(
            "CONFIGURATION_INVALID", "FPL provider configuration is invalid"
        ) from exc


def effective_config_sha256() -> str:
    """Bind bundle and resume lineage to both provider and rights authorities."""

    return canonical_sha256(
        {
            "provider_config_sha256": provider_config_sha256(),
            "rights_config_sha256": rights_config_sha256(),
        }
    )
