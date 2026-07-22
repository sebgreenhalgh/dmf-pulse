"""Complete decision-index and minimum stage-authority contracts."""

from __future__ import annotations

import hashlib
import json
import runpy
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest


@pytest.mark.integration
def test_complete_decision_index_and_every_required_scope(repository_root: Path) -> None:
    manifests = repository_root / "specs/manifests"
    decision_manifest = json.loads((manifests / "decision_manifest.json").read_text("utf-8"))
    authority = json.loads((manifests / "authority_manifest.json").read_text("utf-8"))
    requirements = json.loads((manifests / "stage_authority_requirements.json").read_text("utf-8"))
    assert (
        hashlib.sha256((manifests / "stage_authority_requirements.json").read_bytes()).hexdigest()
        == "d26605207bec6650f1452836c9fde2e627e6eccc1a8ba3dc30eb56c8e026dae2"
    )
    source_path = repository_root / decision_manifest["generated_from"]["path"]
    assert (
        hashlib.sha256(source_path.read_bytes()).hexdigest()
        == decision_manifest["generated_from"]["sha256"]
    )
    decisions = decision_manifest["decisions"]
    assert len(decisions) == 94
    assert len({item["id"] for item in decisions}) == 94
    assert all(item["title"] and item["summary"] and item["decision_sha256"] for item in decisions)
    assert {item["status"] for item in decisions} >= {"ACCEPTED", "PROVISIONAL"}
    assert authority["precedence"] == requirements["precedence"]
    active = {item["scope"]: item for item in authority["scopes"]}
    for scope, minimum in requirements["required_scopes"].items():
        assert set(active[scope]["documents"]) >= set(minimum["documents"])
        assert set(active[scope]["decisions"]) >= set(minimum["decisions"])

    agents = (repository_root / "AGENTS.md").read_text("utf-8")
    authority_section = agents.split("## Authority", maxsplit=1)[1].split("\n## ", maxsplit=1)[0]
    assert [
        line[3:-1]
        for line in authority_section.splitlines()
        if len(line) > 3 and line[0] in "123456" and line[1:3] == ". "
    ] == requirements["precedence"]
    assert requirements["ticket_policy"] in agents


@pytest.mark.integration
def test_validator_rejects_coordinated_authority_and_decision_tampering(
    repository_root: Path, tmp_path: Path
) -> None:
    fixture = tmp_path / "authority"
    fixture.mkdir()
    shutil.copytree(repository_root / "specs", fixture / "specs")
    shutil.copytree(repository_root / "docs/implementation", fixture / "docs/implementation")
    shutil.copytree(repository_root / "tickets", fixture / "tickets")
    shutil.copy2(repository_root / "AGENTS.md", fixture / "AGENTS.md")
    (fixture / "evidence/tickets/FND-001").mkdir(parents=True)
    shutil.copy2(
        repository_root / "evidence/tickets/FND-001/baseline_manifest.json",
        fixture / "evidence/tickets/FND-001/baseline_manifest.json",
    )
    namespace = runpy.run_path(str(repository_root / "scripts/validate_repository.py"))
    validate = cast(Callable[[Path], list[str]], namespace["validate_repository"])
    assert validate(fixture) == []

    requirements_path = fixture / "specs/manifests/stage_authority_requirements.json"
    requirements = json.loads(requirements_path.read_text("utf-8"))
    requirements["required_scopes"]["A2-rules"]["documents"].remove("DMFP-13")
    requirements_path.write_text(json.dumps(requirements), encoding="utf-8")
    authority_path = fixture / "specs/manifests/authority_manifest.json"
    authority = json.loads(authority_path.read_text("utf-8"))
    next(item for item in authority["scopes"] if item["scope"] == "A2-rules")["documents"].remove(
        "DMFP-13"
    )
    authority_path.write_text(json.dumps(authority), encoding="utf-8")
    assert any("pinned v1.1 stage contract" in error for error in validate(fixture))

    shutil.copy2(
        repository_root / "specs/manifests/stage_authority_requirements.json",
        requirements_path,
    )
    shutil.copy2(repository_root / "specs/manifests/authority_manifest.json", authority_path)
    decision_path = fixture / "specs/manifests/decision_manifest.json"
    decision = json.loads(decision_path.read_text("utf-8"))
    decision["decisions"][0]["summary"] = "plausible but substituted decision text"
    decision["decisions"][0]["decision_sha256"] = hashlib.sha256(
        decision["decisions"][0]["summary"].encode()
    ).hexdigest()
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    assert any("exactly match deterministic" in error for error in validate(fixture))
