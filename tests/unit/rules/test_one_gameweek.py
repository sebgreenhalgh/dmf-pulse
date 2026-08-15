from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import synthetic_ruleset


def test_reference_rules_view_is_resolved_from_compiled_values() -> None:
    view = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    assert view.squad_size == 15
    assert view.position_squad_quota["GK"] == 2
    assert view.initial_budget_tenths == 1000
    assert view.auto_substitution_timing == "AFTER_ALL_GAMEWEEK_FIXTURES"
