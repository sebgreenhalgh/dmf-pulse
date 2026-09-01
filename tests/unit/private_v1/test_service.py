from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from dmf_pulse.optimisation.models import OneGameweekPlan
from dmf_pulse.private_v1.artifacts import (
    verify_replay_bundle,
    write_synthetic_replay_bundle,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.service import (
    PrivateV1RecommendationService,
    _exact_root_action_upper_bound,
)

from .e2e_test_support import build_execution_input


def test_exact_root_bound_covers_full_current_scale_candidate_universe() -> None:
    assert (
        _exact_root_action_upper_bound(
            squad_size=15,
            incoming_count=614,
            maximum_transfers=1,
        )
        == 9211
    )


def test_complete_synthetic_run_and_offline_replay(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    execution = build_execution_input(repository_root, tmp_path / "source")
    service = PrivateV1RecommendationService()
    first = service.run(execution)

    assert first.decision.engineering_status == (
        "PRIVATE_V1_E2E_001A_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW"
    )
    assert first.decision.activation_status == "NOT_PRODUCTION_ACTIVE"
    assert first.decision.status == "SUCCESS"
    assert len(first.decision.resulting_squad) == 15
    assert len(set(first.decision.resulting_squad)) == 15
    assert first.decision.chip_action == "NO_CHIP"
    assert first.decision.confidence == "LOW"
    assert first.decision.stage7_model_derived is False
    assert first.decision.solver_optimality == "EXACT_DECLARED_TREE_AND_ACTION_SPACE"
    assert "EXACT_ONLY_WITHIN_DECLARED_CANDIDATE_ACTION_SPACE" in first.decision.warnings
    assert "PLAYER_ALLOCATION_PRIOR_GRADE_E_CANDIDATE_NOT_ACCEPTED" in (first.decision.warnings)
    assert "REPOSITORY_OWNED_SYNTHETIC_SCORE_PRIOR_TEST_ONLY" in first.decision.warnings
    assert "STAGE9_MC_PASS_NOT_REQUIRED_TEST_ONLY" in first.decision.warnings
    assert first.decision.paired_comparison.scenario_count == len(
        first.gameweek_projection.scenario_set.scenarios
    )
    comparison = first.decision.paired_comparison
    assert comparison.recommended_expected_points_before_hit - comparison.transfer_hit_points == (
        comparison.recommended_expected_points_after_hit
    )
    assert (
        comparison.recommended_expected_points_after_hit - comparison.no_transfer_expected_points
        == (comparison.net_expected_uplift)
    )
    assert comparison.gain_p10 <= comparison.gain_median <= comparison.gain_p90
    assert sum((item.probability for item in comparison.gain_pmf), Decimal(0)) == Decimal(1)

    scenarios = first.gameweek_projection.scenario_set.scenarios
    assert scenarios
    assert sum(item.weight for item in scenarios) == pytest.approx(1.0)
    assert all(item.weight > 0 for item in scenarios)
    assert all(
        isinstance(points, int)
        for scenario in scenarios
        for points in scenario.player_points.values()
    )
    assert len(first.gameweek_projection.scenario_set.fixture_result_sha256_by_fixture) == 3
    assert len(first.decision.lineage.stage7_context_sha256_by_fixture) == 3
    assert len(first.decision.lineage.stage8_result_sha256_by_fixture) == 3
    assert len(first.decision.lineage.player_prior_binding_sha256_by_fixture) == 3
    assert len(first.decision.lineage.score_prior_sha256_by_fixture) == 3

    players_by_id = {
        str(mapping.canonical_player_id): next(
            player
            for player in execution.current_state.fpl_input.players
            if player.provider_element_id == mapping.official_fpl_element_id
        )
        for mapping in execution.player_identity_map.players
    }
    positions = [players_by_id[item].position.value for item in first.decision.resulting_squad]
    assert {position: positions.count(position) for position in set(positions)} == {
        "DEF": 5,
        "FWD": 3,
        "GK": 2,
        "MID": 5,
    }
    clubs = [
        int(players_by_id[item].team_identity.external_id_text)
        for item in first.decision.resulting_squad
    ]
    assert max(clubs.count(item) for item in set(clubs)) <= 3

    tactics = first.decision.tactics
    assert len(tactics.starting_xi) == 11
    assert len(set(tactics.starting_xi)) == 11
    assert sum(players_by_id[item].position.value == "GK" for item in tactics.starting_xi) == 1
    assert tactics.captain in tactics.starting_xi
    assert tactics.vice_captain in tactics.starting_xi
    assert tactics.captain != tactics.vice_captain
    assert tactics.captain_points_application_count == 1
    assert len(tactics.bench_outfield_order) == 3
    assert players_by_id[tactics.bench_goalkeeper].position.value == "GK"
    assert set(tactics.starting_xi) | {
        tactics.bench_goalkeeper,
        *tactics.bench_outfield_order,
    } == set(first.decision.resulting_squad)

    recommended = first.optimiser_result.recommended_plan
    baseline = first.optimiser_result.no_transfer_baseline
    assert recommended is not None and baseline is not None
    assert recommended.current_action.tactical_evaluation.exact_stage10_evaluation is True
    assert baseline.current_action.tactical_evaluation.exact_stage10_evaluation is True
    assert recommended.current_action.tactical_evaluation.source == "STAGE10_ADAPTER"
    assert baseline.current_action.tactical_evaluation.source == "STAGE10_ADAPTER"
    recommended_tactics = OneGameweekPlan.model_validate(
        recommended.current_action.tactical_evaluation.tactical_plan
    )
    baseline_tactics = OneGameweekPlan.model_validate(
        baseline.current_action.tactical_evaluation.tactical_plan
    )
    assert {
        (item.scenario_id, item.outcome_draw_id) for item in recommended_tactics.scenario_scores
    } == {(item.scenario_id, item.outcome_draw_id) for item in baseline_tactics.scenario_scores}
    assert recommended.current_action.state_after.bank_tenths >= 0
    if first.decision.transfers:
        current_squad = {
            item.official_fpl_element_id for item in execution.current_state.manager_state.squad
        }
        for transfer in first.decision.transfers:
            assert transfer.official_fpl_element_out in current_squad
            assert transfer.official_fpl_element_in not in current_squad

    for heading in (
        "TARGET",
        "CURRENT STATE",
        "RECOMMENDATION",
        "LINEUP",
        "PROJECTION",
        "DATA QUALITY",
        "REPRODUCIBILITY",
    ):
        assert heading in first.report
    assert "IDENTICAL JOINT SCENARIOS" in first.report
    assert "Confidence: LOW" in first.report
    assert "NO CHIP" in first.report
    assert "dmf private-v1 replay --bundle <bundle-directory>" in first.report
    assert str(tmp_path) not in first.report
    assert "password" not in first.report.casefold()
    assert "secret" not in first.report.casefold()

    bundle = tmp_path / "replay"
    manifest = write_synthetic_replay_bundle(execution, first.decision, first.report, bundle)
    replay = service.replay(bundle)

    assert replay.manifest_sha256 == manifest.manifest_sha256
    assert replay.run.decision == first.decision
    assert replay.run.report == first.report

    relocated = tmp_path / "relocated" / "bundle"
    relocated.parent.mkdir()
    shutil.copytree(bundle, relocated)
    relocated_manifest, relocated_input, relocated_decision, relocated_report = (
        verify_replay_bundle(relocated)
    )
    assert relocated_manifest == manifest
    assert relocated_input == execution
    assert relocated_decision == first.decision
    assert relocated_report == first.report
    assert str(tmp_path).encode() not in (bundle / "manifest.json").read_bytes()

    tampered = tmp_path / "tampered"
    shutil.copytree(bundle, tampered)
    with (tampered / "report.txt").open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(PrivateV1Error, match="REPLAY_HASH_MISMATCH"):
        verify_replay_bundle(tampered)

    extra = tmp_path / "extra"
    shutil.copytree(bundle, extra)
    (extra / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(PrivateV1Error, match="REPLAY_BUNDLE_INVALID"):
        verify_replay_bundle(extra)
