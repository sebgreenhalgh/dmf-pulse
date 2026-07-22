"""Independent behaviour tests for strict configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmf_pulse.config import (
    AppConfig,
    ConfigError,
    EnvironmentName,
    LogLevel,
    deep_merge,
    load_config,
)
from dmf_pulse.config import models as config_models

VALID_BASE = """\
internal_timezone: UTC
display_timezone: Europe/London
artifact_root: artifacts/base
database_dsn_ref: null
log_level: INFO
compute:
  device: cpu
  requested_accelerator: null
  fallback_to_cpu: true
"""


def _config_root(tmp_path: Path, *, base: str = VALID_BASE, overlay: str = "") -> Path:
    root = tmp_path / "config"
    (root / "base").mkdir(parents=True)
    (root / "environments").mkdir()
    (root / "base" / "application.yaml").write_text(base, encoding="utf-8")
    if overlay:
        (root / "environments" / "test.yaml").write_text(overlay, encoding="utf-8")
    return root


@pytest.mark.unit
def test_repository_test_overlay_loads_without_creating_artifact_root(
    repository_root: Path,
) -> None:
    artifact_root = repository_root / "artifacts" / "test"
    assert not artifact_root.exists()
    config = load_config(
        environment=EnvironmentName.TEST,
        config_root=repository_root / "config",
    )
    assert config.environment is EnvironmentName.TEST
    assert config.log_level is LogLevel.WARNING
    assert config.artifact_root == Path("artifacts/test")
    assert not artifact_root.exists()


@pytest.mark.unit
def test_overlay_then_explicit_override_precedence_and_nested_mapping(tmp_path: Path) -> None:
    root = _config_root(
        tmp_path,
        overlay="log_level: WARNING\ncompute:\n  requested_accelerator: cuda\n",
    )
    config = load_config(
        environment=EnvironmentName.TEST,
        config_root=root,
        overrides={"log_level": "ERROR"},
    )
    assert config.log_level is LogLevel.ERROR
    assert config.compute.requested_accelerator == "cuda"
    assert config.compute.fallback_to_cpu is True
    assert config.compute.device == "cpu"


@pytest.mark.unit
def test_deep_merge_does_not_mutate_and_replaces_sequences() -> None:
    base: dict[str, object] = {"nested": {"left": 1, "items": [1, 2]}, "stable": True}
    overlay: dict[str, object] = {"nested": {"right": 2, "items": [3]}}
    assert deep_merge(base, overlay) == {
        "nested": {"items": [3], "left": 1, "right": 2},
        "stable": True,
    }
    assert base == {"nested": {"left": 1, "items": [1, 2]}, "stable": True}
    assert overlay == {"nested": {"right": 2, "items": [3]}}


@pytest.mark.unit
def test_unknown_field_is_rejected_with_sanitized_location(tmp_path: Path) -> None:
    root = _config_root(tmp_path, base=VALID_BASE + "unexpected: true\n")
    with pytest.raises(ConfigError) as caught:
        load_config(environment=EnvironmentName.TEST, config_root=root)
    assert caught.value.code == "CONFIG_VALIDATION_FAILED"
    assert [issue.location for issue in caught.value.issues] == ["unexpected"]


@pytest.mark.unit
def test_missing_base_and_non_mapping_yaml_have_exact_codes(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="required configuration") as missing:
        load_config(environment=EnvironmentName.TEST, config_root=tmp_path)
    assert missing.value.code == "CONFIG_FILE_MISSING"

    root = _config_root(tmp_path, base="- not\n- a mapping\n")
    with pytest.raises(ConfigError) as invalid:
        load_config(environment=EnvironmentName.TEST, config_root=root)
    assert invalid.value.code == "CONFIG_MAPPING_INVALID"


@pytest.mark.unit
def test_path_is_lexically_normalized_and_home_expansion_is_rejected(tmp_path: Path) -> None:
    root = _config_root(tmp_path, base=VALID_BASE.replace("artifacts/base", "artifacts/../safe"))
    config = load_config(environment=EnvironmentName.TEST, config_root=root)
    assert config.artifact_root == Path("safe")

    root = _config_root(tmp_path / "home", base=VALID_BASE.replace("artifacts/base", "~/secret"))
    with pytest.raises(ConfigError) as caught:
        load_config(environment=EnvironmentName.TEST, config_root=root)
    assert caught.value.issues[0].location == "artifact_root"


@pytest.mark.unit
def test_invalid_timezone_log_level_and_compute_field_are_rejected(tmp_path: Path) -> None:
    replacements = (
        ("Europe/London", "Not/A_Real_Zone", "display_timezone"),
        ("log_level: INFO", "log_level: VERBOSE", "log_level"),
        ("fallback_to_cpu: true", "fallback_to_cpu: true\n  extra: nope", "compute.extra"),
    )
    for index, (old, new, expected_location) in enumerate(replacements):
        root = _config_root(tmp_path / str(index), base=VALID_BASE.replace(old, new))
        with pytest.raises(ConfigError) as caught:
            load_config(environment=EnvironmentName.TEST, config_root=root)
        assert expected_location in {issue.location for issue in caught.value.issues}


@pytest.mark.unit
def test_raw_dsn_is_rejected_without_echoing_secret(tmp_path: Path) -> None:
    raw_value = "postgresql://service:" + "do-not-print-123" + "@db.internal/pulse"
    root = _config_root(
        tmp_path,
        base=VALID_BASE.replace("database_dsn_ref: null", f'database_dsn_ref: "{raw_value}"'),
    )
    with pytest.raises(ConfigError) as caught:
        load_config(environment=EnvironmentName.TEST, config_root=root)
    rendered = str(caught.value.as_error_object())
    assert raw_value not in rendered
    assert "do-not-print" not in rendered
    assert caught.value.issues[0].location == "database_dsn_ref"


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw_value",
    [
        "ghp_" + "ConstructedValue12345678",
        "sk-" + "ConstructedValue12345678",
        "xoxb-" + "ConstructedValue12345678",
        "eyJ" + "A" * 20 + "." + "B" * 12 + "." + "C" * 12,
        "AKIA" + "IOSFODNN7EXAMPLE",
    ],
)
def test_raw_token_shapes_are_rejected_without_echo(tmp_path: Path, raw_value: str) -> None:
    root = _config_root(
        tmp_path,
        base=VALID_BASE.replace("database_dsn_ref: null", f'database_dsn_ref: "{raw_value}"'),
    )
    with pytest.raises(ConfigError) as caught:
        load_config(environment=EnvironmentName.TEST, config_root=root)
    assert caught.value.code == "CONFIG_VALIDATION_FAILED"
    assert raw_value not in str(caught.value.as_error_object())
    assert {issue.location for issue in caught.value.issues} == {"database_dsn_ref"}


@pytest.mark.unit
@pytest.mark.parametrize("yaml_value", ["false", '"false"', "0"])
def test_cpu_fallback_must_be_true_strict_boolean(tmp_path: Path, yaml_value: str) -> None:
    root = _config_root(
        tmp_path,
        base=VALID_BASE.replace("fallback_to_cpu: true", f"fallback_to_cpu: {yaml_value}"),
    )
    with pytest.raises(ConfigError) as caught:
        load_config(environment=EnvironmentName.TEST, config_root=root)
    assert "compute.fallback_to_cpu" in {issue.location for issue in caught.value.issues}


@pytest.mark.unit
def test_bundled_london_zoneinfo_fallback_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    class BundledOnlyZoneInfo:
        key = "Europe/London"

        def __init__(self, _value: str) -> None:
            raise config_models.ZoneInfoNotFoundError

        @classmethod
        def from_file(cls, handle: object, *, key: str) -> BundledOnlyZoneInfo:
            assert key == "Europe/London"
            assert hasattr(handle, "read")
            payload = handle.read()  # type: ignore[union-attr]
            assert payload.startswith(b"TZif")
            instance = object.__new__(cls)
            instance.key = key
            return instance

    monkeypatch.setattr(config_models, "TZPATH", ())
    monkeypatch.setattr(config_models, "ZoneInfo", BundledOnlyZoneInfo)
    loaded = config_models._load_zoneinfo("Europe/London")
    assert loaded.key == "Europe/London"


@pytest.mark.unit
def test_safe_reference_and_repeat_load_have_equal_canonical_models(tmp_path: Path) -> None:
    root = _config_root(
        tmp_path,
        base=VALID_BASE.replace("database_dsn_ref: null", "database_dsn_ref: systemd/database-dsn"),
    )
    first = load_config(environment=EnvironmentName.TEST, config_root=root)
    second = load_config(environment=EnvironmentName.TEST, config_root=root)
    assert first == second
    assert first.database_dsn_ref == "systemd/database-dsn"


@pytest.mark.unit
def test_requested_environment_cannot_be_overridden(tmp_path: Path) -> None:
    root = _config_root(tmp_path)
    with pytest.raises(ConfigError) as caught:
        load_config(
            environment=EnvironmentName.TEST,
            config_root=root,
            overrides={"environment": "production"},
        )
    assert caught.value.code == "CONFIG_ENVIRONMENT_MISMATCH"


@pytest.mark.unit
def test_empty_optional_overlay_invalid_yaml_tuple_and_non_string_key(tmp_path: Path) -> None:
    root = _config_root(tmp_path)
    (root / "environments/test.yaml").write_text("", encoding="utf-8")
    config = load_config(environment=EnvironmentName.TEST, config_root=root)
    assert config.environment is EnvironmentName.TEST
    assert deep_merge({"tuple": (1, 2)}, {}) == {"tuple": [1, 2]}

    (root / "base/application.yaml").write_text("key: [unterminated", encoding="utf-8")
    with pytest.raises(ConfigError) as yaml_error:
        load_config(environment=EnvironmentName.TEST, config_root=root)
    assert yaml_error.value.code == "CONFIG_YAML_INVALID"

    with pytest.raises(ConfigError) as mapping_error:
        deep_merge({1: "bad"}, {})  # type: ignore[dict-item]
    assert mapping_error.value.code == "CONFIG_MAPPING_INVALID"


@pytest.mark.unit
def test_artifact_root_requires_a_non_empty_path_value() -> None:
    for value in ("", 123):
        with pytest.raises(ValueError):
            AppConfig(environment=EnvironmentName.TEST, artifact_root=value)  # type: ignore[arg-type]
