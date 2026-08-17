"""Complete deterministic Stage-11 synthetic/reference fixtures."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from dmf_pulse.fpl_points.artifacts import semantic_sha256
from dmf_pulse.fpl_points.models import (
    GameweekAssemblyMode,
    GameweekPointScenario,
    PlayerPosition,
    ProjectionMode,
)
from dmf_pulse.optimisation.manager_state import (
    ManagerState,
    OwnershipSpell,
    seal_manager_state,
)
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidateSquad,
    OptimalityGuarantee,
    SearchScope,
    SolverStatus,
    TacticalConfiguration,
)
from dmf_pulse.optimisation.multi_gameweek_models import (
    MultiGameweekOptimisationRequest,
    PlayerCatalogEntry,
    PlayerPriceState,
    ScenarioTree,
    ScenarioTreeNode,
    SearchPolicy,
    TacticalValueRecord,
    TerminalValuePolicy,
    TransferRules,
    seal_request,
    seal_scenario_tree,
    seal_search_policy,
    seal_terminal_policy,
)
from dmf_pulse.optimisation.multi_gameweek_solver import information_set_key
from dmf_pulse.optimisation.tactics import evaluate_tactical_configuration
from dmf_pulse.rules.compiler import load_compiled_ruleset
from dmf_pulse.rules.multi_gameweek import build_multi_gameweek_transfer_rules
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view

POINT_COMPONENTS = (
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


@dataclass(frozen=True)
class NodeSpec:
    node_id: str
    gameweek: int
    parent_id: str | None = None
    conditional_probability: Decimal = Decimal(1)
    revealed_information: tuple[str, ...] = ()
    points: dict[str, int] = field(default_factory=dict)
    prices: dict[str, int] = field(default_factory=dict)
    purchasable: dict[str, bool] = field(default_factory=dict)
    allowed_transfer_in_ids: tuple[str, ...] = ()
    squads: tuple[tuple[str, ...], ...] = ()
    availability_state: dict[str, str] = field(default_factory=dict)
    fixture_state: dict[str, str] = field(default_factory=dict)
    transition_event: str = "NORMAL"


def compiled_ruleset():
    return load_compiled_ruleset(
        Path("fixtures/optimisation/multi_gameweek/reference_ruleset_test_only.json")
    )


def transfer_rules(*, projection_mode: ProjectionMode = ProjectionMode.TEST) -> TransferRules:
    return build_multi_gameweek_transfer_rules(compiled_ruleset(), projection_mode=projection_mode)


def player_catalog(*, include_second_mid: bool = False) -> tuple[PlayerCatalogEntry, ...]:
    positions = (
        ("p00", PlayerPosition.GK),
        ("p01", PlayerPosition.GK),
        ("p02", PlayerPosition.DEF),
        ("p03", PlayerPosition.DEF),
        ("p04", PlayerPosition.DEF),
        ("p05", PlayerPosition.DEF),
        ("p06", PlayerPosition.DEF),
        ("p07", PlayerPosition.MID),
        ("p08", PlayerPosition.MID),
        ("p09", PlayerPosition.MID),
        ("p10", PlayerPosition.MID),
        ("p11", PlayerPosition.MID),
        ("p12", PlayerPosition.FWD),
        ("p13", PlayerPosition.FWD),
        ("p14", PlayerPosition.FWD),
        ("p15", PlayerPosition.MID),
        ("p16", PlayerPosition.FWD),
        ("p17", PlayerPosition.DEF),
        ("p18", PlayerPosition.GK),
    )
    values = list(positions)
    if include_second_mid:
        values.append(("p19", PlayerPosition.MID))
    return tuple(
        PlayerCatalogEntry(player_id=player_id, club_id=f"club-{player_id}", position=position)
        for player_id, position in values
    )


def base_squad() -> tuple[str, ...]:
    return tuple(f"p{index:02d}" for index in range(15))


def replace(squad: tuple[str, ...], player_out: str, player_in: str) -> tuple[str, ...]:
    return tuple(sorted((*set(squad).difference({player_out}), player_in)))


def _manager_state(
    *,
    catalog: tuple[PlayerCatalogEntry, ...],
    rules: TransferRules,
    root_node_id: str,
    gameweek: int,
    bank_tenths: int,
    free_transfers: int,
    purchase_prices: dict[str, int],
    current_prices: dict[str, int],
) -> ManagerState:
    by_id = {item.player_id: item for item in catalog}
    spells = tuple(
        OwnershipSpell(
            spell_id=f"initial-{player_id}",
            player_id=player_id,
            club_id=by_id[player_id].club_id,
            position=by_id[player_id].position,
            purchase_price_tenths=purchase_prices.get(player_id, current_prices[player_id]),
            current_price_tenths=current_prices[player_id],
            started_gameweek=gameweek,
            started_at_node_id=root_node_id,
        )
        for player_id in base_squad()
    )
    return seal_manager_state(
        ManagerState(
            state_id="manager-state-initial",
            current_gameweek=gameweek,
            observed_node_id=root_node_id,
            bank_tenths=bank_tenths,
            free_transfers=free_transfers,
            ownership_spells=spells,
            ruleset_id=rules.ruleset_id,
            ruleset_version=rules.ruleset_version,
            ruleset_hash=rules.ruleset_hash,
            state_sha256="0" * 64,
        )
    )


def _scenario(
    *,
    node_id: str,
    gameweek: int,
    catalog: tuple[PlayerCatalogEntry, ...],
    points: dict[str, int],
) -> tuple[GameweekPointScenario, ...]:
    player_ids = tuple(item.player_id for item in catalog)
    values = {player_id: points.get(player_id, 0) for player_id in player_ids}
    components = {
        player_id: {
            component: (values[player_id] if component == "appearance" else 0)
            for component in POINT_COMPONENTS
        }
        for player_id in player_ids
    }
    return (
        GameweekPointScenario(
            scenario_id=f"{node_id}-scenario",
            outcome_draw_id=f"{node_id}-draw",
            weight=1.0,
            gameweek_id=f"GW{gameweek}",
            fixture_ids=(f"{node_id}-fixture",),
            player_points=values,
            player_components=components,
            player_bps={player_id: 0 for player_id in player_ids},
            player_bonus={player_id: 0 for player_id in player_ids},
            player_minutes={player_id: 90 for player_id in player_ids},
            player_appeared={player_id: True for player_id in player_ids},
            assembly_mode=GameweekAssemblyMode.SINGLE_FIXTURE,
            approximation_labels=(),
        ),
    )


def _tactic(
    squad: tuple[str, ...],
    catalog: tuple[PlayerCatalogEntry, ...],
    points: dict[str, int],
) -> TacticalConfiguration:
    """Construct the exact deterministic Stage-10 optimum for an all-appear scenario."""

    by_id = {item.player_id: item for item in catalog}
    by_position = {
        position: tuple(
            sorted(
                (player_id for player_id in squad if by_id[player_id].position is position),
                key=lambda player_id: (-points.get(player_id, 0), player_id),
            )
        )
        for position in PlayerPosition
    }
    goalkeeper = by_position[PlayerPosition.GK][0]
    candidates: list[tuple[int, tuple[str, ...]]] = []
    for defenders in range(3, 6):
        for midfielders in range(2, 6):
            for forwards in range(1, 4):
                if defenders + midfielders + forwards != 10:
                    continue
                starting = tuple(
                    sorted(
                        (
                            goalkeeper,
                            *by_position[PlayerPosition.DEF][:defenders],
                            *by_position[PlayerPosition.MID][:midfielders],
                            *by_position[PlayerPosition.FWD][:forwards],
                        )
                    )
                )
                candidates.append(
                    (sum(points.get(player_id, 0) for player_id in starting), starting)
                )
    _, starting = min(candidates, key=lambda item: (-item[0], item[1]))
    bench_gk = next(
        player_id for player_id in by_position[PlayerPosition.GK] if player_id != goalkeeper
    )
    bench = tuple(
        sorted(
            player_id
            for player_id in squad
            if player_id not in set(starting) and player_id != bench_gk
        )
    )
    captain_order = tuple(
        sorted(starting, key=lambda player_id: (-points.get(player_id, 0), player_id))
    )
    return TacticalConfiguration(
        starting_xi=starting,
        bench_goalkeeper=bench_gk,
        bench_order=bench,
        captain=captain_order[0],
        vice_captain=captain_order[1],
    )


def _tactical_record(
    *,
    node_id: str,
    gameweek: int,
    squad: tuple[str, ...],
    catalog: tuple[PlayerCatalogEntry, ...],
    points: dict[str, int],
    current_prices: dict[str, int],
) -> TacticalValueRecord:
    compiled = compiled_ruleset()
    tactical_rules = build_one_gameweek_rules_view(compiled, projection_mode=ProjectionMode.TEST)
    players = {
        item.player_id: CandidatePlayer(
            player_id=item.player_id,
            club_id=item.club_id,
            position=item.position,
            initial_selection_cost_tenths=current_prices[item.player_id],
        )
        for item in catalog
    }
    plan, _ = evaluate_tactical_configuration(
        CandidateSquad(player_ids=squad),
        _tactic(squad, catalog, points),
        _scenario(node_id=node_id, gameweek=gameweek, catalog=catalog, points=points),
        players,
        tactical_rules,
        search_scope=SearchScope.FIXED_SQUAD,
    )
    expected = plan.expected_manager_points
    plan = plan.model_copy(
        update={
            "solver_status": SolverStatus(
                termination="OPTIMAL",
                search_scope=SearchScope.FIXED_SQUAD,
                guarantee=OptimalityGuarantee.EXACT_FIXED_SQUAD,
                objective_value=expected,
                best_bound=expected,
                absolute_gap=Decimal(0),
                relative_gap=Decimal(0),
                tied_optima_total=1,
                returned_ties=1,
            ),
            "plan_sha256": "0" * 64,
        }
    )
    plan_payload = plan.model_dump(mode="json")
    plan_payload["plan_sha256"] = None
    plan = plan.model_copy(update={"plan_sha256": semantic_sha256(plan_payload)})
    return TacticalValueRecord(
        squad_ids=squad,
        expected_points=expected,
        p10_points=Decimal(plan.point_distribution.p10),
        p90_points=Decimal(plan.point_distribution.p90),
        tactical_plan_sha256=plan.plan_sha256,
        tactical_plan=plan.model_dump(mode="json"),
        exact_stage10_evaluation=True,
    )


def build_request(
    specs: tuple[NodeSpec, ...],
    *,
    bank_tenths: int = 0,
    free_transfers: int = 1,
    purchase_prices: dict[str, int] | None = None,
    root_prices: dict[str, int] | None = None,
    max_transfers_per_node: int = 2,
    max_actions_per_state: int = 5000,
    max_state_expansions: int = 25000,
    max_policy_candidates: int = 250000,
    max_returned_root_candidates: int = 1000,
    terminal_enabled: bool = False,
    bank_points_per_tenth: Decimal = Decimal(0),
    free_transfer_points: Decimal = Decimal(0),
    liquidation_points_per_tenth: Decimal = Decimal(0),
    include_second_mid: bool = False,
    projection_mode: ProjectionMode = ProjectionMode.TEST,
    request_id: str = "opt011-test-request",
) -> MultiGameweekOptimisationRequest:
    ordered_specs = tuple(sorted(specs, key=lambda item: (item.gameweek, item.node_id)))
    if not ordered_specs or ordered_specs[0].parent_id is not None:
        raise ValueError("the first node specification must be the root")
    catalog = player_catalog(include_second_mid=include_second_mid)
    player_ids = tuple(item.player_id for item in catalog)
    rules = transfer_rules(projection_mode=projection_mode)
    defaults = {player_id: 50 for player_id in player_ids}
    defaults.update(root_prices or {})
    purchase = dict(defaults)
    purchase.update(purchase_prices or {})
    manager = _manager_state(
        catalog=catalog,
        rules=rules,
        root_node_id=ordered_specs[0].node_id,
        gameweek=ordered_specs[0].gameweek,
        bank_tenths=bank_tenths,
        free_transfers=free_transfers,
        purchase_prices=purchase,
        current_prices=defaults,
    )

    nodes: list[ScenarioTreeNode] = []
    information_keys: dict[str, str] = {}
    inherited_prices: dict[str, dict[str, int]] = {}
    for spec in ordered_specs:
        prices = (
            dict(defaults) if spec.parent_id is None else dict(inherited_prices[spec.parent_id])
        )
        prices.update(spec.prices)
        inherited_prices[spec.node_id] = prices
        price_states = {
            player_id: PlayerPriceState(
                current_price_tenths=prices[player_id],
                purchasable=spec.purchasable.get(player_id, True),
            )
            for player_id in player_ids
        }
        squads = spec.squads or (base_squad(),)
        records = tuple(
            sorted(
                (
                    _tactical_record(
                        node_id=spec.node_id,
                        gameweek=spec.gameweek,
                        squad=tuple(sorted(squad)),
                        catalog=catalog,
                        points=spec.points,
                        current_prices=prices,
                    )
                    for squad in squads
                ),
                key=lambda item: item.squad_ids,
            )
        )
        preliminary = ScenarioTreeNode(
            node_id=spec.node_id,
            parent_id=spec.parent_id,
            gameweek=spec.gameweek,
            conditional_probability=spec.conditional_probability,
            information_set_key="temporary",
            revealed_information=tuple(sorted(spec.revealed_information)),
            availability_state=spec.availability_state,
            fixture_state=spec.fixture_state,
            points_state_id=f"{spec.node_id}-points",
            prices=price_states,
            transition_event=spec.transition_event,
            allowed_transfer_in_ids=tuple(sorted(spec.allowed_transfer_in_ids)),
            tactical_values=records,
        )
        key = information_set_key(
            preliminary,
            parent_key=(information_keys[spec.parent_id] if spec.parent_id is not None else None),
        )
        information_keys[spec.node_id] = key
        nodes.append(preliminary.model_copy(update={"information_set_key": key}))

    tree = seal_scenario_tree(
        ScenarioTree(
            tree_id=f"tree-{request_id}",
            nodes=tuple(nodes),
            tree_sha256="0" * 64,
        )
    )
    search = seal_search_policy(
        SearchPolicy(
            max_transfers_per_node=max_transfers_per_node,
            max_actions_per_state=max_actions_per_state,
            max_state_expansions=max_state_expansions,
            max_policy_candidates=max_policy_candidates,
            max_returned_root_candidates=max_returned_root_candidates,
            alternative_expected_sacrifice_points=Decimal(10),
            material_difference_points=Decimal("0.1"),
            deterministic_seed=0,
            policy_sha256="0" * 64,
        )
    )
    terminal = seal_terminal_policy(
        TerminalValuePolicy(
            policy_id="TEST_TERMINAL_BASELINE_V1",
            policy_version="1.0.0",
            enabled=terminal_enabled,
            bank_points_per_tenth=bank_points_per_tenth,
            free_transfer_points=free_transfer_points,
            liquidation_points_per_tenth=liquidation_points_per_tenth,
            policy_sha256="0" * 64,
        )
    )
    return seal_request(
        MultiGameweekOptimisationRequest(
            request_id=request_id,
            projection_mode=projection_mode,
            initial_state=manager,
            candidate_pool=catalog,
            rules=rules,
            scenario_tree=tree,
            search_policy=search,
            terminal_policy=terminal,
            assumptions=("Synthetic/reference Stage-11 fixture.",),
            request_sha256="0" * 64,
        )
    )


def constrain_mid_transfer_prices(
    *,
    target_out: str = "p07",
    target_in: str = "p15",
    target_price: int = 50,
) -> dict[str, int]:
    values = {player_id: 40 for player_id in ("p07", "p08", "p09", "p10", "p11")}
    values[target_out] = target_price
    values[target_in] = target_price
    return values
