"""Generic bonus ties and fail-closed immutable activation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dmf_pulse.rules.bonus import allocate_bonus
from dmf_pulse.rules.compiler import compile_ruleset, load_compiled_ruleset
from dmf_pulse.rules.errors import RulesActivationError, RulesIntegrityError
from dmf_pulse.rules.lifecycle import activate_ruleset
from dmf_pulse.rules.models import ApprovalRecord, CompiledRuleset, RulesetStatus


@pytest.mark.unit
def test_all_supplied_competition_ranking_oracles(repository_root: Path) -> None:
    value = json.loads(
        (repository_root / "fixtures/rules/RUL-002/bonus_tie_cases.json").read_text("utf-8")
    )
    for case in value["cases"]:
        assert allocate_bonus(case["bps"]) == case["expected"], case["id"]


@pytest.mark.unit
def test_target_activation_is_blocked_with_exact_code(repository_root: Path) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    target = compile_ruleset(root / "target_2026_27_partial")
    approval = ApprovalRecord.model_validate_json(
        (root / "invalid_target_approval.json").read_bytes()
    )
    with pytest.raises(RulesActivationError) as caught:
        activate_ruleset(target, approval, repository_root / "artifacts/never-written")
    assert caught.value.code == "RULESET_ACTIVATION_BLOCKED"
    assert "production_eligible:false" in caught.value.blockers
    assert not (repository_root / "artifacts/never-written").exists()


def _verified(repository_root: Path, destination: Path) -> CompiledRuleset:
    source = destination / "verified-source"
    shutil.copytree(repository_root / "fixtures/rules/RUL-002/synthetic_complete", source)
    manifest = source / "season_manifest.yaml"
    manifest.write_text(
        manifest.read_text("utf-8")
        .replace('status: "REFERENCE_ONLY"', 'status: "VERIFIED"')
        .replace("production_eligible: false", "production_eligible: true"),
        encoding="utf-8",
    )
    return compile_ruleset(source)


@pytest.mark.unit
def test_verified_activation_publishes_once_and_is_self_consistent(
    repository_root: Path, tmp_path: Path
) -> None:
    compiled = _verified(repository_root, tmp_path)
    approval = ApprovalRecord(
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
        approved=True,
        approved_at="2026-07-22T12:00:00Z",
        approved_by="fixture-approver",
    )
    registry = tmp_path / "registry"
    receipt = activate_ruleset(compiled, approval, registry)
    active = load_compiled_ruleset(
        registry / compiled.ruleset_id / f"{compiled.ruleset_version}.json"
    )
    assert active.status is RulesetStatus.ACTIVE
    assert active.ruleset_hash == receipt.ruleset_hash
    with pytest.raises(RulesIntegrityError) as collision:
        activate_ruleset(compiled, approval, registry)
    assert collision.value.code == "RULESET_ACTIVE_COLLISION"


@pytest.mark.unit
def test_approval_identity_and_provenance_fail_closed(
    repository_root: Path, tmp_path: Path
) -> None:
    compiled = _verified(repository_root, tmp_path)
    bad = ApprovalRecord(
        ruleset_id="other-ruleset",
        ruleset_version=compiled.ruleset_version,
        ruleset_hash="0" * 64,
        approved=True,
        approved_at=None,
        approved_by=None,
    )
    with pytest.raises(RulesActivationError) as caught:
        activate_ruleset(compiled, bad, tmp_path / "registry")
    assert set(caught.value.blockers) >= {
        "approval:hash_mismatch",
        "approval:identity_mismatch",
        "approval:provenance_missing",
    }

    malformed = ApprovalRecord(
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=None,
        approved=False,
        approved_at="not-a-time",
        approved_by=" ",
    )
    with pytest.raises(RulesActivationError) as invalid:
        activate_ruleset(compiled, malformed, tmp_path / "registry")
    assert set(invalid.value.blockers) >= {
        "approval:false",
        "approval:hash_mismatch",
        "approval:provenance_invalid",
    }
