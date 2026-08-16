from dmf_pulse.fpl_points.models import ProjectionMode
from dmf_pulse.optimisation.models import OptimisationStatus, SearchScope
from dmf_pulse.optimisation.service import optimise_one_gameweek
from tests.support.optimisation_factories import projection, request, synthetic_ruleset


def test_fixed_squad_blank_gameweek_is_exact_success() -> None:
    rules = synthetic_ruleset()
    result = optimise_one_gameweek(request(), projection(rules.ruleset_hash), rules)
    assert result.status is OptimisationStatus.SUCCESS
    assert result.optimality_guarantee.value == "EXACT_FIXED_SQUAD"
    assert result.solver_status.tactical_configurations_examined == 363_000
    assert result.recommended_plan is not None
    assert result.recommended_plan.expected_manager_points == 0
    assert result.recommended_plan.total_cost_tenths is None
    assert result.recommended_plan.remaining_budget_tenths is None


def test_production_current_target_fails_closed() -> None:
    rules = synthetic_ruleset()
    result = optimise_one_gameweek(
        request(projection_mode=ProjectionMode.PRODUCTION), projection(rules.ruleset_hash), rules
    )
    assert result.status is OptimisationStatus.BLOCKED
    assert result.error_code == "MANAGER_TACTICS_CAPABILITY_UNAVAILABLE"


def test_provided_scope_has_exact_set_guarantee() -> None:
    rules = synthetic_ruleset()
    result = optimise_one_gameweek(
        request(scope=SearchScope.PROVIDED_SQUADS), projection(rules.ruleset_hash), rules
    )
    assert result.status is OptimisationStatus.SUCCESS
    assert result.optimality_guarantee.value == "EXACT_PROVIDED_SET"
    assert result.recommended_plan is not None
    assert result.recommended_plan.total_cost_tenths is None
    assert result.recommended_plan.remaining_budget_tenths is None
