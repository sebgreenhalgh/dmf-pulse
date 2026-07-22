"""Pydantic v2 models for the foundation application configuration."""

from __future__ import annotations

import os
import re
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import TZPATH, ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    StrictBool,
    field_validator,
)

from dmf_pulse.config.sensitivity import looks_sensitive_string

REFERENCE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{2,127}$")
BUNDLED_ZONEINFO_ROOT = Path(__file__).resolve().parents[1] / "_data" / "zoneinfo"


class EnvironmentName(StrEnum):
    """Supported isolated operating environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"
    REPLAY = "replay"


class LogLevel(StrEnum):
    """Supported application log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ComputeDevice(StrEnum):
    """Required compatibility device for FND-001."""

    CPU = "cpu"


class AcceleratorName(StrEnum):
    """Optional accelerator request understood by the foundation."""

    CUDA = "cuda"


def _validate_reference_identifier(value: str) -> str:
    candidate = value.strip()
    looks_like_url_or_dsn = "://" in candidate or "@" in candidate or "?" in candidate
    if (
        REFERENCE_PATTERN.fullmatch(candidate) is None
        or looks_like_url_or_dsn
        or looks_sensitive_string(candidate)
    ):
        raise ValueError("must be an opaque reference identifier, never a secret or DSN value")
    return candidate


ReferenceIdentifier = Annotated[str, AfterValidator(_validate_reference_identifier)]


def _load_zoneinfo(value: str) -> ZoneInfo:
    """Load IANA data from stdlib paths or the base interpreter's standard share path."""

    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        parts = value.split("/")
        if not parts or any(
            part in {"", ".", ".."} or re.fullmatch(r"[A-Za-z0-9_+\-]+", part) is None
            for part in parts
        ):
            raise
        search_roots = [
            *(Path(item) for item in TZPATH),
            Path(sys.base_prefix) / "share" / "zoneinfo",
            BUNDLED_ZONEINFO_ROOT,
        ]
        for root in search_roots:
            candidate = root.joinpath(*parts)
            if candidate.is_file():
                with candidate.open("rb") as handle:
                    return ZoneInfo.from_file(handle, key=value)
        raise


class ComputeConfig(BaseModel):
    """CPU-required compute profile with an optional CUDA request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    device: ComputeDevice = ComputeDevice.CPU
    requested_accelerator: AcceleratorName | None = None
    fallback_to_cpu: StrictBool = True

    @field_validator("device", mode="before")
    @classmethod
    def parse_device(cls, value: object) -> object:
        return ComputeDevice(value) if isinstance(value, str) else value

    @field_validator("requested_accelerator", mode="before")
    @classmethod
    def parse_accelerator(cls, value: object) -> object:
        return AcceleratorName(value) if isinstance(value, str) else value

    @field_validator("fallback_to_cpu")
    @classmethod
    def require_safe_fallback(cls, value: bool) -> bool:
        if not value:
            raise ValueError("CPU fallback must remain enabled")
        return value


class AppConfig(BaseModel):
    """Strict foundation configuration with no implicit I/O or secret resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    environment: EnvironmentName
    internal_timezone: Literal["UTC"] = "UTC"
    display_timezone: str = "Europe/London"
    artifact_root: Path
    database_dsn_ref: ReferenceIdentifier | None = None
    log_level: LogLevel = LogLevel.INFO
    compute: ComputeConfig = ComputeConfig()

    @field_validator("environment", mode="before")
    @classmethod
    def parse_environment(cls, value: object) -> object:
        return EnvironmentName(value.casefold()) if isinstance(value, str) else value

    @field_validator("log_level", mode="before")
    @classmethod
    def parse_log_level(cls, value: object) -> object:
        return LogLevel(value.upper()) if isinstance(value, str) else value

    @field_validator("display_timezone")
    @classmethod
    def validate_display_timezone(cls, value: str) -> str:
        """Require a canonical timezone available through ``zoneinfo``."""

        candidate = value.strip()
        try:
            zone = _load_zoneinfo(candidate)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("must be a valid IANA timezone") from exc
        if zone.key != candidate:
            raise ValueError("must use the canonical IANA timezone name")
        return candidate

    @field_validator("artifact_root", mode="before")
    @classmethod
    def normalize_artifact_root(cls, value: object) -> Path:
        """Normalize a path lexically without creating or resolving it."""

        if not isinstance(value, (str, os.PathLike)):
            raise ValueError("must be a filesystem path")
        candidate = os.fspath(value).strip()
        if not candidate or candidate.startswith("~"):
            raise ValueError("must be a non-empty explicit path without home expansion")
        return Path(os.path.normpath(candidate))
