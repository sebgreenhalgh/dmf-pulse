"""L1-L5 consumed history, no current authority and no capability expansion."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.ingestion.odds.config import load_rights_profiles as load_odds_rights
from dmf_pulse.ingestion.rights import load_rights_profiles as load_fpl_rights
from dmf_pulse.private_v1 import team_strength_live as live
from dmf_pulse.private_v1 import team_strength_live_authority as authority

pytestmark = pytest.mark.unit
PARENT = "c348c3c7f2b26ef929dc0d56fa2dc1dbfd356d7e"
STAMP = datetime(2026, 10, 1, tzinfo=UTC)
OLD_APPROVAL = "DMF-CTS-001P-LIVE-RIGHTS-2026-09-22"
OLD_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L1#ONE-SHOT-2026-09-22"
NEW_APPROVAL = "DMF-CTS-001P-L2-LIVE-RIGHTS-2026-09-22"
NEW_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L2#ONE-SHOT-2026-09-22"
L3_APPROVAL = "DMF-CTS-001P-L3-LIVE-RIGHTS-2026-09-23"
L3_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L3#ONE-SHOT-2026-09-23"
L4_APPROVAL = "DMF-CTS-001P-L4-LIVE-RIGHTS-2026-09-24"
L4_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L4#ONE-SHOT-2026-09-24"
L5_APPROVAL = "DMF-CTS-001P-L5-LIVE-RIGHTS-2026-09-27"
L5_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L5#ONE-SHOT-2026-09-27"


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
        "CURRENT_TEAM_STRENGTH_001P_L5_LIVE_EXECUTION_NOT_COMPLETED",
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
        (L3_APPROVAL, L3_ATTESTATION),
        (L3_APPROVAL, NEW_ATTESTATION),
        (L3_APPROVAL, "wrong"),
        (L4_APPROVAL, L4_ATTESTATION),
        (L4_APPROVAL, L3_ATTESTATION),
        (L4_APPROVAL, "wrong"),
        (L5_APPROVAL, L5_ATTESTATION),
        (L5_APPROVAL, L4_ATTESTATION),
        (L5_APPROVAL, "wrong"),
    ],
)
def test_historical_l1_l2_l3_l4_l5_are_consumed_before_provider_checks(approval, attestation):
    assert authority.L1_APPROVAL == OLD_APPROVAL
    assert authority.L1_ATTESTATION == OLD_ATTESTATION
    assert authority.L2_APPROVAL == NEW_APPROVAL
    assert authority.L2_ATTESTATION == NEW_ATTESTATION
    assert type(authority.CONSUMED_APPROVALS) is frozenset
    assert authority.L3_APPROVAL == L3_APPROVAL
    assert authority.L3_ATTESTATION == L3_ATTESTATION
    expected_consumed = frozenset(
        {OLD_APPROVAL, NEW_APPROVAL, L3_APPROVAL, L4_APPROVAL, L5_APPROVAL}
    )
    assert expected_consumed == authority.CONSUMED_APPROVALS
    assert blocked(approval, attestation)["reason"] == "AUTHORITY_CONSUMED"


@pytest.mark.parametrize(
    "approval,attestation",
    [
        ("wrong", NEW_ATTESTATION),
        ("wrong", OLD_ATTESTATION),
        ("wrong", L3_ATTESTATION),
        ("wrong", "wrong"),
    ],
)
def test_no_unknown_historical_or_current_pair_can_authorize(approval, attestation):
    assert blocked(approval, attestation)["reason"] == "AUTHORITY_INVALID"


def test_l5_pair_is_historical_and_no_current_authority_exists():
    assert (authority.APPROVAL, authority.ATTESTATION) == (L5_APPROVAL, L5_ATTESTATION)
    assert {L4_APPROVAL, L5_APPROVAL} <= authority.CONSUMED_APPROVALS
    assert authority.CURRENT_APPROVAL is authority.CURRENT_ATTESTATION is None
    with pytest.raises(authority.ConsumedL1ApprovalError):
        authority.validate_l1_authority(
            approval=L5_APPROVAL, attestation=L5_ATTESTATION, checked_at=STAMP
        )
    assert (
        authority.profile_sha(load_fpl_rights()[authority.FPL_PROFILE]) == authority.FPL_PROFILE_SHA
    )
    assert (
        authority.profile_sha(load_odds_rights()[authority.ODDS_PROFILE])
        == authority.ODDS_PROFILE_SHA
    )
    result = blocked(L5_APPROVAL, L5_ATTESTATION)
    assert result["reason"] == "AUTHORITY_CONSUMED"
    assert result["prior_l5_one_shot_consumed"]


@pytest.mark.parametrize(
    "approval,attestation",
    [(L4_APPROVAL, "wrong"), ("wrong", L4_ATTESTATION)],
)
def test_l4_mismatch_fails_closed(approval, attestation):
    expected = "AUTHORITY_CONSUMED" if approval == L4_APPROVAL else "AUTHORITY_INVALID"
    assert blocked(approval, attestation)["reason"] == expected


@pytest.mark.parametrize(
    "approval,attestation",
    [
        (L5_APPROVAL, "wrong"),
        ("wrong", L5_ATTESTATION),
        (L5_APPROVAL, L4_ATTESTATION),
        (L4_APPROVAL, L5_ATTESTATION),
    ],
)
def test_l5_wrong_or_mixed_pairs_fail_closed(approval, attestation):
    expected = (
        "AUTHORITY_CONSUMED" if approval in {L4_APPROVAL, L5_APPROVAL} else "AUTHORITY_INVALID"
    )
    assert blocked(approval, attestation)["reason"] == expected


def test_historical_profile_hashes_remain_auditable():
    assert authority.profile_sha(load_fpl_rights()[authority.FPL_PROFILE]) == (
        authority.FPL_PROFILE_SHA
    )
    assert authority.profile_sha(load_odds_rights()[authority.ODDS_PROFILE]) == (
        authority.ODDS_PROFILE_SHA
    )


def test_no_profile_hash_change_can_reactivate_consumed_l5(monkeypatch):
    monkeypatch.setattr(authority, "ODDS_PROFILE_SHA", "0" * 64)
    with pytest.raises(authority.ConsumedL1ApprovalError):
        authority.validate_l1_authority(
            approval=L5_APPROVAL, attestation=L5_ATTESTATION, checked_at=STAMP
        )


@pytest.mark.parametrize(
    "path",
    [
        "config/rights/fpl_profiles.json",
        "config/rights/openfootball_profiles.json",
        "config/rights/odds_profiles.json",
    ],
)
def test_provider_rights_are_byte_identical_to_l5_parent(path):
    assert Path(path).read_text(encoding="utf-8") == parent_text(path)


def test_odds_profile_remains_zero_retention_historical_l5():
    after = json.loads(Path("config/rights/odds_profiles.json").read_text(encoding="utf-8"))
    assert after["profiles"][1]["retention_seconds"] == 0
    assert after["profiles"][1]["human_approval_id"] == L5_APPROVAL


def test_d1_d2_d3_d4_live_control_flow_is_preserved_except_d5_authority_closure():
    before = parent_text("src/dmf_pulse/private_v1/team_strength_live.py")
    expected = before.replace(
        "Governed L1-L5 operator experiment, never selected by ordinary dmf pulse.\n\n"
        "L1-L4 are consumed; exactly one L5 pair is current. Legacy L1 names remain for\n"
        "offline regression; D1-D4 provide closed diagnostic transport and localisation.",
        "Historical L1-L5 operator experiment, never selected by ordinary dmf pulse.\n\n"
        "All five live authorities are consumed. Legacy names remain for offline regression;\n"
        "D1-D5 provide closed diagnostic transport, localisation and resource identity.",
    ).replace(
        '                "prior_l4_one_shot_consumed": True,\n',
        '                "prior_l4_one_shot_consumed": True,\n'
        '                "prior_l5_one_shot_consumed": True,\n',
    )
    actual = Path("src/dmf_pulse/private_v1/team_strength_live.py").read_text(encoding="utf-8")
    assert actual == expected


@pytest.mark.parametrize(
    "path",
    [
        "config/models/current_team_strength_governance.json",
        "src/dmf_pulse/private_v1/team_strength_comparison.py",
        "src/dmf_pulse/private_v1/team_strength_comparison_models.py",
        "src/dmf_pulse/private_v1/team_strength_live_network.py",
        "src/dmf_pulse/private_v1/service.py",
        "src/dmf_pulse/football_events/score_prior_request.py",
        "src/dmf_pulse/football_events/team_strength_model.py",
        "src/dmf_pulse/ingestion/openfootball/team_strength_current.py",
    ],
)
def test_model_decision_and_provider_boundaries_are_parent_identical(path):
    assert Path(path).read_text(encoding="utf-8") == parent_text(path)


def test_standing_fpl_file_exact_identity():
    assert hashlib.sha256(Path("config/rights/fpl_profiles.json").read_bytes()).hexdigest() == (
        "1691229b120054b8d4c65c7d74e5a0f6d9d11947f1a8f261d26649314268011d"
    )
