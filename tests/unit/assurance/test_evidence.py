"""Canonical serialization and strict evidence contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmf_pulse.assurance.canonical import canonical_json_bytes, canonical_sha256
from dmf_pulse.assurance.evidence import (
    CodexResult,
    EvidenceKind,
    EvidenceValidationError,
    RepositoryState,
    ReviewManifest,
    TicketEvidenceManifest,
    validate_evidence_data,
    validate_evidence_file,
)


def _result() -> dict[str, object]:
    return {
        "ticket_id": "FND-001",
        "status": "COMPLETE",
        "summary": "Foundation accepted by the automated contract.",
        "files_changed": [{"path": "src/dmf_pulse/__init__.py", "change": "created"}],
        "public_interfaces": ["dmf --version"],
        "commands": [{"command": "uv run dmf --version", "exit_code": 0, "result": "dmf 0.1.0"}],
        "tests": [{"name": "pytest", "passed": 1}],
        "acceptance": [{"requirement": "version", "status": "PASS"}],
        "dependency_impact": "Approved dependencies only.",
        "migration_impact": "None.",
        "assumptions": [],
        "exclusions_verified": ["No domain code."],
        "risks": [],
        "review_pack": {
            "path": "review_pack/FND-001/DMF_PULSE_FND-001_REVIEW.zip",
            "file_count": 20,
            "sha256": "0" * 64,
        },
    }


@pytest.mark.unit
def test_canonical_json_has_independent_exact_bytes_and_hash() -> None:
    left = {"z": [3, 2, 1], "a": "£", "nested": {"b": True, "a": None}}
    right = {"nested": {"a": None, "b": True}, "a": "£", "z": [3, 2, 1]}
    expected = '{"a":"£","nested":{"a":null,"b":true},"z":[3,2,1]}'.encode()
    assert canonical_json_bytes(left) == expected
    assert canonical_json_bytes(right) == expected
    assert canonical_sha256(left) == canonical_sha256(right)


@pytest.mark.unit
def test_canonical_json_rejects_nan() -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": float("nan")})


@pytest.mark.unit
def test_result_file_detects_kind_and_strictly_validates(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text(json.dumps(_result()), encoding="utf-8")
    validated = validate_evidence_file(path)
    assert validated.kind is EvidenceKind.CODEX_RESULT
    assert validated.model.ticket_id == "FND-001"


@pytest.mark.unit
def test_schema_error_is_actionable_and_never_echoes_rejected_input() -> None:
    value = _result()
    raw = "secret-value-that-must-not-appear"
    value["unexpected"] = raw
    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence_data(value)
    rendered = repr(caught.value.as_error_object())
    assert caught.value.code == "EVIDENCE_SCHEMA_INVALID"
    assert raw not in rendered
    assert "unexpected" in rendered


@pytest.mark.unit
def test_machine_evidence_rejects_scalar_coercion() -> None:
    value = _result()
    commands = value["commands"]
    assert isinstance(commands, list)
    commands[0]["exit_code"] = "0"
    with pytest.raises(EvidenceValidationError):
        validate_evidence_data(value)

    with pytest.raises(ValueError):
        RepositoryState.model_validate(
            {
                "branch": "stage/A2/RUL-002-rules-foundation",
                "head": "a" * 40,
                "clean": "true",
                "pushed": 0,
                "merged": False,
            }
        )

    review = {
        "ticket_id": "FND-001",
        "generated_at": "2026-07-22T00:00:00Z",
        "repository_head": "a" * 40,
        "file_count": "1",
        "files": [],
        "acceptance_status": "BLOCKED",
    }
    with pytest.raises(ValueError):
        ReviewManifest.model_validate(review)


@pytest.mark.unit
def test_unknown_shape_and_invalid_json_have_exact_codes(tmp_path: Path) -> None:
    with pytest.raises(EvidenceValidationError) as unknown:
        validate_evidence_data({"ticket_id": "FND-001"})
    assert unknown.value.code == "EVIDENCE_TYPE_UNKNOWN"

    path = tmp_path / "bad.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(EvidenceValidationError) as invalid:
        validate_evidence_file(path)
    assert invalid.value.code == "EVIDENCE_JSON_INVALID"

    path.write_text('{"ticket_id":"FND-001","value":NaN}', encoding="utf-8")
    with pytest.raises(EvidenceValidationError) as non_finite:
        validate_evidence_file(path)
    assert non_finite.value.code == "EVIDENCE_JSON_INVALID"


@pytest.mark.unit
def test_review_manifest_rejects_duplicate_names() -> None:
    value = {
        "ticket_id": "FND-001",
        "generated_at": "2026-07-22T00:00:00Z",
        "repository_head": "a" * 40,
        "file_count": 2,
        "files": [
            {"name": "same.txt", "sha256": "0" * 64, "bytes": 1, "purpose": "one"},
            {"name": "same.txt", "sha256": "1" * 64, "bytes": 1, "purpose": "two"},
        ],
        "acceptance_status": "COMPLETE",
    }
    with pytest.raises(ValueError, match="duplicate"):
        ReviewManifest.model_validate(value)


@pytest.mark.unit
def test_ticket_and_review_evidence_kinds_and_object_requirement() -> None:
    ticket = {
        "ticket_id": "FND-001",
        "status": "DRAFT",
        "created_at": "2026-07-22T00:00:00Z",
        "commands": [],
        "artifacts": [],
    }
    assert validate_evidence_data(ticket).kind is EvidenceKind.TICKET_MANIFEST
    review = {
        "ticket_id": "FND-001",
        "generated_at": "2026-07-22T00:00:00Z",
        "repository_head": "a" * 40,
        "file_count": 1,
        "files": [],
        "acceptance_status": "BLOCKED",
    }
    assert validate_evidence_data(review).kind is EvidenceKind.REVIEW_MANIFEST
    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence_data([])
    assert caught.value.code == "EVIDENCE_OBJECT_REQUIRED"


@pytest.mark.unit
def test_evidence_file_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "small.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("dmf_pulse.assurance.evidence.MAX_EVIDENCE_BYTES", 1)
    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence_file(path)
    assert caught.value.code == "EVIDENCE_FILE_TOO_LARGE"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("schema_name", "model"),
    [
        ("codex_result.schema.json", CodexResult),
        ("evidence_manifest.schema.json", TicketEvidenceManifest),
        ("review_manifest.schema.json", ReviewManifest),
    ],
)
def test_checked_in_schema_surface_matches_pydantic_model(
    repository_root: Path, schema_name: str, model: type
) -> None:
    schema = json.loads(
        (repository_root / ".codex/schemas" / schema_name).read_text(encoding="utf-8")
    )
    assert schema == model.model_json_schema()


@pytest.mark.unit
def test_codex_result_schema_preserves_exact_legacy_fnd_complete_contract(
    repository_root: Path,
) -> None:
    historical = json.loads(
        (repository_root / "evidence/tickets/FND-001/codex_result.json").read_text(encoding="utf-8")
    )
    assert historical["ticket_id"] == "FND-001"
    assert historical["status"] == "COMPLETE"
    assert "code_commit" not in historical
    assert CodexResult.model_validate(historical).code_commit is None

    schema = CodexResult.model_json_schema()
    complete_gate = schema["allOf"][0]
    ticket_condition = complete_gate["if"]["properties"]["ticket_id"]
    assert ticket_condition == {"not": {"const": "FND-001"}}
    assert "code_commit" in complete_gate["then"]["required"]
