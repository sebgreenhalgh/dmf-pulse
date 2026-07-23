"""Mutation probes for every semantic split-YAML authoring boundary."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.rules.authoring import (
    AppearanceRules,
    BpsAppearanceBand,
    BpsRules,
    ChipsFile,
    CleanSheetRules,
    DeadlinesFile,
    DefensivePositionRule,
    FinalityClaim,
    GoalsConcededRules,
    PassBand,
    PassCompletionRules,
    PositionRule,
    SpecialEventsFile,
    TargetClaimsFile,
    validate_and_normalize_authoring_data,
)
from dmf_pulse.rules.compiler import REQUIRED_FILES
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import SeasonManifest
from dmf_pulse.rules.yaml_loader import load_rules_yaml


def _authoring_data(root: Path) -> tuple[SeasonManifest, dict[str, dict[str, object]]]:
    manifest = SeasonManifest.model_validate(load_rules_yaml(root / "season_manifest.yaml"))
    names = set(REQUIRED_FILES) | set(manifest.extension_files)
    return manifest, {name: load_rules_yaml(root / name) for name in names}


@pytest.mark.unit
def test_nested_authoring_invariants_kill_boundary_mutants(repository_root: Path) -> None:
    root = repository_root / "fixtures/rules/RUL-002/synthetic_complete"
    _, data = _authoring_data(root)

    position = copy.deepcopy(data["positions.yaml"]["positions"]["GK"])
    position["lineup_max"] = 3
    with pytest.raises(ValidationError, match="lineup bounds"):
        PositionRule.model_validate(position)

    appearance = copy.deepcopy(data["scoring.yaml"]["appearance"])
    appearance["bands"][1]["id"] = "SHORT"
    with pytest.raises(ValidationError, match="IDs must be unique"):
        AppearanceRules.model_validate(appearance)
    appearance = copy.deepcopy(data["scoring.yaml"]["appearance"])
    appearance["bands"][0]["max_exclusive"] = 59
    with pytest.raises(ValidationError, match="total and mutually exclusive"):
        AppearanceRules.model_validate(appearance)

    defensive = copy.deepcopy(data["scoring.yaml"]["defensive_contributions"]["by_position"]["DEF"])
    defensive["event_types"].append("CLEARANCE")
    with pytest.raises(ValidationError, match="event types must be unique"):
        DefensivePositionRule.model_validate(defensive)
    defensive = copy.deepcopy(data["scoring.yaml"]["defensive_contributions"]["by_position"]["DEF"])
    defensive["threshold"] = None
    with pytest.raises(ValidationError, match="enabled defensive rules"):
        DefensivePositionRule.model_validate(defensive)
    defensive = copy.deepcopy(data["scoring.yaml"]["defensive_contributions"]["by_position"]["GK"])
    defensive["points"] = 1
    with pytest.raises(ValidationError, match="disabled defensive rules"):
        DefensivePositionRule.model_validate(defensive)
    defensive = copy.deepcopy(data["scoring.yaml"]["defensive_contributions"]["by_position"]["DEF"])
    defensive["max_points"] = 1
    with pytest.raises(ValidationError, match="cannot exceed"):
        DefensivePositionRule.model_validate(defensive)

    bps_band = copy.deepcopy(data["bonus.yaml"]["bps"]["appearance_bands"][0])
    bps_band["min_exclusive"] = 0
    with pytest.raises(ValidationError, match="exactly one lower-bound"):
        BpsAppearanceBand.model_validate(bps_band)
    pass_band = copy.deepcopy(data["bonus.yaml"]["bps"]["pass_completion"]["bands"][0])
    pass_band["max_pct_inclusive"] = 79
    with pytest.raises(ValidationError, match="exactly one upper-bound"):
        PassBand.model_validate(pass_band)
    pass_band = copy.deepcopy(data["bonus.yaml"]["bps"]["pass_completion"]["bands"][0])
    pass_band["min_pct_inclusive"] = 90
    with pytest.raises(ValidationError, match="must not precede"):
        PassBand.model_validate(pass_band)
    pass_completion = copy.deepcopy(data["bonus.yaml"]["bps"]["pass_completion"])
    pass_completion["bands"][1]["min_pct_inclusive"] = 79
    with pytest.raises(ValidationError, match="mutually exclusive"):
        PassCompletionRules.model_validate(pass_completion)
    bps = copy.deepcopy(data["bonus.yaml"]["bps"])
    bps["appearance_bands"][0]["max_inclusive"] = 59
    with pytest.raises(ValidationError, match="total and mutually exclusive"):
        BpsRules.model_validate(bps)

    chips = copy.deepcopy(data["chips.yaml"])
    chips["chips"][-1] = copy.deepcopy(chips["chips"][0])
    with pytest.raises(ValidationError, match="must be unique"):
        ChipsFile.model_validate(chips)


@pytest.mark.unit
def test_future_chip_and_special_event_shapes_are_generic_and_json_safe(
    repository_root: Path,
) -> None:
    root = repository_root / "fixtures/rules/RUL-002/synthetic_complete"
    _, data = _authoring_data(root)
    chips = load_rules_yaml(root / "chips.yaml")
    chips["chips"] = [chips["chips"][0]]
    chips["chips"][0]["key"] = "MYSTERY_CHIP"
    chips["chips"][0]["effects"] = [
        {
            "surface": "SQUAD_SCORE",
            "operation": "MULTIPLY",
            "parameters": {"factor": 3, "enabled": True, "labels": ["captain"], "none": None},
        }
    ]
    assert ChipsFile.model_validate(chips).chips[0].key == "MYSTERY_CHIP"
    events = {
        "events": [
            {
                "event_id": "MIDSEASON_EVENT",
                "effective_gameweeks": {"start_gameweek": 10, "end_gameweek": 12},
                "operation": "DECLARE",
                "parameters": {"label": "synthetic", "weights": [1, 2]},
            }
        ]
    }
    assert SpecialEventsFile.model_validate(events).events[0].event_id == "MIDSEASON_EVENT"
    deadlines = copy.deepcopy(data["deadlines.yaml"])
    deadlines["gameweeks"].append(copy.deepcopy(deadlines["gameweeks"][0]))
    with pytest.raises(ValidationError, match="numbers must be unique"):
        DeadlinesFile.model_validate(deadlines)
    deadlines = copy.deepcopy(data["deadlines.yaml"])
    deadlines["gameweeks"][0]["deadline_utc"] = "2099-99-99T99:99:99Z"
    with pytest.raises(ValidationError, match="real UTC calendar"):
        DeadlinesFile.model_validate(deadlines)

    goals_conceded = copy.deepcopy(data["scoring.yaml"]["goals_conceded"])
    goals_conceded["positions"] = ["GK", "GK"]
    with pytest.raises(ValidationError, match="GK and DEF exactly once"):
        GoalsConcededRules.model_validate(goals_conceded)

    clean_sheets = copy.deepcopy(data["scoring.yaml"]["clean_sheets"])
    clean_sheets["retain_after_normal_substitution"] = False
    with pytest.raises(ValidationError):
        CleanSheetRules.model_validate(clean_sheets)

    target_root = repository_root / "fixtures/rules/RUL-002/target_2026_27_partial"
    _, target = _authoring_data(target_root)
    finality = copy.deepcopy(
        target["target_2026_27_claims.yaml"]["checked_claims"]["gameweek_finality"]
    )
    finality["local_time"] = "99:99"
    with pytest.raises(ValidationError, match="real HH:MM"):
        FinalityClaim.model_validate(finality)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda data: data["squad.yaml"].update(squad_size=16), "RULESET_SQUAD_INVALID"),
        (lambda data: data["lineup.yaml"].update(bench_size=3), "RULESET_LINEUP_INVALID"),
        (
            lambda data: data["lineup.yaml"].update(starting_size=2, bench_size=13),
            "RULESET_LINEUP_INVALID",
        ),
        (
            lambda data: data["assists.yaml"].update(points=4),
            "RULESET_ASSIST_POINTS_MISMATCH",
        ),
        (
            lambda data: data["source_manifest.yaml"].update(
                rule_source_default="SRC-NOT-REGISTERED"
            ),
            "RULESET_SOURCE_REFERENCE",
        ),
        (
            lambda data: data["source_manifest.yaml"]["sources"].append(
                copy.deepcopy(data["source_manifest.yaml"]["sources"][0])
            ),
            "RULESET_SOURCE_INVALID",
        ),
        (
            lambda data: data["source_manifest.yaml"].update(rule_source_default=None),
            "RULESET_SOURCE_REFERENCE",
        ),
    ],
)
def test_cross_file_coherence_mutants_fail_closed(
    repository_root: Path, mutation, code: str
) -> None:
    root = repository_root / "fixtures/rules/RUL-002/synthetic_complete"
    manifest, source = _authoring_data(root)
    data = copy.deepcopy(source)
    mutation(data)
    with pytest.raises(RulesValidationError) as caught:
        validate_and_normalize_authoring_data(manifest, data, ())
    assert caught.value.code == code


@pytest.mark.unit
def test_target_claim_identity_sources_and_blocker_uniqueness(repository_root: Path) -> None:
    root = repository_root / "fixtures/rules/RUL-002/target_2026_27_partial"
    manifest, source = _authoring_data(root)
    blockers = ("target:complete_scoring_table",)

    data = copy.deepcopy(source)
    data["target_2026_27_claims.yaml"]["ruleset_id"] = "other-target"
    with pytest.raises(RulesValidationError) as identity:
        validate_and_normalize_authoring_data(manifest, data, blockers)
    assert identity.value.code == "RULESET_TARGET_IDENTITY"

    data = copy.deepcopy(source)
    data["target_2026_27_claims.yaml"]["checked_claims"]["free_transfer_cap"]["source_refs"] = [
        "SRC-NOT-REGISTERED"
    ]
    with pytest.raises(RulesValidationError) as reference:
        validate_and_normalize_authoring_data(manifest, data, blockers)
    assert reference.value.code == "RULESET_SOURCE_REFERENCE"

    data = copy.deepcopy(source)
    data["scoring.yaml"]["source_refs"] = ["SRC-NOT-REGISTERED"]
    with pytest.raises(RulesValidationError) as draft_reference:
        validate_and_normalize_authoring_data(manifest, data, blockers)
    assert draft_reference.value.code == "RULESET_SOURCE_REFERENCE"

    claims = copy.deepcopy(source["target_2026_27_claims.yaml"])
    claims["unknown_blocking_families"].append(claims["unknown_blocking_families"][0])
    with pytest.raises(ValidationError, match="must be unique"):
        TargetClaimsFile.model_validate(claims)

    complete_root = repository_root / "fixtures/rules/RUL-002/synthetic_complete"
    complete_manifest, complete_data = _authoring_data(complete_root)
    extended = complete_manifest.model_copy(
        update={"extension_files": ("target_2026_27_claims.yaml",)}
    )
    with pytest.raises(RulesValidationError) as extension:
        validate_and_normalize_authoring_data(extended, complete_data, ())
    assert extension.value.code == "RULESET_EXTENSION_STATUS"
