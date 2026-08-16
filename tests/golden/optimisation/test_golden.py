from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.service import optimise_one_gameweek
from tests.support.optimisation_factories import projection, request, synthetic_ruleset


def test_zero_point_golden_signature_is_stable() -> None:
    rules = synthetic_ruleset()
    result = optimise_one_gameweek(
        request(projection_mode=ProjectionMode.TEST), projection(rules.ruleset_hash), rules
    )
    assert result.recommended_plan is not None
    assert result.recommended_plan.expected_manager_points == 0
    assert result.recommended_plan.signature.startswith("p00,p01,p02")
