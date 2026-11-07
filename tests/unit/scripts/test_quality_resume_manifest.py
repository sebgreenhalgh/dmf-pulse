"""Validate current continuation source without rewriting a sealed predecessor."""

from dmf_pulse.assurance.canonical import pretty_json
from dmf_pulse.assurance.manifests import build_repository_manifest
from tests.unit.scripts.script_support import load_script

validator = load_script("validate_repository")


def test_resume_manifest_supersedes_preserved_historical_snapshot(tmp_path):
    source = tmp_path / "owned.txt"
    source.write_text("first\n")
    evidence = tmp_path / "evidence/tickets/DMF-MODEL-QUALITY-001"
    evidence.mkdir(parents=True)
    original = evidence / "current_manifest.json"
    original.write_text(
        pretty_json(build_repository_manifest(tmp_path, ticket_id="DMF-MODEL-QUALITY-001"))
    )
    historical_bytes = original.read_bytes()
    source.write_text("second\n")
    errors = []
    validator._validate_current_manifest(tmp_path, errors)
    assert errors
    resume = evidence / "resume/current_manifest.json"
    resume.parent.mkdir()
    resume.write_text(
        pretty_json(build_repository_manifest(tmp_path, ticket_id="DMF-MODEL-QUALITY-001"))
    )
    errors = []
    validator._validate_current_manifest(tmp_path, errors)
    assert errors == []
    assert original.read_bytes() == historical_bytes
    source.write_text("unexpected mutation\n")
    validator._validate_current_manifest(tmp_path, errors)
    assert errors
    resume.write_text("{}")
    errors = []
    validator._validate_current_manifest(tmp_path, errors)
    assert any("malformed" in error for error in errors)
