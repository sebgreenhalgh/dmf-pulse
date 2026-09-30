"""D7 split policy-capacity diagnostics remain finite and disclosure-safe."""

import pytest

from dmf_pulse.optimisation.multi_gameweek_errors import ResourceLimitKind
from dmf_pulse.optimisation.multi_gameweek_models import (
    BackendStatus,
    MultiGameweekResultStatus,
    OptimalityGuarantee,
    SolverDiagnostics,
    Stage11LayerWork,
)
from dmf_pulse.private_v1 import team_strength_diagnostics as diagnostics
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.team_strength_diagnostics import (
    ComparisonReason,
    ComparisonStage,
    ComparisonTrace,
    RollingPhase,
    TeamStrengthComparisonFailure,
    safe_comparison_failure,
)


def test_split_generated_and_retained_limits_reach_safe_terminal_diagnostic() -> None:
    solver = SolverDiagnostics(
        status=BackendStatus.TIME_RESOURCE_LIMIT_NO_INCUMBENT,
        termination_reason="PRIVATE MESSAGE MUST NOT ESCAPE",
        optimality_guarantee=OptimalityGuarantee.NONE,
        state_expansions=8487,
        observed_action_combinations=768098,
        action_candidates=768098,
        policy_candidates=786433,
        pareto_candidates=20209,
        peak_materialized_policy_candidates=1202,
        peak_retained_pareto_frontier=777,
        resource_limit_kind=ResourceLimitKind.POLICY_GENERATION_LIMIT,
        configured_max_actions_per_state=17000,
        configured_max_state_expansions=25000,
        configured_max_generated_policy_candidates=786432,
        configured_max_retained_pareto_candidates=786432,
        configured_max_returned_root_candidates=8386,
        configured_cumulative_legal_action_limit=786432,
        cumulative_legal_actions=783057,
        reachable_layer_state_count=8726,
        layer_work=(
            Stage11LayerWork(
                depth=2,
                gameweek=8,
                reachable_states=8187,
                unique_economic_states=8187,
                legal_actions_generated=753864,
                action_combinations_considered=753864,
                unique_resulting_squads=190867,
                generated_policy_candidates=760000,
                retained_pareto_candidates=19000,
                objective_winners_retained=19500,
                strict_pareto_dominance_events=740000,
                tie_equivalence_events=500,
                peak_temporary_policy_candidates=1202,
            ),
        ),
        configuration_sha256="0" * 64,
    )
    trace = ComparisonTrace()
    trace.start_world("LEAGUE_BASELINE")
    with trace.activate():
        diagnostics.note_rolling_phase(RollingPhase.VALIDATE_THREE_GW_RESULT)
        diagnostics.note_optimiser_result(
            status=MultiGameweekResultStatus.RESOURCE_LIMIT,
            solver_status=solver,
        )
        failure = trace.failure(
            ComparisonStage.RUN_LEAGUE_BASELINE_WORLD,
            ComparisonReason.BASELINE_WORLD_FAILED,
            PrivateV1Error("MULTI_GAMEWEEK_RESOURCE_LIMIT", "PRIVATE MESSAGE MUST NOT ESCAPE"),
        )
    result = safe_comparison_failure(failure)
    assert result["resource_limit_kind"] == "POLICY_GENERATION_LIMIT"
    assert "configured_max_policy_candidates" not in result
    assert result["configured_max_generated_policy_candidates"] == 786432
    assert result["configured_max_retained_pareto_candidates"] == 786432
    assert result["observed_policy_candidates"] == 786433
    assert result["observed_pareto_candidates"] == 20209
    assert result["observed_peak_materialized_policy_candidates"] == 1202
    assert result["observed_peak_retained_pareto_frontier"] == 777
    assert result["cumulative_legal_actions"] == 783057
    assert result["layer_work"][0]["generated_policy_candidates"] == 760000
    assert "PRIVATE MESSAGE" not in str(result)
    mixed = failure.diagnostic.model_copy(update={"configured_max_policy_candidates": 786432})
    with pytest.raises(ValueError, match="invalid comparison diagnostic"):
        safe_comparison_failure(TeamStrengthComparisonFailure(mixed))
