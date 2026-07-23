"""Immutable database registration of atomic RUL-002 activation bundles."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from dmf_pulse.data_model.errors import DataModelError
from dmf_pulse.data_model.repositories import RulesRegistryRepository, commit_session
from dmf_pulse.data_model.tables import ruleset_activation, ruleset_artifact
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.lifecycle import activate_ruleset
from dmf_pulse.rules.models import ApprovalRecord

pytestmark = pytest.mark.postgres


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _bundle(path: Path, repository_root: Path, *, approved_by: str = "DAT-003 test") -> Path:
    source = path / "source"
    shutil.copytree(repository_root / "fixtures/rules/RUL-002/synthetic_complete", source)
    season_manifest = source / "season_manifest.yaml"
    season_manifest.write_text(
        season_manifest.read_text(encoding="utf-8")
        .replace('status: "REFERENCE_ONLY"', 'status: "VERIFIED"')
        .replace("production_eligible: false", "production_eligible: true"),
        encoding="utf-8",
    )
    compiled = compile_ruleset(source)
    approval = ApprovalRecord(
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
        approved=True,
        approved_at="2026-07-23T12:00:00Z",
        approved_by=approved_by,
    )
    registry = path / "registry"
    activate_ruleset(compiled, approval, registry)
    return registry / compiled.ruleset_id / compiled.ruleset_version


def test_rules_registry_is_idempotent_and_rejects_conflicting_evidence(
    postgres_session_factory: sessionmaker[Session], tmp_path: Path, repository_root: Path
) -> None:
    activation_dir = _bundle(tmp_path / "active", repository_root)
    with postgres_session_factory() as session:
        repository = RulesRegistryRepository(session)
        first = repository.import_activation_bundle(activation_dir)
        assert repository.import_activation_bundle(activation_dir) == first
        commit_session(session)

    relocated = tmp_path / "relocated"
    shutil.copytree(activation_dir, relocated)
    with postgres_session_factory() as session:
        assert RulesRegistryRepository(session).import_activation_bundle(relocated) == first
        commit_session(session)

    with postgres_session_factory() as session:
        assert session.execute(select(func.count()).select_from(ruleset_artifact)).scalar_one() == 1
        assert (
            session.execute(select(func.count()).select_from(ruleset_activation)).scalar_one() == 1
        )

    conflicting_dir = _bundle(
        tmp_path / "conflict", repository_root, approved_by="different approver"
    )
    with postgres_session_factory() as session:
        with pytest.raises(DataModelError) as conflict:
            RulesRegistryRepository(session).import_activation_bundle(conflicting_dir)
        assert conflict.value.code == "RULESET_REGISTRY_INTEGRITY"


def test_rules_registry_rejects_incomplete_and_hash_mismatched_bundles(
    postgres_session_factory: sessionmaker[Session], tmp_path: Path, repository_root: Path
) -> None:
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    with postgres_session_factory() as session:
        with pytest.raises(DataModelError) as missing:
            RulesRegistryRepository(session).import_activation_bundle(incomplete)
        assert missing.value.code == "RULESET_REGISTRY_INTEGRITY"

    mismatched = _bundle(tmp_path / "mismatched", repository_root)
    (mismatched / "approval.json").write_text("{}", encoding="utf-8")
    with postgres_session_factory() as session:
        with pytest.raises(DataModelError) as bad_hash:
            RulesRegistryRepository(session).import_activation_bundle(mismatched)
        assert bad_hash.value.code == "RULESET_REGISTRY_INTEGRITY"

    cross_linked = _bundle(tmp_path / "cross-linked", repository_root)
    receipt_path = cross_linked / "activation_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["verified_ruleset_hash"] = "0" * 64
    receipt_path.write_bytes(_json_bytes(receipt))
    manifest_path = cross_linked / "activation_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["children"]["activation_receipt.json"]["sha256"] = hashlib.sha256(
        receipt_path.read_bytes()
    ).hexdigest()
    manifest_path.write_bytes(_json_bytes(manifest))
    with postgres_session_factory() as session:
        with pytest.raises(DataModelError) as linkage:
            RulesRegistryRepository(session).import_activation_bundle(cross_linked)
        assert linkage.value.code == "RULESET_REGISTRY_INTEGRITY"
