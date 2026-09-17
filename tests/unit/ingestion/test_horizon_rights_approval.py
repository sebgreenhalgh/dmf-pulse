"""Current A2 governed metadata gates; no credential reads or provider access."""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.models import CapabilityValue, RightsCapability, RightsProfile
from dmf_pulse.ingestion.odds.config import load_rights_profiles
from tests.unit.ingestion.test_horizon_probe import _script

pytestmark = pytest.mark.unit
APPROVAL = "DMF-R9C-A2-PRIVATE-RIGHTS-2026-09-17"
NOW = datetime(2026, 9, 17, 14, 44, tzinfo=UTC)
_CAPABILITIES = {
    RightsCapability.AUTOMATED_ACCESS: CapabilityValue.ALLOW,
    RightsCapability.BACKUP: CapabilityValue.UNKNOWN,
    RightsCapability.CACHE: CapabilityValue.ALLOW,
    RightsCapability.DERIVED_STORAGE: CapabilityValue.ALLOW,
    RightsCapability.MANUAL_IMPORT: CapabilityValue.ALLOW,
    RightsCapability.MODEL_TRAINING: CapabilityValue.UNKNOWN,
    RightsCapability.PRIVATE_INTERNAL_USE: CapabilityValue.ALLOW,
    RightsCapability.PUBLIC_DISPLAY: CapabilityValue.DENY,
    RightsCapability.RAW_STORAGE: CapabilityValue.UNKNOWN,
    RightsCapability.REDISTRIBUTION: CapabilityValue.DENY,
    RightsCapability.TRANSIENT_PROCESSING: CapabilityValue.ALLOW,
}
_UNRESOLVED = (
    "raw historical retention requires explicit review",
    "model training and backup require explicit review",
    "public product is a new purpose",
)
_R8B_UNMODIFIED_EXECUTABLE_HASHES = {
    "ingestion/current_state.py": "03a97b7fc9aef3536d01542d34a39bda5b2fcb29cfc3b67b4b637612947277e6",
    "ingestion/odds/automatic_mapping.py": "e45e09e5c6aef2b4b7693a132a26571a5fe38d47b6fc9ff65b55d4187b13d182",
    "ingestion/odds/current.py": "f8e131d2413bcccc2b78959779f0dae0618800f188b524fd2ea5b5299c47e5a9",
    "ingestion/odds/identity.py": "0c4fd04c32bade5a447d151208d464727854cdc717b81170c94c0cbcaaa5ae2b",
    "ingestion/odds/transient.py": "6dc8e6195b84491697caf7530b194fbc5d164982c9a20377d63eca0608ebb49e",
    "markets/current.py": "5e018a571ebf0bf0a33da7b8e87894f7bb31eb14b93b5b31102d586ba9924b17",
    "private_v1/horizon_markets.py": "0696abaf10f73f24d56db6e18fc52fe473b046a00708244d5fd0342e5ada6554",
    # A2 intentionally adds a private prepared-context seam in one_command.py.
    # A1 intentionally evolves private_v1/rolling.py through its private seam.
    "private_v1/rolling_models.py": "32750351fe73dbe8e9e3350971ef12b3e5e05ea89dc820ec25cbda2a3f3d7bdc",
}


@pytest.fixture
def governed_gate(monkeypatch):
    script = _script()
    profile = load_rights_profiles()["the_odds_api_private_analytics_v1"]
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("forbidden access")
        raise AssertionError("governance test must not inspect credentials or use providers")

    class NoEnvironment(dict):
        __getitem__ = get = __contains__ = forbidden

    def gate(*args):
        with monkeypatch.context() as guarded:
            guarded.setattr(os, "environ", NoEnvironment())
            guarded.setattr(os, "getenv", forbidden)
            guarded.setattr(socket, "create_connection", forbidden)
            guarded.setattr(socket, "getaddrinfo", forbidden)
            guarded.setattr(socket.socket, "connect", forbidden)
            guarded.setattr(script, "DirectFplClient", forbidden)
            guarded.setattr(script, "OddsClient", forbidden)
            guarded.setattr(script.EnvironmentOddsCredentialProvider, "_configured", forbidden)
            guarded.setattr(script.EnvironmentOddsCredentialProvider, "get_credential", forbidden)
            result = script.live_rights_blocker(*args)
        assert calls == []
        return result

    return gate, profile


def test_current_governed_approval_and_exact_metadata(governed_gate):
    gate, profile = governed_gate
    assert profile.human_approval_id == APPROVAL
    assert profile.approved_by == "Sebastian"
    assert profile.account_scope == "Sebastian-owned and authorized private The Odds API account"
    assert profile.geography_scope == "United Kingdom private use"
    assert profile.approved_purpose == (
        "one private operator-initiated R9C-A2 live transient four-world decision observation "
        "using one frozen current information set through the existing three-Gameweek decision "
        "pipeline"
    )
    assert profile.terms_source == "The Odds API Terms and Conditions"
    assert profile.terms_version == "checked-2026-08-31"
    assert profile.checked_at == datetime(2026, 9, 11, 21, 21, 31, tzinfo=UTC)
    assert profile.approved_at == datetime(2026, 9, 17, 14, 43, 36, tzinfo=UTC)
    assert profile.capabilities == _CAPABILITIES
    assert profile.unresolved_rights == _UNRESOLVED
    assert gate(profile, APPROVAL, True, NOW) is None


@pytest.mark.parametrize("reference,confirmed", [("different-approval", True), (APPROVAL, False)])
def test_operator_confirmation_still_required(governed_gate, reference, confirmed):
    gate, profile = governed_gate
    assert (
        gate(profile, reference, confirmed, NOW)
        == "EXISTING_PURPOSE_ACCOUNT_GEOGRAPHY_AUTHORITY_NOT_CONFIRMED"
    )


@pytest.mark.parametrize(
    "update",
    [
        {"terms_version": "checked-2026-07-25"},
        {"checked_at": datetime(2026, 7, 25, tzinfo=UTC)},
        {"approved_at": datetime(2026, 7, 25, tzinfo=UTC)},
        {"account_scope": "one future approved private account"},
    ],
    ids=["stale-terms", "stale-review", "stale-approval", "placeholder-account"],
)
def test_unapproved_metadata_still_fails_closed(governed_gate, update):
    gate, profile = governed_gate
    assert (
        gate(profile.model_copy(update=update), APPROVAL, True, NOW)
        == "CURRENT_TERMS_AND_APPLICABLE_ACCOUNT_REVIEW_PENDING"
    )


@pytest.mark.parametrize(
    "capability",
    [
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.PRIVATE_INTERNAL_USE,
    ],
)
@pytest.mark.parametrize("value", [CapabilityValue.DENY, CapabilityValue.UNKNOWN])
def test_required_capabilities_remain_enforced(governed_gate, capability, value):
    gate, profile = governed_gate
    capabilities = dict(profile.capabilities)
    capabilities[capability] = value
    assert (
        gate(profile.model_copy(update={"capabilities": capabilities}), APPROVAL, True, NOW)
        == "RIGHTS_BLOCKED"
    )


@pytest.mark.parametrize(
    "capability",
    [
        RightsCapability.AUTOMATED_ACCESS,
        RightsCapability.TRANSIENT_PROCESSING,
        RightsCapability.PRIVATE_INTERNAL_USE,
    ],
)
def test_missing_required_capability_rejected_by_schema(governed_gate, capability):
    _, profile = governed_gate
    raw = {name: getattr(profile, name) for name in RightsProfile.model_fields}
    raw["capabilities"] = dict(profile.capabilities)
    del raw["capabilities"][capability]
    with pytest.raises(ValidationError, match="every capability exactly once"):
        RightsProfile.model_validate(raw)


def test_r8b_provider_boundaries_and_a2_unmodified_executables_remain_parent_identical(
    repository_root,
) -> None:
    import hashlib

    for relative, digest in _R8B_UNMODIFIED_EXECUTABLE_HASHES.items():
        assert (
            hashlib.sha256((repository_root / "src/dmf_pulse" / relative).read_bytes()).hexdigest()
            == digest
        )
    assert (
        hashlib.sha1((repository_root / "config/rights/fpl_profiles.json").read_bytes()).hexdigest()
        == "cbe6afa0eacc175a6500152460ec04ff4ac990a0"
    )


def test_static_guard_excludes_intentionally_evolving_a1_rolling_and_a2_one_command():
    assert "private_v1/rolling.py" not in _R8B_UNMODIFIED_EXECUTABLE_HASHES
    assert "private_v1/one_command.py" not in _R8B_UNMODIFIED_EXECUTABLE_HASHES
    assert len(_R8B_UNMODIFIED_EXECUTABLE_HASHES) == 8
