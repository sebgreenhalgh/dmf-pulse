"""D3 permanently consumes L1/L2/L3 and creates no L4 authority."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.private_v1 import team_strength_live as live
from dmf_pulse.private_v1 import team_strength_live_authority as authority

pytestmark = pytest.mark.unit
PARENT = "b774056f20e855d7a755186fe62489e3d393ecfe"
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
        (L3_APPROVAL, L3_ATTESTATION),
        (L3_APPROVAL, NEW_ATTESTATION),
        (L3_APPROVAL, "wrong"),
    ],
)
def test_historical_l1_l2_l3_are_consumed_before_provider_checks(approval, attestation):
    assert authority.L1_APPROVAL == OLD_APPROVAL
    assert authority.L1_ATTESTATION == OLD_ATTESTATION
    assert authority.L2_APPROVAL == NEW_APPROVAL
    assert authority.L2_ATTESTATION == NEW_ATTESTATION
    assert type(authority.CONSUMED_APPROVALS) is frozenset
    assert authority.L3_APPROVAL == L3_APPROVAL
    assert authority.L3_ATTESTATION == L3_ATTESTATION
    expected_consumed = frozenset({OLD_APPROVAL, NEW_APPROVAL, L3_APPROVAL})
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
def test_no_unknown_l1_l2_l3_or_l4_pair_can_authorize(approval, attestation):
    assert blocked(approval, attestation)["reason"] == "AUTHORITY_INVALID"


def test_exact_l3_pair_is_consumed_and_no_current_pair_exists():
    assert (authority.APPROVAL, authority.ATTESTATION) == (L3_APPROVAL, L3_ATTESTATION)
    assert L3_APPROVAL in authority.CONSUMED_APPROVALS
    result = blocked(L3_APPROVAL, L3_ATTESTATION)
    assert result["reason"] == "AUTHORITY_CONSUMED"
    assert result["prior_l1_one_shot_consumed"]
    assert result["prior_l2_one_shot_consumed"]
    assert result["prior_l3_one_shot_consumed"]


@pytest.mark.parametrize(
    "path",
    [
        "config/rights/fpl_profiles.json",
        "config/rights/odds_profiles.json",
        "config/rights/openfootball_profiles.json",
    ],
)
def test_provider_rights_are_byte_identical_to_l3_parent(path):
    assert Path(path).read_text(encoding="utf-8") == parent_text(path)


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
