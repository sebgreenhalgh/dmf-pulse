from pathlib import Path

import pytest
from pydantic import ValidationError

from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.rules.authoring import TargetClaimsFile
from dmf_pulse.rules.compiler import load_compiled_ruleset
from dmf_pulse.rules.errors import RulesValidationError
from dmf_pulse.rules.models import RulesetStatus
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from dmf_pulse.rules.yaml_loader import load_rules_yaml
from tests.support.optimisation_factories import synthetic_ruleset


def test_reference_rules_view_is_resolved_from_compiled_values() -> None:
    view = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    assert view.squad_size == 15
    assert view.position_squad_quota["GK"] == 2
    assert view.initial_budget_tenths == 1000
    assert view.auto_substitution_timing == "AFTER_ALL_GAMEWEEK_FIXTURES"


def test_schema_v11_reference_claims_are_strictly_nonproduction(
    repository_root: Path,
) -> None:
    claims_path = (
        repository_root
        / "fixtures/optimisation/one_gameweek/reference_ruleset_source"
        / "target_2026_27_claims.yaml"
    )
    claims = load_rules_yaml(claims_path)
    parsed = TargetClaimsFile.model_validate(claims)
    assert parsed.status == "REFERENCE_ONLY"
    assert parsed.production_eligible is False
    assert parsed.checked_claims is None

    with pytest.raises(ValidationError):
        TargetClaimsFile.model_validate({**claims, "production_eligible": True})
    for status in ("VERIFIED", "ACTIVE"):
        with pytest.raises(ValidationError):
            TargetClaimsFile.model_validate({**claims, "status": status})

    target_claims = load_rules_yaml(
        repository_root / "fixtures/rules/RUL-002/target_2026_27_partial/target_2026_27_claims.yaml"
    )
    assert TargetClaimsFile.model_validate(target_claims).status == "CAPTURED_UNVERIFIED"


def test_test_synthetic_compiled_fixture_is_canonical_and_exact(
    repository_root: Path,
) -> None:
    compiled = load_compiled_ruleset(
        repository_root / "fixtures/optimisation/one_gameweek/reference_ruleset_test_only.json"
    )
    assert compiled.schema_version == "1.1"
    assert compiled.status is RulesetStatus.REFERENCE_ONLY
    assert compiled.production_eligible is False
    assert compiled.ruleset_id == "opt010-test-synthetic"
    assert compiled.season_code == "2099/2100"

    view = build_one_gameweek_rules_view(compiled, projection_mode=ProjectionMode.TEST)
    assert view.squad_size == 15
    assert view.position_squad_quota == {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert view.initial_budget_tenths == 1000
    assert view.max_players_per_club == 3
    assert view.starting_size == 11
    assert view.bench_size == 4
    assert view.lineup_min == {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}
    assert view.lineup_max == {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}
    assert view.captain_multiplier == 2
    assert view.vice_captain_fallback is True
    assert view.auto_substitution_timing == "AFTER_ALL_GAMEWEEK_FIXTURES"
    assert view.auto_substitution_zero_appearance_minutes == 0
    assert view.designated_bench_goalkeeper_if_appeared is True
    assert view.manager_bench_order is True
    assert view.maintain_legal_formation is True

    with pytest.raises(RulesValidationError, match="FULL_SEASON"):
        build_one_gameweek_rules_view(compiled, projection_mode=ProjectionMode.PRODUCTION)


def test_current_target_remains_blocked_for_test_and_production(repository_root: Path) -> None:
    target = load_compiled_ruleset(
        repository_root / "artifacts/rules/fpl-2026-27-0.1.0-prelaunch.1.schema-v1.1.json"
    )
    assert target.status is RulesetStatus.CAPTURED_UNVERIFIED
    for mode in (ProjectionMode.TEST, ProjectionMode.PRODUCTION):
        with pytest.raises(RulesValidationError, match=r"manager-tactics|reference or verified"):
            build_one_gameweek_rules_view(target, projection_mode=mode)
