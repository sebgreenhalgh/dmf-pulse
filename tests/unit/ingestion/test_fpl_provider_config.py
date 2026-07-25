"""Strict provider-configuration loading and lineage tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.config import (
    effective_config_sha256,
    load_provider_config,
    provider_config_sha256,
)
from dmf_pulse.ingestion.rights import rights_config_sha256

pytestmark = pytest.mark.unit


def _provider_path(repository_root: Path) -> Path:
    return repository_root / "config/providers/fpl.json"


def test_provider_config_controls_endpoints_limits_timeouts_and_versions(
    repository_root: Path,
) -> None:
    config = load_provider_config(_provider_path(repository_root))
    assert config.provider_key == "official_fpl"
    assert config.resources.bootstrap.path == "/api/bootstrap-static/"
    assert config.resources.fixtures.path == "/api/fixtures/"
    assert config.max_response_bytes == 5 * 1024 * 1024
    assert config.max_json_depth == 64
    assert config.timeouts_seconds.connect + config.timeouts_seconds.read <= (
        config.timeouts_seconds.total
    )
    assert config.contract_version == "fpl-reference-v1"


def test_provider_config_hash_is_canonical_and_effective_hash_binds_both_authorities(
    repository_root: Path, tmp_path: Path
) -> None:
    path = _provider_path(repository_root)
    value = json.loads(path.read_text(encoding="utf-8"))
    reformatted = tmp_path / "provider.json"
    reformatted.write_text(json.dumps(value, indent=5), encoding="utf-8")
    assert provider_config_sha256(path) == provider_config_sha256(reformatted)
    assert effective_config_sha256() == canonical_sha256(
        {
            "provider_config_sha256": provider_config_sha256(),
            "rights_config_sha256": rights_config_sha256(),
        }
    )


@pytest.mark.parametrize(
    "content",
    (
        '{"provider_key":"official_fpl","provider_key":"other"}',
        '{"provider_key":NaN}',
        "[]",
    ),
)
def test_provider_config_rejects_duplicate_nonfinite_and_nonobject_json(
    content: str, tmp_path: Path
) -> None:
    path = tmp_path / "provider.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(IngestionError) as caught:
        load_provider_config(path)
    assert caught.value.code == "CONFIGURATION_INVALID"


def test_provider_config_rejects_endpoint_and_timeout_drift(
    repository_root: Path, tmp_path: Path
) -> None:
    value = json.loads(_provider_path(repository_root).read_text(encoding="utf-8"))
    value["resources"]["bootstrap"]["path"] = "//attacker.invalid/api"
    value["timeouts_seconds"] = {"connect": 10, "read": 10, "total": 15}
    path = tmp_path / "provider.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(IngestionError) as caught:
        provider_config_sha256(path)
    assert caught.value.code == "CONFIGURATION_INVALID"
