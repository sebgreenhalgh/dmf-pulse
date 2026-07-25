"""Strict specification-manifest validation and CLI failure tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import dmf_pulse.cli.specs_cmd as specs_cmd_module
from dmf_pulse.assurance.specs import (
    APPROVED_DMFP04,
    FrozenInputValidationError,
    SpecValidationError,
    validate_specifications,
)
from dmf_pulse.cli.app import app

pytestmark = pytest.mark.unit


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _valid_root(root: Path) -> dict[str, Any]:
    approved = b"1.0 approved zero-cost source contract\n"
    approved_path = root / "specs/approved" / APPROVED_DMFP04
    approved_path.parent.mkdir(parents=True)
    approved_path.write_bytes(approved)
    document = {
        "document_id": "DMFP-04",
        "filename": APPROVED_DMFP04,
        "version": "1.0 approved",
        "status": "APPROVED",
        "bytes": len(approved),
        "sha256": _sha(approved),
    }
    decision = {
        "id": "ADR-SRC-001",
        "status": "ACCEPTED",
        "source": {
            "path": f"specs/approved/{APPROVED_DMFP04}",
            "document_sha256": _sha(approved),
        },
    }
    scope = {
        "scope": "A4-FPL-ingestion",
        "documents": ["DMFP-04"],
        "decisions": ["ADR-SRC-001"],
    }
    values: dict[str, Any] = {
        "document_manifest.json": {"documents": [document]},
        "decision_manifest.json": {"decisions": [decision]},
        "authority_manifest.json": {"scopes": [scope]},
        "stage_authority_requirements.json": {
            "required_scopes": {
                "A4-FPL-ingestion": {
                    "documents": ["DMFP-04"],
                    "decisions": ["ADR-SRC-001"],
                }
            }
        },
    }
    for name, value in values.items():
        _write_json(root / "specs/manifests" / name, value)
    return values


def _persist(root: Path, values: dict[str, Any]) -> None:
    for name, value in values.items():
        _write_json(root / "specs/manifests" / name, value)


def _errors(root: Path) -> tuple[str, ...]:
    with pytest.raises(SpecValidationError) as caught:
        validate_specifications(root)
    assert caught.value.as_error_object()["error"]["code"] == "SPEC_MANIFEST_INVALID"  # type: ignore[index]
    return caught.value.errors


def test_current_repository_specifications_are_valid(repository_root: Path) -> None:
    report = validate_specifications(repository_root)
    assert report == {
        "decision_count": 94,
        "document_count": 22,
        "ok": True,
        "scope_count": 19,
    }


def test_minimal_authority_graph_is_valid(tmp_path: Path) -> None:
    _valid_root(tmp_path)
    assert validate_specifications(tmp_path)["ok"] is True


Mutation = Callable[[Path, dict[str, Any]], None]


def _document_fault(field: str, value: object) -> Mutation:
    def mutate(_root: Path, values: dict[str, Any]) -> None:
        values["document_manifest.json"]["documents"][0][field] = value

    return mutate


def _decision_fault(field: str, value: object) -> Mutation:
    def mutate(_root: Path, values: dict[str, Any]) -> None:
        values["decision_manifest.json"]["decisions"][0][field] = value

    return mutate


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda _r, v: v.update({"document_manifest.json": []}), "root must be an object"),
        (lambda _r, v: v["document_manifest.json"].update(documents={}), "must be an array"),
        (lambda _r, v: v["document_manifest.json"].update(documents=[None]), "must be an object"),
        (_document_fault("document_id", ""), "invalid document_id"),
        (
            lambda _r, v: v["document_manifest.json"]["documents"].append(
                dict(v["document_manifest.json"]["documents"][0])
            ),
            "duplicate document_id",
        ),
        (_document_fault("filename", "../escape.txt"), "invalid filename"),
        (_document_fault("filename", "paid_provider_DMFP-04.txt"), "paid or obsolete DMFP-04"),
        (_document_fault("version", "draft"), "malformed version"),
        (_document_fault("status", ""), "malformed status"),
        (_document_fault("bytes", 1), "byte count mismatch"),
        (_document_fault("sha256", "bad"), "malformed SHA-256"),
        (_document_fault("sha256", "0" * 64), "SHA-256 mismatch"),
        (
            lambda r, _v: (r / "specs/approved" / APPROVED_DMFP04).unlink(),
            "installed file is missing",
        ),
        (lambda _r, v: v.update({"decision_manifest.json": []}), "root must be an object"),
        (lambda _r, v: v["decision_manifest.json"].update(decisions={}), "must be an array"),
        (lambda _r, v: v["decision_manifest.json"].update(decisions=[None]), "must be an object"),
        (_decision_fault("id", ""), "invalid decision ID"),
        (
            lambda _r, v: v["decision_manifest.json"]["decisions"].append(
                dict(v["decision_manifest.json"]["decisions"][0])
            ),
            "duplicate decision ID",
        ),
        (_decision_fault("status", "INVENTED"), "malformed status"),
        (_decision_fault("source", None), "source must be an object"),
        (
            lambda _r, v: v["decision_manifest.json"]["decisions"][0]["source"].update(
                path="specs/approved/missing.txt"
            ),
            "stale source path",
        ),
        (
            lambda _r, v: v["decision_manifest.json"]["decisions"][0]["source"].update(
                document_sha256="0" * 64
            ),
            "stale source hash",
        ),
        (lambda _r, v: v.update({"authority_manifest.json": []}), "root must be an object"),
        (lambda _r, v: v["authority_manifest.json"].update(scopes={}), "must be an array"),
        (lambda _r, v: v["authority_manifest.json"].update(scopes=[None]), "malformed scope"),
        (
            lambda _r, v: v["authority_manifest.json"]["scopes"].append(
                dict(v["authority_manifest.json"]["scopes"][0])
            ),
            "duplicate scope",
        ),
        (
            lambda _r, v: v["authority_manifest.json"]["scopes"][0].update(documents=[1]),
            "documents must be string IDs",
        ),
        (
            lambda _r, v: v["authority_manifest.json"]["scopes"][0].update(decisions=[1]),
            "decisions must be string IDs",
        ),
        (
            lambda _r, v: v["authority_manifest.json"]["scopes"][0].update(
                documents=["DMFP-MISSING"]
            ),
            "stale documents",
        ),
        (
            lambda _r, v: v["authority_manifest.json"]["scopes"][0].update(
                decisions=["ADR-MISSING"]
            ),
            "stale decisions",
        ),
        (
            lambda _r, v: v.update({"stage_authority_requirements.json": []}),
            "root must be an object",
        ),
        (
            lambda _r, v: v["stage_authority_requirements.json"].update(required_scopes=[]),
            "must be an object",
        ),
        (
            lambda _r, v: v["stage_authority_requirements.json"]["required_scopes"].update(
                stale={}
            ),
            "stale scope stale",
        ),
        (
            lambda _r, v: v["stage_authority_requirements.json"]["required_scopes"][
                "A4-FPL-ingestion"
            ].update(documents=[]),
            "document mismatch",
        ),
        (
            lambda _r, v: v["stage_authority_requirements.json"]["required_scopes"][
                "A4-FPL-ingestion"
            ].update(decisions=[]),
            "decision mismatch",
        ),
        (
            lambda _r, v: v["authority_manifest.json"].update(scopes=[]),
            "A4-FPL-ingestion scope is missing",
        ),
    ],
)
def test_manifest_faults_are_actionable(tmp_path: Path, mutate: Mutation, expected: str) -> None:
    values = _valid_root(tmp_path)
    mutate(tmp_path, values)
    _persist(tmp_path, values)
    assert any(expected in error for error in _errors(tmp_path))


def test_duplicate_filename_and_playbook_install_location_are_checked(tmp_path: Path) -> None:
    values = _valid_root(tmp_path)
    playbook = b"1.0 implementation playbook\n"
    path = tmp_path / "docs/implementation/playbook.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(playbook)
    values["document_manifest.json"]["documents"].append(
        {
            "document_id": "DMF-PULSE-CODEX-PLAYBOOK",
            "filename": APPROVED_DMFP04,
            "version": "1.0",
            "status": "APPROVED",
            "bytes": len(playbook),
            "sha256": _sha(playbook),
        }
    )
    _persist(tmp_path, values)
    errors = _errors(tmp_path)
    assert any("duplicate filename" in item for item in errors)
    assert any("installed file is missing" in item for item in errors)


def test_cli_reports_structured_specification_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _valid_root(tmp_path)
    (tmp_path / "specs/manifests/document_manifest.json").write_text("{", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["specs", "validate"])
    assert result.exit_code == 21
    value = json.loads(result.stdout)
    assert value["ok"] is False
    assert value["error"]["code"] == "SPEC_MANIFEST_INVALID"


def test_cli_enforces_fpl004_frozen_input_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_frozen_inputs(_root: Path) -> dict[str, object]:
        raise FrozenInputValidationError(["fixtures/manifest.json: frozen SHA-256 mismatch"])

    monkeypatch.setattr(
        specs_cmd_module,
        "validate_fpl004_frozen_inputs",
        fail_frozen_inputs,
    )
    result = CliRunner().invoke(app, ["specs", "validate"])
    assert result.exit_code == 21
    value = json.loads(result.stdout)
    assert value["ok"] is False
    assert value["error"]["code"] == "SPEC_MANIFEST_INVALID"
    assert "frozen SHA-256 mismatch" in value["error"]["details"][0]
