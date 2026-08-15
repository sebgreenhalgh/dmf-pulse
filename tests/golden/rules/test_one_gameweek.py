from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import synthetic_ruleset


def test_reference_rules_view_golden_shape() -> None:
    view = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    assert view.model_dump(mode="json")["position_squad_quota"] == {
        "GK": 2,
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
    }
