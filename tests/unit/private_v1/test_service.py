from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from dmf_pulse.fpl_points.models import (
    PENALTY_GOAL_SHARE_PROXY_WARNING,
    PenaltyHierarchyExhaustionPolicy,
    PlayerPosition,
)
from dmf_pulse.ingestion.fpl.direct_payloads import (
    CURRENT_FPL_PENALTY_HIERARCHY_AMBIGUOUS,
    CURRENT_FPL_PENALTY_HIERARCHY_UNAVAILABLE,
    CurrentPenaltyHierarchyEntry,
)
from dmf_pulse.optimisation.models import OneGameweekPlan
from dmf_pulse.optimisation.multi_gameweek_models import PlayerCatalogEntry, PlayerPriceState
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek
from dmf_pulse.private_v1.artifacts import (
    verify_replay_bundle,
    write_synthetic_replay_bundle,
)
from dmf_pulse.private_v1.automatic_inputs import (
    PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.models import (
    PrivateCandidateActionPolicy,
    seal_candidate_action_policy,
)
from dmf_pulse.private_v1.service import (
    PrivateV1RecommendationService,
    _bounded_private_incoming_ids,
    _exact_root_action_upper_bound,
    _MemoizedStage10Evaluator,
    _penalty_hierarchy_exhaustion_policy,
    _penalty_role_limitations,
    _stage11_request,
)

from .e2e_test_support import build_execution_input
from .test_input_coherence import (
    _complete_penalty_entries,
    _penalty_hierarchy,
    _replace,
)


def test_exact_root_bound_covers_full_current_scale_candidate_universe() -> None:
    assert (
        _exact_root_action_upper_bound(
            squad_size=15,
            incoming_count=614,
            maximum_transfers=1,
        )
        == 9211
    )


def test_stage10_evaluates_identical_resulting_squad_once_per_root_node() -> None:
    class Delegate:
        rules = object()

        def __init__(self) -> None:
            self.calls = 0

        def evaluate(self, *, node, state):
            self.calls += 1
            return (node.node_id, state.squad_ids)

    delegate = Delegate()
    evaluator = _MemoizedStage10Evaluator(delegate)  # type: ignore[arg-type]
    node = SimpleNamespace(node_id="root")
    first_state = SimpleNamespace(squad_ids=("a", "b"), bank_tenths=0)
    economically_equivalent = SimpleNamespace(squad_ids=("a", "b"), bank_tenths=10)

    first = evaluator.evaluate(node=node, state=first_state)
    second = evaluator.evaluate(node=node, state=economically_equivalent)

    assert first is second
    assert delegate.calls == 1


def test_certified_pointwise_pruning_cannot_remove_toy_optimum() -> None:
    entries = (
        PlayerCatalogEntry(player_id="best", club_id="club-a", position=PlayerPosition.MID),
        PlayerCatalogEntry(player_id="dominated", club_id="club-a", position=PlayerPosition.MID),
        PlayerCatalogEntry(player_id="route", club_id="club-b", position=PlayerPosition.MID),
    )
    catalog = {item.player_id: item for item in entries}
    prices = {
        "best": PlayerPriceState(current_price_tenths=50),
        "dominated": PlayerPriceState(current_price_tenths=55),
        "route": PlayerPriceState(current_price_tenths=40),
    }
    scenario = SimpleNamespace(
        player_points={"best": 8, "dominated": 7, "route": 3},
        player_appeared={"best": True, "dominated": True, "route": True},
    )
    summaries = {
        player_id: SimpleNamespace(expected_points=points, points_standard_deviation=0)
        for player_id, points in {"best": 8, "dominated": 7, "route": 3}.items()
    }
    gameweek = SimpleNamespace(
        scenario_set=SimpleNamespace(scenarios=(scenario,)),
        player_summaries=summaries,
    )

    retained, certified_count = _bounded_private_incoming_ids(
        ("best", "dominated", "route"),
        catalog=catalog,
        prices=prices,
        gameweek=gameweek,  # type: ignore[arg-type]
        maximum_transfers=2,
    )

    assert retained == ("best", "route")
    assert certified_count == 1


def test_labelled_heuristic_retains_expected_upside_and_price_route_candidates() -> None:
    player_ids = tuple(f"p{index}" for index in range(6))
    entries = tuple(
        PlayerCatalogEntry(
            player_id=player_id,
            club_id=f"club-{player_id}",
            position=PlayerPosition.MID,
        )
        for player_id in player_ids
    )
    catalog = {item.player_id: item for item in entries}
    mean = {"p0": 10, "p1": 9, "p2": 8, "p3": 7, "p4": 1, "p5": 0}
    deviation = {**{player_id: 0 for player_id in player_ids}, "p2": 10}
    prices = {
        player_id: PlayerPriceState(current_price_tenths=(10 if player_id == "p3" else 100))
        for player_id in player_ids
    }
    scenario = SimpleNamespace(
        player_points=mean,
        player_appeared={player_id: True for player_id in player_ids},
    )
    gameweek = SimpleNamespace(
        scenario_set=SimpleNamespace(scenarios=(scenario,)),
        player_summaries={
            player_id: SimpleNamespace(
                expected_points=mean[player_id],
                points_standard_deviation=deviation[player_id],
            )
            for player_id in player_ids
        },
    )

    retained, certified_count = _bounded_private_incoming_ids(
        player_ids,
        catalog=catalog,
        prices=prices,
        gameweek=gameweek,  # type: ignore[arg-type]
        maximum_transfers=2,
    )

    assert retained == ("p0", "p1", "p2", "p3")
    assert certified_count == 0


def test_labelled_heuristic_fails_closed_when_metric_ties_exceed_bound() -> None:
    player_ids = tuple(f"p{index:02d}" for index in range(25))
    catalog = {
        player_id: PlayerCatalogEntry(
            player_id=player_id,
            club_id=f"club-{player_id}",
            position=PlayerPosition.MID,
        )
        for player_id in player_ids
    }
    prices = {player_id: PlayerPriceState(current_price_tenths=50) for player_id in player_ids}
    scenario = SimpleNamespace(
        player_points={player_id: 5 for player_id in player_ids},
        player_appeared={player_id: True for player_id in player_ids},
    )
    gameweek = SimpleNamespace(
        scenario_set=SimpleNamespace(scenarios=(scenario,)),
        player_summaries={
            player_id: SimpleNamespace(expected_points=5, points_standard_deviation=0)
            for player_id in player_ids
        },
    )

    with pytest.raises(PrivateV1Error, match="PRIVATE_TRANSFER_SCREEN_UNBOUNDED"):
        _bounded_private_incoming_ids(
            player_ids,
            catalog=catalog,
            prices=prices,
            gameweek=gameweek,  # type: ignore[arg-type]
            maximum_transfers=2,
        )

    assert _bounded_private_incoming_ids(
        player_ids,
        catalog=catalog,
        prices=prices,
        gameweek=gameweek,  # type: ignore[arg-type]
        maximum_transfers=0,
    ) == ((), 0)


def test_current_penalty_hierarchy_limitation_is_disclosed_without_false_fallback(
    repository_root: Path, tmp_path: Path
) -> None:
    execution = build_execution_input(repository_root, tmp_path / "penalty-hierarchy")
    hierarchy = _penalty_hierarchy(
        execution,
        _complete_penalty_entries(execution),
    )

    result = PrivateV1RecommendationService().run(
        _replace(execution, current_penalty_hierarchy=hierarchy)
    )

    assert "CURRENT_FPL_PENALTY_HIERARCHY_DETERMINISTIC_V1" in result.decision.warnings
    assert "CURRENT_FPL_PENALTY_HIERARCHY_DETERMINISTIC_V1" in result.report
    assert "HISTORICAL_PENALTY_ROLE_FALLBACK_USED" not in result.decision.warnings


def test_ambiguous_team_warning_reaches_decision_and_report(
    repository_root: Path, tmp_path: Path
) -> None:
    execution = build_execution_input(repository_root, tmp_path / "ambiguous-hierarchy")
    complete = _complete_penalty_entries(execution)
    by_team: dict[int, list[int]] = {}
    for player in execution.player_identity_map.players:
        by_team.setdefault(player.official_fpl_team_id, []).append(player.official_fpl_element_id)
    team_id, player_ids = next(
        (team, sorted(values)) for team, values in sorted(by_team.items()) if len(values) >= 2
    )
    hierarchy = _penalty_hierarchy(
        execution,
        (
            *(item for item in complete if item.official_fpl_team_id != team_id),
            CurrentPenaltyHierarchyEntry(
                official_fpl_element_id=player_ids[0],
                official_fpl_team_id=team_id,
                penalties_order=1,
            ),
            CurrentPenaltyHierarchyEntry(
                official_fpl_element_id=player_ids[1],
                official_fpl_team_id=team_id,
                penalties_order=1,
            ),
        ),
    )

    result = PrivateV1RecommendationService().run(
        _replace(execution, current_penalty_hierarchy=hierarchy)
    )

    assert CURRENT_FPL_PENALTY_HIERARCHY_AMBIGUOUS in result.decision.warnings
    assert CURRENT_FPL_PENALTY_HIERARCHY_AMBIGUOUS in result.report


def test_actual_historical_penalty_role_fallback_is_disclosed() -> None:
    execution = SimpleNamespace(current_penalty_hierarchy=object())
    fixture = SimpleNamespace(warnings=("HISTORICAL_PENALTY_ROLE_FALLBACK_USED",))

    assert _penalty_role_limitations(execution, (fixture,)) == (
        "CURRENT_FPL_PENALTY_HIERARCHY_DETERMINISTIC_V1",
        "HISTORICAL_PENALTY_ROLE_FALLBACK_USED",
    )


def test_penalty_hierarchy_team_usability_warnings_reach_private_limitations() -> None:
    execution = SimpleNamespace(
        current_penalty_hierarchy=SimpleNamespace(
            warnings=(
                CURRENT_FPL_PENALTY_HIERARCHY_AMBIGUOUS,
                CURRENT_FPL_PENALTY_HIERARCHY_UNAVAILABLE,
            )
        )
    )

    assert _penalty_role_limitations(execution, ()) == (
        CURRENT_FPL_PENALTY_HIERARCHY_AMBIGUOUS,
        "CURRENT_FPL_PENALTY_HIERARCHY_DETERMINISTIC_V1",
        CURRENT_FPL_PENALTY_HIERARCHY_UNAVAILABLE,
    )


def test_goal_share_proxy_is_private_no_retention_opt_in_and_disclosed() -> None:
    private = SimpleNamespace(
        current_penalty_hierarchy=object(),
        retention_class="PRIVATE_TRANSIENT_NO_RETENTION",
    )
    synthetic = SimpleNamespace(
        current_penalty_hierarchy=object(),
        retention_class="SYNTHETIC_REPLAY_ALLOWED",
    )
    no_hierarchy = SimpleNamespace(
        current_penalty_hierarchy=None,
        retention_class="PRIVATE_TRANSIENT_NO_RETENTION",
    )

    assert _penalty_hierarchy_exhaustion_policy(private) is (
        PenaltyHierarchyExhaustionPolicy.PRIVATE_CURRENT_PENALTY_ROLE_GOAL_SHARE_PROXY_V1
    )
    assert _penalty_hierarchy_exhaustion_policy(synthetic) is (
        PenaltyHierarchyExhaustionPolicy.BLOCK
    )
    assert _penalty_hierarchy_exhaustion_policy(no_hierarchy) is (
        PenaltyHierarchyExhaustionPolicy.BLOCK
    )

    fixture = SimpleNamespace(warnings=(PENALTY_GOAL_SHARE_PROXY_WARNING,))
    assert PENALTY_GOAL_SHARE_PROXY_WARNING in _penalty_role_limitations(private, (fixture,))


def test_complete_synthetic_run_and_offline_replay(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    execution = build_execution_input(repository_root, tmp_path / "source")
    service = PrivateV1RecommendationService()
    first = service.run(execution)

    policy_payload = execution.candidate_action_policy.model_dump(mode="python")
    policy_payload.update(
        {
            "rationale": (
                f"{PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1}: toy bounded-search proof."
            ),
            "semantic_sha256": "0" * 64,
        }
    )
    bounded_policy = seal_candidate_action_policy(
        PrivateCandidateActionPolicy.model_construct(**policy_payload)
    )
    bounded_execution = _replace(execution, candidate_action_policy=bounded_policy)
    bounded_request, bounded_tactical, _, bounded_scope = _stage11_request(
        bounded_execution,
        first.gameweek_projection,
    )
    bounded = optimise_multi_gameweek(bounded_request, evaluator=bounded_tactical)

    assert bounded_scope.retained_incoming_ids == (
        bounded_request.scenario_tree.root.allowed_transfer_in_ids
    )
    assert bounded.recommended_plan is not None
    assert first.optimiser_result.recommended_plan is not None
    assert bounded.recommended_plan.current_action.action.signature == (
        first.optimiser_result.recommended_plan.current_action.action.signature
    )
    assert bounded.recommended_plan.utility.objective_total == (
        first.optimiser_result.recommended_plan.utility.objective_total
    )

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
