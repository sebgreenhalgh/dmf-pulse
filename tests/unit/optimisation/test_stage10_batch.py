"""001L exact node-scoped Stage-10 batch equivalence and work proofs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dmf_pulse.fpl_points.models import (
    GameweekAssemblyMode,
    GameweekPointScenario,
    PlayerPosition,
    ProjectionMode,
)
from dmf_pulse.optimisation.models import (
    CandidatePlayer,
    CandidateSquad,
    OneGameweekOptimiserPolicy,
)
from dmf_pulse.optimisation.multi_gameweek_errors import InfeasiblePolicyError
from dmf_pulse.optimisation.multi_gameweek_models import (
    PlayerCatalogEntry,
    PlayerPriceState,
    ScenarioTreeNode,
)
from dmf_pulse.optimisation.multi_gameweek_solver import information_set_key
from dmf_pulse.optimisation.stage10_adapter import Stage10TacticalAdapter
from dmf_pulse.optimisation.tactics import (
    ExactTacticalNodeKernel,
    optimise_fixed_squad_tactics_exact,
)
from dmf_pulse.rules.one_gameweek import build_one_gameweek_rules_view
from tests.support.optimisation_factories import POINT_COMPONENTS, players, synthetic_ruleset

pytestmark = pytest.mark.unit


def _players() -> tuple[CandidatePlayer, ...]:
    extras = (
        CandidatePlayer(player_id="p15", club_id="club-15", position=PlayerPosition.DEF),
        CandidatePlayer(player_id="p16", club_id="club-16", position=PlayerPosition.MID),
        CandidatePlayer(player_id="p17", club_id="club-17", position=PlayerPosition.FWD),
    )
    return tuple(sorted((*players(), *extras), key=lambda item: item.player_id))


def _squads() -> tuple[CandidateSquad, ...]:
    base = tuple(item.player_id for item in players())
    replacements = (("p06", "p15"), ("p11", "p16"), ("p14", "p17"))
    values = [base]
    for outgoing, incoming in replacements:
        values.append(tuple(sorted((set(base) - {outgoing}) | {incoming})))
    return tuple(CandidateSquad(player_ids=value) for value in values)


def _scenarios(candidate_ids: tuple[str, ...]) -> tuple[GameweekPointScenario, ...]:
    absent_sets = (
        frozenset(),
        frozenset({"p00"}),
        frozenset({"p02"}),
        frozenset({"p02", "p03", "p07"}),
        frozenset({"p04", "p08", "p12"}),
        frozenset({"p00", "p01", "p05", "p10"}),
        frozenset({"p06", "p11", "p14"}),
        frozenset(candidate_ids),
    )
    weights = (0.05, 0.10, 0.15, 0.20, 0.05, 0.10, 0.15, 0.20)
    values: list[GameweekPointScenario] = []
    for scenario_index, (absent, weight) in enumerate(zip(absent_sets, weights, strict=True)):
        points = {
            player_id: ((index * 7 + scenario_index * 3) % 19) - 4
            for index, player_id in enumerate(candidate_ids)
        }
        appeared = {player_id: player_id not in absent for player_id in candidate_ids}
        values.append(
            GameweekPointScenario(
                scenario_id=f"batch-{scenario_index}",
                outcome_draw_id=f"draw-{scenario_index}",
                weight=weight,
                gameweek_id="GW3",
                fixture_ids=("fixture",),
                player_points=points,
                player_components={
                    player_id: {
                        component: (points[player_id] if component == "appearance" else 0)
                        for component in POINT_COMPONENTS
                    }
                    for player_id in candidate_ids
                },
                player_bps={player_id: 0 for player_id in candidate_ids},
                player_bonus={player_id: 0 for player_id in candidate_ids},
                player_minutes={
                    player_id: 90 if appeared[player_id] else 0 for player_id in candidate_ids
                },
                player_appeared=appeared,
                assembly_mode=GameweekAssemblyMode.SINGLE_FIXTURE,
                approximation_labels=(),
            )
        )
    return tuple(values)


def _policy() -> OneGameweekOptimiserPolicy:
    return OneGameweekOptimiserPolicy(
        max_squad_candidates=300,
        max_tactical_configurations=5_000_000,
        max_scenario_score_operations=2_000_000_000,
        max_returned_ties=16,
    )


def _node(candidate_ids: tuple[str, ...]) -> ScenarioTreeNode:
    preliminary = ScenarioTreeNode(
        node_id="GW3-root",
        gameweek=3,
        conditional_probability=1,
        information_set_key="pending",
        points_state_id="stage9",
        prices={
            player_id: PlayerPriceState(current_price_tenths=50) for player_id in candidate_ids
        },
        tactical_values=(),
    )
    return preliminary.model_copy(
        update={"information_set_key": information_set_key(preliminary, parent_key=None)}
    )


def test_node_kernel_matches_retained_reference_for_absence_and_weight_golden() -> None:
    candidate_players = _players()
    player_map = {item.player_id: item for item in candidate_players}
    scenarios = _scenarios(tuple(player_map))
    rules = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    kernel = ExactTacticalNodeKernel(
        scenarios=scenarios,
        players=player_map,
        rules=rules,
    )

    for squad in _squads():
        reference = optimise_fixed_squad_tactics_exact(
            squad, scenarios, player_map, rules, _policy()
        )
        accelerated = kernel.optimise(squad, _policy())

        assert accelerated == reference

    work = kernel.work_snapshot()
    assert work.squads_evaluated == len(_squads())
    assert work.logical_scenario_operations > 5 * work.factored_scenario_operations
    assert work.canonical_scenario_operations == len(_squads()) * len(scenarios)


def test_node_kernel_preserves_tied_optima_and_canonical_hash() -> None:
    candidate_players = tuple(players())
    player_map = {item.player_id: item for item in candidate_players}
    candidate_ids = tuple(player_map)
    scenarios = tuple(
        scenario.model_copy(
            update={
                "player_points": {player_id: 0 for player_id in candidate_ids},
                "player_components": {
                    player_id: {component: 0 for component in POINT_COMPONENTS}
                    for player_id in candidate_ids
                },
            }
        )
        for scenario in _scenarios(candidate_ids)[:2]
    )
    scenarios = (
        scenarios[0].model_copy(update={"weight": 0.25}),
        scenarios[1].model_copy(update={"weight": 0.75}),
    )
    rules = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    squad = CandidateSquad(player_ids=candidate_ids)

    reference = optimise_fixed_squad_tactics_exact(squad, scenarios, player_map, rules, _policy())
    accelerated = ExactTacticalNodeKernel(
        scenarios=scenarios,
        players=player_map,
        rules=rules,
    ).optimise(squad, _policy())

    assert accelerated == reference
    assert accelerated[3] > 1
    assert accelerated[0].plan_sha256 == reference[0].plan_sha256


def test_batch_adapter_is_exact_order_independent_and_reports_truthful_progress() -> None:
    candidate_players = _players()
    candidate_ids = tuple(item.player_id for item in candidate_players)
    scenarios = _scenarios(candidate_ids)
    rules = build_one_gameweek_rules_view(synthetic_ruleset(), projection_mode=ProjectionMode.TEST)
    adapter = Stage10TacticalAdapter(
        candidate_pool=tuple(
            PlayerCatalogEntry(
                player_id=item.player_id,
                club_id=item.club_id,
                position=item.position,
            )
            for item in candidate_players
        ),
        rules=rules,
        policy=_policy(),
        scenarios_by_node={"GW3-root": scenarios},
    )
    node = _node(candidate_ids)
    squads = _squads()
    progress: list[tuple[int, int]] = []

    reference = {
        squad.player_ids: adapter.evaluate(
            node=node,
            state=SimpleNamespace(squad_ids=squad.player_ids),  # type: ignore[arg-type]
        )
        for squad in squads
    }
    forward = adapter.evaluate_many(
        node=node,
        squads=(*squads, squads[0]),
        progress=progress.append,
    )
    reverse = adapter.evaluate_many(node=node, squads=tuple(reversed(squads)))

    assert forward == reference == reverse
    assert tuple(forward) == tuple(sorted(forward))
    assert progress == [(index, len(squads)) for index in range(1, len(squads) + 1)]


def test_batch_adapter_fails_closed_for_missing_scenarios_or_kernel_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_players = _players()
    candidate_ids = tuple(item.player_id for item in candidate_players)
    scenarios = _scenarios(candidate_ids)
    adapter = Stage10TacticalAdapter(
        candidate_pool=tuple(
            PlayerCatalogEntry(
                player_id=item.player_id,
                club_id=item.club_id,
                position=item.position,
            )
            for item in candidate_players
        ),
        rules=build_one_gameweek_rules_view(
            synthetic_ruleset(), projection_mode=ProjectionMode.TEST
        ),
        policy=_policy(),
        scenarios_by_node={"GW3-root": scenarios},
    )
    node = _node(candidate_ids)

    with pytest.raises(InfeasiblePolicyError, match="no Stage-9 joint scenarios"):
        adapter.evaluate_many(
            node=node.model_copy(update={"node_id": "missing"}),
            squads=(_squads()[0],),
        )

    def fail_kernel(*_args: object, **_kwargs: object) -> object:
        raise ValueError("synthetic exact-kernel failure")

    monkeypatch.setattr(ExactTacticalNodeKernel, "optimise", fail_kernel)
    with pytest.raises(InfeasiblePolicyError, match="found no legal plan"):
        adapter.evaluate_many(node=node, squads=(_squads()[0],))
