"""Account facts preserve missingness and cannot self-authorize acquisition."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from dmf_pulse.operation.account import OddsAccountEvidence, prepare_account_review
from dmf_pulse.operation.cli import operation_app
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.packages import read_nonexecuting_input
from tests.unit.credentials.test_service import NOW


def complete(**updates):
    values = dict(
        account_ref="odds-account-owned-example",
        evidence_ref="owned-redacted-example",
        redacted_evidence_sha256="a" * 64,
        plan_name="Owned Example Plan",
        plan_ref="owned-plan",
        covered_sports=("soccer_epl",),
        covered_regions=("uk",),
        covered_markets=("h2h", "totals"),
        operator_country="DE",
        permitted_countries=("DE",),
        permitted_purposes=("PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",),
        plan_credit_allowance=100,
        remaining_credits=50,
        used_credits=None,
        last_request_cost=None,
        observed_at=NOW,
        period_started_at=NOW - timedelta(days=1),
        resets_at=NOW + timedelta(days=1),
        reset_period="SUBSCRIPTION_MONTH",
        other_usage="EXCLUSIVE_ACCOUNT_DURING_PILOT",
        safety_reserve_credits=3,
        proposed_quota_max_age_seconds=300,
        terms_version="owned-terms-example",
        terms_reviewed_at=NOW,
        terms_evidence_sha256="b" * 64,
    )
    values.update(updates)
    return OddsAccountEvidence(**values)


def test_empty_facts_are_specific_missing_fields_not_zero_balances():
    facts = OddsAccountEvidence(account_ref="odds-account-owned-example")
    report = prepare_account_review(facts, now=NOW)
    assert report.state == "INCOMPLETE"
    assert report.evidence.remaining_credits is None and report.evidence.used_credits is None
    assert "ACCOUNT_REMAINING_CREDITS_REQUIRED" in report.blockers
    assert "ACCOUNT_RESETS_AT_REQUIRED" in report.blockers
    assert "ACCOUNT_OTHER_USAGE_REQUIRED" in report.blockers
    assert report.runtime_authority == "NOT_GRANTED" and report.entitlement_verified is False


def test_complete_dated_evidence_is_only_ready_for_independent_review():
    report = prepare_account_review(complete(), now=NOW)
    assert report.state == "READY_FOR_INDEPENDENT_ACCOUNT_REVIEW" and report.blockers == ()
    assert (
        report.entitlement_verified
        is report.owner_budget_accepted
        is report.project_rights_approved
        is False
    )
    assert report.evidence.used_credits is None and report.evidence.last_request_cost is None
    assert report.evidence.operator_country == "DE" and report.evidence.covered_regions == ("uk",)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("covered_sports", (), "ACCOUNT_EPL_NOT_COVERED"),
        ("covered_regions", ("eu",), "ACCOUNT_UK_MARKET_REGION_NOT_COVERED"),
        ("covered_markets", ("h2h",), "ACCOUNT_REQUIRED_MARKETS_NOT_COVERED"),
        ("permitted_purposes", (), "ACCOUNT_PURPOSE_NOT_COVERED"),
        ("permitted_countries", ("GB",), "ACCOUNT_OPERATOR_GEOGRAPHY_NOT_COVERED"),
        ("remaining_credits", 4, "ACCOUNT_QUALIFIED_AVAILABLE_CREDITS_INSUFFICIENT"),
        ("observed_at", NOW - timedelta(minutes=6), "ACCOUNT_OBSERVATION_STALE"),
        ("observed_at", NOW + timedelta(seconds=1), "ACCOUNT_OBSERVATION_IN_FUTURE"),
        ("other_usage", "QUALIFIED_RESERVATION", "ACCOUNT_OTHER_USAGE_RESERVATION_REQUIRED"),
    ],
)
def test_ineligible_observed_scope_is_explicit(field, value, reason):
    result = prepare_account_review(complete(**{field: value}), now=NOW)
    assert result.state == "INCOMPLETE" and reason in result.blockers


def test_other_usage_reservation_is_added_to_safety_and_pilot_cost():
    facts = complete(other_usage="QUALIFIED_RESERVATION", other_usage_reserved_credits=46)
    assert (
        "ACCOUNT_QUALIFIED_AVAILABLE_CREDITS_INSUFFICIENT"
        in prepare_account_review(facts, now=NOW).blockers
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"observed_at": NOW.replace(tzinfo=None)},
        {"remaining_credits": True},
        {"remaining_credits": 101},
        {"used_credits": 101},
        {"used_credits": 2, "last_request_cost": 3},
        {"other_usage_reserved_credits": 1},
        {"resets_at": NOW},
        {"covered_markets": ("h2h", "h2h")},
        {"plan_name": "f" * 32},
        {"account_ref": "owned@example.invalid"},
    ],
)
def test_inconsistent_or_secret_shaped_facts_are_not_accepted(updates):
    with pytest.raises(ValidationError):
        complete(**updates)


def test_model_construct_and_resealed_approval_flags_do_not_bypass_contract():
    broken = complete().model_copy(update={"remaining_credits": True})
    with pytest.raises(ValidationError):
        prepare_account_review(broken, now=NOW)
    report = prepare_account_review(complete(), now=NOW).model_dump(mode="json")
    report["entitlement_verified"] = True
    from dmf_pulse.operation.account import AccountReviewPackage

    with pytest.raises(ValidationError):
        AccountReviewPackage.model_validate_json(json.dumps(report))


def test_editable_input_and_immutable_report_workflow_is_nonexecuting(tmp_path):
    raw = tmp_path / "account-input.json"
    output = tmp_path / "account-review.json"
    runner = CliRunner()
    result = runner.invoke(
        operation_app,
        ["account-draft", "--account-ref", "odds-account-owned-example", "--output", str(raw)],
    )
    assert result.exit_code == 0 and raw.exists()
    assert json.loads(result.stdout)["runtime_authority"] == "NOT_GRANTED"
    data = json.loads(raw.read_bytes())
    data["plan_name"] = "Owned Example Plan"
    raw.write_text(json.dumps(data), encoding="utf-8")
    result = runner.invoke(
        operation_app, ["review-account", "--input", str(raw), "--output", str(output)]
    )
    assert result.exit_code == 0
    value = json.loads(result.stdout)
    assert value["state"] == "INCOMPLETE" and value["entitlement_verified"] is False
    assert value["runtime_authority"] == "NOT_GRANTED"
    assert (
        runner.invoke(
            operation_app, ["review-account", "--input", str(raw), "--output", str(output)]
        ).exit_code
        != 0
    )


def test_unknown_sensitive_input_and_duplicate_keys_have_safe_errors(tmp_path):
    raw = tmp_path / "account.json"
    for body in (
        '{"account_ref":"odds-account-owned-example","account_ref":"other"}',
        '{"account_ref":"odds-account-owned-example","api_key":"placeholder"}',
    ):
        raw.write_text(body, encoding="utf-8")
        with pytest.raises(OperationError) as error:
            read_nonexecuting_input(raw, OddsAccountEvidence)
        assert error.value.code == "OPERATOR_ARTIFACT_INVALID"
        assert error.value.__context__ is None
