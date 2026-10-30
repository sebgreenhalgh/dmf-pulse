"""Owned three-source enrollment and wheel, never an actual account or permission."""

import csv
import hashlib
import io
from datetime import timedelta
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_json_bytes
from dmf_pulse.dashboard.authorization import SourceScope
from dmf_pulse.ingestion.odds.config import load_rights_profiles as odds_profiles
from dmf_pulse.ingestion.openfootball.config import load_rights_profiles as score_profiles
from dmf_pulse.operation.enrollment import (
    InstalledEnrollment,
    SourceQualification,
    rights_fingerprint,
)
from dmf_pulse.operation.packages import PilotProposal, prepare_pilot
from dmf_pulse.operation.wheel import RESOURCE, EnrollmentInput, _record_hash, _zip_bytes
from tests.unit.dashboard.test_live_authorization import NOW, setup
from tests.unit.operation.test_supplier_enrollment import qualification


def wheel_case(tmp_path):
    _, original, _, _ = setup(tmp_path)
    fpl = qualification()
    scopes, qualifications = [fpl.scope], [fpl]
    for provider, profile in (
        ("ODDS", odds_profiles()["the_odds_api_private_analytics_v1"]),
        ("OPENFOOTBALL", score_profiles()["openfootball_football_json_score_prior_v1"]),
    ):
        profile = profile.model_copy(
            update={"rights_profile_id": "owned-new-purpose-" + provider.lower()}
        )
        old_scope = next(row for row in original.source_scopes if row.provider == provider)
        scope = SourceScope.model_validate(
            {
                **old_scope.model_dump(),
                "profile_id": profile.rights_profile_id,
                "profile_sha256": rights_fingerprint(profile),
                "source_kind": "RIGHTS_QUALIFIED_PRIVATE",
            }
        )
        scopes.append(scope)
        qualifications.append(
            SourceQualification(
                qualification_id="owned-" + provider.lower(),
                scope=scope,
                profile=profile,
                purpose="PRIVATE_OPERATOR_FPL_RECOMMENDATIONS",
                permission_basis="VENDOR_TERMS_AND_ACCOUNT",
                permission_evidence_sha256="a" * 64,
                account_review_sha256="d" * 64 if provider == "ODDS" else None,
                independent_review_sha256="b" * 64,
                decision_ref="owned-not-real-approval",
                operator_country="DE",
                qualified_at=NOW - timedelta(minutes=1),
                valid_until=NOW + timedelta(minutes=10),
                control_metadata_retention_approved=True,
            )
        )
    members = {
        "dmf_pulse/__init__.py": b'"""Owned wheel fixture, never imported."""\n',
        "dmf_pulse/owned.py": b"OWNED = True\n",
        RESOURCE: canonical_json_bytes(InstalledEnrollment().model_dump(mode="json")) + b"\n",
        "dmf_pulse-0.2.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: dmf-pulse\nVersion: 0.2.0\n",
        "dmf_pulse-0.2.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    digest = hashlib.sha256()
    for path in sorted(
        Path(name.removeprefix("dmf_pulse/"))
        for name in members
        if name.startswith("dmf_pulse/") and name != RESOURCE
    ):
        digest.update(
            path.as_posix().encode() + b"\0" + members["dmf_pulse/" + path.as_posix()] + b"\0"
        )
    record = "dmf_pulse-0.2.0.dist-info/RECORD"
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name, body in sorted(members.items()):
        writer.writerow((name, _record_hash(body), len(body)))
    writer.writerow((record, "", ""))
    members[record] = output.getvalue().encode()
    base = tmp_path / "dmf_pulse-0.2.0-py3-none-any.whl"
    base.write_bytes(_zip_bytes(members))
    quota = original.plan_quota.model_copy(
        update={"allocated_monthly_credits": 2, "evidence_sha256": "d" * 64}
    )
    approval = original.model_copy(
        update={
            "authorization_id": "ACCEL005-PILOT-owned-example",
            "classification": "PRIVATE_CURRENT",
            "implementation_sha": digest.hexdigest()[:40],
            "source_scopes": tuple(scopes),
            "plan_quota": quota,
            "ledger_backend": "POSTGRES",
            "usage": "ONE_SHOT",
            "qualified_deadline_at": NOW + timedelta(hours=1),
            "horizons": (1,),
            "daily_request_limit": 1,
            "daily_credit_limit": 2,
            "monthly_request_limit": 1,
            "monthly_credit_limit": 2,
        }
    )
    proposal = PilotProposal(
        authorization_id=approval.authorization_id,
        operator_ref=approval.operator_ref,
        entry_id=17,
        qualified_deadline_at=approval.qualified_deadline_at,
        owner_approval_evidence_sha256=approval.approval_evidence_sha256,
        account_entitlement_evidence_sha256="d" * 64,
        project_rights_review_sha256=approval.review_sha256,
        implementation_sha=approval.implementation_sha,
        wheel_sha256=hashlib.sha256(base.read_bytes()).hexdigest(),
        source_scopes=approval.source_scopes,
        plan_quota=quota,
        ledger_id=approval.ledger_id,
        control_receipt_sha256="e" * 64,
        control_metadata_retention_approved=True,
    )
    registry = InstalledEnrollment(
        approvals=(approval,),
        qualifications=tuple(qualifications),
        default_authorization_id=approval.authorization_id,
    )
    return (
        base,
        EnrollmentInput(owner_package=prepare_pilot(proposal, now=NOW), candidate=registry),
        members,
    )
