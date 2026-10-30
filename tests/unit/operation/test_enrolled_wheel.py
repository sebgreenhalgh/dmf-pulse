"""Complete populated review and exact installed-permit assembly, using owned bytes."""

import hashlib
import json
from datetime import timedelta
from zipfile import ZipFile

import pytest
from typer.testing import CliRunner

from dmf_pulse.operation import enrollment, wheel
from dmf_pulse.operation.cli import operation_app
from dmf_pulse.operation.enrollment import InstalledEnrollment, ReleasePermit
from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.packages import read_metadata, write_nonexecuting_input
from tests.unit.dashboard.test_live_authorization import NOW
from tests.unit.operation.enrollment_support import wheel_case

pytestmark = pytest.mark.unit


@pytest.fixture
def case(tmp_path):
    return wheel_case(tmp_path)


def test_populated_draft_never_grants_or_assembles_without_installed_permit(case, tmp_path):
    base, request, _ = case
    review = wheel.prepare_enrollment(base, request, now=NOW)
    assert wheel.EnrollmentInput.model_validate_json(request.model_dump_json()) == request
    assert wheel.EnrollmentWheelReview.model_validate_json(review.model_dump_json()) == review
    assert review.semantic_sha256 and review.runtime_authority == "NOT_GRANTED"
    output = tmp_path / "denied.whl"
    with pytest.raises(OperationError, match="INSTALLED_RELEASE_PERMIT_REQUIRED"):
        wheel.assemble_enrolled_wheel(base, review, output, permit_id="self-claimed", now=NOW)
    assert not output.exists()


def permit_for(review):
    return ReleasePermit(
        permit_id="owned-release-only",
        base_wheel_sha256=review.base_wheel_sha256,
        registry_sha256=review.registry_sha256,
        owner_package_sha256=review.owner_package_sha256,
        independent_review_sha256="f" * 64,
        owner_decision_ref="owned-not-real-acceptance",
        accepted_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=5),
    )


def test_exact_owned_installed_permit_transforms_only_registry_and_record(
    case, tmp_path, monkeypatch
):
    base, request, members = case
    review = wheel.prepare_enrollment(base, request, now=NOW)
    monkeypatch.setattr(
        wheel,
        "installed_enrollment",
        lambda: InstalledEnrollment(release_permits=(permit_for(review),)),
    )
    directory = tmp_path / "enrolled"
    directory.mkdir()
    output = directory / base.name
    digest = wheel.assemble_enrolled_wheel(
        base, review, output, permit_id="owned-release-only", now=NOW
    )
    assert (
        digest
        == review.expected_enrolled_wheel_sha256
        == hashlib.sha256(output.read_bytes()).hexdigest()
    )
    with ZipFile(output) as archive:
        assert {name for name in members if archive.read(name) != members[name]} == {
            wheel.RESOURCE,
            "dmf_pulse-0.2.0.dist-info/RECORD",
        }
        assert (
            InstalledEnrollment.model_validate_json(archive.read(wheel.RESOURCE))
            == request.candidate
        )
    with pytest.raises(OperationError, match="WRITE_FAILED"):
        wheel.assemble_enrolled_wheel(base, review, output, permit_id="owned-release-only", now=NOW)


@pytest.mark.parametrize(
    "attack", ["base", "resource", "package", "expected_output", "expiry", "fingerprint"]
)
def test_tampered_review_or_wheel_cannot_inherit_permit(case, tmp_path, monkeypatch, attack):
    base, request, _ = case
    review = wheel.prepare_enrollment(base, request, now=NOW)
    permit = permit_for(review)
    monkeypatch.setattr(
        wheel, "installed_enrollment", lambda: InstalledEnrollment(release_permits=(permit,))
    )
    at = NOW
    if attack == "base":
        base.write_bytes(b"owned corrupt wheel")
    elif attack == "resource":
        review = review.model_copy(
            update={
                "candidate": request.candidate.model_copy(update={"default_authorization_id": None})
            }
        )
    elif attack == "package":
        review = review.model_copy(update={"owner_package_sha256": "0" * 64})
    elif attack == "expected_output":
        review = review.model_copy(update={"expected_enrolled_wheel_sha256": "0" * 64})
    elif attack == "expiry":
        at = permit.expires_at
    else:
        changed = request.candidate.approvals[0].model_copy(update={"implementation_sha": "0" * 40})
        review = review.model_copy(
            update={"candidate": request.candidate.model_copy(update={"approvals": (changed,)})}
        )
    output = tmp_path / "denied.whl"
    with pytest.raises(OperationError):
        wheel.assemble_enrolled_wheel(base, review, output, permit_id="owned-release-only", now=at)
    assert not output.exists()


@pytest.mark.parametrize(
    "alias",
    [
        "dmf_pulse/./owned.py",
        "dmf_pulse//owned.py",
        "DMF_PULSE/owned.py",
        "dmf_pulse/owned.py.",
        "dmf_pulse/owned.py ",
        "dmf_pulse/CON",
    ],
)
def test_cross_platform_ambiguous_wheel_names_are_rejected(case, tmp_path, alias):
    _, _, members = case
    members[alias] = b"owned ambiguous bytes"
    path = tmp_path / "ambiguous.whl"
    path.write_bytes(wheel._zip_bytes(members))
    with pytest.raises(OperationError, match="BASE_WHEEL_INVALID"):
        wheel._wheel_members(path)


def test_private_registry_parse_failure_discards_document_and_context(monkeypatch):
    canary = "owned-private-registry-canary"

    class Resource:
        def joinpath(self, name):
            return self

        def read_bytes(self):
            return ("{" + canary).encode()

    monkeypatch.setattr(enrollment, "files", lambda package: Resource())
    with pytest.raises(OperationError) as caught:
        enrollment.installed_enrollment()
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    trace = caught.value.__traceback__
    while trace:
        if trace.tb_frame.f_code.co_filename.endswith("enrollment.py"):
            assert canary not in str(trace.tb_frame.f_locals)
        trace = trace.tb_next


def test_launch_default_empty_registry_never_starts_dashboard(monkeypatch):
    from dmf_pulse.cli import dashboard

    monkeypatch.setattr(
        dashboard, "dashboard_command", lambda **kwargs: pytest.fail("unapproved dashboard started")
    )
    result = CliRunner().invoke(operation_app, ["launch"])
    assert result.exit_code == 2 and "REVIEWED_DEFAULT_LAUNCH_REQUIRED" in result.output


def test_cli_prepares_private_nonexecuting_complete_review(case, tmp_path, monkeypatch):
    from dmf_pulse.operation import cli

    base, request, _ = case

    class Clock:
        @staticmethod
        def now(zone):
            return NOW

    monkeypatch.setattr(cli, "datetime", Clock)
    input_path, output = tmp_path / "input.json", tmp_path / "review.json"
    write_nonexecuting_input(input_path, request)
    result = CliRunner().invoke(
        operation_app,
        [
            "prepare-enrollment",
            "--base-wheel",
            str(base),
            "--input",
            str(input_path),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["runtime_authority"] == "NOT_GRANTED"
    assert read_metadata(output, wheel.EnrollmentWheelReview).candidate == request.candidate


def test_release_carrier_is_detached_review_only_and_cannot_enroll_itself(case, tmp_path):
    base, request, _ = case
    review = wheel.prepare_enrollment(base, request, now=NOW)
    output = tmp_path / "carrier-review.zip"
    digest = wheel.prepare_release_carrier_review(base, permit_for(review), output)
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    with ZipFile(output) as archive:
        receipt = json.loads(archive.read("REVIEW-ONLY.json"))
        assert receipt["runtime_authority"] == "NOT_INSTALLED_REVIEW_ONLY"
        assert (
            hashlib.sha256(archive.read(base.name)).hexdigest() == receipt["carrier_wheel_sha256"]
        )
    assert enrollment.installed_enrollment() == InstalledEnrollment()
    with pytest.raises(OperationError, match="INSTALLED_RELEASE_PERMIT_REQUIRED"):
        wheel.assemble_enrolled_wheel(
            base, review, tmp_path / "unapproved.whl", permit_id="owned-release-only", now=NOW
        )
    with pytest.raises(OperationError, match="WRITE_FAILED"):
        wheel.prepare_release_carrier_review(base, permit_for(review), output)


def test_invalid_output_wheel_filename_does_not_report_installable_success(
    case, tmp_path, monkeypatch
):
    base, request, _ = case
    review = wheel.prepare_enrollment(base, request, now=NOW)
    monkeypatch.setattr(
        wheel,
        "installed_enrollment",
        lambda: InstalledEnrollment(release_permits=(permit_for(review),)),
    )
    with pytest.raises(OperationError, match="ENROLLMENT_OUTPUT_INVALID"):
        wheel.assemble_enrolled_wheel(
            base, review, tmp_path / "arbitrary.whl", permit_id="owned-release-only", now=NOW
        )
