"""All historical references fail before rights, credentials or providers."""

from datetime import UTC, datetime

import pytest

from dmf_pulse.private_v1 import team_strength_live_authority as authority
from tests.unit.private_v1.test_team_strength_l2 import blocked


def test_no_current_authority():
    assert authority.CURRENT_APPROVAL is None
    assert authority.CURRENT_ATTESTATION is None
    assert len(authority.CONSUMED_APPROVALS) == 8
    assert not hasattr(authority, "L9_APPROVAL")


@pytest.mark.parametrize("index", range(1, 9))
def test_historical_authority_never_checks_rights_or_providers(index, monkeypatch):
    def forbidden():
        raise AssertionError("consumed authority reached a rights loader")

    monkeypatch.setattr(authority, "load_fpl_rights", forbidden)
    monkeypatch.setattr(authority, "load_odds_rights", forbidden)
    approval = getattr(authority, f"L{index}_APPROVAL")
    attestation = getattr(authority, f"L{index}_ATTESTATION")
    with pytest.raises(authority.ConsumedL1ApprovalError):
        authority.validate_l1_authority(
            approval=approval, attestation=attestation, checked_at=datetime(2026, 10, 2, tzinfo=UTC)
        )
    assert blocked(approval, attestation)["reason"] == "AUTHORITY_CONSUMED"


def test_unknown_authority_fails_closed():
    assert blocked("unknown", "unknown")["reason"] == "AUTHORITY_INVALID"
