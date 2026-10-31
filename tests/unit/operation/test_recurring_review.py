"""Separate manual reuse preparation; all permissions, wheels and accounts are owned fixtures."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from zipfile import ZipFile

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from dmf_pulse.operation import cli, wheel
from dmf_pulse.operation.enrollment import InstalledEnrollment
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.packages import (
    OwnerPackage,
    PilotProposal,
    RecurringOwnerPackage,
    RecurringProposal,
    prepare_pilot,
    prepare_recurring,
    read_metadata,
    write_nonexecuting_input,
)
from tests.unit.dashboard.test_live_authorization import NOW
from tests.unit.operation.enrollment_support import wheel_case
from tests.unit.operation.test_enrolled_wheel import permit_for

pytestmark = pytest.mark.unit


def recurring_case(tmp_path):
    base, pilot_request, members = wheel_case(tmp_path)
    pilot = pilot_request.owner_package.proposal
    quota = pilot.plan_quota.model_copy(update={"allocated_monthly_credits": 12})
    values = pilot.model_dump(exclude={"schema_version", "authorization_id"})
    proposal = RecurringProposal(
        **{
            **values,
            "authorization_id": "ACCEL005-RECURRING-owned-only",
            "plan_quota": quota,
            "daily_request_limit": 2,
            "daily_credit_limit": 4,
            "monthly_request_limit": 6,
            "monthly_credit_limit": 12,
            "recurring_budget_acceptance_evidence_sha256": "c" * 64,
        }
    )
    approval = pilot_request.candidate.approvals[0].model_copy(
        update={
            "authorization_id": proposal.authorization_id,
            "plan_quota": quota,
            "usage": "MANUAL_RECURRING",
            "horizons": (1, 3),
            **{
                name: getattr(proposal, name)
                for name in (
                    "daily_request_limit",
                    "daily_credit_limit",
                    "monthly_request_limit",
                    "monthly_credit_limit",
                )
            },
        }
    )
    registry = pilot_request.candidate.model_copy(
        update={"approvals": (approval,), "default_authorization_id": approval.authorization_id}
    )
    return (
        base,
        wheel.EnrollmentInput(
            owner_package=prepare_recurring(proposal, now=NOW), candidate=registry
        ),
        members,
    )


def test_pilot_defaults_remain_one_shot_and_cannot_inherit_recurring_acceptance():
    pilot = prepare_pilot(PilotProposal(authorization_id="ACCEL005-PILOT-owned"), now=NOW)
    assert pilot.usage == "ONE_SHOT" and pilot.horizon == 1
    assert (
        pilot.odds_gets,
        pilot.reserved_odds_credits,
        pilot.proposed_daily_requests,
        pilot.proposed_monthly_requests,
        pilot.proposed_daily_credits,
        pilot.proposed_monthly_credits,
        pilot.automatic_retries,
    ) == (1, 2, 1, 1, 2, 2, 0)
    with pytest.raises(ValidationError):
        RecurringProposal.model_validate(pilot.proposal.model_dump())
    with pytest.raises(ValidationError):
        OwnerPackage.model_validate({**pilot.model_dump(), "horizons": (1, 3)})


def test_missing_recurring_limits_and_decision_are_typed_blockers():
    proposal = RecurringProposal(authorization_id="ACCEL005-RECURRING-owned")
    package = prepare_recurring(proposal, now=NOW)
    assert package.state == "INCOMPLETE" and package.runtime_authority == "NOT_GRANTED"
    assert {
        "RECURRING_DAILY_REQUEST_LIMIT_REQUIRED",
        "RECURRING_DAILY_CREDIT_LIMIT_REQUIRED",
        "RECURRING_MONTHLY_REQUEST_LIMIT_REQUIRED",
        "RECURRING_MONTHLY_CREDIT_LIMIT_REQUIRED",
        "RECURRING_BUDGET_ACCEPTANCE_REQUIRED",
        "OWNER_APPROVAL_REQUIRED",
    } <= set(package.blockers)
    assert package.usage == "MANUAL_RECURRING" and package.horizons == (1, 3)
    assert (
        package.odds_gets_per_refresh,
        package.reserved_odds_credits_per_refresh,
        package.automatic_retries,
    ) == (1, 2, 0)


@pytest.mark.parametrize(
    "changes",
    [
        {"daily_request_limit": 0},
        {"daily_request_limit": True},
        {"daily_credit_limit": 1},
        {"monthly_request_limit": 1.0},
        {"monthly_credit_limit": "4"},
        {"daily_request_limit": 2, "monthly_request_limit": 1},
        {"daily_credit_limit": 4, "monthly_credit_limit": 2},
        {"daily_request_limit": 2, "daily_credit_limit": 2},
        {"monthly_request_limit": 3, "monthly_credit_limit": 4},
        {"horizons": (1,)},
        {"horizons": (3, 1)},
        {"horizons": (1, 1)},
        {"horizons": (True, 3)},
        {"horizons": (1, 3.0)},
        {"automatic_retries": 1},
        {"authorization_id": "ACCEL005-PILOT-owned"},
    ],
)
def test_recurring_scope_rejects_unbounded_or_coerced_input(changes):
    with pytest.raises(ValidationError):
        RecurringProposal.model_validate(
            {"authorization_id": "ACCEL005-RECURRING-owned", **changes}
        )


def test_complete_review_remains_nonexecuting_and_authenticates_roundtrip(tmp_path):
    base, request, _ = recurring_case(tmp_path)
    package = request.owner_package
    assert isinstance(package, RecurringOwnerPackage)
    assert package.state == "READY_FOR_INDEPENDENT_OWNER_REVIEW"
    assert wheel.EnrollmentInput.model_validate_json(request.model_dump_json()) == request
    review = wheel.prepare_enrollment(base, request, now=NOW)
    assert review.runtime_authority == "NOT_GRANTED" and review.candidate == request.candidate
    assert review.owner_package_sha256 == package.semantic_sha256
    assert review.base_wheel_sha256 == hashlib.sha256(base.read_bytes()).hexdigest()
    assert review.candidate.default_authorization_id == package.proposal.authorization_id
    with pytest.raises(OperationError, match="INSTALLED_RELEASE_PERMIT_REQUIRED"):
        wheel.assemble_enrolled_wheel(
            base, review, tmp_path / "unapproved.whl", permit_id="self-claimed", now=NOW
        )
    assert not (tmp_path / "unapproved.whl").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"recurring_budget_acceptance_evidence_sha256": None},
        {"monthly_credit_limit": 14},
        {"qualified_deadline_at": NOW},
    ],
)
def test_missing_budget_acceptance_excess_allocation_and_expired_deadline_block(tmp_path, changes):
    _, request, _ = recurring_case(tmp_path)
    proposal = request.owner_package.proposal.model_copy(update=changes)
    package = prepare_recurring(proposal, now=NOW)
    assert package.state == "INCOMPLETE" and package.runtime_authority == "NOT_GRANTED"
    with pytest.raises(ValidationError):
        RecurringOwnerPackage.model_validate(
            {
                **package.model_dump(),
                "state": "READY_FOR_INDEPENDENT_OWNER_REVIEW",
                "blockers": (),
            }
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"usage": "ONE_SHOT"},
        {"horizons": (1,)},
        {"daily_request_limit": 1},
        {"daily_credit_limit": 2},
        {"monthly_request_limit": 5},
        {"monthly_credit_limit": 10},
        {"qualified_deadline_at": NOW + timedelta(hours=2)},
        {"approval_evidence_sha256": "f" * 64},
    ],
)
def test_enrollment_cannot_borrow_pilot_scope_or_another_budget(tmp_path, changes):
    base, request, _ = recurring_case(tmp_path)
    changed = request.candidate.approvals[0].model_copy(update=changes)
    request = request.model_copy(
        update={"candidate": request.candidate.model_copy(update={"approvals": (changed,)})}
    )
    with pytest.raises(OperationError, match="ENROLLMENT_PROPOSAL_SCOPE_MISMATCH"):
        wheel.prepare_enrollment(base, request, now=NOW)


@pytest.mark.parametrize("recurring", [False, True])
def test_enrollment_rechecks_quota_age_and_exact_source_validity_at_preparation(
    tmp_path, recurring
):
    base, request, _ = recurring_case(tmp_path) if recurring else wheel_case(tmp_path)
    with pytest.raises(OperationError, match="ENROLLMENT_PROPOSAL_SCOPE_MISMATCH"):
        wheel.prepare_enrollment(base, request, now=NOW + timedelta(seconds=301))
    qualification = request.candidate.qualifications[0].model_copy(update={"valid_until": NOW})
    candidate = request.candidate.model_copy(
        update={"qualifications": (qualification, *request.candidate.qualifications[1:])}
    )
    with pytest.raises(OperationError, match="ENROLLMENT_SOURCE_CLOSURE_REQUIRED"):
        wheel.prepare_enrollment(base, request.model_copy(update={"candidate": candidate}), now=NOW)


def test_trusted_permit_preserves_code_and_exact_recurring_scope(tmp_path, monkeypatch):
    base, request, members = recurring_case(tmp_path)
    review = wheel.prepare_enrollment(base, request, now=NOW)
    monkeypatch.setattr(
        wheel,
        "installed_enrollment",
        lambda: InstalledEnrollment(release_permits=(permit_for(review),)),
    )
    directory = tmp_path / "reviewed"
    directory.mkdir()
    output = directory / base.name
    digest = wheel.assemble_enrolled_wheel(
        base, review, output, permit_id="owned-release-only", now=NOW
    )
    assert digest == review.expected_enrolled_wheel_sha256
    with ZipFile(output) as archive:
        assert {name for name in members if archive.read(name) != members[name]} == {
            wheel.RESOURCE,
            "dmf_pulse-0.2.0.dist-info/RECORD",
        }
        assert (
            InstalledEnrollment.model_validate_json(archive.read(wheel.RESOURCE))
            == request.candidate
        )


def test_recurring_cli_prepares_and_enrollment_cli_reviews_without_installation(
    tmp_path, monkeypatch
):
    base, request, _ = recurring_case(tmp_path)

    class Clock:
        @staticmethod
        def now(zone):
            return NOW

    monkeypatch.setattr(cli, "datetime", Clock)
    proposal_path, package_path = tmp_path / "input.json", tmp_path / "owner.json"
    write_nonexecuting_input(proposal_path, request.owner_package.proposal)
    args = [
        "prepare-recurring",
        "--authorization-id",
        request.owner_package.proposal.authorization_id,
        "--input",
        str(proposal_path),
        "--output",
        str(package_path),
    ]
    response = CliRunner().invoke(cli.operation_app, args)
    assert response.exit_code == 0, response.output
    assert json.loads(response.stdout)["runtime_authority"] == "NOT_GRANTED"
    assert read_metadata(package_path, RecurringOwnerPackage) == request.owner_package
    assert CliRunner().invoke(cli.operation_app, args).exit_code == 2
    enrollment_path, review_path = tmp_path / "enrollment.json", tmp_path / "review.json"
    write_nonexecuting_input(enrollment_path, request)
    response = CliRunner().invoke(
        cli.operation_app,
        [
            "prepare-enrollment",
            "--base-wheel",
            str(base),
            "--input",
            str(enrollment_path),
            "--output",
            str(review_path),
        ],
    )
    assert response.exit_code == 0, response.output
    assert read_metadata(review_path, wheel.EnrollmentWheelReview).candidate == request.candidate


@pytest.mark.parametrize("attack", ["identity", "invalid", "unknown_field"])
def test_recurring_cli_failures_never_expose_input_or_write_package(tmp_path, attack):
    proposal = RecurringProposal(authorization_id="ACCEL005-RECURRING-owned")
    path, output = tmp_path / "input.json", tmp_path / "output.json"
    write_nonexecuting_input(path, proposal)
    if attack == "invalid":
        path.write_text('{"private-canary":', encoding="utf-8")
    if attack == "unknown_field":
        path.write_text(
            json.dumps({**proposal.model_dump(mode="json"), "opaque_canary": "private-canary"}),
            encoding="utf-8",
        )
    response = CliRunner().invoke(
        cli.operation_app,
        [
            "prepare-recurring",
            "--authorization-id",
            "ACCEL005-RECURRING-other" if attack == "identity" else proposal.authorization_id,
            "--input",
            str(path),
            "--output",
            str(output),
        ],
    )
    assert response.exit_code == 2 and not output.exists()
    assert "private-canary" not in response.output and "Traceback" not in response.output
