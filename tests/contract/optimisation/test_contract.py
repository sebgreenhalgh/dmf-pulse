import pytest

from dmf_pulse.optimisation.models import (
    AutosubEvent,
    CandidatePoolSnapshot,
    CandidateSquad,
    OneGameweekOptimisationRequest,
    OneGameweekOptimisationResult,
    OneGameweekPlan,
    ScenarioManagerScore,
    TacticalConfiguration,
)
from tests.support.optimisation_factories import request


def test_request_does_not_expose_budget_or_raw_stage9_fields() -> None:
    assert "budget_tenths" not in OneGameweekOptimisationRequest.model_fields
    assert "stage9_points" not in OneGameweekOptimisationRequest.model_fields


def test_frozen_sol_plan_public_field_names_are_exact() -> None:
    assert set(CandidatePoolSnapshot.model_fields) == {
        "schema_version",
        "information_cutoff_utc",
        "players",
        "source_bundle_ids",
        "snapshot_sha256",
    }
    assert set(CandidateSquad.model_fields) == {"player_ids"}
    assert set(OneGameweekOptimisationRequest.model_fields) == {
        "schema_version",
        "request_id",
        "projection_mode",
        "gameweek_id",
        "information_cutoff_utc",
        "search_scope",
        "candidate_pool",
        "fixed_squad_ids",
        "provided_candidate_squads",
        "required_player_ids",
        "excluded_player_ids",
        "request_sha256",
    }
    assert set(TacticalConfiguration.model_fields) == {
        "starting_xi",
        "bench_goalkeeper",
        "bench_order",
        "captain",
        "vice_captain",
    }
    assert set(AutosubEvent.model_fields) == {
        "player_out",
        "player_in",
        "bench_slot",
        "reason_code",
    }
    assert set(ScenarioManagerScore.model_fields) == {
        "scenario_id",
        "outcome_draw_id",
        "counted_player_ids",
        "autosubs",
        "captain_resolution",
        "effective_captain_id",
        "base_points",
        "captain_bonus_points",
        "bench_contribution_points",
        "manager_points",
    }
    assert set(OneGameweekPlan.model_fields) == {
        "squad",
        "tactical_configuration",
        "total_cost_tenths",
        "remaining_budget_tenths",
        "expected_manager_points",
        "point_distribution",
        "scenario_scores",
        "legality",
        "solver_status",
        "explanations",
        "plan_sha256",
    }
    assert set(OneGameweekOptimisationResult.model_fields) == {
        "schema_version",
        "status",
        "request_id",
        "gameweek_id",
        "objective",
        "recommended_plan",
        "tied_optimal_plans",
        "solver_status",
        "lineage",
        "upstream_mc_status",
        "upstream_warnings",
        "explanations",
        "error_code",
        "error_message",
        "result_sha256",
    }


def test_request_and_snapshot_hashes_are_required_contract_fields() -> None:
    value = request()
    with pytest.raises(ValueError):
        CandidatePoolSnapshot.model_validate(
            value.candidate_pool.model_dump(exclude={"snapshot_sha256"})
        )
    with pytest.raises(ValueError):
        OneGameweekOptimisationRequest.model_validate(value.model_dump(exclude={"request_sha256"}))
