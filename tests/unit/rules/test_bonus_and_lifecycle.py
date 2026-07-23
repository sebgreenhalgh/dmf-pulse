"""Generic bonus ties and fail-closed immutable activation."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from dmf_pulse.rules.bonus import allocate_bonus
from dmf_pulse.rules.compiler import compile_ruleset, load_compiled_ruleset
from dmf_pulse.rules.errors import RulesActivationError, RulesIntegrityError
from dmf_pulse.rules.lifecycle import activate_ruleset
from dmf_pulse.rules.models import ApprovalRecord, CompiledRuleset, FixtureScenario, RulesetStatus
from dmf_pulse.rules.scoring import score_fixture


@pytest.mark.unit
def test_all_supplied_competition_ranking_oracles(repository_root: Path) -> None:
    value = json.loads(
        (repository_root / "fixtures/rules/RUL-002/bonus_tie_cases.json").read_text("utf-8")
    )
    for case in value["cases"]:
        assert allocate_bonus(case["bps"], {1: 3, 2: 2, 3: 1}) == case["expected"], case["id"]


@pytest.mark.unit
def test_nonstandard_bonus_policy_drives_generic_ranking() -> None:
    assert allocate_bonus({"alpha": 10, "beta": 9, "gamma": 8}, {1: 5, 2: 3, 3: 2}) == {
        "alpha": 5,
        "beta": 3,
        "gamma": 2,
    }


@pytest.mark.unit
def test_compiled_nonstandard_bonus_policy_drives_fixture_scoring(
    repository_root: Path, tmp_path: Path
) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    source = tmp_path / "nonstandard-bonus"
    shutil.copytree(root / "synthetic_complete", source)
    bonus = source / "bonus.yaml"
    bonus.write_text(
        bonus.read_text("utf-8").replace('{"1": 3, "2": 2, "3": 1}', '{"1": 5, "2": 3, "3": 2}'),
        encoding="utf-8",
    )
    ruleset = compile_ruleset(source)
    scenario = FixtureScenario.model_validate_json((root / "golden_fixture_001.json").read_bytes())
    assert score_fixture(ruleset, scenario).players["home-fwd"].bonus == 5


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
    activation_dir = registry / compiled.ruleset_id / compiled.ruleset_version
    active = load_compiled_ruleset(activation_dir / "active_ruleset.json")
    assert active.status is RulesetStatus.ACTIVE
    assert active.ruleset_hash == receipt.ruleset_hash
    assert activate_ruleset(compiled, approval, registry) == receipt
    assert {path.name for path in activation_dir.iterdir()} == {
        "verified_ruleset.json",
        "active_ruleset.json",
        "approval.json",
        "activation_receipt.json",
        "activation_manifest.json",
    }
    manifest = json.loads((activation_dir / "activation_manifest.json").read_text("utf-8"))
    assert manifest["ruleset_id"] == compiled.ruleset_id
    assert manifest["ruleset_version"] == compiled.ruleset_version
    assert set(manifest["children"]) == {
        "verified_ruleset.json",
        "active_ruleset.json",
        "approval.json",
        "activation_receipt.json",
    }
    for filename, record in manifest["children"].items():
        assert (
            hashlib.sha256((activation_dir / filename).read_bytes()).hexdigest() == record["sha256"]
        )
        assert record["ruleset_id"] == compiled.ruleset_id
        assert record["ruleset_version"] == compiled.ruleset_version
    different_approval = approval.model_copy(update={"approved_by": "different-approver"})
    with pytest.raises(RulesIntegrityError) as collision:
        activate_ruleset(compiled, different_approval, registry)
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
