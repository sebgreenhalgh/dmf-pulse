from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.candidate_pool import conservative_squad_upper_bound
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import request, synthetic_ruleset


def test_reference_pool_preflight_is_one_complete_squad() -> None:
    rules = synthetic_ruleset()
    view = build_one_gameweek_rules_view(rules, projection_mode=ProjectionMode.TEST)
    assert conservative_squad_upper_bound(request(), view) == 1
