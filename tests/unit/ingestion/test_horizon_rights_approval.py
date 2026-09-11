"""R8A-R1 governed metadata gates; no credential reads or provider access."""

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
APPROVAL = "DMF-R8A-PRIVATE-RIGHTS-2026-09-11"
NOW = datetime(2026, 9, 11, 21, 23, tzinfo=UTC)


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
    assert profile.terms_source == "The Odds API Terms and Conditions"
    assert profile.terms_version == "checked-2026-08-31"
    assert profile.checked_at == datetime(2026, 9, 11, 21, 21, 31, tzinfo=UTC)
    assert profile.approved_at == datetime(2026, 9, 11, 21, 22, 20, tzinfo=UTC)
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
