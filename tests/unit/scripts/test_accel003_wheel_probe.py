"""Verifier rejects partial process proofs and never drops numerical/model mismatches."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PROBE = runpy.run_path(str(ROOT / "scripts/accel003_wheel_probe.py"))
VERIFY = runpy.run_path(str(ROOT / "scripts/verify_wheel.py"))
compare = PROBE["compare_exact"]
require = VERIFY["_require_accel003_acceptance"]
VerificationError = VERIFY["VerificationError"]
pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "name,value",
    [
        ("expected_points", 1.25),
        ("points_variance", 0.2),
        ("minutes", 60),
        ("probability", 0.3),
        ("hit_points", 4),
        ("model_version_ids", ["changed-model"]),
        ("ruleset_hash", "b" * 64),
    ],
)
def test_every_non_custody_numerical_or_model_field_is_checked(name, value):
    left = {"presentation": {"gameweeks": [{"summaries": {"owned": {name: value}}}]}}
    right = copy.deepcopy(left)
    right["presentation"]["gameweeks"][0]["summaries"]["owned"][name] = None
    result = compare(left, right)
    assert len(result["mismatches"]) == 1
    assert result["excluded"] == []


def test_custody_exclusion_is_exactly_scoped_and_retains_both_identities():
    left = {
        "decision": {"lineage": {"code_sha": "a" * 40}},
        "presentation": {
            "fixtures": [
                {"summaries": {"owned": {"source_bundle_ids": ["a" * 64], "expected_points": 1.25}}}
            ]
        },
    }
    right = copy.deepcopy(left)
    right["decision"]["lineage"]["code_sha"] = "b" * 40
    right["presentation"]["fixtures"][0]["summaries"]["owned"]["source_bundle_ids"] = ["b" * 64]
    result = compare(left, right)
    assert result["mismatches"] == []
    assert {row["path"] for row in result["excluded"]} == {
        "/decision/lineage/code_sha",
        "/presentation/fixtures/0/summaries/owned/source_bundle_ids",
    }
    assert result["numeric_fields"] == 1
    assert all(row["left"] != row["right"] for row in result["excluded"])


@pytest.mark.parametrize("path", ["code_sha", "semantic_sha256", "source_bundle_ids"])
def test_hash_named_numerical_values_are_never_excluded(path):
    assert compare({"decision": {path: 1}}, {"decision": {path: 2}})["mismatches"]


def test_only_exact_owned_quota_vintages_are_control_exclusions():
    assert (
        compare(
            {"presentation": {"market_quota_remaining": 98}},
            {"presentation": {"market_quota_remaining": 100}},
        )["mismatches"]
        == []
    )
    assert compare(
        {"presentation": {"market_quota_remaining": 97}},
        {"presentation": {"market_quota_remaining": 100}},
    )["mismatches"]


def test_shape_type_and_unexpected_metadata_mismatches_are_retained():
    for left, right in (
        ({"a": [1]}, {"a": [1, 2]}),
        ({"a": 1}, {"b": 1}),
        ({"a": True}, {"a": 1}),
        ({"decision": {"unexpected_hash": "a" * 64}}, {"decision": {"unexpected_hash": "b" * 64}}),
    ):
        assert compare(left, right)["mismatches"]


def test_screen_disclosure_normalizes_only_one_exact_custody_token():
    left = {
        "decision": {"action_space_disclosure": "Retained2; screen SHA256: " + "a" * 64 + "; exact"}
    }
    right = copy.deepcopy(left)
    right["decision"]["action_space_disclosure"] = (
        "Retained2; screen SHA256: " + "b" * 64 + "; exact"
    )
    receipt = compare(left, right)
    assert receipt["mismatches"] == []
    assert receipt["excluded"][0]["left"] == left["decision"]["action_space_disclosure"]
    right["decision"]["action_space_disclosure"] = (
        "Retained3; screen SHA256: " + "b" * 64 + "; exact"
    )
    assert compare(left, right)["mismatches"]
    right["decision"]["action_space_disclosure"] = (
        left["decision"]["action_space_disclosure"] + "; screen SHA256: " + "b" * 64 + "; extra"
    )
    assert compare(left, right)["mismatches"]


def valid_receipt():
    cases = []
    guards = []
    for horizon in (1, 3):
        cases.append(
            {
                "horizon": horizon,
                "catalogue": 121,
                "projected": 120,
                "blocked": 1,
                "default_process_worker": True,
                "same_run_browser_decision_equal": True,
                "all_numeric_projection_and_decision_fields_exact": True,
                "player_gameweek_details_equal": 120 * horizon,
                "owned_transport_attempts": {"FPL": 8, "ODDS": 1, "OPENFOOTBALL": 4},
                "external_provider_requests": 0,
                "cleanup": "CONFIRMED",
                "actual_spawn_child_pid": horizon,
                "reference_spawn_child_pid": horizon + 10,
                "reference_service": "DEFAULT_DEMO_PROCESS_ACCEPTED_CLI_SYNTHETIC",
            }
        )
        guards.append(
            {"pid": horizon, "role": "__mp_main__", "self_test_denials": 1, "unexpected_denials": 0}
        )
        guards.append(
            {
                "pid": horizon + 10,
                "role": "__mp_main__",
                "self_test_denials": 1,
                "unexpected_denials": 0,
            }
        )
    cancellations = []
    for phase, pid, calls in (("acquisition", 4, 1), ("modelling", 5, 13)):
        cancellations.append(
            {
                "phase": phase,
                "actual_spawn_child_pid": pid,
                "pause_marker_observed": True,
                "terminated_and_handle_closed": True,
                "result_withheld": True,
                "reservation_still_spent": True,
                "owned_attempts_before_cancellation": calls,
            }
        )
        guards.append(
            {"pid": pid, "role": "__mp_main__", "self_test_denials": 1, "unexpected_denials": 0}
        )
    return {
        "status": "PASS",
        "classification": "OWNED_SYNTHETIC_ENGINEERING_ONLY",
        "horizons": [1, 3],
        "cleanup": "CONFIRMED",
        "external_provider_requests": 0,
        "all_numeric_projection_and_decision_fields_exact": True,
        "no_full_semantic_hash_parity_claim": True,
        "cases": cases,
        "cancellations": cancellations,
        "installed_cli": {
            "cohort_freeze_labels_score": "PASS",
            "report_exact_service_equality": True,
            "player_evidence_exact_service_equality": True,
            "real_cohort_size": 0,
        },
        "network_guards": guards,
    }


def test_complete_receipt_is_accepted():
    value = valid_receipt()
    assert require(value) == value


@pytest.mark.parametrize(
    "attack",
    [
        "pending",
        "missing_horizon",
        "fake_worker",
        "partial_players",
        "numerical_difference",
        "wrong_calls",
        "live_network",
        "unclosed",
        "cancellation_absent",
        "cancel_result_leak",
        "unspent",
        "child_guard_absent",
        "guard_bypassed",
        "cli_partial",
        "real_cohort",
        "boolean_zero",
        "reference_guard_absent",
    ],
)
def test_partial_or_false_process_acceptance_is_rejected(attack):
    value = valid_receipt()
    if attack == "pending":
        value["status"] = "PENDING"
    elif attack == "missing_horizon":
        value["cases"].pop()
    elif attack == "fake_worker":
        value["cases"][0]["default_process_worker"] = False
    elif attack == "partial_players":
        value["cases"][0]["player_gameweek_details_equal"] = 1
    elif attack == "numerical_difference":
        value["all_numeric_projection_and_decision_fields_exact"] = False
    elif attack == "wrong_calls":
        value["cases"][0]["owned_transport_attempts"]["ODDS"] = 2
    elif attack == "live_network":
        value["external_provider_requests"] = 1
    elif attack == "unclosed":
        value["cases"][0]["cleanup"] = "PENDING"
    elif attack == "cancellation_absent":
        value["cancellations"] = []
    elif attack == "cancel_result_leak":
        value["cancellations"][0]["result_withheld"] = False
    elif attack == "unspent":
        value["cancellations"][0]["reservation_still_spent"] = False
    elif attack == "child_guard_absent":
        value["network_guards"].pop()
    elif attack == "guard_bypassed":
        value["network_guards"][0]["unexpected_denials"] = 1
    elif attack == "cli_partial":
        value["installed_cli"]["cohort_freeze_labels_score"] = "UNAVAILABLE"
    elif attack == "real_cohort":
        value["installed_cli"]["real_cohort_size"] = 8
    elif attack == "reference_guard_absent":
        value["cases"][0]["reference_spawn_child_pid"] = 999
    else:
        value["external_provider_requests"] = False
    with pytest.raises(VerificationError):
        require(value)
