"""Schema v1.1, target-season player points, and capability governance regressions."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml

from dmf_pulse.rules.authoring import (
    ChipsFileV11,
    DeadlinesFileV11,
    LineupFileV11,
    PricesFileV11,
    TransfersFileV11,
)
from dmf_pulse.rules.bps import calculate_bps
from dmf_pulse.rules.capabilities import (
    compile_capability_artifact,
    interpretation_decision_hash,
    load_capability_artifact,
    write_capability_artifact,
)
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import (
    BpsEvents,
    DefensiveActions,
    FPLPosition,
    InterpretationDecision,
    PlayerScenario,
    RuleCapability,
)
from dmf_pulse.rules.yaml_loader import load_rules_yaml


def _target(repository_root: Path) -> Path:
    return repository_root / "fixtures/rules/RUL-002/target_2026_27_partial"


def _plain_goalkeeper(**updates: object) -> PlayerScenario:
    bps = BpsEvents.model_validate({name: 0 for name in BpsEvents.model_fields})
    value: dict[str, object] = {
        "player_id": "gk",
        "team_id": "A",
        "position": FPLPosition.GK,
        "minutes": 90,
        "goals_non_penalty": 0,
        "goals_penalty": 0,
        "eligible_assists": 0,
        "goals_conceded_while_eligible": 0,
        "saves": 0,
        "penalty_saves": 0,
        "penalty_misses": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "own_goals": 0,
        "defensive_actions": DefensiveActions(
            ball_recoveries=0, blocks=0, clearances=0, interceptions=0, tackles=0
        ),
        "bps": bps,
    }
    value.update(updates)
    return PlayerScenario.model_validate(value)


@pytest.fixture
def target_ruleset(repository_root: Path):
    return compile_ruleset(_target(repository_root))


@pytest.mark.unit
def test_v10_reference_and_synthetic_compile_with_identical_hashes(repository_root: Path) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    assert compile_ruleset(root / "reference_2025_26").ruleset_hash == (
        "12271ab0b32a461baa3778f2e914f45744ccf9d5302c37c4a5f2ffb89e0c1139"
    )
    assert compile_ruleset(root / "synthetic_complete").ruleset_hash == (
        "98e8614d9971ec2b1e45a357e89f79172bbc5dd4dc87044c3c131b3de6b0aab8"
    )


@pytest.mark.unit
def test_manager_state_schema_shapes_are_available_without_player_points_dependency() -> None:
    assert "automatic_substitutions" in LineupFileV11.model_fields
    assert set(TransfersFileV11.model_fields) == {"transition", "chip_interactions"}
    assert "selling_price" in PricesFileV11.model_fields
    assert "chips" in ChipsFileV11.model_fields
    assert "gameweek_finality" in DeadlinesFileV11.model_fields


@pytest.mark.unit
def test_2026_27_save_bps_events_stack_additively(target_ruleset) -> None:
    inside = _plain_goalkeeper(
        saves=1, bps=_plain_goalkeeper().bps.model_copy(update={"saves_inside_box": 1})
    )
    assert calculate_bps(target_ruleset, inside, clean_sheet_eligible=False, goals_conceded=0) == 9

    outside_big = _plain_goalkeeper(
        saves=1,
        bps=_plain_goalkeeper().bps.model_copy(
            update={"saves_outside_box": 1, "big_chance_saves": 1}
        ),
    )
    assert (
        calculate_bps(target_ruleset, outside_big, clean_sheet_eligible=False, goals_conceded=0)
        == 9
    )

    inside_big = _plain_goalkeeper(
        saves=1,
        bps=_plain_goalkeeper().bps.model_copy(
            update={"saves_inside_box": 1, "big_chance_saves": 1}
        ),
    )
    assert (
        calculate_bps(target_ruleset, inside_big, clean_sheet_eligible=False, goals_conceded=0)
        == 10
    )


@pytest.mark.unit
def test_penalty_save_composes_with_all_save_bps(target_ruleset) -> None:
    player = _plain_goalkeeper(
        saves=1,
        penalty_saves=1,
        bps=_plain_goalkeeper().bps.model_copy(
            update={"saves_inside_box": 1, "big_chance_saves": 1}
        ),
    )
    assert calculate_bps(target_ruleset, player, clean_sheet_eligible=False, goals_conceded=0) == 17


@pytest.mark.unit
def test_being_tackled_is_absent_and_cbi_groups_by_three(target_ruleset) -> None:
    tackled = _plain_goalkeeper(
        bps=_plain_goalkeeper().bps.model_copy(update={"times_tackled": 20})
    )
    assert calculate_bps(target_ruleset, tackled, clean_sheet_eligible=False, goals_conceded=0) == 6
    two = _plain_goalkeeper(
        defensive_actions=DefensiveActions(
            ball_recoveries=0, blocks=1, clearances=1, interceptions=0, tackles=0
        )
    )
    three = two.model_copy(
        update={
            "defensive_actions": DefensiveActions(
                ball_recoveries=0, blocks=1, clearances=1, interceptions=1, tackles=0
            )
        }
    )
    assert calculate_bps(target_ruleset, two, clean_sheet_eligible=False, goals_conceded=0) == 6
    assert calculate_bps(target_ruleset, three, clean_sheet_eligible=False, goals_conceded=0) == 7


@pytest.mark.unit
def test_assist_policy_and_rule_provenance_are_compiled(target_ruleset) -> None:
    policy = target_ruleset.rules["assists"]["eligibility_policy"]
    assert policy["defensive_touches"]["inside_box"] == {
        "intended_destination_required": False,
        "max_defensive_touches": 1,
    }
    assert policy["rebounds"]["scorer_own_rebound_disqualifies"] is True
    pointer = "/rules/bonus/bps/save_big_chance_additional"
    provenance = target_ruleset.rule_provenance[pointer]
    assert provenance.source_refs == ("SRC-FPL-2026-RULES-001", "SRC-FPL-2026-BPS-001")
    assert "big-chance saves" in provenance.sources[1].locator


@pytest.mark.unit
def test_player_points_dependency_closure_excludes_manager_state(target_ruleset) -> None:
    artifact = compile_capability_artifact(target_ruleset, RuleCapability.PLAYER_POINTS)
    assert artifact.source_backed
    assert artifact.ready_for_human_approval
    assert artifact.production_eligible
    assert artifact.blockers == ()
    assert artifact.rule_verification
    assert all("value" in record and record["sources"] for record in artifact.rule_verification)
    assert all(
        source["accessed_on"] == "2026-08-14"
        for record in artifact.rule_verification
        for source in record["sources"]
    )
    forbidden_paths = {
        "/rules/positions",
        "/rules/squad",
        "/rules/lineup",
        "/rules/transfers",
        "/rules/prices",
        "/rules/chips",
        "/rules/deadlines",
        "/rules/special_events",
    }
    forbidden_leaf_names = {"squad_quota", "lineup_min", "lineup_max", "bench"}
    assert not set(artifact.dependency_paths) & forbidden_paths

    def leaf_paths(value: object, path: str = "") -> set[str]:
        if isinstance(value, dict):
            return {
                item for key, child in value.items() for item in leaf_paths(child, f"{path}/{key}")
            }
        if isinstance(value, list):
            return {
                item
                for index, child in enumerate(value)
                for item in leaf_paths(child, f"{path}/{index}")
            }
        return {path}

    leaves = {
        leaf.rsplit("/", maxsplit=1)[-1]
        for selected in artifact.selected_rules.values()
        for leaf in leaf_paths(selected)
    }
    assert not leaves & forbidden_leaf_names
    assert (
        compile_capability_artifact(target_ruleset, RuleCapability.PLAYER_POINTS).capability_hash
        == artifact.capability_hash
    )


@pytest.mark.unit
def test_player_points_capability_artifact_is_canonical_and_deterministic(
    target_ruleset, tmp_path: Path
) -> None:
    artifact = compile_capability_artifact(target_ruleset, RuleCapability.PLAYER_POINTS)
    output = tmp_path / "player-points.json"
    write_capability_artifact(artifact, output)
    first = output.read_bytes()
    write_capability_artifact(
        compile_capability_artifact(target_ruleset, RuleCapability.PLAYER_POINTS), output
    )
    assert output.read_bytes() == first
    assert load_capability_artifact(output).capability_hash == artifact.capability_hash


@pytest.mark.unit
def test_full_season_remains_blocked_by_manager_state(target_ruleset) -> None:
    artifact = compile_capability_artifact(target_ruleset, RuleCapability.FULL_SEASON)
    assert not artifact.ready_for_human_approval
    assert not artifact.production_eligible
    assert any(blocker == "unknown:/rules/transfers" for blocker in artifact.blockers)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("capability", "expected_blocker"),
    (
        (RuleCapability.GW1_INITIAL_SQUAD, "unknown:/rules/squad"),
        (RuleCapability.TRANSFER_STATE, "unknown:/rules/transfers"),
        (RuleCapability.CHIP_STATE, "unknown:/rules/chips"),
        (RuleCapability.FULL_SEASON, "unknown:/rules/special_events"),
    ),
)
def test_manager_state_capabilities_remain_blocked(
    target_ruleset, capability, expected_blocker
) -> None:
    artifact = compile_capability_artifact(target_ruleset, capability)
    assert not artifact.production_eligible
    assert artifact.blockers
    assert expected_blocker in artifact.blockers
    assert "interpretation:INT-FPL-2026-BONUS-TIES-001:out_of_scope" not in artifact.blockers


@pytest.mark.unit
@pytest.mark.parametrize("rule_path", ["/rules/scoring", "/rules/bonus/bps", "/rules/assists"])
def test_player_points_refuses_unknown_required_rule(
    repository_root: Path, tmp_path: Path, rule_path: str
) -> None:
    target = tmp_path / "target"
    shutil.copytree(_target(repository_root), target)
    verification = load_rules_yaml(target / "rule_verification.yaml")
    record = next(item for item in verification["rules"] if item["rule_path"] == rule_path)
    record["verification_status"] = "UNKNOWN"
    (target / "rule_verification.yaml").write_text(
        yaml.safe_dump(verification, sort_keys=False), encoding="utf-8"
    )
    artifact = compile_capability_artifact(compile_ruleset(target), RuleCapability.PLAYER_POINTS)
    assert not artifact.ready_for_human_approval
    assert any(blocker.startswith("unknown:") for blocker in artifact.blockers)


@pytest.mark.unit
def test_capability_dependencies_cannot_be_weakened(repository_root: Path, tmp_path: Path) -> None:
    target = tmp_path / "target"
    shutil.copytree(_target(repository_root), target)
    capabilities = load_rules_yaml(target / "capabilities.yaml")
    capabilities["capabilities"]["PLAYER_POINTS"]["rule_paths"].remove("/rules/assists")
    (target / "capabilities.yaml").write_text(
        yaml.safe_dump(capabilities, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(RulesValidationError, match="dependencies"):
        compile_ruleset(target)


@pytest.mark.unit
def test_player_points_rejects_reintroduced_manager_state_dependency(
    repository_root: Path, tmp_path: Path
) -> None:
    target = tmp_path / "target"
    shutil.copytree(_target(repository_root), target)
    capabilities = load_rules_yaml(target / "capabilities.yaml")
    capabilities["capabilities"]["PLAYER_POINTS"]["rule_paths"].append("/rules/positions")
    (target / "capabilities.yaml").write_text(
        yaml.safe_dump(capabilities, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(RulesValidationError, match="dependencies"):
        compile_ruleset(target)


@pytest.mark.unit
def test_approved_interpretation_is_hash_bound_and_auditable(
    repository_root: Path, tmp_path: Path
) -> None:
    target = tmp_path / "target"
    shutil.copytree(_target(repository_root), target)
    interpretations = load_rules_yaml(target / "interpretations.yaml")
    compiled = compile_ruleset(target)
    artifact = compile_capability_artifact(compiled, RuleCapability.PLAYER_POINTS)
    assert artifact.production_eligible
    assert artifact.blockers == ()
    audited = artifact.interpretations[0]
    assert audited.approved_by == "Sebastian Greenhalgh"
    assert audited.approved_at == "2026-08-14T15:08:25Z"
    assert audited.scope == (RuleCapability.PLAYER_POINTS,)
    assert audited.meaning[-1] == "Expected-BPS ranking is prohibited."
    assert interpretation_decision_hash(audited) == audited.decision_hash

    interpretations["decisions"][0]["rationale"] = "Mutated after approval"
    (target / "interpretations.yaml").write_text(
        yaml.safe_dump(interpretations, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(RulesValidationError, match="decision hash"):
        compile_ruleset(target)


@pytest.mark.unit
def test_unapproved_interpretation_cannot_satisfy_capability(
    repository_root: Path, tmp_path: Path
) -> None:
    target = tmp_path / "target"
    shutil.copytree(_target(repository_root), target)
    interpretations = load_rules_yaml(target / "interpretations.yaml")
    raw = interpretations["decisions"][0]
    raw.update(approved=False, approved_by=None, approved_at=None)
    raw["decision_hash"] = interpretation_decision_hash(raw)
    verification = load_rules_yaml(target / "rule_verification.yaml")
    verification["rules"][-1]["interpretation_approval_states"] = {raw["decision_id"]: "UNAPPROVED"}
    (target / "rule_verification.yaml").write_text(
        yaml.safe_dump(verification, sort_keys=False), encoding="utf-8"
    )
    (target / "interpretations.yaml").write_text(
        yaml.safe_dump(interpretations, sort_keys=False), encoding="utf-8"
    )
    ruleset = compile_ruleset(target)
    decision = InterpretationDecision.model_validate(copy.deepcopy(raw))
    assert not decision.approved
    artifact = compile_capability_artifact(ruleset, RuleCapability.PLAYER_POINTS)
    assert not artifact.production_eligible
    assert artifact.blockers == ("interpretation:INT-FPL-2026-BONUS-TIES-001:unapproved",)


@pytest.mark.unit
def test_approved_interpretation_metadata_cannot_claim_unapproved(
    repository_root: Path, tmp_path: Path
) -> None:
    target = tmp_path / "target"
    shutil.copytree(_target(repository_root), target)
    verification = load_rules_yaml(target / "rule_verification.yaml")
    verification["rules"][-1]["interpretation_approval_states"] = {
        "INT-FPL-2026-BONUS-TIES-001": "UNAPPROVED"
    }
    (target / "rule_verification.yaml").write_text(
        yaml.safe_dump(verification, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(RulesValidationError, match="approval state"):
        compile_ruleset(target)
