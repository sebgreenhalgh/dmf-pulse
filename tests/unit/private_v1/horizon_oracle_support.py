"""Small complete synthetic transfer universes for R5 exact differential checks."""

from decimal import Decimal
from types import SimpleNamespace

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import PlayerPosition
from dmf_pulse.optimisation.manager_state import seal_manager_state
from dmf_pulse.optimisation.multi_gameweek_models import (
    PlayerCatalogEntry,
    PlayerPriceState,
    TransferActionScope,
    seal_request,
    seal_scenario_tree,
    seal_search_policy,
)
from dmf_pulse.optimisation.multi_gameweek_solver import information_set_key
from tests.support.multi_gameweek_factories import NodeSpec, build_request
from tests.unit.optimisation.test_future_transfer_scope import LINEAR_ASSUMPTIONS
from tests.unit.optimisation.test_stage11_exact_acceleration import _ExactSurrogate


class HorizonPointsEvaluator(_ExactSurrogate):
    def __init__(self, points):
        super().__init__()
        self.points = points

    def _value(self, node, squad_ids):
        points = sum((Decimal(self.points[node.gameweek].get(p, 0)) for p in squad_ids), Decimal(0))
        return (
            super()
            ._value(node, squad_ids)
            .model_copy(
                update={
                    "expected_points": points,
                    "p10_points": points,
                    "p90_points": points,
                }
            )
        )


def oracle_fixture(case="root"):
    incoming = ("p15", "p19", "p20", "p21", "p22")
    request = build_request(
        (NodeSpec("root", 1), NodeSpec("next", 2, "root"), NodeSpec("last", 3, "next")),
        include_second_mid=True,
    )
    additions = tuple(
        PlayerCatalogEntry(player_id=p, club_id=f"club-{p}", position=PlayerPosition.MID)
        for p in incoming
        if p not in {e.player_id for e in request.candidate_pool}
    )
    catalog = tuple(sorted((*request.candidate_pool, *additions), key=lambda p: p.player_id))
    prices = {p.player_id: PlayerPriceState(current_price_tenths=50) for p in catalog}
    root = {"p15": 8, "p19": 7, "p20": 3, "p21": -2, "p22": 4}
    future = {"p15": 2, "p19": 1, "p20": 30, "p21": -1, "p22": 30}
    if case == "future":
        root = {p: -i - 1 for i, p in enumerate(incoming)}
    if case in {"budget", "club"}:
        prices["p21"] = PlayerPriceState(current_price_tenths=30)
        prices["p22"] = PlayerPriceState(current_price_tenths=70)
        root["p21"] = future["p21"] = 1
    if case == "club":
        catalog = tuple(
            p.model_copy(update={"club_id": "saturated"})
            if p.player_id in {"p00", "p02", "p07", "p22"}
            else p
            for p in catalog
        )
        clubs = {p.player_id: p.club_id for p in catalog}
        state = seal_manager_state(
            request.initial_state.model_copy(
                update={
                    "ownership_spells": tuple(
                        s.model_copy(update={"club_id": clubs[s.player_id]})
                        for s in request.initial_state.ownership_spells
                    )
                }
            )
        )
        request = request.model_copy(update={"initial_state": state})
    projections = []
    points = {1: root, 2: future, 3: future}
    for gw in range(1, 4):
        projections.append(
            SimpleNamespace(
                result_sha256=canonical_sha256({"gw": gw, "points": points[gw]}),
                scenario_set=SimpleNamespace(
                    gameweek_id=f"GW-{gw}",
                    scenarios=(
                        SimpleNamespace(
                            player_points=points[gw], player_appeared={p: True for p in incoming}
                        ),
                    ),
                ),
                player_summaries={
                    p: SimpleNamespace(expected_points=points[gw][p], points_standard_deviation=0)
                    for p in incoming
                },
            )
        )
    policy = seal_search_policy(
        request.search_policy.model_copy(
            update={
                "transfer_action_scope": TransferActionScope(
                    root_maximum_transfers=1, continuation_mode="FREE_TRANSFERS_ONLY"
                )
            }
        )
    )
    request = seal_request(
        request.model_copy(
            update={
                "candidate_pool": catalog,
                "search_policy": policy,
                "assumptions": LINEAR_ASSUMPTIONS,
            }
        )
    )
    return with_candidates(request, incoming, prices=prices), incoming, tuple(projections), points


def with_candidates(request, incoming, *, prices=None):
    nodes = []
    for original in request.scenario_tree.nodes:
        node = original.model_copy(
            update={
                "allowed_transfer_in_ids": tuple(sorted(incoming)),
                "prices": prices or original.prices,
            }
        )
        node = node.model_copy(
            update={
                "information_set_key": information_set_key(
                    node, parent_key=nodes[-1].information_set_key if nodes else None
                )
            }
        )
        nodes.append(node)
    tree = seal_scenario_tree(request.scenario_tree.model_copy(update={"nodes": tuple(nodes)}))
    return seal_request(request.model_copy(update={"scenario_tree": tree}))
