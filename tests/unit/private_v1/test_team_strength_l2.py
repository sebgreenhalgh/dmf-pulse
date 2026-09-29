"""L1-L6 consumed history, exact L7 authority and no capability expansion."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.ingestion.odds.config import load_rights_profiles as load_odds_rights
from dmf_pulse.ingestion.rights import load_rights_profiles as load_fpl_rights
from dmf_pulse.optimisation.multi_gameweek_policy import load_multi_gameweek_search_policy
from dmf_pulse.private_v1 import team_strength_live as live
from dmf_pulse.private_v1 import team_strength_live_authority as authority

pytestmark = pytest.mark.unit
PARENT = "fbafe72bba6639c9f6758bd2ccf3a9288876e1a7"
D6_PARENT = "7ae84993083756aadf13eb01c019ecd7ed0b196f"
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
L6_APPROVAL = "DMF-CTS-001P-L6-LIVE-RIGHTS-2026-09-28"
L6_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L6#ONE-SHOT-2026-09-28"
L7_APPROVAL = "DMF-CTS-001P-L7-LIVE-RIGHTS-2026-09-29"
L7_ATTESTATION = "CURRENT-TEAM-STRENGTH-001P-L7#ONE-SHOT-2026-09-29"


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
        "CURRENT_TEAM_STRENGTH_001P_L7_LIVE_EXECUTION_NOT_COMPLETED",
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
        (L6_APPROVAL, L6_ATTESTATION),
        (L6_APPROVAL, L5_ATTESTATION),
        (L6_APPROVAL, "wrong"),
    ],
)
def test_historical_l1_through_l6_are_consumed_before_provider_checks(approval, attestation):
    assert authority.L1_APPROVAL == OLD_APPROVAL
    assert authority.L1_ATTESTATION == OLD_ATTESTATION
    assert authority.L2_APPROVAL == NEW_APPROVAL
    assert authority.L2_ATTESTATION == NEW_ATTESTATION
    assert type(authority.CONSUMED_APPROVALS) is frozenset
    assert authority.L3_APPROVAL == L3_APPROVAL
    assert authority.L3_ATTESTATION == L3_ATTESTATION
    expected_consumed = frozenset(
        {OLD_APPROVAL, NEW_APPROVAL, L3_APPROVAL, L4_APPROVAL, L5_APPROVAL, L6_APPROVAL}
    )
    assert expected_consumed == authority.CONSUMED_APPROVALS
    assert blocked(approval, attestation)["reason"] == "AUTHORITY_CONSUMED"


@pytest.mark.parametrize(
    "approval,attestation",
    [
        ("wrong", NEW_ATTESTATION),
        ("wrong", OLD_ATTESTATION),
        ("wrong", L3_ATTESTATION),
        ("wrong", L6_ATTESTATION),
        ("wrong", L7_ATTESTATION),
        ("wrong", "wrong"),
    ],
)
def test_no_unknown_historical_or_current_pair_can_authorize(approval, attestation):
    assert blocked(approval, attestation)["reason"] == "AUTHORITY_INVALID"


def test_exact_l7_pair_is_current_and_l6_remains_consumed():
    assert (authority.APPROVAL, authority.ATTESTATION) == (L7_APPROVAL, L7_ATTESTATION)
    assert {L4_APPROVAL, L5_APPROVAL, L6_APPROVAL} <= authority.CONSUMED_APPROVALS
    assert (authority.CURRENT_APPROVAL, authority.CURRENT_ATTESTATION) == (
        L7_APPROVAL,
        L7_ATTESTATION,
    )
    assert (
        authority.validate_l1_authority(
            approval=L7_APPROVAL, attestation=L7_ATTESTATION, checked_at=STAMP
        )
        is None
    )
    assert (
        authority.profile_sha(load_fpl_rights()[authority.FPL_PROFILE]) == authority.FPL_PROFILE_SHA
    )
    assert (
        authority.profile_sha(load_odds_rights()[authority.ODDS_PROFILE])
        == authority.ODDS_PROFILE_SHA
    )
    result = blocked(L7_APPROVAL, L7_ATTESTATION)
    assert result["reason"] == "PUBLIC_READINESS_INVALID"
    assert not result["private_attempt_consumed"]


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


@pytest.mark.parametrize(
    "approval,attestation",
    [
        (L6_APPROVAL, "wrong"),
        ("wrong", L6_ATTESTATION),
        (L6_APPROVAL, L5_ATTESTATION),
        (L5_APPROVAL, L6_ATTESTATION),
    ],
)
def test_l6_wrong_or_mixed_pairs_fail_closed(approval, attestation):
    expected = (
        "AUTHORITY_CONSUMED" if approval in {L5_APPROVAL, L6_APPROVAL} else "AUTHORITY_INVALID"
    )
    assert blocked(approval, attestation)["reason"] == expected


@pytest.mark.parametrize(
    "approval,attestation",
    [
        (L7_APPROVAL, "wrong"),
        ("wrong", L7_ATTESTATION),
        (L7_APPROVAL, L6_ATTESTATION),
        (L6_APPROVAL, L7_ATTESTATION),
    ],
)
def test_l7_wrong_or_mixed_pairs_fail_closed(approval, attestation):
    expected = "AUTHORITY_CONSUMED" if approval == L6_APPROVAL else "AUTHORITY_INVALID"
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


def test_no_profile_hash_change_can_reactivate_consumed_l6(monkeypatch):
    monkeypatch.setattr(authority, "ODDS_PROFILE_SHA", "0" * 64)
    with pytest.raises(authority.ConsumedL1ApprovalError):
        authority.validate_l1_authority(
            approval=L6_APPROVAL, attestation=L6_ATTESTATION, checked_at=STAMP
        )


def test_prior_l6_odds_profile_hash_cannot_authorize_l7(monkeypatch):
    old_l6_sha = "3695768150ba789da6b1b35739245dbc5cfa54e3a7542a375d12581d5f758ca4"
    assert old_l6_sha != authority.ODDS_PROFILE_SHA
    monkeypatch.setattr(authority, "ODDS_PROFILE_SHA", old_l6_sha)
    with pytest.raises(ValueError, match="exact provider purpose"):
        authority.validate_l1_authority(
            approval=L7_APPROVAL, attestation=L7_ATTESTATION, checked_at=STAMP
        )


@pytest.mark.parametrize(
    "path",
    [
        "config/rights/fpl_profiles.json",
        "config/rights/openfootball_profiles.json",
    ],
)
def test_fpl_and_openfootball_rights_are_byte_identical_to_d6_parent(path):
    assert Path(path).read_text(encoding="utf-8") == parent_text(path)


def test_only_odds_purpose_metadata_changes_without_capability_expansion():
    before = json.loads(parent_text("config/rights/odds_profiles.json"))["profiles"][1]
    after = json.loads(Path("config/rights/odds_profiles.json").read_text(encoding="utf-8"))
    current = after["profiles"][1]
    changed = {key for key in before if before[key] != current[key]}
    assert changed == {"approved_at", "approved_purpose", "human_approval_id", "notes"}
    assert before["capabilities"] == current["capabilities"]
    assert before["unresolved_rights"] == current["unresolved_rights"]
    assert before["account_scope"] == current["account_scope"]
    assert before["geography_scope"] == current["geography_scope"]
    assert before["terms_source"] == current["terms_source"]
    assert before["terms_version"] == current["terms_version"]
    assert current["retention_seconds"] == 0
    assert current["human_approval_id"] == L7_APPROVAL


def test_d1_through_d6_live_control_flow_is_preserved_except_l7_identity():
    before = parent_text("src/dmf_pulse/private_v1/team_strength_live.py")
    expected = (
        before.replace(
            "Historical L1-L6 operator experiment, never selected by ordinary dmf pulse.\n\n"
            "All six live authorities are consumed. Legacy names remain for offline regression;\n"
            "D1-D6 preserve closed diagnostics, localisation and exact resource identities.",
            "Governed L1-L7 operator experiment, never selected by ordinary dmf pulse.\n\n"
            "L1-L6 are consumed; exactly one L7 pair is current. Legacy names remain for offline\n"
            "regression; D1-D6 preserve closed diagnostics, localisation and exact resource identities.",
        )
        .replace("CURRENT_TEAM_STRENGTH_001P_L6", "CURRENT_TEAM_STRENGTH_001P_L7")
        .replace("CURRENT-TEAM-STRENGTH-001P-L6", "CURRENT-TEAM-STRENGTH-001P-L7")
    )
    actual = Path("src/dmf_pulse/private_v1/team_strength_live.py").read_text(encoding="utf-8")
    assert actual == expected


@pytest.mark.parametrize(
    "path",
    [
        "config/models/current_team_strength_governance.json",
        "config/optimisation/multi_gameweek.yaml",
        "src/dmf_pulse/optimisation/resources/multi_gameweek.yaml",
        "src/dmf_pulse/optimisation/multi_gameweek_errors.py",
        "src/dmf_pulse/optimisation/multi_gameweek_models.py",
        "src/dmf_pulse/optimisation/multi_gameweek_policy.py",
        "src/dmf_pulse/optimisation/multi_gameweek_service.py",
        "src/dmf_pulse/optimisation/multi_gameweek_solver.py",
        "src/dmf_pulse/private_v1/team_strength_comparison.py",
        "src/dmf_pulse/private_v1/team_strength_comparison_models.py",
        "src/dmf_pulse/private_v1/team_strength_diagnostics.py",
        "src/dmf_pulse/private_v1/team_strength_live_network.py",
        "src/dmf_pulse/private_v1/prepared_control.py",
        "src/dmf_pulse/private_v1/rolling.py",
        "src/dmf_pulse/private_v1/rolling_models.py",
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


def test_standing_fpl_purpose_remains_adequate_without_expansion():
    profile = load_fpl_rights()[authority.FPL_PROFILE]
    assert profile.approved_purpose == (
        "low-volume operator-initiated read-only private recommendation; no production service"
    )
    assert profile.retention_seconds == 0
    assert profile.unresolved_rights == ()
    assert {key.value: value.value for key, value in profile.capabilities.items()} == {
        "automated_access": "ALLOW",
        "backup": "DENY",
        "cache": "DENY",
        "derived_storage": "DENY",
        "manual_import": "DENY",
        "model_training": "DENY",
        "private_internal_use": "ALLOW",
        "public_display": "DENY",
        "raw_storage": "DENY",
        "redistribution": "DENY",
        "transient_processing": "ALLOW",
    }


def test_d6_only_separately_measured_policy_capacity_changes():
    policy = load_multi_gameweek_search_policy()
    assert policy.max_transfers_per_node == 2
    assert policy.max_actions_per_state == 5000
    assert policy.max_state_expansions == 25000
    assert policy.max_policy_candidates == 786432
    assert policy.max_cumulative_legal_actions == 786432
    assert policy.max_returned_root_candidates == 1000


@pytest.mark.parametrize(
    "path",
    [
        "config/optimisation/multi_gameweek.yaml",
        "src/dmf_pulse/optimisation/resources/multi_gameweek.yaml",
    ],
)
def test_d6_capacity_files_change_only_two_distinct_work_units(path):
    before = subprocess.run(
        ["git", "show", f"{D6_PARENT}:{path}"],
        check=True,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    ).stdout
    expected = before.replace(
        "max_policy_candidates: 250000", "max_policy_candidates: 786432"
    ).replace(
        "max_cumulative_legal_actions: 524288",
        "max_cumulative_legal_actions: 786432",
    )
    assert Path(path).read_text(encoding="utf-8") == expected


def test_l6_generated_near_envelope_exactness_evidence():
    root = Path("evidence/tickets/CURRENT-TEAM-STRENGTH-001P-L6")
    low = json.loads((root / "generated-legacy-envelope-failure.json").read_text())
    current = json.loads((root / "generated-near-envelope-capacity.json").read_text())
    high = json.loads((root / "generated-high-cap-reference.json").read_text())

    low_solve = low["whole_public_solve"]
    assert low["configured_cumulative_legal_action_limit"] == 250000
    assert low_solve["status"] == "RESOURCE_LIMIT"
    assert low_solve["diagnostics"]["status"] == "TIME_RESOURCE_LIMIT_NO_INCUMBENT"
    assert low_solve["diagnostics"]["resource_limit_kind"] == ("CUMULATIVE_LEGAL_ACTION_LIMIT")
    assert low_solve["profile"]["cumulative_legal_actions"] == 250036

    for payload, cap in ((current, 524288), (high, 1048576)):
        solve = payload["whole_public_solve"]
        assert payload["configured_cumulative_legal_action_limit"] == cap
        assert solve["status"] == "SUCCESS"
        assert solve["profile"]["cumulative_legal_actions"] == 320610
        assert solve["profile"]["cumulative_state_expansions"] == 3126

    assert (
        current["whole_public_solve"]["decision_semantics"]
        == (high["whole_public_solve"]["decision_semantics"])
    )
    semantics = current["whole_public_solve"]["decision_semantics"]
    assert semantics["semantic_sha256"] == (
        "f5b3d892d999e399be67c6137726adb54d136ccc73a40699b19f5d1efe5e2f47"
    )
    assert all(
        semantics["value"][key] is not None
        for key in (
            "recommended",
            "no_transfer_baseline",
            "root_counterfactual",
            "transfer_count_frontier",
        )
    )


def test_d6_l6_shaped_scalability_evidence_and_exactness_oracle():
    path = Path("evidence/tickets/CURRENT-TEAM-STRENGTH-001P-L6-D6/SCALABILITY-BENCHMARKS.json")
    evidence = json.loads(path.read_text(encoding="utf-8"))
    shape = evidence["stress_shape"]
    assert shape["root_action_upper"] == 8386
    assert shape["effective_max_actions_per_state"] == 17000
    assert shape["effective_max_returned_root_candidates"] == 8386
    assert shape["observed_max_action_combinations"] == 1032
    assert shape["reachable_non_root_states"] >= 9249
    parent = evidence["immutable_parent_at_524288"]
    assert parent["resource_limit_kind"] == "CUMULATIVE_LEGAL_ACTION_LIMIT"
    assert parent["first_crossing"] > 524288
    proposed = evidence["proposed_at_786432"]
    high = evidence["progressive_caps"][-1]
    assert proposed["cumulative_legal_actions"] == 520651
    assert proposed["decision_semantic_sha256"] == high["decision_semantic_sha256"]
    assert [item["cap"] for item in evidence["progressive_caps"]] == [
        524288,
        786432,
        1048576,
        1572864,
        2097152,
    ]
    assert all(evidence["exactness"].values())


def test_l7_rerun_preserves_d6_complete_workload_and_decision():
    path = Path("evidence/tickets/CURRENT-TEAM-STRENGTH-001P-L7/D6-REGRESSION.json")
    evidence = json.loads(path.read_text(encoding="utf-8"))
    assert evidence["source"] == "REPOSITORY_OWNED_SYNTHETIC_ONLY"
    assert evidence["current_cap"] == evidence["max_policy_candidates"] == 786432
    assert evidence["high_cap"] == 1048576
    assert evidence["current_status"] == evidence["high_cap_status"] == "SUCCESS"
    assert evidence["total_cumulative_legal_actions"] == evidence["policy_candidates"] == 520651
    assert evidence["state_expansions"] == 12887
    assert evidence["effective_max_actions_per_state"] == 17000
    assert evidence["effective_max_returned_root_candidates"] == 8386
    assert evidence["root_action_upper"] == 8386
    assert evidence["decision_semantic_sha256"] == (
        "33536fdcf68d72ca252f1997b86989f7b96078c5a070363c17502ba7c664a044"
    )
    assert all(evidence["exactness"].values())
    assert sum(row["legal_actions_generated"] for row in evidence["layer_work"]) == 520651
