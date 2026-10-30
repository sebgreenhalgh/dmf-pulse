"""Review and assemble a private enrolled wheel without editing application source."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import re
import stat
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from dmf_pulse.assurance.canonical import canonical_json_bytes
from dmf_pulse.operation.enrollment import InstalledEnrollment, ReleasePermit, installed_enrollment
from dmf_pulse.operation.models import Metadata, MetadataTime, OperationError, Sha
from dmf_pulse.operation.packages import OwnerPackage

RESOURCE = "dmf_pulse/dashboard/resources/production_refresh_enrollments.json"
MAX_WHEEL_BYTES = 64 * 1024 * 1024


class EnrollmentInput(Metadata):
    owner_package: OwnerPackage
    candidate: InstalledEnrollment


class EnrollmentWheelReview(Metadata):
    schema_version: Literal["private-enrollment-wheel-review-v1"] = (
        "private-enrollment-wheel-review-v1"
    )
    prepared_at: datetime
    base_wheel_sha256: Sha
    registry_sha256: Sha
    expected_enrolled_wheel_sha256: Sha
    owner_package_sha256: Sha
    candidate: InstalledEnrollment
    runtime_authority: Literal["NOT_GRANTED"] = "NOT_GRANTED"
    acceptance_required: Literal["DETACHED_REVIEW_AND_INSTALLED_RELEASE_PERMIT"] = (
        "DETACHED_REVIEW_AND_INSTALLED_RELEASE_PERMIT"
    )


def _members_or_none(path: Path) -> tuple[dict[str, bytes], str] | None:
    try:
        if (
            path.is_symlink()
            or not stat.S_ISREG(path.stat().st_mode)
            or path.stat().st_size > MAX_WHEEL_BYTES
        ):
            return None
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size > MAX_WHEEL_BYTES
                or path.is_symlink()
            ):
                return None
            body = stream.read(MAX_WHEEL_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(body) != before.st_size or (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            return None
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            infos = archive.infolist()
            if len(infos) > 2000 or sum(item.file_size for item in infos) > MAX_WHEEL_BYTES:
                return None
            names = [item.filename for item in infos]
            if len(names) != len({name.casefold() for name in names}) or any(
                name.startswith(("/", "\\"))
                or "\\" in name
                or ":" in name
                or ".." in PurePosixPath(name).parts
                or name.endswith("/")
                or PurePosixPath(name).as_posix() != name
                or any(
                    part.rstrip(". ") != part
                    or part.split(".")[0].upper()
                    in {
                        "CON",
                        "PRN",
                        "AUX",
                        "NUL",
                        *("COM" + str(index) for index in range(1, 10)),
                        *("LPT" + str(index) for index in range(1, 10)),
                    }
                    for part in PurePosixPath(name).parts
                )
                or (name.casefold().startswith("dmf_pulse/") and not name.startswith("dmf_pulse/"))
                or stat.S_ISLNK(item.external_attr >> 16)
                for name, item in zip(names, infos, strict=True)
            ):
                return None
            return {item.filename: archive.read(item) for item in infos}, hashlib.sha256(
                body
            ).hexdigest()
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        return None


def _wheel_members(path: Path) -> tuple[dict[str, bytes], str]:
    result = _members_or_none(path)
    if result is None:
        raise OperationError("ENROLLMENT_BASE_WHEEL_INVALID")
    return result


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, (2020, 2, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, members[name])
    return output.getvalue()


def _enrolled_bytes(base: Path, candidate: InstalledEnrollment) -> tuple[bytes, str, str]:
    members, base_sha = _wheel_members(base)
    records = [name for name in members if name.endswith(".dist-info/RECORD")]
    if RESOURCE not in members or len(records) != 1:
        raise OperationError("ENROLLMENT_BASE_WHEEL_INVALID")
    record = records[0]
    # Authenticate every base-wheel member against its existing RECORD before use.
    try:
        rows = list(csv.reader(io.StringIO(members[record].decode("utf-8"))))
        if len(rows) != len(members) or {row[0] for row in rows} != set(members):
            raise ValueError("wheel inventory differs")
        for name, digest, size in rows:
            if name == record:
                if digest or size:
                    raise ValueError("RECORD self entry differs")
            elif digest != _record_hash(members[name]) or size != str(len(members[name])):
                raise ValueError("wheel member hash differs")
    except (ValueError, UnicodeError, IndexError):
        raise OperationError("ENROLLMENT_BASE_WHEEL_INVALID") from None
    code_digest = hashlib.sha256()
    paths = {
        Path(name.removeprefix("dmf_pulse/")): name
        for name in members
        if name.startswith("dmf_pulse/") and name != RESOURCE
    }
    for path in sorted(paths):
        code_digest.update(path.as_posix().encode())
        code_digest.update(b"\0")
        code_digest.update(members[paths[path]])
        code_digest.update(b"\0")
    if any(row.implementation_sha != code_digest.hexdigest()[:40] for row in candidate.approvals):
        raise OperationError("ENROLLMENT_INSTALLED_IMPLEMENTATION_MISMATCH")
    registry = canonical_json_bytes(candidate.model_dump(mode="json")) + b"\n"
    members[RESOURCE] = registry
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name in sorted(members):
        writer.writerow(
            (name, "", "")
            if name == record
            else (name, _record_hash(members[name]), len(members[name]))
        )
    members[record] = output.getvalue().encode("utf-8")
    return _zip_bytes(members), hashlib.sha256(registry).hexdigest(), base_sha


def _record_hash(body: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode(
        "ascii"
    )


def prepare_enrollment(
    base: Path, request: EnrollmentInput, *, now: datetime
) -> EnrollmentWheelReview:
    now = MetadataTime(checked_at=now).checked_at
    request = EnrollmentInput.model_validate(request)
    package, registry = request.owner_package, request.candidate
    proposal = package.proposal
    if (
        package.state != "READY_FOR_INDEPENDENT_OWNER_REVIEW"
        or len(registry.approvals) != 1
        or registry.release_permits
    ):
        raise OperationError("ENROLLMENT_COMPLETE_REVIEW_PACKAGE_REQUIRED")
    approval = registry.approvals[0]
    if (
        approval.authorization_id != proposal.authorization_id
        or approval.status != "APPROVED_REVIEWED"
        or approval.usage != "ONE_SHOT"
        or approval.horizons != (1,)
        or approval.ledger_backend != "POSTGRES"
        or approval.qualified_deadline_at != proposal.qualified_deadline_at
        or approval.source_scopes != proposal.source_scopes
        or approval.plan_quota != proposal.plan_quota
        or approval.ledger_id != proposal.ledger_id
        or approval.implementation_sha != proposal.implementation_sha
        or approval.approval_evidence_sha256 != proposal.owner_approval_evidence_sha256
        or approval.review_sha256 != proposal.project_rights_review_sha256
        or approval.operator_ref != proposal.operator_ref
        or approval.purpose != "PRIVATE_OPERATOR_FPL_RECOMMENDATIONS"
        or approval.daily_request_limit != 1
        or approval.monthly_request_limit != 1
        or approval.daily_credit_limit != 2
        or approval.monthly_credit_limit != 2
        or not approval.not_before <= now < approval.expires_at
        or proposal.qualified_deadline_at is None
        or proposal.qualified_deadline_at <= now
    ):
        raise OperationError("ENROLLMENT_PROPOSAL_SCOPE_MISMATCH")
    if proposal.entry_id is None or not any(
        route.path == f"/api/my-team/{proposal.entry_id}/"
        for scope in approval.source_scopes
        if scope.provider == "FPL"
        for route in scope.routes
    ):
        raise OperationError("ENROLLMENT_MANAGER_SCOPE_MISMATCH")
    if len(registry.qualifications) != 3:
        raise OperationError("ENROLLMENT_SOURCE_CLOSURE_REQUIRED")
    for scope in approval.source_scopes:
        rows = [row for row in registry.qualifications if row.scope == scope]
        if len(rows) != 1 or not rows[0].qualified_at <= now < rows[0].valid_until:
            raise OperationError("ENROLLMENT_SOURCE_CLOSURE_REQUIRED")
        if (
            scope.provider == "ODDS"
            and rows[0].account_review_sha256 != proposal.account_entitlement_evidence_sha256
        ):
            raise OperationError("ENROLLMENT_ACCOUNT_REVIEW_MISMATCH")
    body, registry_sha, base_sha = _enrolled_bytes(base, registry)
    if base_sha != proposal.wheel_sha256:
        raise OperationError("ENROLLMENT_BASE_WHEEL_MISMATCH")
    return EnrollmentWheelReview(
        prepared_at=now,
        base_wheel_sha256=base_sha,
        registry_sha256=registry_sha,
        expected_enrolled_wheel_sha256=hashlib.sha256(body).hexdigest(),
        owner_package_sha256=package.semantic_sha256,
        candidate=registry,
    )


def assemble_enrolled_wheel(
    base: Path, review: EnrollmentWheelReview, output: Path, *, permit_id: str, now: datetime
) -> str:
    """Only a matching separately installed release permit enables assembly."""
    now = MetadataTime(checked_at=now).checked_at
    review = EnrollmentWheelReview.model_validate(review)
    rows = [row for row in installed_enrollment().release_permits if row.permit_id == permit_id]
    if len(rows) != 1 or not rows[0].accepted_at <= now < rows[0].expires_at:
        raise OperationError("INSTALLED_RELEASE_PERMIT_REQUIRED")
    permit = rows[0]
    if (permit.base_wheel_sha256, permit.registry_sha256, permit.owner_package_sha256) != (
        review.base_wheel_sha256,
        review.registry_sha256,
        review.owner_package_sha256,
    ):
        raise OperationError("INSTALLED_RELEASE_PERMIT_MISMATCH")
    body, registry_sha, base_sha = _enrolled_bytes(base, review.candidate)
    digest = hashlib.sha256(body).hexdigest()
    if (
        base_sha != review.base_wheel_sha256
        or registry_sha != review.registry_sha256
        or digest != review.expected_enrolled_wheel_sha256
    ):
        raise OperationError("ENROLLMENT_REVIEW_IDENTITY_MISMATCH")
    if (
        output.name != base.name
        or re.fullmatch(
            r"dmf_pulse-0\.2\.0-(?:[0-9][A-Za-z0-9_.]*-)?py3-none-any\.whl", output.name
        )
        is None
        or output.is_symlink()
    ):
        raise OperationError("ENROLLMENT_OUTPUT_INVALID")
    try:
        with output.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise OperationError("ENROLLMENT_OUTPUT_WRITE_FAILED") from None
    return digest


def prepare_release_carrier_review(base: Path, accepted_permit: ReleasePermit, output: Path) -> str:
    """Maintainer packaging only: create a review ZIP, never install or enroll it.

    A separately accepted release decision supplies this record. Its authenticity
    is assessed in detached release review; feeding a file here confers no runtime
    authority. Only deliberate installation of the exact reviewed code/resource
    carrier changes the existing trusted boundary.
    """
    accepted_permit = ReleasePermit.model_validate(accepted_permit)
    members, base_sha = _wheel_members(base)
    try:
        original = InstalledEnrollment.model_validate_json(members[RESOURCE])
    except (ValueError, KeyError):
        raise OperationError("ENROLLMENT_BASE_WHEEL_INVALID") from None
    if original != InstalledEnrollment() or base_sha != accepted_permit.base_wheel_sha256:
        raise OperationError("RELEASE_CARRIER_EMPTY_EXACT_BASE_REQUIRED")
    candidate = InstalledEnrollment(release_permits=(accepted_permit,))
    body, _, pinned_base = _enrolled_bytes(base, candidate)
    if pinned_base != base_sha:
        raise OperationError("ENROLLMENT_BASE_WHEEL_MISMATCH")
    receipt = (
        canonical_json_bytes(
            {
                "schema_version": "private-release-carrier-review-v1",
                "base_wheel_sha256": base_sha,
                "carrier_wheel_sha256": hashlib.sha256(body).hexdigest(),
                "accepted_permit_semantic_sha256": accepted_permit.semantic_sha256,
                "runtime_authority": "NOT_INSTALLED_REVIEW_ONLY",
                "required_transition": "INDEPENDENT_DETACHED_REVIEW_THEN_EXPLICIT_TRUSTED_INSTALLATION",
                "provider_requests": 0,
            }
        )
        + b"\n"
    )
    archive = _zip_bytes({base.name: body, "REVIEW-ONLY.json": receipt})
    if output.suffix != ".zip" or output.is_symlink():
        raise OperationError("RELEASE_CARRIER_REVIEW_ZIP_REQUIRED")
    try:
        with output.open("xb") as stream:
            stream.write(archive)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise OperationError("ENROLLMENT_OUTPUT_WRITE_FAILED") from None
    return hashlib.sha256(archive).hexdigest()
