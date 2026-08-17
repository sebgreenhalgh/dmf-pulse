"""Synthetic/reference Stage-11 fixture factory; no target-season rule claim."""

from __future__ import annotations

from decimal import Decimal
from itertools import combinations, product

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import PlayerPosition, ProjectionMode
from dmf_pulse.optimisation.manager_state import ManagerState, OwnershipSpell, seal_manager_state
from dmf_pulse.optimisation.models import (
    ExplanationItem,
    LegalityReport,
    OneGameweekPlan,
    PointDistributionSummary,
    PointMass,
    SearchScope,
    TacticalConfiguration,
)
from dmf_pulse.optimisation.models import (
    OptimalityGuarantee as Stage10OptimalityGuarantee,
)
from dmf_pulse.optimisation.models import (
    SolverStatus as Stage10SolverStatus,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    FreeTransferEventRule,
    MultiGameweekOptimisationRequest,
    PlayerCatalogEntry,
    PlayerPriceState,
    ScenarioTree,
    ScenarioTreeNode,
    SearchPolicy,
    SellingPriceRule,
    TacticalValueRecord,
    TerminalValuePolicy,
    TransferRules,
    seal_request,
    seal_scenario_tree,
    seal_search_policy,
    seal_terminal_policy,
)
from dmf_pulse.optimisation.multi_gameweek_solver import information_set_key

BASE_POSITIONS: dict[str, PlayerPosition] = {
    "gk_1": PlayerPosition.GK,
    "gk_2": PlayerPosition.GK,
    **{f"def_{index}": PlayerPosition.DEF for index in range(1, 6)},
    **{f"mid_{index}": PlayerPosition.MID for index in range(1, 6)},
    **{f"fwd_{index}": PlayerPosition.FWD for index in range(1, 4)},
}
BASE_SQUAD = tuple(sorted(BASE_POSITIONS))
ZERO_HASH = "0" * 64
RULESET_HASH = "a" * 64

FIXTURE_KINDS = (
    "simple_one_ft",
    "roll_ft",
    "rational_hit",
    "retained_selling_profit",
    "price_fall",
    "repurchase_resets_cohort",
    "funding_transfer_bundle",
    "price_change_blocks_later_route",
    "injury_revealed_after_current_decision",
    "postponed_reassigned_fixture",
    "horizon_reversal",
    "futures_identical_until_revelation",
    "clairvoyance_trap",
    "terminal_value_reversal",
    "tied_plans",
    "malformed_scenario_probabilities_tree",
    "illegal_manager_state",
    "infeasible_future_state",
    "resource_limit_incumbent",
    "no_materially_distinct_alternative",
)


def _catalog(extras: dict[str, PlayerPosition]) -> tuple[PlayerCatalogEntry, ...]:
    positions = {**BASE_POSITIONS, **extras}
    return tuple(
        PlayerCatalogEntry(
            player_id=player_id,
            club_id=f"club_{index:02d}",
            position=positions[player_id],
        )
        for index, player_id in enumerate(sorted(positions), start=1)
    )


def _rules(*, earn: int = 1) -> TransferRules:
    return TransferRules(
        ruleset_id="dmf.synthetic.reference",
        ruleset_version="1.0.0",
        ruleset_hash=RULESET_HASH,
        projection_mode=ProjectionMode.TEST,
        capability="REFERENCE_ONLY",
        squad_size=15,
        position_squad_quota={
            PlayerPosition.GK: 2,
            PlayerPosition.DEF: 5,
            PlayerPosition.MID: 5,
            PlayerPosition.FWD: 3,
        },
        max_players_per_club=3,
        maximum_free_transfers=5,
        hit_cost_per_paid_transfer=4,
        max_transfers_per_deadline=3,
        selling_price_rule=SellingPriceRule(
            rule_id="synthetic-half-profit-full-loss",
            retained_profit_numerator=1,
            retained_profit_denominator=2,
        ),
        event_rules={
            "NORMAL": FreeTransferEventRule(earn_for_next_deadline=earn),
            "SYNTHETIC_UNLIMITED": FreeTransferEventRule(
                unlimited_transfers_without_hits=True,
                earn_for_next_deadline=earn,
            ),
        },
    )


def _legal_squads(
    candidate_pool: tuple[PlayerCatalogEntry, ...],
) -> tuple[tuple[str, ...], ...]:
    by_position = {
        position: tuple(item.player_id for item in candidate_pool if item.position is position)
        for position in PlayerPosition
    }
    squads = []
    for goalkeepers, defenders, midfielders, forwards in product(
        combinations(by_position[PlayerPosition.GK], 2),
        combinations(by_position[PlayerPosition.DEF], 5),
        combinations(by_position[PlayerPosition.MID], 5),
        combinations(by_position[PlayerPosition.FWD], 3),
    ):
        squads.append(tuple(sorted((*goalkeepers, *defenders, *midfielders, *forwards))))
    return tuple(sorted(squads))


def _stage10_tactic(squad: tuple[str, ...]) -> TacticalConfiguration:
    # Synthetic IDs carry their position prefix.
    def ids(prefix: str) -> tuple[str, ...]:
        return tuple(sorted(player for player in squad if player.startswith(prefix)))

    goalkeepers = ids("gk_")
    defenders = ids("def_")
    midfielders = ids("mid_")
    forwards = ids("fwd_")
    starting = (
        goalkeepers[0],
        *defenders[:3],
        *midfielders[:4],
        *forwards[:3],
    )
    bench = (*defenders[3:], *midfielders[4:])
    return TacticalConfiguration(
        starting_xi=starting,
        bench_goalkeeper=goalkeepers[1],
        bench_order=(bench[0], bench[1], bench[2]),
        captain=starting[1],
        vice_captain=starting[2],
    )


def _records(
    node_id: str,
    legal_squads: tuple[tuple[str, ...], ...],
    values: dict[str, Decimal],
    *,
    omit: bool = False,
) -> tuple[TacticalValueRecord, ...]:
    if omit:
        return ()
    records = []
    for squad in legal_squads:
        expected = sum((values.get(player_id, Decimal(2)) for player_id in squad), Decimal(0))
        point = int(expected)
        distribution = PointDistributionSummary(
            pmf=(PointMass(points=point, probability=Decimal(1)),),
            expected_points=expected,
            minimum=point,
            p10=point - 3,
            median=point,
            p90=point + 3,
            maximum=point,
            probability_field_11=Decimal(1),
            probability_field_10_or_fewer=Decimal(0),
            captain_fallback_probability=Decimal(0),
            captain_and_vice_failure_probability=Decimal(0),
            expected_bench_contribution=Decimal(0),
            component_means={"manager_points": expected},
            component_covariance={"manager_points": {"manager_points": Decimal(0)}},
        )
        stage10 = OneGameweekPlan(
            squad=squad,
            tactical_configuration=_stage10_tactic(squad),
            total_cost_tenths=None,
            remaining_budget_tenths=None,
            expected_manager_points=expected,
            point_distribution=distribution,
            scenario_scores=(),
            legality=LegalityReport(legal=True),
            solver_status=Stage10SolverStatus(
                termination="OPTIMAL",
                search_scope=SearchScope.FIXED_SQUAD,
                guarantee=Stage10OptimalityGuarantee.EXACT_FIXED_SQUAD,
                objective_value=expected,
                best_bound=expected,
                absolute_gap=Decimal(0),
                relative_gap=Decimal(0),
                tied_optima_total=1,
                returned_ties=1,
            ),
            explanations=(
                ExplanationItem(
                    code="SYNTHETIC_STAGE10_RECORD",
                    message=f"Synthetic exact Stage-10 tactical record for {node_id}.",
                ),
            ),
            plan_sha256=ZERO_HASH,
        )
        payload = stage10.model_dump(mode="json")
        payload["plan_sha256"] = None
        digest = semantic_sha256(payload)
        stage10 = stage10.model_copy(update={"plan_sha256": digest})
        records.append(
            TacticalValueRecord(
                squad_ids=squad,
                expected_points=expected,
                p10_points=Decimal(distribution.p10),
                p90_points=Decimal(distribution.p90),
                tactical_plan_sha256=digest,
                tactical_plan=stage10.model_dump(mode="json"),
            )
        )
    return tuple(records)


def _default_nodes(horizon: int) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []
    for gameweek in range(1, horizon + 1):
        nodes.append(
            {
                "node_id": f"n{gameweek}",
                "parent_id": None if gameweek == 1 else f"n{gameweek - 1}",
                "gameweek": gameweek,
                "probability": Decimal(1),
                "revealed": tuple(f"gw{value}" for value in range(2, gameweek + 1)),
                "availability": {},
                "fixture": {"state": "SCHEDULED"},
                "points_state_id": f"points-n{gameweek}",
            }
        )
    return nodes


def build_fixture(kind: str) -> MultiGameweekOptimisationRequest:
    if kind not in FIXTURE_KINDS:
        raise KeyError(kind)
    extras: dict[str, PlayerPosition] = {}
    nodes = _default_nodes(2)
    values: dict[str, dict[str, Decimal]] = {}
    prices: dict[str, dict[str, int]] = {}
    purchasable: dict[str, dict[str, bool]] = {}
    purchase_prices: dict[str, int] = {}
    bank = 0
    free_transfers = 1
    earn = 1
    terminal_bank = Decimal(0)
    terminal_ft = Decimal(0)
    terminal_liquidation = Decimal(0)
    terminal_enabled = False
    max_transfers = 2
    max_policy_candidates = 50_000
    max_returned = 500
    omit_tactics: set[str] = set()
    illegal_state = False
    allowed_transfer_in_ids: tuple[str, ...] | None = None

    if kind in {"simple_one_ft", "retained_selling_profit", "price_fall"}:
        extras = {"mid_6": PlayerPosition.MID}
        values = {
            "n1": {"mid_1": Decimal(0), "mid_6": Decimal(8)},
            "n2": {"mid_1": Decimal(0), "mid_6": Decimal(8)},
        }
    elif kind == "roll_ft":
        extras = {"mid_6": PlayerPosition.MID, "def_6": PlayerPosition.DEF}
        values = {
            "n1": {"mid_6": Decimal(1), "def_6": Decimal(1)},
            "n2": {"mid_6": Decimal(5), "def_6": Decimal(5)},
        }
    elif kind == "rational_hit":
        extras = {"mid_6": PlayerPosition.MID, "def_6": PlayerPosition.DEF}
        values = {
            "n1": {
                "mid_1": Decimal(0),
                "def_1": Decimal(0),
                "mid_6": Decimal(7),
                "def_6": Decimal(7),
            },
            "n2": {
                "mid_1": Decimal(0),
                "def_1": Decimal(0),
                "mid_6": Decimal(7),
                "def_6": Decimal(7),
            },
        }
    elif kind == "repurchase_resets_cohort":
        extras = {"mid_6": PlayerPosition.MID}
        nodes = _default_nodes(3)
        values = {
            "n1": {
                "mid_1": Decimal(0),
                "mid_2": Decimal(5),
                "mid_3": Decimal(5),
                "mid_4": Decimal(5),
                "mid_5": Decimal(5),
                "mid_6": Decimal(8),
            },
            "n2": {
                "mid_1": Decimal(0),
                "mid_2": Decimal(5),
                "mid_3": Decimal(5),
                "mid_4": Decimal(5),
                "mid_5": Decimal(5),
                "mid_6": Decimal(2),
            },
            "n3": {
                "mid_1": Decimal(12),
                "mid_2": Decimal(5),
                "mid_3": Decimal(5),
                "mid_4": Decimal(5),
                "mid_5": Decimal(5),
                "mid_6": Decimal(0),
            },
        }
        prices = {"n2": {"mid_1": 52}, "n3": {"mid_1": 52, "mid_6": 54}}
        allowed_transfer_in_ids = ("mid_1", "mid_6")
    elif kind == "funding_transfer_bundle":
        extras = {"mid_6": PlayerPosition.MID, "def_6": PlayerPosition.DEF}
        prices = {
            "n1": {"mid_6": 60, "def_6": 40},
            "n2": {"mid_6": 60, "def_6": 40},
        }
        values = {
            "n1": {"mid_6": Decimal(12), "def_6": Decimal(1)},
            "n2": {"mid_6": Decimal(12), "def_6": Decimal(1)},
        }
    elif kind == "price_change_blocks_later_route":
        extras = {"mid_6": PlayerPosition.MID}
        prices = {"n1": {"mid_6": 50}, "n2": {"mid_6": 55}}
        values = {
            "n1": {"mid_1": Decimal(2), "mid_6": Decimal(2)},
            "n2": {"mid_1": Decimal(2), "mid_6": Decimal(10)},
        }
    elif kind in {
        "injury_revealed_after_current_decision",
        "postponed_reassigned_fixture",
    }:
        extras = {"mid_6": PlayerPosition.MID, "mid_7": PlayerPosition.MID}
        nodes = [
            _default_nodes(1)[0],
            {
                "node_id": "n2_a",
                "parent_id": "n1",
                "gameweek": 2,
                "probability": Decimal("0.5"),
                "revealed": ("branch_a",),
                "availability": {"mid_6": "AVAILABLE", "mid_7": "UNAVAILABLE"},
                "fixture": {"state": "POSTPONED" if kind.startswith("postponed") else "SCHEDULED"},
                "points_state_id": "points-a",
            },
            {
                "node_id": "n2_b",
                "parent_id": "n1",
                "gameweek": 2,
                "probability": Decimal("0.5"),
                "revealed": ("branch_b",),
                "availability": {"mid_6": "UNAVAILABLE", "mid_7": "AVAILABLE"},
                "fixture": {"state": "REASSIGNED" if kind.startswith("postponed") else "SCHEDULED"},
                "points_state_id": "points-b",
            },
        ]
        values = {
            "n1": {"mid_6": Decimal(1), "mid_7": Decimal(1)},
            "n2_a": {"mid_6": Decimal(12), "mid_7": Decimal(0)},
            "n2_b": {"mid_6": Decimal(0), "mid_7": Decimal(12)},
        }
    elif kind == "horizon_reversal":
        extras = {"mid_6": PlayerPosition.MID, "def_6": PlayerPosition.DEF}
        earn = 0
        values = {
            "n1": {"mid_1": Decimal(2), "mid_6": Decimal(6), "def_6": Decimal(1)},
            "n2": {
                "mid_1": Decimal(8),
                "mid_6": Decimal(2),
                "def_1": Decimal(2),
                "def_6": Decimal(7),
            },
        }
    elif kind == "futures_identical_until_revelation":
        extras = {"mid_6": PlayerPosition.MID, "mid_7": PlayerPosition.MID}
        nodes = [
            _default_nodes(1)[0],
            {
                "node_id": "n2",
                "parent_id": "n1",
                "gameweek": 2,
                "probability": Decimal(1),
                "revealed": ("gw2",),
                "availability": {},
                "fixture": {"state": "SCHEDULED"},
                "points_state_id": "points-common",
            },
            {
                "node_id": "n3_a",
                "parent_id": "n2",
                "gameweek": 3,
                "probability": Decimal("0.5"),
                "revealed": ("branch_a", "gw2"),
                "availability": {"mid_6": "AVAILABLE", "mid_7": "UNAVAILABLE"},
                "fixture": {"state": "SCHEDULED"},
                "points_state_id": "points-a",
            },
            {
                "node_id": "n3_b",
                "parent_id": "n2",
                "gameweek": 3,
                "probability": Decimal("0.5"),
                "revealed": ("branch_b", "gw2"),
                "availability": {"mid_6": "UNAVAILABLE", "mid_7": "AVAILABLE"},
                "fixture": {"state": "SCHEDULED"},
                "points_state_id": "points-b",
            },
        ]
        values = {
            "n1": {"mid_6": Decimal(1), "mid_7": Decimal(1)},
            "n2": {"mid_6": Decimal(1), "mid_7": Decimal(1)},
            "n3_a": {"mid_6": Decimal(12), "mid_7": Decimal(0)},
            "n3_b": {"mid_6": Decimal(0), "mid_7": Decimal(12)},
        }
    elif kind == "clairvoyance_trap":
        extras = {"mid_6": PlayerPosition.MID, "mid_7": PlayerPosition.MID}
        nodes = [
            _default_nodes(1)[0],
            {
                "node_id": "n2_a",
                "parent_id": "n1",
                "gameweek": 2,
                "probability": Decimal("0.5"),
                "revealed": ("branch_a",),
                "availability": {},
                "fixture": {"state": "SCHEDULED"},
                "points_state_id": "points-a",
            },
            {
                "node_id": "n2_b",
                "parent_id": "n1",
                "gameweek": 2,
                "probability": Decimal("0.5"),
                "revealed": ("branch_b",),
                "availability": {},
                "fixture": {"state": "SCHEDULED"},
                "points_state_id": "points-b",
            },
        ]
        values = {
            "n1": {"mid_1": Decimal(0), "mid_6": Decimal(1), "mid_7": Decimal(1)},
            "n2_a": {"mid_1": Decimal(0), "mid_6": Decimal(12), "mid_7": Decimal(0)},
            "n2_b": {"mid_1": Decimal(0), "mid_6": Decimal(0), "mid_7": Decimal(12)},
        }
        purchasable = {
            "n2_a": {"mid_6": False, "mid_7": False},
            "n2_b": {"mid_6": False, "mid_7": False},
        }
    elif kind == "terminal_value_reversal":
        extras = {"mid_6": PlayerPosition.MID}
        nodes = _default_nodes(1)
        prices = {"n1": {"mid_6": 45}}
        values = {
            "n1": {
                "mid_1": Decimal(2),
                "mid_2": Decimal(3),
                "mid_3": Decimal(3),
                "mid_4": Decimal(3),
                "mid_5": Decimal(3),
                "mid_6": Decimal(1),
            }
        }
        terminal_enabled = True
        terminal_bank = Decimal("0.3")
    elif kind == "tied_plans":
        extras = {"mid_6": PlayerPosition.MID, "mid_7": PlayerPosition.MID}
        values = {
            "n1": {"mid_6": Decimal(6), "mid_7": Decimal(6)},
            "n2": {"mid_6": Decimal(6), "mid_7": Decimal(6)},
        }
    elif kind == "malformed_scenario_probabilities_tree":
        extras = {"mid_6": PlayerPosition.MID}
        nodes = [
            _default_nodes(1)[0],
            {
                "node_id": "n2_a",
                "parent_id": "n1",
                "gameweek": 2,
                "probability": Decimal("0.4"),
                "revealed": ("a",),
                "availability": {},
                "fixture": {"state": "SCHEDULED"},
                "points_state_id": "points-a",
            },
            {
                "node_id": "n2_b",
                "parent_id": "n1",
                "gameweek": 2,
                "probability": Decimal("0.4"),
                "revealed": ("b",),
                "availability": {},
                "fixture": {"state": "SCHEDULED"},
                "points_state_id": "points-b",
            },
        ]
    elif kind == "illegal_manager_state":
        extras = {"mid_6": PlayerPosition.MID}
        illegal_state = True
    elif kind == "infeasible_future_state":
        extras = {"mid_6": PlayerPosition.MID}
        omit_tactics.add("n2")
    elif kind == "resource_limit_incumbent":
        extras = {"mid_6": PlayerPosition.MID}
        nodes = _default_nodes(1)
        values = {"n1": {"mid_6": Decimal(8)}}
        max_policy_candidates = 1
    elif kind == "no_materially_distinct_alternative":
        nodes = _default_nodes(1)
        max_transfers = 0

    if kind == "retained_selling_profit":
        purchase_prices["mid_1"] = 50
        prices = {"n1": {"mid_1": 54, "mid_6": 52}, "n2": {"mid_1": 54, "mid_6": 52}}
    if kind == "price_fall":
        purchase_prices["mid_1"] = 50
        prices = {"n1": {"mid_1": 48, "mid_6": 48}, "n2": {"mid_1": 48, "mid_6": 48}}

    candidate_pool = _catalog(extras)
    rules = _rules(earn=earn)
    legal_squads = _legal_squads(candidate_pool)
    all_ids = tuple(item.player_id for item in candidate_pool)
    built_nodes: list[ScenarioTreeNode] = []
    information_keys: dict[str, str] = {}
    for raw in sorted(nodes, key=lambda item: (int(item["gameweek"]), str(item["node_id"]))):
        node_id = str(raw["node_id"])
        node_prices = {
            player_id: PlayerPriceState(
                current_price_tenths=prices.get(node_id, {}).get(player_id, 50),
                purchasable=purchasable.get(node_id, {}).get(player_id, True),
            )
            for player_id in all_ids
        }
        node = ScenarioTreeNode(
            node_id=node_id,
            parent_id=raw["parent_id"],
            gameweek=int(raw["gameweek"]),
            conditional_probability=raw["probability"],
            information_set_key="placeholder",
            revealed_information=tuple(raw["revealed"]),
            availability_state=dict(raw["availability"]),
            fixture_state=dict(raw["fixture"]),
            points_state_id=str(raw["points_state_id"]),
            prices=node_prices,
            allowed_transfer_in_ids=(
                tuple(sorted(allowed_transfer_in_ids))
                if allowed_transfer_in_ids is not None
                else tuple(sorted(extras))
            ),
            tactical_values=_records(
                node_id,
                legal_squads,
                values.get(node_id, {}),
                omit=node_id in omit_tactics,
            ),
        )
        parent_key = information_keys.get(node.parent_id) if node.parent_id is not None else None
        key = information_set_key(node, parent_key=parent_key)
        node = node.model_copy(update={"information_set_key": key})
        information_keys[node.node_id] = key
        built_nodes.append(node)
    tree = seal_scenario_tree(
        ScenarioTree(
            tree_id=f"fixture-{kind}",
            nodes=tuple(built_nodes),
            tree_sha256=ZERO_HASH,
        )
    )
    root = tree.root
    active_ids = BASE_SQUAD[:-1] if illegal_state else BASE_SQUAD
    catalog = {item.player_id: item for item in candidate_pool}
    spells = tuple(
        sorted(
            (
                OwnershipSpell(
                    spell_id=f"spell-initial-{player_id}",
                    player_id=player_id,
                    club_id=catalog[player_id].club_id,
                    position=catalog[player_id].position,
                    purchase_price_tenths=purchase_prices.get(player_id, 50),
                    current_price_tenths=root.prices[player_id].current_price_tenths,
                    started_gameweek=1,
                    started_at_node_id=root.node_id,
                )
                for player_id in active_ids
            ),
            key=lambda item: (item.player_id, item.started_gameweek, item.spell_id),
        )
    )
    initial_state = seal_manager_state(
        ManagerState(
            state_id=f"state-initial-{kind}",
            current_gameweek=1,
            observed_node_id=root.node_id,
            bank_tenths=bank,
            free_transfers=free_transfers,
            ownership_spells=spells,
            ruleset_id=rules.ruleset_id,
            ruleset_version=rules.ruleset_version,
            ruleset_hash=rules.ruleset_hash,
            state_sha256=ZERO_HASH,
        )
    )
    search = seal_search_policy(
        SearchPolicy(
            max_transfers_per_node=max_transfers,
            max_actions_per_state=2_000,
            max_state_expansions=5_000,
            max_policy_candidates=max_policy_candidates,
            max_returned_root_candidates=max_returned,
            alternative_expected_sacrifice_points=Decimal(5),
            material_difference_points=Decimal("0.25"),
            deterministic_seed=0,
            policy_sha256=ZERO_HASH,
        )
    )
    terminal = seal_terminal_policy(
        TerminalValuePolicy(
            policy_id="synthetic-terminal-v1",
            policy_version="1.0.0",
            enabled=terminal_enabled,
            bank_points_per_tenth=terminal_bank,
            free_transfer_points=terminal_ft,
            liquidation_points_per_tenth=terminal_liquidation,
            policy_sha256=ZERO_HASH,
        )
    )
    return seal_request(
        MultiGameweekOptimisationRequest(
            request_id=f"fixture-{kind}",
            projection_mode=ProjectionMode.TEST,
            initial_state=initial_state,
            candidate_pool=candidate_pool,
            rules=rules,
            scenario_tree=tree,
            search_policy=search,
            terminal_policy=terminal,
            assumptions=("Synthetic/reference fixture; no target-season rule claim.",),
            request_sha256=ZERO_HASH,
        )
    )
