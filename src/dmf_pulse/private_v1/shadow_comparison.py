"""Offline four-world R9C-A1.03 decision comparison over the canonical service.

This module is intentionally unreferenced by ordinary private recommendation
construction.  It invokes the existing rolling service once per isolated world
and records lineage/equality assertions; it does not implement an optimiser,
projector, transport, or alternate active prior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Literal

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.current_player_posterior import CurrentPlayerAllocationShadow
from dmf_pulse.private_v1.rolling import (
    PrivateV1RollingRecommendationService,
    PrivateV1RollingRunResult,
)
from dmf_pulse.private_v1.rolling_models import PrivateV1RollingExecutionInput
from dmf_pulse.private_v1.shadow_adapter import ShadowFixtureAllocationProfileResolver

ComparisonWorld = Literal["STALE", "CENTRAL_TEMPORARY", "LOW_SHRINKAGE", "HIGH_SHRINKAGE"]
FrozenFixtureHashes = tuple[tuple[int, tuple[tuple[str, str], ...]], ...]
FrozenGameweekHashes = tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class ShadowDecisionSignature:
    """Opaque decision fields whose equality defines one world-level policy."""

    root_action_signature: str
    by_gameweek_action_signatures: tuple[str, str, str]
    tactical_plan_sha256s: tuple[str, str, str]
    optimiser_result_sha256: str
    semantic_sha256: str


@dataclass(frozen=True, slots=True)
class ShadowComparisonWorldResult:
    world: ComparisonWorld
    decision_signature: ShadowDecisionSignature
    rolling_decision_sha256: str
    stage7_context_sha256_by_gameweek: FrozenFixtureHashes
    stage8_distribution_sha256_by_gameweek: FrozenFixtureHashes
    stage9_fixture_projection_sha256_by_gameweek: FrozenFixtureHashes
    stage9_gameweek_projection_sha256_by_gameweek: FrozenGameweekHashes
    scenario_alignment_sha256_by_gameweek: FrozenGameweekHashes
    candidate_screen_sha256: str
    candidate_screen_node_count: int
    plan_expected_horizon_utility: Decimal
    baseline_expected_horizon_utility: Decimal
    expected_uplift: Decimal
    timing_ms_by_stage: tuple[tuple[str, Decimal], ...]
    semantic_sha256: str


@dataclass(frozen=True, slots=True)
class ShadowComparisonPair:
    left: ComparisonWorld
    right: ComparisonWorld
    root_action_equal: bool
    continuation_policy_equal: bool
    candidate_screen_equal: bool
    classification: Literal["ROBUST", "ROOT_SENSITIVE", "CONTINUATION_SENSITIVE"]


@dataclass(frozen=True, slots=True)
class FourWorldShadowComparison:
    schema_version: str
    rolling_execution_input_sha256: str
    shadow_sha256: str
    results: tuple[
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
    ]
    pairs: tuple[ShadowComparisonPair, ...]
    stage7_stage8_equal: bool
    model_input_status: str
    production_activation: bool
    new_network_requests: int
    persistence_performed: bool
    semantic_sha256: str


def _hash_dataclass(
    value: ShadowDecisionSignature | ShadowComparisonWorldResult | FourWorldShadowComparison,
) -> str:
    """Hash a sealed comparison record without its derived seal field."""

    payload = asdict(value)
    return canonical_sha256(
        _canonical_value({key: item for key, item in payload.items() if key != "semantic_sha256"})
    )


def _canonical_value(value: object) -> object:
    """Represent timing/utility decimals exactly in the JSON hash contract."""

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in value.items()
            if key != "timing_ms_by_stage"
        }
    if isinstance(value, (list, tuple)):
        return tuple(_canonical_value(item) for item in value)
    return value


def _seal_signature(value: ShadowDecisionSignature) -> ShadowDecisionSignature:
    return ShadowDecisionSignature(
        root_action_signature=value.root_action_signature,
        by_gameweek_action_signatures=value.by_gameweek_action_signatures,
        tactical_plan_sha256s=value.tactical_plan_sha256s,
        optimiser_result_sha256=value.optimiser_result_sha256,
        semantic_sha256=_hash_dataclass(value),
    )


def _seal_world_result(value: ShadowComparisonWorldResult) -> ShadowComparisonWorldResult:
    return ShadowComparisonWorldResult(
        world=value.world,
        decision_signature=value.decision_signature,
        rolling_decision_sha256=value.rolling_decision_sha256,
        stage7_context_sha256_by_gameweek=value.stage7_context_sha256_by_gameweek,
        stage8_distribution_sha256_by_gameweek=value.stage8_distribution_sha256_by_gameweek,
        stage9_fixture_projection_sha256_by_gameweek=value.stage9_fixture_projection_sha256_by_gameweek,
        stage9_gameweek_projection_sha256_by_gameweek=value.stage9_gameweek_projection_sha256_by_gameweek,
        scenario_alignment_sha256_by_gameweek=value.scenario_alignment_sha256_by_gameweek,
        candidate_screen_sha256=value.candidate_screen_sha256,
        candidate_screen_node_count=value.candidate_screen_node_count,
        plan_expected_horizon_utility=value.plan_expected_horizon_utility,
        baseline_expected_horizon_utility=value.baseline_expected_horizon_utility,
        expected_uplift=value.expected_uplift,
        timing_ms_by_stage=value.timing_ms_by_stage,
        semantic_sha256=_hash_dataclass(value),
    )


def _seal_comparison(value: FourWorldShadowComparison) -> FourWorldShadowComparison:
    return FourWorldShadowComparison(
        schema_version=value.schema_version,
        rolling_execution_input_sha256=value.rolling_execution_input_sha256,
        shadow_sha256=value.shadow_sha256,
        results=value.results,
        pairs=value.pairs,
        stage7_stage8_equal=value.stage7_stage8_equal,
        model_input_status=value.model_input_status,
        production_activation=value.production_activation,
        new_network_requests=value.new_network_requests,
        persistence_performed=value.persistence_performed,
        semantic_sha256=_hash_dataclass(value),
    )


def _scenario_alignment(run: PrivateV1RollingRunResult) -> dict[int, str]:
    """Bind scenario IDs and probabilities, not their Stage-9 point values."""

    return {
        int(projection.scenario_set.gameweek_id.removeprefix("GW-")): canonical_sha256(
            tuple(
                (item.scenario_id, str(item.weight)) for item in projection.scenario_set.scenarios
            )
        )
        for projection in run.gameweek_projections
    }


def _freeze_fixture_hashes(value: dict[int, dict[str, str]]) -> FrozenFixtureHashes:
    return tuple(
        (gameweek, tuple(sorted(items.items()))) for gameweek, items in sorted(value.items())
    )


def _freeze_gameweek_hashes(value: dict[int, str]) -> FrozenGameweekHashes:
    return tuple(sorted(value.items()))


def _candidate_screen_sha(run: PrivateV1RollingRunResult) -> tuple[str, int]:
    nodes = tuple(
        (
            node.node_id,
            node.gameweek,
            node.allowed_transfer_in_ids,
        )
        for node in run.optimiser_request.scenario_tree.nodes
    )
    return canonical_sha256(nodes), len(nodes)


def _world_result(
    world: ComparisonWorld, run: PrivateV1RollingRunResult
) -> ShadowComparisonWorldResult:
    decision = run.decision
    by_gameweek = tuple(item.tactical_plan_sha256 for item in decision.by_gameweek)
    if len(by_gameweek) != 3:
        raise ValueError("canonical rolling decision does not contain three Gameweeks")
    action_signatures = tuple(
        canonical_sha256(
            {
                "gameweek": item.gameweek,
                "transfers": tuple(move.model_dump(mode="json") for move in item.transfers),
                "hit_points": item.hit_points,
                "bank_after_tenths": item.bank_after_tenths,
            }
        )
        for item in decision.by_gameweek
    )
    signature = _seal_signature(
        ShadowDecisionSignature(
            root_action_signature=canonical_sha256(
                {
                    "gameweek": decision.do_now.gameweek,
                    "transfers": tuple(
                        move.model_dump(mode="json") for move in decision.do_now.transfers
                    ),
                    "hit_points": decision.do_now.hit_points,
                    "bank_after_tenths": decision.do_now.bank_after_tenths,
                }
            ),
            by_gameweek_action_signatures=(
                action_signatures[0],
                action_signatures[1],
                action_signatures[2],
            ),
            tactical_plan_sha256s=(by_gameweek[0], by_gameweek[1], by_gameweek[2]),
            optimiser_result_sha256=decision.lineage.optimiser_result_sha256,
            semantic_sha256="",
        )
    )
    candidate_screen_sha, node_count = _candidate_screen_sha(run)
    lineage = decision.lineage
    return _seal_world_result(
        ShadowComparisonWorldResult(
            world=world,
            decision_signature=signature,
            rolling_decision_sha256=decision.semantic_sha256,
            stage7_context_sha256_by_gameweek=_freeze_fixture_hashes(
                lineage.stage7_context_sha256_by_gameweek
            ),
            stage8_distribution_sha256_by_gameweek=_freeze_fixture_hashes(
                lineage.stage8_distribution_sha256_by_gameweek
            ),
            stage9_fixture_projection_sha256_by_gameweek=_freeze_fixture_hashes(
                lineage.fixture_projection_sha256_by_gameweek
            ),
            stage9_gameweek_projection_sha256_by_gameweek=_freeze_gameweek_hashes(
                lineage.gameweek_projection_sha256_by_gameweek
            ),
            scenario_alignment_sha256_by_gameweek=_freeze_gameweek_hashes(_scenario_alignment(run)),
            candidate_screen_sha256=candidate_screen_sha,
            candidate_screen_node_count=node_count,
            plan_expected_horizon_utility=(
                decision.horizon_comparison.plan_expected_horizon_utility
            ),
            baseline_expected_horizon_utility=(
                decision.horizon_comparison.baseline_expected_horizon_utility
            ),
            expected_uplift=decision.horizon_comparison.expected_uplift,
            timing_ms_by_stage=tuple((item.stage, item.elapsed_ms) for item in run.stage_timings),
            semantic_sha256="",
        )
    )


def _pair(
    left: ShadowComparisonWorldResult, right: ShadowComparisonWorldResult
) -> ShadowComparisonPair:
    root_equal = (
        left.decision_signature.root_action_signature
        == right.decision_signature.root_action_signature
    )
    continuation_equal = (
        left.decision_signature.by_gameweek_action_signatures[1:]
        == right.decision_signature.by_gameweek_action_signatures[1:]
    )
    return ShadowComparisonPair(
        left=left.world,
        right=right.world,
        root_action_equal=root_equal,
        continuation_policy_equal=continuation_equal,
        candidate_screen_equal=left.candidate_screen_sha256 == right.candidate_screen_sha256,
        classification=(
            "ROBUST"
            if root_equal and continuation_equal
            else "CONTINUATION_SENSITIVE"
            if root_equal
            else "ROOT_SENSITIVE"
        ),
    )


def run_four_world_shadow_comparison(
    execution: PrivateV1RollingExecutionInput,
    shadow: CurrentPlayerAllocationShadow,
) -> FourWorldShadowComparison:
    """Run STALE and each compiled shadow world with isolated service state.

    The stale call intentionally uses ordinary construction with no resolver.
    Every injected world gets a fresh service and resolver, preventing tactical
    or optimiser cache state from crossing a world boundary.
    """

    shadow = CurrentPlayerAllocationShadow.model_validate(shadow.model_dump(mode="python"))
    runs: list[tuple[ComparisonWorld, PrivateV1RollingRunResult]] = [
        ("STALE", PrivateV1RollingRecommendationService().run(execution))
    ]
    for world in ("CENTRAL_TEMPORARY", "LOW_SHRINKAGE", "HIGH_SHRINKAGE"):
        resolver = ShadowFixtureAllocationProfileResolver(shadow=shadow, world=world)
        runs.append(
            (
                world,
                PrivateV1RollingRecommendationService(_allocation_profile_resolver=resolver).run(
                    execution
                ),
            )
        )
    results = tuple(_world_result(world, run) for world, run in runs)
    reference = results[0]
    if any(
        item.stage7_context_sha256_by_gameweek != reference.stage7_context_sha256_by_gameweek
        or item.stage8_distribution_sha256_by_gameweek
        != reference.stage8_distribution_sha256_by_gameweek
        for item in results[1:]
    ):
        raise ValueError("shadow comparison changed Stage-7 or Stage-8 lineage")
    if any(
        item.scenario_alignment_sha256_by_gameweek
        != reference.scenario_alignment_sha256_by_gameweek
        for item in results[1:]
    ):
        raise ValueError("shadow comparison scenario IDs/probabilities diverged")
    pairs = tuple(
        _pair(results[left], results[right])
        for left in range(len(results))
        for right in range(left + 1, len(results))
    )
    return _seal_comparison(
        FourWorldShadowComparison(
            schema_version="r9c-a1-four-world-three-gw-shadow-comparison-v1",
            rolling_execution_input_sha256=execution.semantic_sha256,
            shadow_sha256=shadow.semantic_sha256,
            results=(results[0], results[1], results[2], results[3]),
            pairs=pairs,
            stage7_stage8_equal=True,
            model_input_status="SHADOW_NOT_MODEL_INPUT",
            production_activation=False,
            new_network_requests=0,
            persistence_performed=False,
            semantic_sha256="",
        )
    )


__all__ = [
    "ComparisonWorld",
    "FourWorldShadowComparison",
    "ShadowComparisonPair",
    "ShadowComparisonWorldResult",
    "ShadowDecisionSignature",
    "run_four_world_shadow_comparison",
]
