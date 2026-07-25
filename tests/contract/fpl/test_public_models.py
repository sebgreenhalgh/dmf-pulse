"""Frozen public result-model and checked-in schema tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from dmf_pulse.ingestion.models import (
    DriftClassification,
    FplValidationResult,
    MissingnessValue,
    ProviderResourceResult,
    ProviderSnapshotResult,
    QualityIssue,
    QualityReport,
    RightsDecision,
    SchemaDriftReport,
    SourceBundleMember,
    SourceBundleSummary,
)

pytestmark = pytest.mark.contract

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)
BOOTSTRAP_ID = UUID("00000000-0000-4000-8000-000000000001")
FIXTURES_ID = UUID("00000000-0000-4000-8000-000000000002")


def _quality() -> QualityReport:
    return QualityReport(status="PASS", warning_count=0, blocker_count=0, issues=())


def _rights() -> RightsDecision:
    return RightsDecision(
        profile_id="synthetic_test_v1",
        profile_version="1.0.0",
        capability="derived_storage",
        decision="ALLOW",
        reason="CAPABILITY_ALLOWED",
        checked_at=NOW,
    )


def _bundle() -> SourceBundleSummary:
    return SourceBundleSummary(
        bundle_id=UUID("00000000-0000-4000-8000-000000000003"),
        competition_id=UUID("00000000-0000-4000-8000-000000000004"),
        season_id=UUID("00000000-0000-4000-8000-000000000005"),
        information_cutoff=NOW,
        members=(
            SourceBundleMember(role="BOOTSTRAP", source_snapshot_id=BOOTSTRAP_ID, usable_at=NOW),
            SourceBundleMember(role="FIXTURES", source_snapshot_id=FIXTURES_ID, usable_at=NOW),
        ),
        semantic_sha256="a" * 64,
        quality_status="PASS",
    )


def test_public_snapshot_serialization_has_exact_top_level_contract() -> None:
    result = ProviderSnapshotResult(
        status="USABLE",
        provider="synthetic_fpl",
        resources=(
            ProviderResourceResult(
                resource="bootstrap",
                source_snapshot_id=BOOTSTRAP_ID,
                lifecycle_state="USABLE",
                drift="MISSING_OPTIONAL",
                raw_retention="RETAINED",
                usable_at=NOW,
            ),
            ProviderResourceResult(
                resource="fixtures",
                source_snapshot_id=FIXTURES_ID,
                lifecycle_state="USABLE",
                drift="NO_DRIFT",
                raw_retention="RETAINED",
                usable_at=NOW,
            ),
        ),
        rights=_rights(),
        quality=_quality(),
        canonical_effects={"fixture_count": 1},
        source_bundle=_bundle(),
    )
    output = result.model_dump(mode="json")
    assert tuple(output) == (
        "schema_version",
        "status",
        "provider",
        "resources",
        "rights",
        "quality",
        "canonical_effects",
        "source_bundle",
    )
    assert output["schema_version"] == "1.0.0"
    assert output["source_bundle"]["members"][0]["role"] == "BOOTSTRAP"
    assert output["source_bundle"]["members"][1]["role"] == "FIXTURES"
    assert json.loads(result.model_dump_json()) == output


@pytest.mark.parametrize(
    ("issues", "status", "warnings", "blockers"),
    [
        ((), "PASS", 0, 0),
        (
            (QualityIssue(severity="P3", code="DRIFT", subject_scope="source"),),
            "PASS_WITH_WARNINGS",
            1,
            0,
        ),
        ((QualityIssue(severity="P1", code="INVALID", subject_scope="source"),), "BLOCKED", 0, 1),
    ],
)
def test_quality_status_is_derived_from_exact_issue_counts(
    issues: tuple[QualityIssue, ...], status: str, warnings: int, blockers: int
) -> None:
    report = QualityReport(
        status=status,  # type: ignore[arg-type]
        warning_count=warnings,
        blocker_count=blockers,
        issues=issues,
    )
    assert report.status == status


def test_quality_report_rejects_false_success_and_false_counts() -> None:
    issue = QualityIssue(severity="P0", code="BROKEN", subject_scope="global")
    with pytest.raises(ValidationError, match="quality counts or status"):
        QualityReport(status="PASS", warning_count=0, blocker_count=0, issues=(issue,))


def test_quality_issue_has_typed_missingness_and_consistent_decision_impact() -> None:
    issue = QualityIssue(
        severity="P2",
        code="OPTIONAL_FIELD_ABSENT",
        subject_scope="source_snapshot",
        missingness=MissingnessValue.NOT_PUBLISHED,
    )
    assert issue.missingness is MissingnessValue.NOT_PUBLISHED
    assert issue.decision_impact == "NONBLOCKING"
    assert issue.evidence_sha256 is not None

    with pytest.raises(ValidationError, match="decision impact contradicts severity"):
        QualityIssue(
            severity="P1",
            code="MAPPING_FAILED",
            subject_scope="source_snapshot",
            missingness=MissingnessValue.MAPPING_FAILED,
            decision_impact="NONBLOCKING",
        )


def test_bundle_requires_exact_order_distinct_members_and_aware_cutoff() -> None:
    bundle = _bundle()
    with pytest.raises(ValidationError, match="ordered BOOTSTRAP then FIXTURES"):
        SourceBundleSummary(**{**bundle.model_dump(), "members": tuple(reversed(bundle.members))})
    duplicate = SourceBundleMember(role="FIXTURES", source_snapshot_id=BOOTSTRAP_ID, usable_at=NOW)
    with pytest.raises(ValidationError, match="distinct snapshots"):
        SourceBundleSummary(**{**bundle.model_dump(), "members": (bundle.members[0], duplicate)})
    with pytest.raises(ValidationError, match="timezone-aware"):
        SourceBundleSummary(
            **{**bundle.model_dump(), "information_cutoff": datetime(2026, 8, 1, 12)}
        )
    post_cutoff = SourceBundleMember(
        role="FIXTURES",
        source_snapshot_id=FIXTURES_ID,
        usable_at=datetime(2026, 8, 1, 12, 0, 1, tzinfo=UTC),
    )
    with pytest.raises(ValidationError, match="usable no later than"):
        SourceBundleSummary(**{**bundle.model_dump(), "members": (bundle.members[0], post_cutoff)})


def test_public_models_reject_extra_fields_and_mutation() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        RightsDecision(
            profile_id="p",
            profile_version="1.0.0",
            capability="raw_storage",
            decision="DENY",
            reason="CAPABILITY_DENIED",
            checked_at=NOW,
            leaked="forbidden",  # type: ignore[call-arg]
        )
    report = _quality()
    with pytest.raises(ValidationError, match="frozen"):
        report.status = "BLOCKED"  # type: ignore[misc]


def test_schema_constants_are_enforced_by_runtime_models() -> None:
    bundle = _bundle()
    with pytest.raises(ValidationError):
        SourceBundleSummary(**{**bundle.model_dump(), "bundle_type": "OTHER"})
    snapshot = ProviderSnapshotResult(
        status="USABLE",
        provider="synthetic_fpl",
        resources=(),
        rights=_rights(),
        quality=_quality(),
        canonical_effects={},
    )
    with pytest.raises(ValidationError):
        ProviderSnapshotResult(**{**snapshot.model_dump(), "schema_version": "2.0.0"})


def test_checked_in_schema_required_keys_and_enums_match_models(repository_root: Path) -> None:
    contract_root = repository_root / "public_contracts"
    snapshot_schema = json.loads(
        (contract_root / "provider_snapshot_result.schema.json").read_text("utf-8")
    )
    bundle_schema = json.loads(
        (contract_root / "source_bundle_summary.schema.json").read_text("utf-8")
    )
    quality_schema = json.loads((contract_root / "quality_report.schema.json").read_text("utf-8"))
    rights_schema = json.loads((contract_root / "rights_decision.schema.json").read_text("utf-8"))

    assert set(snapshot_schema["required"]) == {
        "schema_version",
        "status",
        "provider",
        "resources",
        "rights",
        "quality",
        "canonical_effects",
    }
    assert snapshot_schema["properties"]["schema_version"]["const"] == "1.0.0"
    assert set(snapshot_schema["properties"]["status"]["enum"]) == {
        "USABLE",
        "USABLE_WITH_WARNINGS",
        "QUARANTINED",
        "RIGHTS_BLOCKED",
        "FAILED",
    }
    assert bundle_schema["properties"]["bundle_type"]["const"] == "FPL_BOOTSTRAP_FIXTURES"
    assert bundle_schema["properties"]["members"]["minItems"] == 2
    assert bundle_schema["properties"]["members"]["maxItems"] == 2
    assert set(quality_schema["required"]) == set(QualityReport.model_fields)
    assert set(rights_schema["required"]) == set(RightsDecision.model_fields) - {"checked_at"}


def test_validation_result_has_stable_drift_and_quality_shape() -> None:
    drift = SchemaDriftReport(
        contract_version="fpl-reference-v1",
        classification=DriftClassification.ADDITIVE_UNKNOWN,
        unknown_paths=("$.future",),
        payload_sha256="1" * 64,
        observed_type_fingerprint="2" * 64,
        schema_fingerprint="3" * 64,
    )
    result = FplValidationResult(
        status="VALID_WITH_WARNINGS",
        provider="synthetic_fpl",
        resource="bootstrap",
        contract_version="fpl-reference-v1",
        payload_semantic_sha256="4" * 64,
        drift=drift,
        quality=QualityReport(
            status="PASS_WITH_WARNINGS",
            warning_count=1,
            blocker_count=0,
            issues=(
                QualityIssue(severity="P3", code="ADDITIVE_DRIFT", subject_scope="source_snapshot"),
            ),
        ),
        next_action="eligible_for_synthetic_ingestion",
    )
    output = result.model_dump(mode="json")
    assert tuple(output) == (
        "schema_version",
        "status",
        "provider",
        "resource",
        "contract_version",
        "payload_semantic_sha256",
        "drift",
        "quality",
        "next_action",
    )
    assert output["drift"]["adapter_version"] == "fpl-reference-v1"
    assert output["drift"]["classification"] == "ADDITIVE_UNKNOWN"


def test_rights_profile_times_normalize_to_utc(repository_root: Path) -> None:
    raw = json.loads(
        (repository_root / "config" / "rights" / "fpl_profiles.json").read_text("utf-8")
    )["profiles"][0]
    raw["checked_at"] = "2026-07-23T01:00:00+01:00"
    raw["approved_at"] = "2026-07-23T02:00:00+02:00"
    from dmf_pulse.ingestion.models import RightsProfile

    profile = RightsProfile.model_validate(raw, strict=False)
    assert profile.checked_at == datetime(2026, 7, 23, tzinfo=UTC)
    assert profile.approved_at == datetime(2026, 7, 23, tzinfo=UTC)
