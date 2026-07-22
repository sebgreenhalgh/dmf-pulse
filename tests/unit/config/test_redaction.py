"""Branch-complete defense-in-depth redaction tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmf_pulse.config.models import AppConfig, EnvironmentName
from dmf_pulse.config.redaction import (
    REDACTED,
    canonical_config,
    looks_sensitive_string,
    redact_sensitive,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "-----BEGIN " + "PRIVATE KEY-----",
        "Bearer " + "FakeBearer987654321",
        "https://service:" + "credential@example.invalid/path",
        "https://example.invalid/path?" + "token=" + "constructed-value",
        "eyJ" + "A" * 20 + "." + "B" * 12 + "." + "C" * 12,
        "AKIA" + "IOSFODNN7EXAMPLE",
        "http://[invalid-ipv6",
    ],
)
def test_sensitive_string_shapes_are_detected(value: str) -> None:
    assert looks_sensitive_string(value) is True


@pytest.mark.unit
def test_safe_url_and_reference_remain_visible_but_sensitive_key_does_not() -> None:
    assert looks_sensitive_string("https://example.invalid/public?format=json") is False
    value = {
        "database_dsn_ref": "systemd/database-dsn",
        "password": None,
        "nested": (Path("artifacts"), "safe"),
    }
    assert redact_sensitive(value) == {
        "database_dsn_ref": "systemd/database-dsn",
        "nested": ["artifacts", "safe"],
        "password": REDACTED,
    }


@pytest.mark.unit
def test_canonical_config_is_json_compatible_and_sorted() -> None:
    config = AppConfig(environment=EnvironmentName.REPLAY, artifact_root=Path("artifacts/replay"))
    result = canonical_config(config)
    assert list(result) == sorted(result)
    assert result["environment"] == "replay"
    assert result["artifact_root"] == str(Path("artifacts/replay"))


@pytest.mark.unit
def test_reference_key_redacts_defensively_if_an_unvalidated_token_reaches_display() -> None:
    jwt = "eyJ" + "A" * 20 + "." + "B" * 12 + "." + "C" * 12
    assert redact_sensitive({"database_dsn_ref": jwt}) == {"database_dsn_ref": REDACTED}
