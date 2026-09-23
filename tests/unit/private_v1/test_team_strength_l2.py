"""L3 exact authority, consumed history, and no provider-capability expansion."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.private_v1 import team_strength_live as live
from dmf_pulse.private_v1 import team_strength_live_authority as authority

pytestmark = pytest.mark.unit
PARENT = "d2a5e49c1e6b95b89bdcbf5ef23f05ecb67e00db"
STAMP = datetime(2026, 10, 1, tzinfo=UTC)
OLD_APPROVAL = "DMF-CTS-001P-LIVE-RIGHTS-2026-09-22"
OLD_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L1#ONE-SHOT-2026-09-22"
NEW_APPROVAL = "DMF-CTS-001P-L2-LIVE-RIGHTS-2026-09-22"
NEW_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L2#ONE-SHOT-2026-09-22"
L3_APPROVAL = "DMF-CTS-001P-L3-LIVE-RIGHTS-2026-09-23"
L3_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L3#ONE-SHOT-2026-09-23"


def parent_text(path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{PARENT}:{path}"],
        check=True,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    ).stdout


class ForbiddenCredentials:
    def get(self):
        raise AssertionError("Phase A must not inspect credentials")

    get_credential = get


def blocked(approval: str, attestation: str):
    service = live.TeamStrengthL1ObservationService(
        clock=lambda: STAMP,
        fpl_credentials=ForbiddenCredentials(),
        odds_credentials=ForbiddenCredentials(),
    )
    result = service.run(
        live.L1OperatorRequest(42, "a" * 40, approval, attestation, "0" * 64), None
    )
    assert result["fpl_requests"] == result["odds_requests"] == 0
    assert result["private_attempt_consumed"] is False
    assert result["retry_performed"] is False
    assert result["production_activation"] is False
    assert result["status"] in {
        "CURRENT_TEAM_STRENGTH_001P_L3_LIVE_EXECUTION_NOT_COMPLETED",
        "TEAM_STRENGTH_PUBLIC_PREFLIGHT_BLOCKED",
    }
    return result


@pytest.mark.parametrize(
    "approval,attestation",
    [
        (OLD_APPROVAL, OLD_ATTESTATION),
        (OLD_APPROVAL, NEW_ATTESTATION),
        (OLD_APPROVAL, "wrong"),
        (NEW_APPROVAL, NEW_ATTESTATION),
        (NEW_APPROVAL, OLD_ATTESTATION),
        (NEW_APPROVAL, "wrong"),
    ],
)
def test_historical_l1_and_l2_are_consumed_before_provider_checks(approval, attestation):
    assert authority.L1_APPROVAL == OLD_APPROVAL
    assert authority.L1_ATTESTATION == OLD_ATTESTATION
    assert authority.L2_APPROVAL == NEW_APPROVAL
    assert authority.L2_ATTESTATION == NEW_ATTESTATION
    assert type(authority.CONSUMED_APPROVALS) is frozenset
    expected_consumed = frozenset({OLD_APPROVAL, NEW_APPROVAL})
    assert expected_consumed == authority.CONSUMED_APPROVALS
    assert blocked(approval, attestation)["reason"] == "AUTHORITY_CONSUMED"


@pytest.mark.parametrize(
    "approval,attestation",
    [("wrong", NEW_ATTESTATION), ("wrong", OLD_ATTESTATION), ("wrong", "wrong")],
)
def test_no_unknown_pair_can_authorize(approval, attestation):
    assert blocked(approval, attestation)["reason"] == "AUTHORITY_INVALID"


def test_exact_l3_pair_and_pinned_rights_pass_before_credentials():
    assert (authority.APPROVAL, authority.ATTESTATION) == (L3_APPROVAL, L3_ATTESTATION)
    assert L3_APPROVAL not in authority.CONSUMED_APPROVALS
    authority.validate_l1_authority(
        approval=L3_APPROVAL, attestation=L3_ATTESTATION, checked_at=STAMP
    )
    assert (
        authority.profile_sha(authority.load_fpl_rights()[authority.FPL_PROFILE])
        == authority.FPL_PROFILE_SHA
    )
    assert (
        authority.profile_sha(authority.load_odds_rights()[authority.ODDS_PROFILE])
        == authority.ODDS_PROFILE_SHA
    )
    assert blocked(L3_APPROVAL, L3_ATTESTATION)["reason"] == "PUBLIC_READINESS_INVALID"


@pytest.mark.parametrize(
    "approval,attestation",
    [(L3_APPROVAL, "wrong"), ("wrong", L3_ATTESTATION)],
)
def test_l3_mismatch_fails_closed(approval, attestation):
    assert blocked(approval, attestation)["reason"] == "AUTHORITY_INVALID"


def test_old_odds_profile_sha_is_rejected(monkeypatch):
    monkeypatch.setattr(
        authority,
        "ODDS_PROFILE_SHA",
        "bc5dfa98500459bc50c00e4cd44a30e64e0df04957f383ec8107947ac5350faf",
    )
    with pytest.raises(ValueError, match="provider purpose"):
        authority.validate_l1_authority(
            approval=L3_APPROVAL, attestation=L3_ATTESTATION, checked_at=STAMP
        )


@pytest.mark.parametrize(
    "path",
    [
        "config/rights/fpl_profiles.json",
        "config/rights/openfootball_profiles.json",
    ],
)
def test_provider_rights_are_byte_identical_to_l2_parent(path):
    assert Path(path).read_text(encoding="utf-8") == parent_text(path)


def test_only_odds_purpose_metadata_changes_without_capability_expansion():
    before = json.loads(parent_text("config/rights/odds_profiles.json"))
    after = json.loads(Path("config/rights/odds_profiles.json").read_text(encoding="utf-8"))
    assert before["profiles"][0] == after["profiles"][0]
    left, right = before["profiles"][1], after["profiles"][1]
    assert {key for key in left if left[key] != right[key]} == {
        "approved_at",
        "approved_purpose",
        "human_approval_id",
        "notes",
    }
    assert left["capabilities"] == right["capabilities"]
    assert right["retention_seconds"] == 0
    assert right["human_approval_id"] == L3_APPROVAL


@pytest.mark.parametrize(
    "path",
    [
        "config/models/current_team_strength_governance.json",
        "src/dmf_pulse/private_v1/team_strength_diagnostics.py",
        "src/dmf_pulse/private_v1/team_strength_comparison.py",
        "src/dmf_pulse/private_v1/team_strength_comparison_models.py",
        "src/dmf_pulse/private_v1/team_strength_live_network.py",
        "src/dmf_pulse/private_v1/one_command.py",
        "src/dmf_pulse/private_v1/service.py",
        "src/dmf_pulse/football_events/score_prior_request.py",
        "src/dmf_pulse/football_events/team_strength_model.py",
        "src/dmf_pulse/ingestion/openfootball/team_strength_current.py",
    ],
)
def test_d1_protected_authority_and_implementation_unchanged(path):
    assert Path(path).read_text(encoding="utf-8") == parent_text(path)


def test_standing_fpl_file_exact_identity():
    assert hashlib.sha256(Path("config/rights/fpl_profiles.json").read_bytes()).hexdigest() == (
        "1691229b120054b8d4c65c7d74e5a0f6d9d11947f1a8f261d26649314268011d"
    )
