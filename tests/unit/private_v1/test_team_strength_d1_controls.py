"""Input control versus genuine candidate-derived work; ordinary service preservation."""

import ast
from types import SimpleNamespace

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import PlayerPosition
from dmf_pulse.optimisation.multi_gameweek_models import (
    PlayerCatalogEntry,
    PlayerPriceState,
    TransferActionScope,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_policy import load_multi_gameweek_search_policy
from dmf_pulse.private_v1 import team_strength_comparison as comparison
from dmf_pulse.private_v1.service import _exact_root_action_upper_bound, bounded_horizon_screen
from tests.unit.private_v1.team_strength_d1_parent_support import parent_source


def test_real_candidate_screen_can_move_derived_budget_without_hard_control_divergence():
    ids = tuple(f"{position.value}-{i}" for position in PlayerPosition for i in range(6))
    catalog = {
        p: PlayerCatalogEntry(
            player_id=p, club_id=f"club-{p}", position=PlayerPosition(p.split("-")[0])
        )
        for p in ids
    }
    prices = {p: PlayerPriceState(current_price_tenths=40 if p.endswith("-2") else 50) for p in ids}
    execution = SimpleNamespace(
        maximum_transfers_per_deadline=2,
        search_scope_mode="PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V3",
    )
    base = load_multi_gameweek_search_policy()
    controls, derived = [], []
    for variant in (0, 1):
        projections = tuple(
            SimpleNamespace(
                result_sha256=str(gw) * 64,
                scenario_set=SimpleNamespace(gameweek_id=f"GW-{gw}"),
                player_summaries={
                    p: SimpleNamespace(
                        expected_points=100 - int(p[-1]),
                        points_standard_deviation=50 if variant and p == "MID-5" else 0,
                    )
                    for p in ids
                },
            )
            for gw in (1, 2, 3)
        )
        screen = bounded_horizon_screen(
            ids, catalog=catalog, prices=prices, gameweeks=projections, protected_incoming_ids=()
        )
        count = len(screen.nodes[0].retained_incoming_ids)
        upper = _exact_root_action_upper_bound(
            squad_size=15, incoming_count=count, maximum_transfers=2
        )
        assert count == (12, 13)[variant] and upper == (7111, 8386)[variant]
        effective = seal_search_policy(
            base.model_copy(
                update={
                    "max_returned_root_candidates": max(base.max_returned_root_candidates, upper),
                    "max_actions_per_state": screen.maximum_action_combinations,
                    "transfer_action_scope": TransferActionScope(
                        root_maximum_transfers=2, continuation_mode="FREE_TRANSFERS_ONLY"
                    ),
                }
            )
        )
        derived.append(canonical_sha256(effective.model_dump(mode="json")))
        controls.append(comparison._input_work_budget_control(execution, effective))
    assert derived[0] != derived[1] and controls[0] == controls[1]
    altered = seal_search_policy(
        effective.model_copy(
            update={
                "transfer_action_scope": TransferActionScope(
                    root_maximum_transfers=2, continuation_mode="RULES_BOUNDED"
                )
            }
        )
    )
    assert comparison._input_work_budget_control(execution, altered) != controls[-1]
    assert comparison._input_work_budget_control(execution, base) != controls[-1]
    altered = seal_search_policy(
        effective.model_copy(update={"deterministic_seed": effective.deterministic_seed + 1})
    )
    assert comparison._input_work_budget_control(execution, altered) != controls[-1]


def test_ordinary_service_is_parent_ast_except_scoped_diagnostic_notes(repository_root):
    relative = "src/dmf_pulse/private_v1/service.py"
    parent = ast.parse(parent_source(repository_root, relative))
    current = ast.parse((repository_root / relative).read_text())

    class RemoveNotes(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == "dmf_pulse.private_v1.team_strength_diagnostics":
                return None
            return node

        def visit_Expr(self, node):
            if (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id
                in {
                    "note_stage8_input",
                    "note_stage8_input_failure",
                    "note_stage8_blocked",
                    "note_stage8_projected",
                }
            ):
                return None
            return node

    assert ast.dump(parent) == ast.dump(RemoveNotes().visit(current))
