"""Deterministic Stage-11 structural benchmark for 001N-R2."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from time import perf_counter

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from dmf_pulse.fpl_points.artifacts import semantic_sha256  # noqa: E402
from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode  # noqa: E402
from dmf_pulse.optimisation.manager_state import ManagerState, seal_manager_state  # noqa: E402
from dmf_pulse.optimisation.models import CandidateSquad  # noqa: E402
from dmf_pulse.optimisation.multi_gameweek_models import (  # noqa: E402
    PlayerCatalogEntry,
    PlayerPriceState,
    TacticalNodeEvaluation,
    seal_request,
    seal_scenario_tree,
)
from dmf_pulse.optimisation.multi_gameweek_solver import (  # noqa: E402
    Stage11SearchProfile,
    apply_transfer_action,
    enumerate_legal_actions,
    information_set_key,
    root_node,
    solve_frontier,
)
from dmf_pulse.optimisation.stage10_adapter import Stage10TacticalAdapter  # noqa: E402
from dmf_pulse.private_v1.service import (  # noqa: E402
    _MemoizedStage10Evaluator,
    load_one_gameweek_policy,
)
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view  # noqa: E402
from tests.support.multi_gameweek_factories import (  # noqa: E402
    NodeSpec,
    _scenario,
    build_request,
    compiled_ruleset,
)


@dataclass
class ExactSurrogate:
    calls: int = 0

    @staticmethod
    def _evaluation(*, node, squad_ids: tuple[str, ...]) -> TacticalNodeEvaluation:
        value = Decimal(
            sum(
                (index + 1) * sum(player_id.encode("utf-8"))
                for index, player_id in enumerate(squad_ids)
            )
        ) / Decimal(1000)
        digest = semantic_sha256({"node_id": node.node_id, "squad_ids": squad_ids})
        return TacticalNodeEvaluation(
            expected_points=value,
            p10_points=value - Decimal(1),
            p90_points=value + Decimal(1),
            tactical_plan_sha256=digest,
            tactical_plan={},
            exact_stage10_evaluation=True,
            source="FROZEN_STAGE10_RECORD",
        )

    def evaluate(self, *, node, state: ManagerState) -> TacticalNodeEvaluation:
        self.calls += 1
        return self._evaluation(node=node, squad_ids=state.squad_ids)

    def evaluate_many(
        self,
        *,
        node,
        squads: tuple[CandidateSquad, ...],
        progress=None,
    ) -> dict[tuple[str, ...], TacticalNodeEvaluation]:
        results = {}
        for completed, squad in enumerate(squads, start=1):
            self.calls += 1
            results[squad.player_ids] = self._evaluation(node=node, squad_ids=squad.player_ids)
            if progress is not None:
                progress((completed, len(squads)))
        return results


@dataclass
class CountingExactStage10:
    delegate: Stage10TacticalAdapter
    calls: int = 0

    @property
    def rules(self):
        return self.delegate.rules

    def evaluate(self, *, node, state: ManagerState) -> TacticalNodeEvaluation:
        self.calls += 1
        return self.delegate.evaluate(node=node, state=state)

    def evaluate_many(
        self,
        *,
        node,
        squads: tuple[CandidateSquad, ...],
        progress=None,
    ) -> dict[tuple[str, ...], TacticalNodeEvaluation]:
        self.calls += len(squads)
        return self.delegate.evaluate_many(node=node, squads=squads, progress=progress)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incoming", type=int, choices=(3, 4, 12, 16), default=12)
    parser.add_argument("--scenarios", type=int, default=1)
    parser.add_argument("--tactical", choices=("exact", "surrogate"), default="surrogate")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.scenarios <= 0:
        parser.error("--scenarios must be positive")
    incoming = ("p15", "p16", "p17", "p18")[: args.incoming]
    request = build_request(
        (
            NodeSpec(node_id="GW-1", gameweek=1, allowed_transfer_in_ids=incoming),
            NodeSpec(
                node_id="GW-2",
                parent_id="GW-1",
                gameweek=2,
                allowed_transfer_in_ids=incoming,
            ),
            NodeSpec(
                node_id="GW-3",
                parent_id="GW-2",
                gameweek=3,
                allowed_transfer_in_ids=incoming,
            ),
        ),
        free_transfers=2,
        max_transfers_per_node=2,
        max_actions_per_state=10000,
        max_state_expansions=100000,
        max_policy_candidates=1000000,
        max_returned_root_candidates=10000,
    )
    if args.incoming >= 12:
        # STANDARD-scale fixed incoming universe. All incoming players are reachable.
        # One incumbent per position costs 50; the other eleven cost 40. With zero
        # bank and incoming prices 50, legal budget/position rules keep the oracle
        # benchmark tractable without truncating any declared 0/1/2-transfer action.
        positions = (PlayerPosition.GK, PlayerPosition.DEF, PlayerPosition.MID, PlayerPosition.FWD)
        extras = tuple(
            PlayerCatalogEntry(
                player_id=f"in-{index:02d}",
                club_id=f"incoming-club-{index // 2}",
                position=positions[index % 4],
            )
            for index in range(args.incoming)
        )
        incoming = tuple(item.player_id for item in extras)
        catalog = tuple(sorted((*request.candidate_pool[:15], *extras), key=lambda p: p.player_id))
        prices = {
            item.player_id: PlayerPriceState(
                current_price_tenths=(
                    50
                    if item.player_id in incoming or item.player_id in {"p00", "p02", "p07", "p12"}
                    else 40
                )
            )
            for item in catalog
        }
        spells = tuple(
            spell.model_copy(
                update={
                    "purchase_price_tenths": prices[spell.player_id].current_price_tenths,
                    "current_price_tenths": prices[spell.player_id].current_price_tenths,
                }
            )
            for spell in request.initial_state.ownership_spells
        )
        state = seal_manager_state(
            request.initial_state.model_copy(update={"ownership_spells": spells})
        )
        nodes = []
        parent_key = None
        for node in request.scenario_tree.nodes:
            node = node.model_copy(
                update={
                    "prices": prices,
                    "allowed_transfer_in_ids": incoming,
                    "tactical_values": (),
                }
            )
            parent_key = information_set_key(node, parent_key=parent_key)
            nodes.append(node.model_copy(update={"information_set_key": parent_key}))
        request = request.model_copy(
            update={
                "candidate_pool": catalog,
                "initial_state": state,
                "scenario_tree": seal_scenario_tree(
                    request.scenario_tree.model_copy(update={"nodes": tuple(nodes)})
                ),
            }
        )
    request = seal_request(
        request.model_copy(
            update={
                "assumptions": tuple(
                    sorted(
                        {
                            *request.assumptions,
                            "DETERMINISTIC_NO_NEW_INFORMATION_REVELATION_V1",
                            "EXPECTED_THREE_GAMEWEEK_POINTS_WITH_LEGAL_RECOURSE",
                            "FUTURE_PRICE_CHANGES_NOT_MODELLED_IN_PRIVATE_3GW_V1",
                            "NO_CHIP_EXPLICIT",
                            "THREE_GAMEWEEK_ZERO_TERMINAL_VALUE_AFTER_HORIZON",
                        }
                    )
                ),
                "request_sha256": "0" * 64,
            }
        )
    )

    def evaluator_delegate():
        if args.tactical == "surrogate":
            return ExactSurrogate()
        points = {
            item.player_id: 1 + index % 11 for index, item in enumerate(request.candidate_pool)
        }
        scenarios = {}
        for node in request.scenario_tree.nodes:
            base = _scenario(
                node_id=node.node_id,
                gameweek=node.gameweek,
                catalog=request.candidate_pool,
                points=points,
            )[0]
            node_scenarios = []
            for index in range(args.scenarios):
                appeared = {
                    player_id: args.scenarios == 1 or (index + player_index) % 7 != 0
                    for player_index, player_id in enumerate(base.player_appeared)
                }
                node_scenarios.append(
                    base.model_copy(
                        update={
                            "scenario_id": f"{node.node_id}-scenario-{index:03d}",
                            "outcome_draw_id": f"{node.node_id}-draw-{index:03d}",
                            "weight": 1.0 / args.scenarios,
                            "player_appeared": appeared,
                            "player_minutes": {
                                p: 90 if present else 0 for p, present in appeared.items()
                            },
                            "player_points": {
                                p: base.player_points[p] if present else 0
                                for p, present in appeared.items()
                            },
                            "player_components": {
                                p: base.player_components[p]
                                if present
                                else {component: 0 for component in base.player_components[p]}
                                for p, present in appeared.items()
                            },
                        }
                    )
                )
            scenarios[node.node_id] = tuple(node_scenarios)
        return CountingExactStage10(
            Stage10TacticalAdapter(
                candidate_pool=request.candidate_pool,
                rules=build_one_gameweek_rules_view(
                    compiled_ruleset(), projection_mode=ProjectionMode.TEST
                ),
                policy=load_one_gameweek_policy(),
                scenarios_by_node=scenarios,
            )
        )

    root = root_node(request.scenario_tree)
    root_actions = enumerate_legal_actions(
        request.initial_state,
        node=root,
        candidate_pool=request.candidate_pool,
        rules=request.rules,
        policy=request.search_policy,
    )
    root_squads = tuple(
        CandidateSquad(
            player_ids=apply_transfer_action(
                request.initial_state,
                action,
                node=root,
                candidate_pool=request.candidate_pool,
                rules=request.rules,
            ).state.squad_ids
        )
        for action in root_actions
    )

    before_delegate = evaluator_delegate()
    before_evaluator = _MemoizedStage10Evaluator(before_delegate)  # type: ignore[arg-type]
    before_evaluator.precompute_node(node=root, squads=root_squads)
    before_profile = Stage11SearchProfile()
    started = perf_counter()
    before = solve_frontier(request, before_evaluator, profile=before_profile)
    before_elapsed = perf_counter() - started

    after_delegate = evaluator_delegate()
    after_evaluator = _MemoizedStage10Evaluator(after_delegate)  # type: ignore[arg-type]
    after_evaluator.precompute_node(node=root, squads=root_squads)
    after_profile = Stage11SearchProfile()
    started = perf_counter()
    after = solve_frontier(
        request,
        after_evaluator,
        prefer_deterministic_linear=True,
        profile=after_profile,
    )
    after_elapsed = perf_counter() - started
    if not before.complete or not after.complete or before.candidates != after.candidates:
        raise AssertionError(
            "benchmark must complete with exact full policy/history/tactical equality"
        )
    rendered = json.dumps(
        {
            "after": {
                "elapsed_seconds": str(after_elapsed),
                "profile": after_profile.as_dict(),
                "retained_root_candidates": len(after.candidates),
                "tactical_batch_calls": after_evaluator.batch_calls,
                "tactical_cache_entries": len(after_evaluator._cache),
                "tactical_cache_hits": after_evaluator.cache_hits,
                "tactical_cache_misses": after_evaluator.cache_misses,
                "tactical_delegate_calls": after_delegate.calls,
                "tactical_individual_calls": after_evaluator.individual_calls,
                "tactical_by_node": {
                    key: asdict(value) for key, value in after_evaluator.counters_by_node.items()
                },
                "solver_counters": after.diagnostics.model_dump(mode="json"),
            },
            "before": {
                "elapsed_seconds": str(before_elapsed),
                "profile": before_profile.as_dict(),
                "retained_root_candidates": len(before.candidates),
                "tactical_batch_calls": before_evaluator.batch_calls,
                "tactical_cache_entries": len(before_evaluator._cache),
                "tactical_cache_hits": before_evaluator.cache_hits,
                "tactical_cache_misses": before_evaluator.cache_misses,
                "tactical_delegate_calls": before_delegate.calls,
                "tactical_individual_calls": before_evaluator.individual_calls,
                "tactical_by_node": {
                    key: asdict(value) for key, value in before_evaluator.counters_by_node.items()
                },
                "solver_counters": before.diagnostics.model_dump(mode="json"),
            },
            "exact_candidate_equality": before.candidates == after.candidates,
            "incoming_count": len(incoming),
            "speedup": str(before_elapsed / after_elapsed),
            "scenario_count": args.scenarios,
            "tactical_mode": args.tactical,
        },
        indent=2,
        sort_keys=True,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8", newline="\n")
    print(rendered)


if __name__ == "__main__":
    main()
