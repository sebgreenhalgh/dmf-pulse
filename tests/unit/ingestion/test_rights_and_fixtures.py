"""Rights fail-closed and manifest-bound fixture tests."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest

from dmf_pulse.ingestion import fixtures as fixtures_module
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fixtures import approve_synthetic_fixture
from dmf_pulse.ingestion.models import (
    CapabilityValue,
    RightsCapability,
    RightsProfileStatus,
)
from dmf_pulse.ingestion.rights import (
    decide_rights,
    load_rights_profiles,
    require_rights,
    rights_config_sha256,
)

pytestmark = pytest.mark.unit


def _config(root: Path) -> Path:
    return root / "config" / "rights" / "fpl_profiles.json"


def _write_fixture_tree(
    root: Path,
    *,
    body: bytes = b'{"synthetic":true}',
    profile_id: str = "synthetic_test_v1",
    digest: str | None = None,
    entries: int = 1,
) -> Path:
    target = root / "fixtures" / "case" / "payload.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(body)
    item = {
        "bytes": len(body),
        "path": "fixtures/case/payload.json",
        "rights_profile": profile_id,
        "sha256": digest or hashlib.sha256(body).hexdigest(),
        "synthetic": True,
    }
    manifest = {"entries": [item.copy() for _ in range(entries)]}
    (root / "fixtures" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return target


def test_required_profiles_encode_the_conservative_capability_matrix(repository_root: Path) -> None:
    profiles = load_rights_profiles(_config(repository_root))
    synthetic = profiles["synthetic_test_v1"]
    official = profiles["fpl_official_private_manual_v1"]

    assert set(profiles) == {"synthetic_test_v1", "fpl_official_private_manual_v1"}
    assert synthetic.status is RightsProfileStatus.HUMAN_APPROVED
    assert synthetic.capabilities[RightsCapability.RAW_STORAGE] is CapabilityValue.ALLOW
    assert synthetic.capabilities[RightsCapability.DERIVED_STORAGE] is CapabilityValue.ALLOW
    assert synthetic.capabilities[RightsCapability.MODEL_TRAINING] is CapabilityValue.DENY
    assert synthetic.capabilities[RightsCapability.AUTOMATED_ACCESS] is CapabilityValue.DENY
    assert official.retention_seconds == 0
    assert official.termination_deletion_required is True
    assert official.capabilities[RightsCapability.MANUAL_IMPORT] is CapabilityValue.ALLOW
    assert official.capabilities[RightsCapability.TRANSIENT_PROCESSING] is CapabilityValue.ALLOW
    assert official.capabilities[RightsCapability.RAW_STORAGE] is CapabilityValue.DENY
    assert official.capabilities[RightsCapability.DERIVED_STORAGE] is CapabilityValue.UNKNOWN
    assert official.capabilities[RightsCapability.AUTOMATED_ACCESS] is CapabilityValue.DENY


def test_default_profile_loader_resolves_repository_resource() -> None:
    assert set(load_rights_profiles()) == {
        "synthetic_test_v1",
        "fpl_official_private_manual_v1",
    }


def test_decisions_are_stable_and_unknown_is_denied(repository_root: Path) -> None:
    profiles = load_rights_profiles(_config(repository_root))
    synthetic = decide_rights(profiles["synthetic_test_v1"], RightsCapability.RAW_STORAGE)
    unknown = decide_rights(
        profiles["fpl_official_private_manual_v1"], RightsCapability.DERIVED_STORAGE
    )

    assert synthetic.decision == "ALLOW"
    assert synthetic.reason == "CAPABILITY_ALLOWED"
    assert (
        synthetic.checked_at is not None and synthetic.checked_at.utcoffset().total_seconds() == 0
    )
    assert unknown.decision == "DENY"
    assert unknown.reason == "CAPABILITY_UNKNOWN_DENIED"


def test_nonapproved_profile_denies_even_an_allow_capability(repository_root: Path) -> None:
    profile = load_rights_profiles(_config(repository_root))["synthetic_test_v1"]
    draft = profile.model_copy(update={"status": RightsProfileStatus.DRAFT})
    decision = decide_rights(draft, RightsCapability.RAW_STORAGE)
    assert decision.decision == "DENY"
    assert decision.reason == "PROFILE_NOT_APPROVED"


def test_loaded_rights_capability_map_is_deeply_immutable(repository_root: Path) -> None:
    profile = load_rights_profiles(_config(repository_root))["fpl_official_private_manual_v1"]
    with pytest.raises(TypeError):
        profile.capabilities[RightsCapability.AUTOMATED_ACCESS] = CapabilityValue.ALLOW
    capabilities = profile.capabilities
    with pytest.raises(TypeError):
        capabilities |= {RightsCapability.AUTOMATED_ACCESS: CapabilityValue.ALLOW}
    assert decide_rights(profile, RightsCapability.AUTOMATED_ACCESS).decision == "DENY"


def test_rights_decision_time_is_distinct_from_terms_check_time(repository_root: Path) -> None:
    profile = load_rights_profiles(_config(repository_root))["synthetic_test_v1"]
    decision_at = profile.checked_at + timedelta(days=3)
    decision = decide_rights(
        profile,
        RightsCapability.RAW_STORAGE,
        checked_at=decision_at,
    )
    assert decision.checked_at == decision_at
    assert decision.checked_at != profile.checked_at


def test_require_rights_has_stable_secret_safe_failure(repository_root: Path) -> None:
    profile = load_rights_profiles(_config(repository_root))["fpl_official_private_manual_v1"]
    with pytest.raises(IngestionError) as raised:
        require_rights(profile, RightsCapability.AUTOMATED_ACCESS)
    error = raised.value
    assert error.code == "RIGHTS_BLOCKED"
    assert error.exit_code == 4
    assert error.details["transport_call_count"] == 0
    assert error.details["capability"] == "automated_access"
    assert "Sebastian" not in str(error.as_error_object())


def test_require_rights_returns_the_allow_decision(repository_root: Path) -> None:
    profile = load_rights_profiles(_config(repository_root))["synthetic_test_v1"]
    decision = require_rights(profile, RightsCapability.RAW_STORAGE)
    assert decision.decision == "ALLOW"
    assert decision.capability == "raw_storage"


def test_ingestion_error_without_details_has_exact_public_shape() -> None:
    error = IngestionError("UNRECOGNIZED", "safe synthetic failure")
    assert error.exit_code == 8
    assert error.as_error_object() == {
        "error": {
            "code": "UNRECOGNIZED",
            "message": "safe synthetic failure",
            "retryable": False,
        },
        "schema_version": "1.0.0",
        "status": "FAILED",
    }


def test_rights_config_hash_is_canonical_across_json_formatting(
    repository_root: Path, tmp_path: Path
) -> None:
    original = _config(repository_root)
    value = json.loads(original.read_text(encoding="utf-8"))
    reformatted = tmp_path / "profiles.json"
    reformatted.write_text(json.dumps(value, indent=7, sort_keys=True), encoding="utf-8")
    assert rights_config_sha256(original) == rights_config_sha256(reformatted)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(schema_version="2.0.0"),
        lambda value: value.update(profiles="not-a-list"),
        lambda value: value["profiles"].append(value["profiles"][0].copy()),
        lambda value: value["profiles"][0]["capabilities"].pop("raw_storage"),
        lambda value: value["profiles"][0].update(retention_reason=None),
        lambda value: value["profiles"][0].update(attribution_required=True, attribution_text=None),
        lambda value: value["profiles"][0].update(checked_at="2026-07-23T00:00:00"),
    ],
)
def test_invalid_rights_registries_fail_closed(
    repository_root: Path, tmp_path: Path, mutation: object
) -> None:
    value = json.loads(_config(repository_root).read_text(encoding="utf-8"))
    mutation(value)  # type: ignore[operator]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(IngestionError) as raised:
        load_rights_profiles(path)
    assert raised.value.code == "CONFIGURATION_INVALID"


@pytest.mark.parametrize("body", [b"not json", b"\xff"])
def test_unreadable_rights_registry_fails_closed(tmp_path: Path, body: bytes) -> None:
    path = tmp_path / "profiles.json"
    path.write_bytes(body)
    with pytest.raises(IngestionError) as raised:
        load_rights_profiles(path)
    assert raised.value.code == "CONFIGURATION_INVALID"


def test_duplicate_rights_registry_keys_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(
        '{"schema_version":"1.0.0","schema_version":"1.0.0","profiles":[]}',
        encoding="utf-8",
    )
    with pytest.raises(IngestionError) as raised:
        load_rights_profiles(path)
    assert raised.value.code == "CONFIGURATION_INVALID"


def test_missing_rights_registry_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(IngestionError) as raised:
        load_rights_profiles(tmp_path / "missing.json")
    assert raised.value.code == "CONFIGURATION_INVALID"


def test_repository_fixture_is_approved_only_for_its_bound_profile(repository_root: Path) -> None:
    path = repository_root / "fixtures" / "fpl" / "FPL-004" / "happy_path" / "bootstrap.json"
    approved = approve_synthetic_fixture(path, profile_id="synthetic_test_v1")
    assert approved.path == path.resolve()
    assert approved.relative_path == "fixtures/fpl/FPL-004/happy_path/bootstrap.json"
    assert approved.sha256 == "b878e03f0eddb88889794f86df486c0d28f33e2498b58b9e66f947dd7c6e611e"

    with pytest.raises(IngestionError) as raised:
        approve_synthetic_fixture(path, profile_id="fpl_official_private_manual_v1")
    assert raised.value.code == "FIXTURE_NOT_APPROVED"


def test_nrm006_frozen_manifest_approves_only_synthetic_profiles(repository_root: Path) -> None:
    path = repository_root / "fixtures/odds/NRM-006/happy_path_market_query.json"
    approved = approve_synthetic_fixture(path, profile_id="synthetic_the_odds_api_v1")
    assert approved.relative_path == "fixtures/odds/NRM-006/happy_path_market_query.json"
    assert approved.sha256 == "ec556ddd6edf2f57f1489fb1c7641fb4cca244c88438c879e353e84dc761eafa"

    with pytest.raises(IngestionError) as raised:
        approve_synthetic_fixture(path, profile_id="the_odds_api_private_analytics_v1")
    assert raised.value.code == "FIXTURE_NOT_APPROVED"


def test_self_authored_manifest_outside_approved_fixture_root_is_not_authority(
    tmp_path: Path,
) -> None:
    target = _write_fixture_tree(tmp_path)
    with pytest.raises(IngestionError) as raised:
        approve_synthetic_fixture(target, profile_id="synthetic_test_v1")
    assert raised.value.code == "FIXTURE_NOT_APPROVED"


def test_fixture_approval_rejects_missing_manifest_and_missing_file(tmp_path: Path) -> None:
    unregistered = tmp_path / "unregistered.json"
    unregistered.write_text("{}", encoding="utf-8")
    with pytest.raises(IngestionError, match="manifest"):
        approve_synthetic_fixture(unregistered, profile_id="synthetic_test_v1")
    with pytest.raises(IngestionError, match="unavailable"):
        approve_synthetic_fixture(tmp_path / "missing.json", profile_id="synthetic_test_v1")


@pytest.mark.parametrize(
    "case",
    ["hash", "bytes", "profile", "synthetic", "duplicate", "path"],
)
def test_fixture_manifest_mismatch_is_rejected(tmp_path: Path, case: str) -> None:
    target = _write_fixture_tree(tmp_path)
    manifest_path = tmp_path / "fixtures" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["entries"][0]
    if case == "hash":
        entry["sha256"] = "0" * 64
    elif case == "bytes":
        entry["bytes"] += 1
    elif case == "profile":
        entry["rights_profile"] = "different"
    elif case == "synthetic":
        entry["synthetic"] = False
    elif case == "duplicate":
        manifest["entries"].append(entry.copy())
    else:
        entry["path"] = "fixtures/case/different.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(IngestionError) as raised:
        approve_synthetic_fixture(target, profile_id="synthetic_test_v1")
    assert raised.value.code == "FIXTURE_NOT_APPROVED"


def test_fixture_symlink_is_rejected_before_manifest_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write_fixture_tree(tmp_path)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == target or original(self))
    with pytest.raises(IngestionError, match="regular file"):
        approve_synthetic_fixture(target, profile_id="synthetic_test_v1")


def test_invalid_fixture_manifest_is_rejected(tmp_path: Path) -> None:
    target = _write_fixture_tree(tmp_path)
    (tmp_path / "fixtures" / "manifest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(IngestionError, match="manifest is invalid"):
        approve_synthetic_fixture(target, profile_id="synthetic_test_v1")


def test_fixture_manifest_read_failure_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write_fixture_tree(tmp_path)
    manifest_path = tmp_path / "fixtures" / "manifest.json"
    original = Path.read_bytes

    def fail_manifest(path: Path, *args: object, **kwargs: object) -> bytes:
        if path == manifest_path:
            raise OSError("synthetic read failure")
        return original(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_bytes", fail_manifest)
    with pytest.raises(IngestionError, match="manifest is invalid") as raised:
        approve_synthetic_fixture(target, profile_id="synthetic_test_v1")
    assert raised.value.code == "FIXTURE_NOT_APPROVED"


def test_fixture_manifest_outside_named_fixture_tree_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "case" / "payload.json"
    target.parent.mkdir()
    target.write_text("{}", encoding="utf-8")
    (target.parent / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(IngestionError, match="outside fixtures"):
        approve_synthetic_fixture(target, profile_id="synthetic_test_v1")


@pytest.mark.parametrize("case", ("entries", "metadata", "path", "bytes"))
def test_trusted_manifest_still_rejects_structural_and_content_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    body = b'{"synthetic":true}'
    target = tmp_path / "fixtures" / "case" / "payload.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(body)
    entry = {
        "bytes": len(body),
        "path": "fixtures/case/payload.json",
        "rights_profile": "synthetic_test_v1",
        "sha256": hashlib.sha256(body).hexdigest(),
        "synthetic": True,
    }
    manifest: dict[str, object] = {
        "manifest_version": "1.0.0",
        "pack_id": "SYNTHETIC",
        "fixture_count": 1,
        "entries": [entry],
    }
    if case == "entries":
        manifest["entries"] = "invalid"
    elif case == "metadata":
        manifest["fixture_count"] = 2
    elif case == "path":
        entry["path"] = "fixtures/case/different.json"
    else:
        entry["bytes"] = len(body) + 1
    manifest_path = tmp_path / "fixtures" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    monkeypatch.setitem(fixtures_module.TRUSTED_MANIFESTS, digest, "SYNTHETIC")

    with pytest.raises(IngestionError) as raised:
        approve_synthetic_fixture(target, profile_id="synthetic_test_v1")
    assert raised.value.code == "FIXTURE_NOT_APPROVED"
