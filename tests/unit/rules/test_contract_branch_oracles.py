"""Fail-closed rules branches required by the DAT-003 remediation coverage gate."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.rules import bps as bps_module
from dmf_pulse.rules import compiler as compiler_module
from dmf_pulse.rules import scoring as scoring_module
from dmf_pulse.rules.aggregation import score_gameweek
from dmf_pulse.rules.authoring import GameweekWindow, SpecialEvent, SpecialEventsFile
from dmf_pulse.rules.bonus import allocate_bonus
from dmf_pulse.rules.compiler import compile_ruleset
from dmf_pulse.rules.errors import RulesIntegrityError, RulesValidationError
from dmf_pulse.rules.lifecycle import activate_ruleset
from dmf_pulse.rules.models import (
    ApprovalRecord,
    FixtureScenario,
    GameweekScenario,
    GameweekScoreResult,
    RuleProvenance,
    RuleSourceReference,
    UnknownRule,
)


@pytest.mark.unit
def test_authoring_and_provenance_models_reject_ambiguous_values() -> None:
    with pytest.raises(ValidationError, match="cannot precede"):
        GameweekWindow(start_gameweek=2, end_gameweek=1)
    event = SpecialEvent(
        event_id="EVENT_ONE",
        effective_gameweeks=GameweekWindow(start_gameweek=1, end_gameweek=1),
        operation="RECORD_ONLY",
        parameters={},
    )
    with pytest.raises(ValidationError, match="must be unique"):
        SpecialEventsFile(events=(event, event))
    with pytest.raises(ValidationError, match="must be unique"):
        UnknownRule(
            verification_status="UNKNOWN",
            value=None,
            source_refs=("SRC-ONE", "SRC-ONE"),
        )

    source = RuleSourceReference(
        source_id="SRC-ONE",
        locator="synthetic contract oracle",
        verification_status="VERIFIED",
        refresh_trigger="on contract change",
    )
    with pytest.raises(ValidationError, match="must be unique"):
        RuleProvenance(
            rule_id="FPL-TEST",
            source_refs=("SRC-ONE", "SRC-ONE"),
            sources=(source, source),
        )
    with pytest.raises(ValidationError, match="match source_refs"):
        RuleProvenance(
            rule_id="FPL-TEST",
            source_refs=("SRC-OTHER",),
            sources=(source,),
        )


@pytest.mark.unit
def test_bonus_pass_and_scoring_configuration_fail_closed(
    repository_root: Path,
) -> None:
    with pytest.raises(ValueError, match="positive integers"):
        allocate_bonus({"player": 1}, {True: 3})

    root = repository_root / "fixtures/rules/RUL-002"
    ruleset = compile_ruleset(root / "synthetic_complete")
    raw_fixture = (root / "golden_fixture_001.json").read_bytes()
    fixture = FixtureScenario.model_validate_json(raw_fixture)
    player = fixture.players[0].model_copy(
        update={
            "bps": fixture.players[0].bps.model_copy(
                update={"pass_attempts": 100, "passes_completed": 100}
            )
        }
    )
    pass_config: dict[str, object] = {
        "pass_completion": {
            "min_attempts": 1,
            "bands": [
                {"min_pct_inclusive": 0, "max_pct_inclusive": 100, "bps": 1},
                {"min_pct_inclusive": 0, "max_pct_inclusive": 100, "bps": 2},
            ],
        }
    }
    with pytest.raises(RulesIntegrityError) as overlapping:
        bps_module._pass_bps(pass_config, player)
    assert overlapping.value.code == "RULESET_PASS_BANDS"

    changed = ruleset.model_copy(deep=True)
    changed.rules["bonus"]["bonus_points_by_competition_rank"] = {"zero": 3}
    with pytest.raises(RulesIntegrityError) as rank:
        scoring_module._bonus_rank_awards(changed)
    assert rank.value.code == "RULESET_BONUS_RANK_INVALID"
    changed.rules["bonus"]["bonus_points_by_competition_rank"] = {"1": -1}
    with pytest.raises(RulesIntegrityError) as award:
        scoring_module._bonus_rank_awards(changed)
    assert award.value.code == "RULESET_BONUS_RANK_INVALID"
    with pytest.raises(RulesIntegrityError) as event:
        scoring_module._defensive_contribution(
            player,
            {
                "by_position": {
                    player.position.value: {
                        "enabled": True,
                        "event_types": ["UNSUPPORTED"],
                    }
                }
            },
        )
    assert event.value.code == "RULESET_DEFENSIVE_EVENTS"


@pytest.mark.unit
def test_compiler_provenance_shape_and_collision_oracles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(RulesValidationError) as no_manifest:
        compiler_module._build_rule_provenance({"scoring": {"points": 1}})
    assert no_manifest.value.code == "RULESET_SOURCE_INVALID"
    with pytest.raises(RulesValidationError) as malformed_manifest:
        compiler_module._build_rule_provenance(
            {"source_manifest": {"sources": "invalid"}, "scoring": {"points": 1}}
        )
    assert malformed_manifest.value.code == "RULESET_SOURCE_INVALID"
    with pytest.raises(RulesValidationError) as malformed_source:
        compiler_module._build_rule_provenance(
            {"source_manifest": {"sources": ["invalid"]}, "scoring": {"points": 1}}
        )
    assert malformed_source.value.code == "RULESET_SOURCE_INVALID"

    manifest = {
        "sources": [
            {
                "source_id": "SRC-ONE",
                "locator": "synthetic contract oracle",
                "status": "VERIFIED",
                "refresh_trigger": "on contract change",
            }
        ],
        "rule_source_default": None,
    }
    with pytest.raises(RulesValidationError) as unreferenced:
        compiler_module._build_rule_provenance(
            {"source_manifest": manifest, "scoring": {"points": 1}}
        )
    assert unreferenced.value.code == "RULESET_SOURCE_REFERENCE"
    with pytest.raises(RulesValidationError) as missing:
        compiler_module._build_rule_provenance(
            {
                "source_manifest": manifest,
                "scoring": {"points": 1, "source_refs": ["SRC-MISSING"]},
            }
        )
    assert missing.value.code == "RULESET_SOURCE_REFERENCE"

    assert "/rules/scoring/points" in compiler_module._build_rule_provenance(
        {
            "source_manifest": manifest,
            "scoring": {"points": 1, "source_refs": ["SRC-ONE"]},
        }
    )

    manifest["rule_source_default"] = "SRC-ONE"
    monkeypatch.setattr(compiler_module, "_rule_id", lambda _pointer, _tokens: "FPL-COLLISION")
    with pytest.raises(RulesValidationError) as collision:
        compiler_module._build_rule_provenance(
            {"source_manifest": manifest, "scoring": {"one": 1, "two": 2}}
        )
    assert collision.value.code == "RULESET_RULE_ID_COLLISION"

    monkeypatch.setattr(Path, "read_bytes", lambda _path: (_ for _ in ()).throw(OSError()))
    with pytest.raises(RulesValidationError) as unavailable:
        compiler_module._read_source(tmp_path / "missing.yaml")
    assert unavailable.value.code == "RULESET_FILE_UNAVAILABLE"


@pytest.mark.unit
def test_declarative_blocker_shape_is_deterministic() -> None:
    blockers = compiler_module._declarative_execution_blockers(
        {
            "chips.yaml": {"chips": ["invalid", {"effects": [{"operation": "record"}]}]},
            "special_events.yaml": {"events": [{"event_id": "event"}]},
        }
    )
    assert blockers == [
        "unimplemented:chips[1].effects[0]",
        "unimplemented:special_events.events[0]",
    ]


@pytest.mark.unit
def test_gameweek_result_rejects_every_aggregate_false_success(repository_root: Path) -> None:
    root = repository_root / "fixtures/rules/RUL-002"
    ruleset = compile_ruleset(root / "synthetic_complete")
    fixture = FixtureScenario.model_validate_json((root / "golden_fixture_001.json").read_bytes())
    scenario = GameweekScenario(
        gameweek_id=fixture.gameweek_id,
        fixtures=(
            fixture.model_copy(update={"fixture_id": "fixture-z"}),
            fixture.model_copy(update={"fixture_id": "fixture-a"}),
        ),
    )
    valid = score_gameweek(ruleset, scenario).model_dump(mode="json")

    mutations = []
    wrong_ids = copy.deepcopy(valid)
    wrong_ids["fixture_ids"][0] = "wrong"
    mutations.append(wrong_ids)
    unsorted = copy.deepcopy(valid)
    unsorted["fixture_ids"].reverse()
    unsorted["fixture_results"].reverse()
    mutations.append(unsorted)
    wrong_identity = copy.deepcopy(valid)
    wrong_identity["fixture_results"][0]["ruleset_id"] = "wrong"
    mutations.append(wrong_identity)
    wrong_players = copy.deepcopy(valid)
    wrong_players["players"] = {}
    mutations.append(wrong_players)
    wrong_totals = copy.deepcopy(valid)
    wrong_totals["player_totals"] = {}
    mutations.append(wrong_totals)
    for mutation in mutations:
        with pytest.raises(ValidationError):
            GameweekScoreResult.model_validate(mutation)


def _verified(repository_root: Path, temporary: Path):
    source = temporary / "verified-source"
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
def test_activation_existing_artifact_checks_fail_closed(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compiled = _verified(repository_root, tmp_path)
    approval = ApprovalRecord(
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        ruleset_hash=compiled.ruleset_hash,
        approved=True,
        approved_at="2026-07-22T12:00:00Z",
        approved_by="contract-oracle",
    )
    registry = tmp_path / "registry"
    destination = registry / compiled.ruleset_id / compiled.ruleset_version
    destination.parent.mkdir(parents=True)
    destination.write_text("not a directory", encoding="utf-8")
    with pytest.raises(RulesIntegrityError) as not_directory:
        activate_ruleset(compiled, approval, registry)
    assert not_directory.value.code == "RULESET_ACTIVE_COLLISION"

    destination.unlink()
    destination.mkdir()
    (destination / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RulesIntegrityError) as wrong_files:
        activate_ruleset(compiled, approval, registry)
    assert wrong_files.value.code == "RULESET_ACTIVE_COLLISION"

    shutil.rmtree(destination)
    activate_ruleset(compiled, approval, registry)
    original = Path.read_bytes

    def fail_activation_read(path: Path) -> bytes:
        if path.parent == destination:
            raise OSError("constructed read failure")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", fail_activation_read)
    with pytest.raises(RulesIntegrityError) as unreadable:
        activate_ruleset(compiled, approval, registry)
    assert unreadable.value.code == "RULESET_ACTIVE_COLLISION"
