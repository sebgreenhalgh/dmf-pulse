"""Deterministic YAML overlay loading with no write or external-system side effects."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from dmf_pulse.config.errors import ConfigError, ConfigIssue
from dmf_pulse.config.models import AppConfig, EnvironmentName


def _clone_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _clone_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_value(item) for item in value]
    if isinstance(value, tuple):
        return [_clone_value(item) for item in value]
    return value


def _validate_mapping_keys(value: Mapping[Any, object], label: str) -> None:
    for key, nested in value.items():
        if not isinstance(key, str):
            raise ConfigError("CONFIG_MAPPING_INVALID", f"{label} contains a non-string key")
        if isinstance(nested, Mapping):
            _validate_mapping_keys(nested, label)


def deep_merge(base: Mapping[str, object], overlay: Mapping[str, object]) -> dict[str, object]:
    """Recursively merge mappings; scalars and sequences replace the prior value."""

    _validate_mapping_keys(base, "base mapping")
    _validate_mapping_keys(overlay, "overlay mapping")
    result = {key: _clone_value(value) for key, value in base.items()}
    for key, overlay_value in overlay.items():
        base_value = result.get(key)
        if isinstance(base_value, Mapping) and isinstance(overlay_value, Mapping):
            result[key] = deep_merge(base_value, overlay_value)
        else:
            result[key] = _clone_value(overlay_value)
    return result


def _load_yaml_mapping(path: Path, *, required: bool, label: str) -> dict[str, object]:
    if not path.is_file():
        if required:
            raise ConfigError(
                "CONFIG_FILE_MISSING",
                f"required configuration file is missing: {label}",
            )
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigError("CONFIG_YAML_INVALID", f"configuration YAML is invalid: {label}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ConfigError("CONFIG_MAPPING_INVALID", f"configuration must be a mapping: {label}")
    _validate_mapping_keys(raw, label)
    return {str(key): _clone_value(value) for key, value in raw.items()}


def _validation_issues(error: ValidationError) -> tuple[ConfigIssue, ...]:
    issues = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(part) for part in item.get("loc", ())) or "$"
        issues.append(
            ConfigIssue(
                location=location,
                message=str(item.get("msg", "invalid value")),
                issue_type=str(item.get("type", "value_error")),
            )
        )
    return tuple(
        sorted(issues, key=lambda issue: (issue.location, issue.issue_type, issue.message))
    )


def load_config(
    *,
    environment: EnvironmentName,
    config_root: Path,
    overrides: Mapping[str, object] | None = None,
) -> AppConfig:
    """Load base → environment → explicit overrides and validate the result."""

    base = _load_yaml_mapping(
        config_root / "base" / "application.yaml",
        required=True,
        label="base/application.yaml",
    )
    environment_overlay = _load_yaml_mapping(
        config_root / "environments" / f"{environment.value}.yaml",
        required=False,
        label=f"environments/{environment.value}.yaml",
    )
    merged = deep_merge(base, environment_overlay)
    if overrides is not None:
        merged = deep_merge(merged, overrides)
    configured_environment = merged.get("environment")
    if configured_environment is not None and configured_environment != environment.value:
        raise ConfigError(
            "CONFIG_ENVIRONMENT_MISMATCH",
            "configuration environment does not match the requested environment",
        )
    merged["environment"] = environment.value
    try:
        return AppConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(
            "CONFIG_VALIDATION_FAILED",
            "configuration validation failed",
            issues=_validation_issues(exc),
        ) from exc


def default_config(*, environment: EnvironmentName = EnvironmentName.DEVELOPMENT) -> AppConfig:
    """Return the installed-wheel fallback without reading the filesystem."""

    try:
        return AppConfig(
            environment=environment,
            artifact_root=Path("artifacts"),
        )
    except ValidationError as exc:
        raise ConfigError(
            "CONFIG_VALIDATION_FAILED",
            "built-in configuration validation failed",
            issues=_validation_issues(exc),
        ) from exc
