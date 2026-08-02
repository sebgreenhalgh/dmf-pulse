"""Evidence-model provenance and ticket-manifest negative controls."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmf_pulse.assurance import evidence as evidence_module
from dmf_pulse.assurance.evidence import (
    FPL_REQUIRED_BASELINE,
    FPL_REQUIRED_BRANCH,
    FPL_REVIEW_PATH,
    ODD_REQUIRED_BASELINE,
    ODD_REQUIRED_BRANCH,
    ODD_REVIEW_PATH,
    CodexResult,
    EvidenceArtifact,
    EvidenceKind,
    EvidenceValidationError,
    ReviewManifest,
    ReviewPackReference,
    TicketEvidenceManifest,
    ValidatedEvidence,
    validate_ticket_evidence,
)

pytestmark = pytest.mark.unit
HEAD = "a" * 40


def _result_value(ticket: str) -> dict[str, object]:
    contracts = {
        "RUL-002": (
            "12049a7de23a4a8fcca3d219dbcab1bf5e1027ea",
            "stage/A2/RUL-002-rules-foundation",
            "review_pack/RUL-002/DMF_PULSE_RUL-002_REVIEW.zip",
        ),
        "FPL-004": (FPL_REQUIRED_BASELINE, FPL_REQUIRED_BRANCH, FPL_REVIEW_PATH),
        "ODD-005": (ODD_REQUIRED_BASELINE, ODD_REQUIRED_BRANCH, ODD_REVIEW_PATH),
    }
    baseline, branch, review_path = contracts[ticket]
    return {
        "acceptance": [],
        "assumptions": [],
        "code_commit": HEAD,
        "commands": [],
        "exclusions_verified": [],
        "files_changed": [],
        "public_interfaces": [],
        "repository": {
            "baseline": baseline,
            "branch": branch,
            "clean": True,
            "head": HEAD,
            "merged": False,
            "pushed": False,
        },
        "review_pack": {
            "file_count": 20,
            "path": review_path,
            "payload_sha256": "b" * 64,
        },
        "risks": [],
        "status": "FAILED",
        "summary": "Synthetic evidence boundary.",
        "tests": [],
        "ticket_id": ticket,
    }


def test_review_reference_requires_exactly_one_payload_digest() -> None:
    with pytest.raises(ValueError, match="requires payload"):
        ReviewPackReference(path="review.zip", file_count=1)
    with pytest.raises(ValueError, match="cannot be combined"):
        ReviewPackReference(
            path="review.zip",
            file_count=1,
            payload_sha256="a" * 64,
            sha256="b" * 64,
        )


@pytest.mark.parametrize("ticket", ("RUL-002", "FPL-004", "ODD-005"))
def test_stage_result_rejects_review_reference_and_repository_drift(ticket: str) -> None:
    value = _result_value(ticket)
    review = value["review_pack"]
    assert isinstance(review, dict)
    review["path"] = "wrong.zip"
    with pytest.raises(ValueError, match="20-file review reference"):
        CodexResult.model_validate(value)

    value = _result_value(ticket)
    repository = value["repository"]
    assert isinstance(repository, dict)
    repository["clean"] = False
    with pytest.raises(ValueError, match="clean repository provenance"):
        CodexResult.model_validate(value)


def _manifest(ticket: str, *, baseline: str | None = None) -> dict[str, object]:
    return {
        "acceptance_status": "FAILED",
        "archive_sha256": None,
        "baseline": baseline,
        "file_count": 20,
        "files": [],
        "generated_at": "2026-08-02T00:00:00Z",
        "payload_sha256": "a" * 64,
        "repository_head": HEAD,
        "ticket_id": ticket,
    }


def test_review_manifest_rejects_file_count_and_each_stage_provenance() -> None:
    too_small = _manifest("FND-001")
    too_small["file_count"] = 1
    too_small["files"] = [
        {"bytes": 1, "name": "a", "purpose": "a", "sha256": "a" * 64},
        {"bytes": 1, "name": "b", "purpose": "b", "sha256": "b" * 64},
    ]
    with pytest.raises(ValueError, match="smaller"):
        ReviewManifest.model_validate(too_small)

    for ticket in ("RUL-002", "FPL-004", "ODD-005"):
        with pytest.raises(ValueError, match="manifest provenance"):
            ReviewManifest.model_validate(_manifest(ticket, baseline="0" * 40))


def test_ticket_validation_rejects_wrong_kind_and_ticket_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrong_kind = ReviewManifest.model_validate(_manifest("FND-001"))
    monkeypatch.setattr(
        evidence_module,
        "validate_evidence_file",
        lambda _path: ValidatedEvidence(EvidenceKind.REVIEW_MANIFEST, wrong_kind),
    )
    with pytest.raises(EvidenceValidationError) as kind_error:
        validate_ticket_evidence(tmp_path, "ODD-005")
    assert kind_error.value.code == "EVIDENCE_MANIFEST_KIND"

    mismatched = TicketEvidenceManifest(
        ticket_id="FND-001",
        status="DRAFT",
        created_at="2026-08-02T00:00:00Z",
        commands=[],
        artifacts=[],
    )
    monkeypatch.setattr(
        evidence_module,
        "validate_evidence_file",
        lambda _path: ValidatedEvidence(EvidenceKind.TICKET_MANIFEST, mismatched),
    )
    with pytest.raises(EvidenceValidationError) as mismatch:
        validate_ticket_evidence(tmp_path, "ODD-005")
    assert mismatch.value.code == "EVIDENCE_TICKET_MISMATCH"


def test_ticket_validation_rejects_invalid_ticket_and_unsorted_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(EvidenceValidationError) as invalid_ticket:
        validate_ticket_evidence(tmp_path, "../invalid")
    assert invalid_ticket.value.code == "EVIDENCE_TICKET_INVALID"

    evidence_root = tmp_path / "evidence/tickets/ODD-005"
    evidence_root.mkdir(parents=True)
    (evidence_root / "a.txt").write_text("a", encoding="utf-8")
    (evidence_root / "b.txt").write_text("b", encoding="utf-8")
    manifest = TicketEvidenceManifest(
        ticket_id="ODD-005",
        status="DRAFT",
        created_at="2026-08-02T00:00:00Z",
        commands=[],
        artifacts=[
            EvidenceArtifact(
                path="evidence/tickets/ODD-005/b.txt",
                bytes=1,
                sha256="b" * 64,
            ),
            EvidenceArtifact(
                path="evidence/tickets/ODD-005/a.txt",
                bytes=1,
                sha256="a" * 64,
            ),
        ],
    )
    monkeypatch.setattr(
        evidence_module,
        "validate_evidence_file",
        lambda _path: ValidatedEvidence(EvidenceKind.TICKET_MANIFEST, manifest),
    )
    with pytest.raises(EvidenceValidationError) as order:
        validate_ticket_evidence(tmp_path, "ODD-005")
    assert order.value.code == "EVIDENCE_ARTIFACT_ORDER"


def test_file_hash_wraps_unavailable_artifact(tmp_path: Path) -> None:
    with pytest.raises(EvidenceValidationError) as caught:
        evidence_module._file_sha256(tmp_path)
    assert caught.value.code == "EVIDENCE_ARTIFACT_UNAVAILABLE"
