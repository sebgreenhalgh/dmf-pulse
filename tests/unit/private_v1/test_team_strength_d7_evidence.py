"""Offline D7 capacity evidence and authority-boundary checks."""

import json
from pathlib import Path

import pytest

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.private_v1 import team_strength_live_authority as authority

pytestmark = pytest.mark.unit

EVIDENCE = Path("evidence/tickets/CURRENT-TEAM-STRENGTH-001P-L7-D7/POLICY-CAPACITY.json")


def test_d7_capacity_evidence_is_authenticated_offline_and_complete() -> None:
    payload = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    claimed = payload.pop("semantic_sha256")
    assert semantic_sha256(payload) == claimed
    assert claimed == "90e42fd03e32f2eb7e5df6e97c404a41a7784557c6ecaff65674cbda97721e1c"
    assert payload["classification"] == "OFFLINE_REPOSITORY_OWNED_SYNTHETIC_ONLY"
    assert payload["provider_access"] == {
        "credentials_inspected": False,
        "fpl_requests": 0,
        "live_openfootball_requests": 0,
        "odds_requests": 0,
    }
    assert payload["authority"] == {
        "l1_through_l7_consumed": True,
        "l8_authority_exists": False,
    }
    assert {case["projection_ordering"] for case in payload["cases"]} == {
        "BASELINE_LIKE",
        "SHIFTED_SHADOW_LIKE",
    }
    assert all(case["governed_high_decision_semantics_equal"] for case in payload["cases"])
    assert max(case["complete_generated_policy_candidates"] for case in payload["cases"]) == 1432641
    assert all(case["complete_cumulative_legal_actions"] == 1432370 for case in payload["cases"])
    assert all(
        case["layers"][-1]["unique_resulting_active_squads"] == 327724 for case in payload["cases"]
    )


def test_d7_closes_every_historical_live_authority() -> None:
    assert authority.CURRENT_APPROVAL is None
    assert authority.CURRENT_ATTESTATION is None
    assert (
        frozenset(
            {
                authority.L1_APPROVAL,
                authority.L2_APPROVAL,
                authority.L3_APPROVAL,
                authority.L4_APPROVAL,
                authority.L5_APPROVAL,
                authority.L6_APPROVAL,
                authority.L7_APPROVAL,
            }
        )
        == authority.CONSUMED_APPROVALS
    )
