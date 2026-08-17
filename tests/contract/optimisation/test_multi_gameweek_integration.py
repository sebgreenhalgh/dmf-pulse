"""Stage-9/10/rules/service/artifact/CLI integration for OPT-011."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli.optimise import optimise_app
from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import (
    GameweekAssemblyMode,
    GameweekPointScenario,
    PlayerPosition,
    ProjectionMode,
)
from dmf_pulse.optimisation.errors import OptimisationError
from dmf_pulse.optimisation.manager_state import ManagerState, OwnershipSpell, seal_manager_state
from dmf_pulse.optimisation.models import OneGameweekOptimiserPolicy, OneGameweekRulesView
from dmf_pulse.optimisation.multi_gameweek_artifacts import (
    load_verified_artifact,
    persist_result,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekOptimisationRequest,
    MultiGameweekOptimisationResult,
    PlayerCatalogEntry,
    PlayerPriceState,
    ScenarioTreeNode,
)
from dmf_pulse.optimisation.multi_gameweek_service import (
    advance_current_action,
    optimise_multi_gameweek,
    reroot_request_after_observation,
)
from dmf_pulse.optimisation.multi_gameweek_solver import information_set_key
from dmf_pulse.optimisation.stage10_adapter import Stage10TacticalAdapter
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules
from tests.support.multi_gameweek_factories import compiled_ruleset

pytestmark = pytest.mark.integration


def test_reference_rules_compile_to_request_transfer_contract() -> None:
    request = MultiGameweekOptimisationRequest.model_validate_json(
        Path("fixtures/optimisation/multi_gameweek/request.json").read_bytes()
    )
    resolved = build_multi_gameweek_transfer_rules(
        compiled_ruleset(), projection_mode=ProjectionMode.TEST
    )
    assert resolved == request.rules
    assert resolved.maximum_free_transfers == 5
    assert resolved.hit_cost_per_paid_transfer == 4
    assert resolved.selling_price_rule.retained_profit_numerator == 1
    assert resolved.selling_price_rule.retained_profit_denominator == 2


def test_cli_optimise_then_advance_executes_same_application_service(tmp_path: Path) -> None:
    runner = CliRunner()
    request_path = Path("fixtures/optimisation/multi_gameweek/request.json").resolve()
    ruleset_path = Path(
        "fixtures/optimisation/multi_gameweek/reference_ruleset_test_only.json"
    ).resolve()
    artifacts = tmp_path / "artifacts"
    optimised = runner.invoke(
        optimise_app,
        [
            "multi-gameweek",
            "--request",
            str(request_path),
            "--ruleset",
            str(ruleset_path),
            "--artifact-root",
            str(artifacts),
            "--output",
            "json",
        ],
    )
    assert optimised.exit_code == 0, optimised.output
    payload = json.loads(optimised.output)
    assert payload["status"] == "SUCCESS"
    assert payload["current_action"]["transfers_out"] == ["p07"]
    assert payload["current_action"]["transfers_in"] == ["p15"]
    result_path = next(artifacts.rglob("results/**/*.json"))
    advanced = runner.invoke(
        optimise_app,
        [
            "advance-multi-gameweek",
            "--request",
            str(request_path),
            "--result",
            str(result_path),
            "--artifact-root",
            str(artifacts),
            "--observed-node",
            "gw2-price-rise",
            "--output",
            "json",
        ],
    )
    assert advanced.exit_code == 0, advanced.output
    state = json.loads(advanced.output)["manager_state"]
    assert state["current_gameweek"] == 2
    assert state["observed_node_id"] == "gw2-price-rise"
    assert "p15" in {
        item["player_id"] for item in state["ownership_spells"] if item["ended_gameweek"] is None
    }


def test_immutable_result_artifact_round_trip_and_tamper_rejection(tmp_path: Path) -> None:
    request = MultiGameweekOptimisationRequest.model_validate_json(
        Path("fixtures/optimisation/multi_gameweek/request.json").read_bytes()
    )
    result = optimise_multi_gameweek(request)
    path = persist_result(result, artifact_root=tmp_path)
    loaded = load_verified_artifact(path, MultiGameweekOptimisationResult)
    assert loaded == result
    sidecar = path.with_suffix(".sha256")
    sidecar.write_text("0" * 64 + f"  {path.name}\n", encoding="ascii")
    with pytest.raises(OptimisationError):
        load_verified_artifact(path, MultiGameweekOptimisationResult)


def test_rolling_horizon_executes_root_observes_and_resolves_subtree() -> None:
    request = MultiGameweekOptimisationRequest.model_validate_json(
        Path("fixtures/optimisation/multi_gameweek/request.json").read_bytes()
    )
    result = optimise_multi_gameweek(request)
    advanced = advance_current_action(request, result, observed_node_id="gw2-price-rise")
    next_request = reroot_request_after_observation(
        request,
        advanced,
        request_id="opt011-rolling-gw2",
    )
    next_result = optimise_multi_gameweek(next_request)
    assert next_result.recommended_plan is not None
    assert next_result.current_action is not None
    assert next_result.current_action.transfer_count == 0
    assert next_result.recommended_plan.current_action.gameweek == 2


def test_explicit_stage10_adapter_uses_stage9_joint_scenario_and_real_tactical_plan() -> None:
    catalog = tuple(
        PlayerCatalogEntry(player_id=player_id, club_id=f"club-{player_id}", position=position)
        for player_id, position in (
            ("g0", PlayerPosition.GK),
            ("g1", PlayerPosition.GK),
            ("d0", PlayerPosition.DEF),
            ("d1", PlayerPosition.DEF),
            ("m0", PlayerPosition.MID),
            ("f0", PlayerPosition.FWD),
        )
    )
    ruleset_hash = "1" * 64
    state = seal_manager_state(
        ManagerState(
            state_id="small-state",
            current_gameweek=1,
            observed_node_id="small-node",
            bank_tenths=0,
            free_transfers=1,
            ownership_spells=tuple(
                sorted(
                    (
                        OwnershipSpell(
                            spell_id=f"spell-{item.player_id}",
                            player_id=item.player_id,
                            club_id=item.club_id,
                            position=item.position,
                            purchase_price_tenths=50,
                            current_price_tenths=50,
                            started_gameweek=1,
                            started_at_node_id="small-node",
                        )
                        for item in catalog
                    ),
                    key=lambda item: (item.player_id, item.started_gameweek, item.spell_id),
                )
            ),
            ruleset_id="small-rules",
            ruleset_version="1",
            ruleset_hash=ruleset_hash,
            state_sha256="0" * 64,
        )
    )
    points = {"g0": 2, "g1": 0, "d0": 5, "d1": 1, "m0": 4, "f0": 3}
    components = {
        player_id: {
            component: (value if component == "appearance" else 0)
            for component in (
                "appearance",
                "goals",
                "assists",
                "clean_sheet",
                "saves",
                "penalty_saves",
                "defensive_contributions",
                "goals_conceded",
                "penalty_misses",
                "yellow_cards",
                "red_cards",
                "own_goals",
                "bonus",
            )
        }
        for player_id, value in points.items()
    }
    scenario = GameweekPointScenario(
        scenario_id="small-scenario",
        outcome_draw_id="small-draw",
        weight=1.0,
        gameweek_id="GW1",
        fixture_ids=("small-fixture",),
        player_points=points,
        player_components=components,
        player_bps={player_id: 0 for player_id in points},
        player_bonus={player_id: 0 for player_id in points},
        player_minutes={player_id: 90 for player_id in points},
        player_appeared={player_id: True for player_id in points},
        assembly_mode=GameweekAssemblyMode.SINGLE_FIXTURE,
        approximation_labels=(),
    )
    preliminary = ScenarioTreeNode(
        node_id="small-node",
        gameweek=1,
        conditional_probability=Decimal(1),
        information_set_key="temporary",
        points_state_id="small-points",
        prices={item.player_id: PlayerPriceState(current_price_tenths=50) for item in catalog},
        tactical_values=(),
    )
    node = preliminary.model_copy(
        update={"information_set_key": information_set_key(preliminary, parent_key=None)}
    )
    tactical_rules = OneGameweekRulesView(
        ruleset_id="small-rules",
        ruleset_version="1",
        ruleset_hash=ruleset_hash,
        projection_mode=ProjectionMode.TEST,
        squad_size=6,
        position_squad_quota={
            PlayerPosition.GK: 2,
            PlayerPosition.DEF: 2,
            PlayerPosition.MID: 1,
            PlayerPosition.FWD: 1,
        },
        starting_size=2,
        bench_size=4,
        lineup_min={
            PlayerPosition.GK: 1,
            PlayerPosition.DEF: 0,
            PlayerPosition.MID: 0,
            PlayerPosition.FWD: 0,
        },
        lineup_max={
            PlayerPosition.GK: 1,
            PlayerPosition.DEF: 1,
            PlayerPosition.MID: 1,
            PlayerPosition.FWD: 1,
        },
        initial_budget_tenths=300,
        max_players_per_club=3,
        captain_multiplier=2,
        vice_captain_fallback=True,
        auto_substitution_timing="AFTER_ALL_GAMEWEEK_FIXTURES",
        auto_substitution_zero_appearance_minutes=0,
        designated_bench_goalkeeper_if_appeared=True,
        manager_bench_order=True,
        maintain_legal_formation=True,
        manager_capability="REFERENCE_ONLY",
        manager_capability_hash=None,
    )
    policy = OneGameweekOptimiserPolicy(
        max_squad_candidates=1,
        max_tactical_configurations=1000,
        max_scenario_score_operations=10000,
        max_returned_ties=4,
    )
    adapter = Stage10TacticalAdapter(
        candidate_pool=catalog,
        rules=tactical_rules,
        policy=policy,
        scenarios_by_node={"small-node": (scenario,)},
    )
    evaluation = adapter.evaluate(node=node, state=state)
    assert evaluation.source == "STAGE10_ADAPTER"
    assert evaluation.exact_stage10_evaluation is True
    assert evaluation.tactical_plan["plan_sha256"] == evaluation.tactical_plan_sha256
    assert evaluation.expected_points == Decimal(12)
    payload = dict(evaluation.tactical_plan)
    claimed = payload.pop("plan_sha256")
    payload["plan_sha256"] = None
    assert claimed == semantic_sha256(payload)
