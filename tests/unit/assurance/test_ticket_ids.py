"""Generic ticket identifier and evidence compatibility contracts."""

from __future__ import annotations

import pytest

from dmf_pulse.assurance.evidence import CodexResult, TicketEvidenceManifest
from dmf_pulse.assurance.tickets import TicketIdError, ticket_paths, validate_ticket_id


@pytest.mark.unit
@pytest.mark.parametrize("ticket_id", ["FND-001", "RUL-002", "ABC.123-X9"])
def test_ticket_ids_are_preserved_exactly(ticket_id: str, tmp_path) -> None:
    assert validate_ticket_id(ticket_id) == ticket_id
    paths = ticket_paths(tmp_path, ticket_id)
    assert paths.evidence == tmp_path / "evidence" / "tickets" / ticket_id
    assert paths.review_zip.name == f"DMF_PULSE_{ticket_id}_REVIEW.zip"


@pytest.mark.unit
@pytest.mark.parametrize(
    "ticket_id",
    [
        "../RUL-002",
        "RUL/002",
        "RUL\\002",
        "RUL:002",
        "rul-002",
        "-RUL",
        ".RUL",
        "RUL..002",
        "RUL 002",
        "CON",
        "NUL.LOG",
        "COM1",
        "AB",
        "A" * 41,
    ],
)
def test_ticket_ids_reject_traversal_and_malformed_values(ticket_id: str) -> None:
    with pytest.raises(TicketIdError):
        validate_ticket_id(ticket_id)


@pytest.mark.unit
def test_new_complete_evidence_requires_actual_commit() -> None:
    result = {
        "ticket_id": "RUL-002",
        "status": "COMPLETE",
        "summary": "done",
        "files_changed": [],
        "commands": [],
        "tests": [],
        "acceptance": [],
        "assumptions": [],
        "risks": [],
        "review_pack": {
            "path": "review_pack/RUL-002/DMF_PULSE_RUL-002_REVIEW.zip",
            "file_count": 20,
            "payload_sha256": "0" * 64,
        },
    }
    with pytest.raises(ValueError, match="Git commit"):
        CodexResult.model_validate(result)
    manifest = {
        "ticket_id": "RUL-002",
        "status": "COMPLETE",
        "created_at": "2026-07-22T00:00:00Z",
        "commands": [],
        "artifacts": [],
    }
    with pytest.raises(ValueError, match="Git commit"):
        TicketEvidenceManifest.model_validate(manifest)


@pytest.mark.unit
def test_legacy_fnd_digest_is_accepted_but_new_digest_is_unambiguous() -> None:
    legacy = {
        "ticket_id": "FND-001",
        "status": "COMPLETE",
        "summary": "legacy",
        "files_changed": [],
        "commands": [],
        "tests": [],
        "acceptance": [],
        "assumptions": [],
        "risks": [],
        "review_pack": {"path": "legacy.zip", "file_count": 20, "sha256": "1" * 64},
    }
    assert CodexResult.model_validate(legacy).review_pack.effective_payload_sha256 == "1" * 64
    with pytest.raises(ValueError, match="cannot be combined"):
        CodexResult.model_validate(
            {
                **legacy,
                "review_pack": {
                    "path": "x.zip",
                    "file_count": 20,
                    "sha256": "1" * 64,
                    "payload_sha256": "2" * 64,
                },
            }
        )
