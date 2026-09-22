"""L2 authority-only delta: no real credentials, providers or changed mathematics."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.private_v1 import team_strength_live as live
from dmf_pulse.private_v1 import team_strength_live_authority as authority

pytestmark = pytest.mark.unit
PARENT = "4d712ecf84e9c1f01a0f29354bd93c5296befb35"
STAMP = datetime(2026, 10, 1, tzinfo=UTC)
OLD_APPROVAL = "DMF-CTS-001P-LIVE-RIGHTS-2026-09-22"
OLD_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L1#ONE-SHOT-2026-09-22"
NEW_APPROVAL = "DMF-CTS-001P-L2-LIVE-RIGHTS-2026-09-22"
NEW_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L2#ONE-SHOT-2026-09-22"


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
        "CURRENT_TEAM_STRENGTH_001P_L2_LIVE_EXECUTION_NOT_COMPLETED",
        "TEAM_STRENGTH_PUBLIC_PREFLIGHT_BLOCKED",
    }
    return result


@pytest.mark.parametrize("attestation", [OLD_ATTESTATION, NEW_ATTESTATION, "wrong"])
def test_historical_l1_is_consumed_before_current_pair_or_provider_checks(attestation):
    assert authority.L1_APPROVAL == OLD_APPROVAL
    assert authority.L1_ATTESTATION == OLD_ATTESTATION
    assert type(authority.CONSUMED_APPROVALS) is frozenset
    expected_consumed = frozenset({OLD_APPROVAL})
    assert expected_consumed == authority.CONSUMED_APPROVALS
    assert blocked(OLD_APPROVAL, attestation)["reason"] == "AUTHORITY_CONSUMED"


@pytest.mark.parametrize(
    "approval,attestation",
    [(NEW_APPROVAL, OLD_ATTESTATION), (NEW_APPROVAL, "wrong"), ("wrong", NEW_ATTESTATION)],
)
def test_mismatched_pair_cannot_authorize(approval, attestation):
    assert blocked(approval, attestation)["reason"] == "AUTHORITY_INVALID"


def test_exact_new_pair_and_pinned_rights_pass_without_reading_credentials():
    assert (authority.APPROVAL, authority.ATTESTATION) == (NEW_APPROVAL, NEW_ATTESTATION)
    assert NEW_APPROVAL not in authority.CONSUMED_APPROVALS
    authority.validate_l1_authority(
        approval=NEW_APPROVAL, attestation=NEW_ATTESTATION, checked_at=STAMP
    )
    fpl = authority.load_fpl_rights()[authority.FPL_PROFILE]
    odds = authority.load_odds_rights()[authority.ODDS_PROFILE]
    assert authority.profile_sha(fpl) == (
        "f319842091b89b0f8cc207b681d2584e1cce282e570d5d4daba92b06ae85f095"
    )
    assert (
        authority.profile_sha(odds)
        == authority.ODDS_PROFILE_SHA
        == ("bc5dfa98500459bc50c00e4cd44a30e64e0df04957f383ec8107947ac5350faf")
    )
    assert blocked(NEW_APPROVAL, NEW_ATTESTATION)["reason"] == "PUBLIC_READINESS_INVALID"


def test_only_odds_purpose_metadata_changes_and_no_capability_expansion():
    path = "config/rights/odds_profiles.json"
    before = json.loads(parent_text(path))
    after = json.loads(Path(path).read_text(encoding="utf-8"))
    assert before["schema_version"] == after["schema_version"]
    assert before["profiles"][0] == after["profiles"][0]
    left, right = before["profiles"][1], after["profiles"][1]
    assert left.keys() == right.keys()
    assert {key for key in left if left[key] != right[key]} == {
        "approved_at",
        "approved_purpose",
        "human_approval_id",
        "notes",
    }
    assert right["human_approval_id"] == NEW_APPROVAL
    assert right["retention_seconds"] == 0
    assert right["capabilities"]["public_display"] == "DENY"
    assert right["capabilities"]["redistribution"] == "DENY"


@pytest.mark.parametrize(
    "path",
    [
        "config/rights/fpl_profiles.json",
        "config/rights/openfootball_profiles.json",
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


@pytest.mark.parametrize(
    "path", ["src/dmf_pulse/private_v1/team_strength_live.py", "scripts/run_team_strength_l1.py"]
)
def test_existing_operator_changes_only_current_identity_and_documentation(path):
    before = ast.parse(parent_text(path))
    current = Path(path).read_text(encoding="utf-8")
    for new, old in (
        ("CURRENT_TEAM_STRENGTH_001P_L2_", "CURRENT_TEAM_STRENGTH_001P_L1_"),
        ("CURRENT-TEAM-STRENGTH-001P-L2", "CURRENT-TEAM-STRENGTH-001P-L1"),
        ("Invalid L2 operator arguments", "Invalid L1 operator arguments"),
        ("private CTS L2 observation", "private CTS L1 observation"),
    ):
        current = current.replace(new, old)
    after = ast.parse(current)
    # Only module documentation is nonsemantic; retain every function body.
    before.body = before.body[1:]
    after.body = after.body[1:]
    assert ast.dump(before, include_attributes=False) == ast.dump(after, include_attributes=False)


def test_standing_fpl_file_exact_identity():
    assert hashlib.sha256(Path("config/rights/fpl_profiles.json").read_bytes()).hexdigest() == (
        "1691229b120054b8d4c65c7d74e5a0f6d9d11947f1a8f261d26649314268011d"
    )
