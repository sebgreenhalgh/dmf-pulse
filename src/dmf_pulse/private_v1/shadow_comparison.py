"""Offline four-world R9C-A1.03 decision comparison over the canonical service.

This module is intentionally unreferenced by ordinary private recommendation
construction.  It invokes the existing rolling service once per isolated world
and records lineage/equality assertions; it does not implement an optimiser,
projector, transport, or alternate active prior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal
from typing import Any, Literal

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.current_player_posterior import CurrentPlayerAllocationShadow
from dmf_pulse.private_v1.rolling import (
    PrivateRollingStage11Work,
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
    by_gameweek_transfers: tuple[
        tuple[tuple[str, str], ...],
        tuple[tuple[str, str], ...],
        tuple[tuple[str, str], ...],
    ]
    by_gameweek_hit_points: tuple[int, int, int]
    tactical_plan_sha256s: tuple[str, str, str]
    tactical_selection_signatures: tuple[str, str, str]
    optimiser_result_sha256: str
    root_transfers: tuple[tuple[str, str], ...]
    root_hit_points: int
    root_squad_sha256: str
    root_free_transfer_state_sha256: str
    starting_xi: tuple[str, ...]
    captain: str
    vice_captain: str
    semantic_sha256: str

    def __post_init__(self) -> None:
        if len(self.semantic_sha256) != 64 or self.semantic_sha256 != _hash_dataclass(self):
            raise ValueError("decision signature semantic hash does not match")


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
    root_randomness_sha256: str
    fixture_order_sha256: str
    prices_sha256: str
    manager_state_sha256: str
    rules_sha256: str
    work_budget_semantics_sha256: str
    terminal_policy_sha256: str
    candidate_policy_sha256: str
    optimiser_request_sha256: str
    solver_status: Literal["OPTIMAL"]
    recommended_plan_present: Literal[True]
    no_transfer_baseline_present: Literal[True]
    horizon_frontier_present: Literal[True]
    stage11_work: PrivateRollingStage11Work
    gain_p10: int
    gain_median: int
    gain_p90: int
    probability_plan_beats_baseline: Decimal
    frontier_sha256: str
    plan_expected_horizon_utility: Decimal
    baseline_expected_horizon_utility: Decimal
    expected_uplift: Decimal
    timing_ms_by_stage: tuple[tuple[str, Decimal], ...]
    semantic_sha256: str

    def __post_init__(self) -> None:
        if len(self.semantic_sha256) != 64 or self.semantic_sha256 != _hash_dataclass(self):
            raise ValueError("world result semantic hash does not match")


@dataclass(frozen=True, slots=True)
class ShadowComparisonPair:
    left: ComparisonWorld
    right: ComparisonWorld
    root_action_changed: bool
    full_plan_changed: bool
    starting_xi_changed: bool
    captain_changed: bool
    vice_captain_changed: bool
    continuation_changed: bool
    candidate_screen_equal: bool
    optimal_utility_delta: Decimal
    hold_utility_delta: Decimal
    uplift_delta: Decimal
    classification: Literal[
        "EXACT_PLAN_ROBUST",
        "UTILITY_ONLY_MOVEMENT",
        "ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE",
        "ROOT_ACTION_ROBUST_TACTICS_SENSITIVE",
        "WORLD_SENSITIVE_ROOT_ACTION",
    ]
    semantic_sha256: str

    def __post_init__(self) -> None:
        if self.left == self.right:
            raise ValueError("pairwise comparison worlds must differ")
        if len(self.semantic_sha256) != 64 or self.semantic_sha256 != _hash_dataclass(self):
            raise ValueError("pairwise comparison semantic hash does not match")


@dataclass(frozen=True, slots=True)
class FourWorldShadowComparison:
    schema_version: str
    rolling_execution_input_sha256: str
    shadow_sha256: str
    experiment_mode: Literal["SYNTHETIC_OFFLINE_NOT_ACTIVE"]
    target_gameweek: int
    history_gameweeks: tuple[int, ...]
    horizon_gameweeks: tuple[int, int, int]
    information_cutoff_utc: str
    world_set: tuple[ComparisonWorld, ComparisonWorld, ComparisonWorld, ComparisonWorld]
    results: tuple[
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
        ShadowComparisonWorldResult,
    ]
    pairs: tuple[ShadowComparisonPair, ...]
    stage7_identical_across_worlds: bool
    stage8_identical_across_worlds: bool
    root_randomness_aligned: bool
    scenario_identity_aligned: bool
    candidate_universe_same_across_worlds: bool
    prices_identical_across_worlds: bool
    manager_state_identical_across_worlds: bool
    rules_identical_across_worlds: bool
    work_budget_semantics_identical_across_worlds: bool
    model_input_status: str
    production_activation: bool
    new_network_requests: int
    persistence_performed: bool
    semantic_sha256: str

    def __post_init__(self) -> None:
        worlds = tuple(item.world for item in self.results)
        if self.world_set != worlds or worlds != (
            "STALE",
            "CENTRAL_TEMPORARY",
            "LOW_SHRINKAGE",
            "HIGH_SHRINKAGE",
        ):
            raise ValueError("comparison worlds are incomplete or noncanonical")
        expected_pairs = tuple(
            (worlds[left], worlds[right])
            for left in range(len(worlds))
            for right in range(left + 1, len(worlds))
        )
        if tuple((item.left, item.right) for item in self.pairs) != expected_pairs:
            raise ValueError("comparison does not contain the canonical six world pairs")
        if self.horizon_gameweeks != (
            self.target_gameweek,
            self.target_gameweek + 1,
            self.target_gameweek + 2,
        ) or self.history_gameweeks != tuple(range(1, self.target_gameweek)):
            raise ValueError("comparison target, history, and horizon are incoherent")
        controls = (
            self.stage7_identical_across_worlds,
            self.stage8_identical_across_worlds,
            self.root_randomness_aligned,
            self.scenario_identity_aligned,
            self.candidate_universe_same_across_worlds,
            self.prices_identical_across_worlds,
            self.manager_state_identical_across_worlds,
            self.rules_identical_across_worlds,
            self.work_budget_semantics_identical_across_worlds,
        )
        if not all(controls):
            raise ValueError("comparison controls are not all aligned")
        if len(self.semantic_sha256) != 64 or self.semantic_sha256 != _hash_dataclass(self):
            raise ValueError("comparison semantic hash does not match")


def _hash_dataclass(
    value: (
        ShadowDecisionSignature
        | ShadowComparisonWorldResult
        | ShadowComparisonPair
        | FourWorldShadowComparison
    ),
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
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_value(asdict(value))
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in value.items()
            if key != "timing_ms_by_stage"
        }
    if isinstance(value, (list, tuple)):
        return tuple(_canonical_value(item) for item in value)
    return value


def _json_value(value: object) -> object:
    """Convert comparison records to JSON values while retaining diagnostics."""

    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def build_shadow_comparison_artifact(
    comparison: FourWorldShadowComparison,
    *,
    generating_implementation_sha: str,
    case: Literal["ROOT_SENSITIVE", "CONTINUATION_SENSITIVE"],
) -> dict[str, object]:
    """Build the deterministic repository evidence envelope for one real solve."""

    if len(generating_implementation_sha) != 40 or any(
        character not in "0123456789abcdef" for character in generating_implementation_sha
    ):
        raise ValueError("generating implementation SHA must be forty lowercase hex characters")
    comparison_payload = _json_value(comparison)
    semantic_basis = {
        "artifact_schema_version": "r9c-a1-synthetic-four-world-comparison-artifact-v1",
        "evidence_class": "SYNTHETIC",
        "execution_mode": "OFFLINE",
        "activation_status": "NOT_PRODUCTION_ACTIVE",
        "case": case,
        "generating_implementation_sha": generating_implementation_sha,
        "synthetic_input_semantic_sha256": comparison.rolling_execution_input_sha256,
        "comparison_semantic_sha256": comparison.semantic_sha256,
        "world_result_semantic_sha256s": tuple(
            (item.world, item.semantic_sha256) for item in comparison.results
        ),
        "pair_semantic_sha256s": tuple(
            (item.left, item.right, item.semantic_sha256) for item in comparison.pairs
        ),
    }
    return {
        **semantic_basis,
        "scenario_pairing_disclosure": (
            "COMMON_STAGE7_STAGE8_SCENARIO_IDENTITIES_AND_PROBABILITIES; "
            "EVENT_ALLOCATION_RANDOM_CONSUMPTION_MAY_DIVERGE_BY_WORLD"
        ),
        "candidate_universe_disclosure": (
            "IDENTICAL_CANONICAL_CANDIDATE_AND_LEGAL_ACTION_UNIVERSE_ACROSS_WORLDS"
        ),
        "comparison": comparison_payload,
        "timing_status": "NON_SEMANTIC_DIAGNOSTIC_MEASUREMENTS",
        "artifact_semantic_sha256": canonical_sha256(semantic_basis),
    }


def _sealed[
    SealedRecord: (
        ShadowDecisionSignature,
        ShadowComparisonWorldResult,
        ShadowComparisonPair,
        FourWorldShadowComparison,
    )
](record_type: type[SealedRecord], /, **payload: Any) -> SealedRecord:
    """Construct one record with a verified seal; unsealed public construction fails."""

    semantic_sha256 = canonical_sha256(_canonical_value(payload))
    return record_type(**payload, semantic_sha256=semantic_sha256)


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
    candidate_ids = tuple(item.player_id for item in run.optimiser_request.candidate_pool)
    return canonical_sha256({"nodes": nodes, "candidate_ids": candidate_ids}), len(nodes)


def _control_hashes(
    execution: PrivateV1RollingExecutionInput,
    run: PrivateV1RollingRunResult,
) -> dict[str, str]:
    request = run.optimiser_request
    return {
        "root_randomness": canonical_sha256(
            {
                "root_seed": execution.current_execution.root_seed,
                "scenario_count": execution.current_execution.scenario_count,
            }
        ),
        "fixture_order": canonical_sha256(
            tuple(
                tuple(sorted(projection.scenario_set.fixture_result_sha256_by_fixture))
                for projection in run.gameweek_projections
            )
        ),
        "prices": canonical_sha256(
            tuple(
                (
                    node.node_id,
                    tuple(
                        (player_id, price.model_dump(mode="json"))
                        for player_id, price in sorted(node.prices.items())
                    ),
                )
                for node in request.scenario_tree.nodes
            )
        ),
        "manager_state": request.initial_state.state_sha256,
        "rules": canonical_sha256(request.rules.model_dump(mode="json")),
        "work_budget": canonical_sha256(request.search_policy.model_dump(mode="json")),
        "terminal_policy": canonical_sha256(request.terminal_policy.model_dump(mode="json")),
        "candidate_policy": run.decision.lineage.candidate_action_policy_sha256,
    }


def _world_result(
    world: ComparisonWorld,
    run: PrivateV1RollingRunResult,
    execution: PrivateV1RollingExecutionInput,
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
    by_gameweek_transfers = tuple(
        tuple((move.player_out_id, move.player_in_id) for move in item.transfers)
        for item in decision.by_gameweek
    )
    tactical_selection_signatures = tuple(
        canonical_sha256(
            {
                "starting_xi": item.tactics.starting_xi,
                "bench_goalkeeper": item.tactics.bench_goalkeeper,
                "bench_outfield_order": item.tactics.bench_outfield_order,
                "captain": item.tactics.captain,
                "vice_captain": item.tactics.vice_captain,
            }
        )
        for item in decision.by_gameweek
    )
    signature = _sealed(
        ShadowDecisionSignature,
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
        by_gameweek_transfers=(
            by_gameweek_transfers[0],
            by_gameweek_transfers[1],
            by_gameweek_transfers[2],
        ),
        by_gameweek_hit_points=tuple(item.hit_points for item in decision.by_gameweek),
        tactical_plan_sha256s=(by_gameweek[0], by_gameweek[1], by_gameweek[2]),
        tactical_selection_signatures=(
            tactical_selection_signatures[0],
            tactical_selection_signatures[1],
            tactical_selection_signatures[2],
        ),
        optimiser_result_sha256=decision.lineage.optimiser_result_sha256,
        root_transfers=tuple(
            (item.player_out_id, item.player_in_id) for item in decision.do_now.transfers
        ),
        root_hit_points=decision.do_now.hit_points,
        root_squad_sha256=canonical_sha256(decision.do_now.squad_after),
        root_free_transfer_state_sha256=decision.do_now.free_transfer_state.semantic_sha256,
        starting_xi=decision.do_now.tactics.starting_xi,
        captain=decision.do_now.tactics.captain,
        vice_captain=decision.do_now.tactics.vice_captain,
    )
    candidate_screen_sha, node_count = _candidate_screen_sha(run)
    controls = _control_hashes(execution, run)
    lineage = decision.lineage
    return _sealed(
        ShadowComparisonWorldResult,
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
        root_randomness_sha256=controls["root_randomness"],
        fixture_order_sha256=controls["fixture_order"],
        prices_sha256=controls["prices"],
        manager_state_sha256=controls["manager_state"],
        rules_sha256=controls["rules"],
        work_budget_semantics_sha256=controls["work_budget"],
        terminal_policy_sha256=controls["terminal_policy"],
        candidate_policy_sha256=controls["candidate_policy"],
        optimiser_request_sha256=decision.lineage.optimiser_request_sha256,
        solver_status="OPTIMAL",
        recommended_plan_present=True,
        no_transfer_baseline_present=True,
        horizon_frontier_present=True,
        stage11_work=run.stage11_work,
        gain_p10=decision.horizon_comparison.gain_p10,
        gain_median=decision.horizon_comparison.gain_median,
        gain_p90=decision.horizon_comparison.gain_p90,
        probability_plan_beats_baseline=(
            decision.horizon_comparison.probability_plan_beats_baseline
        ),
        frontier_sha256=decision.transfer_frontier.semantic_sha256,
        plan_expected_horizon_utility=(decision.horizon_comparison.plan_expected_horizon_utility),
        baseline_expected_horizon_utility=(
            decision.horizon_comparison.baseline_expected_horizon_utility
        ),
        expected_uplift=decision.horizon_comparison.expected_uplift,
        timing_ms_by_stage=tuple((item.stage, item.elapsed_ms) for item in run.stage_timings),
    )


def _pair(
    left: ShadowComparisonWorldResult, right: ShadowComparisonWorldResult
) -> ShadowComparisonPair:
    left_signature = left.decision_signature
    right_signature = right.decision_signature
    root_changed = left_signature.root_action_signature != right_signature.root_action_signature
    continuation_changed = (
        left_signature.by_gameweek_action_signatures[1:]
        != right_signature.by_gameweek_action_signatures[1:]
    )
    tactics_changed = (
        left_signature.tactical_selection_signatures
        != right_signature.tactical_selection_signatures
    )
    full_plan_changed = (
        left_signature.by_gameweek_action_signatures
        != right_signature.by_gameweek_action_signatures
        or tactics_changed
    )
    utility_changed = (
        left.plan_expected_horizon_utility != right.plan_expected_horizon_utility
        or left.baseline_expected_horizon_utility != right.baseline_expected_horizon_utility
        or left.expected_uplift != right.expected_uplift
    )
    classification: Literal[
        "EXACT_PLAN_ROBUST",
        "UTILITY_ONLY_MOVEMENT",
        "ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE",
        "ROOT_ACTION_ROBUST_TACTICS_SENSITIVE",
        "WORLD_SENSITIVE_ROOT_ACTION",
    ]
    if root_changed:
        classification = "WORLD_SENSITIVE_ROOT_ACTION"
    elif continuation_changed:
        classification = "ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE"
    elif tactics_changed:
        classification = "ROOT_ACTION_ROBUST_TACTICS_SENSITIVE"
    elif utility_changed:
        classification = "UTILITY_ONLY_MOVEMENT"
    else:
        classification = "EXACT_PLAN_ROBUST"
    return _sealed(
        ShadowComparisonPair,
        left=left.world,
        right=right.world,
        root_action_changed=root_changed,
        full_plan_changed=full_plan_changed,
        starting_xi_changed=left_signature.starting_xi != right_signature.starting_xi,
        captain_changed=left_signature.captain != right_signature.captain,
        vice_captain_changed=left_signature.vice_captain != right_signature.vice_captain,
        continuation_changed=continuation_changed,
        candidate_screen_equal=left.candidate_screen_sha256 == right.candidate_screen_sha256,
        optimal_utility_delta=(
            right.plan_expected_horizon_utility - left.plan_expected_horizon_utility
        ),
        hold_utility_delta=(
            right.baseline_expected_horizon_utility - left.baseline_expected_horizon_utility
        ),
        uplift_delta=right.expected_uplift - left.expected_uplift,
        classification=classification,
    )


def run_four_world_shadow_comparison(
    execution: PrivateV1RollingExecutionInput,
    shadow: CurrentPlayerAllocationShadow,
    *,
    _world_order: tuple[ComparisonWorld, ...] = (
        "STALE",
        "CENTRAL_TEMPORARY",
        "LOW_SHRINKAGE",
        "HIGH_SHRINKAGE",
    ),
) -> FourWorldShadowComparison:
    """Run STALE and each compiled shadow world with isolated service state.

    The stale call intentionally uses ordinary construction with no resolver.
    Every injected world gets a fresh service and resolver, preventing tactical
    or optimiser cache state from crossing a world boundary.
    """

    canonical_worlds: tuple[ComparisonWorld, ...] = (
        "STALE",
        "CENTRAL_TEMPORARY",
        "LOW_SHRINKAGE",
        "HIGH_SHRINKAGE",
    )
    if len(_world_order) != 4 or set(_world_order) != set(canonical_worlds):
        raise ValueError("execution order must contain each comparison world exactly once")
    shadow = CurrentPlayerAllocationShadow.model_validate(shadow.model_dump(mode="python"))
    target_gameweek = execution.horizon_gameweeks[0]
    cutoff = execution.current_execution.current_state.information_cutoff
    for compiled_world in shadow.worlds:
        posterior = compiled_world.posterior
        if (
            posterior.target_gameweek != target_gameweek
            or posterior.source_gameweeks != tuple(range(1, target_gameweek))
            or posterior.information_cutoff != cutoff
        ):
            raise ValueError("shadow target, history, or cutoff differs from rolling execution")
    run_by_world: dict[ComparisonWorld, PrivateV1RollingRunResult] = {}
    for world in _world_order:
        if world == "STALE":
            service = PrivateV1RollingRecommendationService()
        else:
            service = PrivateV1RollingRecommendationService(
                _allocation_profile_resolver=ShadowFixtureAllocationProfileResolver(
                    shadow=shadow,
                    world=world,
                )
            )
        run_by_world[world] = service.run(execution)
    results = tuple(
        _world_result(world, run_by_world[world], execution) for world in canonical_worlds
    )
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
    if any(item.candidate_screen_sha256 != reference.candidate_screen_sha256 for item in results):
        raise ValueError("shadow comparison candidate universes diverged")
    control_fields = (
        "root_randomness_sha256",
        "fixture_order_sha256",
        "prices_sha256",
        "manager_state_sha256",
        "rules_sha256",
        "work_budget_semantics_sha256",
        "terminal_policy_sha256",
        "candidate_policy_sha256",
    )
    for field_name in control_fields:
        if any(getattr(item, field_name) != getattr(reference, field_name) for item in results[1:]):
            raise ValueError(f"shadow comparison control diverged: {field_name}")
    pairs = tuple(
        _pair(results[left], results[right])
        for left in range(len(results))
        for right in range(left + 1, len(results))
    )
    return _sealed(
        FourWorldShadowComparison,
        schema_version="r9c-a1-four-world-three-gw-shadow-comparison-v1",
        rolling_execution_input_sha256=execution.semantic_sha256,
        shadow_sha256=shadow.semantic_sha256,
        experiment_mode="SYNTHETIC_OFFLINE_NOT_ACTIVE",
        target_gameweek=execution.horizon_gameweeks[0],
        history_gameweeks=shadow.worlds[0].posterior.source_gameweeks,
        horizon_gameweeks=execution.horizon_gameweeks,
        information_cutoff_utc=execution.current_execution.current_state.information_cutoff.isoformat().replace(
            "+00:00", "Z"
        ),
        world_set=("STALE", "CENTRAL_TEMPORARY", "LOW_SHRINKAGE", "HIGH_SHRINKAGE"),
        results=(results[0], results[1], results[2], results[3]),
        pairs=pairs,
        stage7_identical_across_worlds=True,
        stage8_identical_across_worlds=True,
        root_randomness_aligned=True,
        scenario_identity_aligned=True,
        candidate_universe_same_across_worlds=True,
        prices_identical_across_worlds=True,
        manager_state_identical_across_worlds=True,
        rules_identical_across_worlds=True,
        work_budget_semantics_identical_across_worlds=True,
        model_input_status="SHADOW_NOT_MODEL_INPUT",
        production_activation=False,
        new_network_requests=0,
        persistence_performed=False,
    )


__all__ = [
    "ComparisonWorld",
    "FourWorldShadowComparison",
    "ShadowComparisonPair",
    "ShadowComparisonWorldResult",
    "ShadowDecisionSignature",
    "build_shadow_comparison_artifact",
    "run_four_world_shadow_comparison",
]
