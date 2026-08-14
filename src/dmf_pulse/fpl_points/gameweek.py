"""Coherent blank, single, and shared-draw multi-fixture Gameweek assembly."""

from __future__ import annotations

from math import isclose

from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.models import (
    POINT_COMPONENT_NAMES,
    BpsCompletenessMode,
    ConfidenceGrade,
    FixtureProjectionResult,
    GameweekAssemblyMode,
    GameweekPointScenario,
    GameweekScenarioSet,
    SimulationStatus,
)
from dmf_pulse.fpl_points.seed import stable_identifier


def assemble_blank_gameweek(
    *,
    gameweek_id: str,
    player_ids: tuple[str, ...],
    ruleset_hash: str,
    confidence_grade: ConfidenceGrade = "E",
    model_version_ids: tuple[str, ...] = (),
    dataset_version_ids: tuple[str, ...] = (),
    source_bundle_ids: tuple[str, ...] = (),
    upstream_stage8_sha256s: tuple[str, ...] = (),
) -> GameweekScenarioSet:
    players = tuple(sorted(set(player_ids)))
    scenario = GameweekPointScenario(
        scenario_id=stable_identifier("blank", 0, gameweek_id),
        outcome_draw_id=stable_identifier("blank-draw", 0, gameweek_id),
        weight=1.0,
        gameweek_id=gameweek_id,
        fixture_ids=(),
        player_points={player_id: 0 for player_id in players},
        player_components={
            player_id: {component: 0 for component in POINT_COMPONENT_NAMES}
            for player_id in players
        },
        player_bps={player_id: 0 for player_id in players},
        player_bonus={player_id: 0 for player_id in players},
        assembly_mode=GameweekAssemblyMode.BLANK,
        approximation_labels=(),
    )
    return GameweekScenarioSet(
        gameweek_id=gameweek_id,
        scenarios=(scenario,),
        player_ids=players,
        ruleset_hash=ruleset_hash,
        assembly_mode=GameweekAssemblyMode.BLANK,
        bps_completeness_mode=BpsCompletenessMode.EVENT_LINKED_ONLY,
        confidence_grade=confidence_grade,
        model_version_ids=tuple(sorted(set(model_version_ids))),
        dataset_version_ids=tuple(sorted(set(dataset_version_ids))),
        source_bundle_ids=tuple(sorted(set(source_bundle_ids))),
        upstream_stage8_sha256s=tuple(sorted(set(upstream_stage8_sha256s))),
        warnings=(),
    )


def assemble_gameweek(
    fixture_results: tuple[FixtureProjectionResult, ...],
) -> GameweekScenarioSet:
    if not fixture_results:
        raise FplPointsError(
            "GAMEWEEK_FIXTURES_EMPTY",
            "use assemble_blank_gameweek for a blank Gameweek",
        )
    if any(result.status is not SimulationStatus.SUCCESS for result in fixture_results):
        raise FplPointsError("GAMEWEEK_FIXTURE_BLOCKED", "all fixture projections must succeed")
    fixture_ids = tuple(result.fixture_id for result in fixture_results)
    if len(set(fixture_ids)) != len(fixture_ids):
        raise FplPointsError(
            "GAMEWEEK_FIXTURE_DUPLICATE",
            "Gameweek assembly requires unique fixture identities",
        )
    gameweeks = {result.gameweek_id for result in fixture_results}
    if len(gameweeks) != 1:
        raise FplPointsError("GAMEWEEK_ID_MISMATCH", "fixtures belong to different Gameweeks")
    rulesets = {result.ruleset.ruleset_hash for result in fixture_results}
    if len(rulesets) != 1:
        raise FplPointsError("GAMEWEEK_RULESET_MISMATCH", "fixtures use different rulesets")
    bps_modes = {
        scenario.bps_completeness_mode
        for result in fixture_results
        for scenario in result.scenarios
    }
    if len(bps_modes) != 1:
        raise FplPointsError("GAMEWEEK_BPS_MODE_MISMATCH", "fixtures mix BPS completeness modes")
    gameweek_id = next(iter(gameweeks))
    fixture_results = tuple(sorted(fixture_results, key=lambda item: item.fixture_id))
    if len(fixture_results) == 1:
        result = fixture_results[0]
        scenarios = tuple(
            GameweekPointScenario(
                scenario_id=scenario.scenario_id,
                outcome_draw_id=scenario.outcome_draw_id,
                weight=scenario.weight,
                gameweek_id=gameweek_id,
                fixture_ids=(result.fixture_id,),
                player_points={
                    player_id: score.total for player_id, score in scenario.players.items()
                },
                player_components={
                    player_id: {
                        component: getattr(score, component) for component in POINT_COMPONENT_NAMES
                    }
                    for player_id, score in scenario.players.items()
                },
                player_bps={player_id: score.bps for player_id, score in scenario.players.items()},
                player_bonus={
                    player_id: score.bonus for player_id, score in scenario.players.items()
                },
                assembly_mode=GameweekAssemblyMode.SINGLE_FIXTURE,
                approximation_labels=(),
            )
            for scenario in result.scenarios
        )
        player_ids = tuple(sorted(result.scenarios[0].players))
        return GameweekScenarioSet(
            gameweek_id=gameweek_id,
            scenarios=scenarios,
            player_ids=player_ids,
            ruleset_hash=next(iter(rulesets)),
            assembly_mode=GameweekAssemblyMode.SINGLE_FIXTURE,
            bps_completeness_mode=result.scenarios[0].bps_completeness_mode,
            confidence_grade=result.scenarios[0].confidence_grade,
            model_version_ids=tuple(
                sorted(
                    {item for scenario in result.scenarios for item in scenario.model_version_ids}
                )
            ),
            dataset_version_ids=tuple(
                sorted(
                    {item for scenario in result.scenarios for item in scenario.dataset_version_ids}
                )
            ),
            source_bundle_ids=tuple(
                sorted(
                    {item for scenario in result.scenarios for item in scenario.source_bundle_ids}
                )
            ),
            upstream_stage8_sha256s=(result.upstream_stage8_sha256,),
            warnings=(),
        )
    maps = [
        {scenario.outcome_draw_id: scenario for scenario in result.scenarios}
        for result in fixture_results
    ]
    draw_ids = set(maps[0])
    if any(set(mapping) != draw_ids for mapping in maps[1:]):
        raise FplPointsError(
            "GAMEWEEK_SHARED_DRAW_MISMATCH",
            "multi-fixture assembly requires the same shared outcome-draw IDs",
        )
    assembled: list[GameweekPointScenario] = []
    all_players: set[str] = set()
    for draw_id in sorted(draw_ids):
        fixture_scenarios = tuple(mapping[draw_id] for mapping in maps)
        reference_weight = fixture_scenarios[0].weight
        if any(
            not isclose(item.weight, reference_weight, rel_tol=0.0, abs_tol=1e-12)
            for item in fixture_scenarios[1:]
        ):
            raise FplPointsError(
                "GAMEWEEK_SHARED_WEIGHT_MISMATCH", "shared draws have inconsistent weights"
            )
        totals: dict[str, int] = {}
        components: dict[str, dict[str, int]] = {}
        bps_totals: dict[str, int] = {}
        bonus_totals: dict[str, int] = {}
        for scenario in fixture_scenarios:
            for player_id, score in scenario.players.items():
                totals[player_id] = totals.get(player_id, 0) + score.total
                player_components = components.setdefault(
                    player_id, {component: 0 for component in POINT_COMPONENT_NAMES}
                )
                for component in POINT_COMPONENT_NAMES:
                    player_components[component] += getattr(score, component)
                bps_totals[player_id] = bps_totals.get(player_id, 0) + score.bps
                bonus_totals[player_id] = bonus_totals.get(player_id, 0) + score.bonus
                all_players.add(player_id)
        assembled.append(
            GameweekPointScenario(
                scenario_id=stable_identifier(
                    "gw", fixture_scenarios[0].root_seed, gameweek_id, draw_id
                ),
                outcome_draw_id=draw_id,
                weight=reference_weight,
                gameweek_id=gameweek_id,
                fixture_ids=tuple(result.fixture_id for result in fixture_results),
                player_points=dict(sorted(totals.items())),
                player_components={key: components[key] for key in sorted(components)},
                player_bps=dict(sorted(bps_totals.items())),
                player_bonus=dict(sorted(bonus_totals.items())),
                assembly_mode=GameweekAssemblyMode.SHARED_OUTCOME_DRAW,
                approximation_labels=("NO_SEQUENTIAL_CROSS_FIXTURE_TRANSITION",),
            )
        )
    total_weight = sum(scenario.weight for scenario in assembled)
    if not isclose(total_weight, 1.0, rel_tol=0.0, abs_tol=1e-10):
        raise FplPointsError("GAMEWEEK_WEIGHTS_INVALID", "assembled weights do not sum to one")
    return GameweekScenarioSet(
        gameweek_id=gameweek_id,
        scenarios=tuple(assembled),
        player_ids=tuple(sorted(all_players)),
        ruleset_hash=next(iter(rulesets)),
        assembly_mode=GameweekAssemblyMode.SHARED_OUTCOME_DRAW,
        bps_completeness_mode=next(iter(bps_modes)),
        confidence_grade=max(
            (
                scenario.confidence_grade
                for result in fixture_results
                for scenario in result.scenarios
            ),
            key=lambda grade: "ABCDE".index(grade),
        ),
        model_version_ids=tuple(
            sorted(
                {
                    item
                    for result in fixture_results
                    for scenario in result.scenarios
                    for item in scenario.model_version_ids
                }
            )
        ),
        dataset_version_ids=tuple(
            sorted(
                {
                    item
                    for result in fixture_results
                    for scenario in result.scenarios
                    for item in scenario.dataset_version_ids
                }
            )
        ),
        source_bundle_ids=tuple(
            sorted(
                {
                    item
                    for result in fixture_results
                    for scenario in result.scenarios
                    for item in scenario.source_bundle_ids
                }
            )
        ),
        upstream_stage8_sha256s=tuple(
            sorted({result.upstream_stage8_sha256 for result in fixture_results})
        ),
        warnings=(
            "Cross-fixture injuries, dismissals, fatigue, and readiness transitions are not yet "
            "propagated; fixture draws share deterministic latent draw identity only.",
        ),
    )
