"""Seal count-only D7 capacity evidence from repository-owned offline probes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.artifacts import semantic_sha256


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid D7 probe object: {path.name}")
    return value


def _as_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"D7 {name} must be an integer")
    return value


def _require_probe_contract(
    governed: dict[str, object], reference: dict[str, object], *, ordering: str
) -> None:
    raw_ordering = {
        "BASELINE_LIKE": "baseline",
        "SHIFTED_SHADOW_LIKE": "shifted-shadow",
    }[ordering]
    common = {
        "projection_ordering": raw_ordering,
        "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "stress_case": "L6_SHAPE_13_INCOMING",
    }
    for probe in (governed, reference):
        if any(probe.get(name) != value for name, value in common.items()):
            raise ValueError("D7 probe source, shape or projection ordering differs")
        if _as_int(probe.get("effective_max_actions_per_state"), name="action cap") < 17000:
            raise ValueError("D7 probe action/state capacity is insufficient")
        if _as_int(probe.get("root_action_upper"), name="root upper") < 8386:
            raise ValueError("D7 probe root action upper is insufficient")
        if _as_int(probe.get("candidate_pool_size"), name="catalog size") != 35:
            raise ValueError("D7 probe catalog size differs from the declared stress")
        if _as_int(probe.get("fixture_extra_players_per_position"), name="fixture extras") != 5:
            raise ValueError("D7 probe fixture breadth differs from the declared stress")
        expected_positions = {"GK": 3, "DEF": 4, "MID": 3, "FWD": 3}
        if (
            probe.get("root_incoming_by_position") != expected_positions
            or probe.get("terminal_incoming_by_position") != expected_positions
        ):
            raise ValueError("D7 probe node scope positional shape differs")
        if (
            _as_int(probe.get("effective_max_returned_root_candidates"), name="root capacity")
            < 8386
        ):
            raise ValueError("D7 probe root retained capacity is insufficient")
        if _as_int(probe.get("retained_incoming_count"), name="root incoming") != 13:
            raise ValueError("D7 probe does not retain all 13 root incoming candidates")
        if _as_int(probe.get("terminal_retained_incoming_count"), name="terminal incoming") != 13:
            raise ValueError("D7 probe does not retain all 13 terminal incoming candidates")
        if _as_int(probe.get("root_terminal_incoming_overlap"), name="scope overlap") != 6:
            raise ValueError("D7 probe does not use the declared time-varying candidate scopes")
        if probe.get("configured_max_policy_candidates") is not None:
            raise ValueError("D7 v2 probe retained the legacy overloaded capacity")
    governed_caps = (
        governed.get("configured_max_generated_policy_candidates"),
        governed.get("configured_max_retained_pareto_candidates"),
        governed.get("configured_cumulative_legal_action_limit"),
    )
    if governed_caps != (2097152, 786432, 2097152):
        raise ValueError("D7 governed probe capacities differ")
    high_caps = (
        reference.get("configured_max_generated_policy_candidates"),
        reference.get("configured_max_retained_pareto_candidates"),
        reference.get("configured_cumulative_legal_action_limit"),
    )
    if high_caps != (10000000, 10000000, 10000000):
        raise ValueError("D7 high probe is not the declared 10-million ceiling")


def _validated_decision_value(semantics: object) -> tuple[dict[str, object], str]:
    if not isinstance(semantics, dict):
        raise ValueError("D7 probe lacks decision semantic identity")
    value = semantics.get("value")
    claimed = semantics.get("semantic_sha256")
    if not isinstance(value, dict) or not isinstance(claimed, str):
        raise ValueError("D7 probe decision semantic payload is malformed")
    if canonical_sha256(value) != claimed:
        raise ValueError("D7 probe decision semantic authentication failed")
    required_plans = ("recommended", "no_transfer_baseline", "root_counterfactual")
    if any(not isinstance(value.get(name), dict) for name in required_plans):
        raise ValueError("D7 probe lacks a required decision plan")
    recommended = value["recommended"]
    if not isinstance(recommended, dict):
        raise ValueError("D7 recommended plan is malformed")
    current_action = recommended.get("current_action")
    future_policy = recommended.get("future_policy")
    if (
        not isinstance(current_action, dict)
        or not isinstance(future_policy, list)
        or len(future_policy) < 2
    ):
        raise ValueError("D7 probe lacks the complete future policy")
    if not isinstance(recommended.get("utility"), dict):
        raise ValueError("D7 probe lacks objective utilities")
    for name in ("conservative_alternative", "high_upside_alternative"):
        alternative = value.get(name)
        if not isinstance(alternative, dict):
            raise ValueError("D7 probe lacks a supported objective alternative")
        if not isinstance(alternative.get("availability"), str) or not isinstance(
            alternative.get("reason"), str
        ):
            raise ValueError("D7 objective alternative is malformed")
        plan = alternative.get("plan")
        if plan is not None and not isinstance(plan, dict):
            raise ValueError("D7 objective alternative plan is malformed")
    frontier = value.get("transfer_count_frontier")
    if not isinstance(frontier, list) or not frontier:
        raise ValueError("D7 probe lacks the complete transfer-count frontier")
    return value, claimed


def _case(
    governed: dict[str, object],
    reference: dict[str, object],
    *,
    ordering: str,
    peak_memory_bytes: int | None = None,
) -> dict[str, object]:
    _require_probe_contract(governed, reference, ordering=ordering)
    governed_solve = governed["whole_public_solve"]
    reference_solve = reference["whole_public_solve"]
    if not isinstance(governed_solve, dict) or not isinstance(reference_solve, dict):
        raise ValueError("D7 probe lacks whole public solve")
    if governed_solve["status"] != "SUCCESS" or reference_solve["status"] != "SUCCESS":
        raise ValueError("D7 governed/reference solve did not both succeed")
    governed_value, governed_sha = _validated_decision_value(governed_solve["decision_semantics"])
    reference_value, reference_sha = _validated_decision_value(
        reference_solve["decision_semantics"]
    )
    if governed_sha != reference_sha or governed_value != reference_value:
        raise ValueError("D7 governed/reference decision semantics differ")
    profile = governed_solve["profile"]
    reference_profile = reference_solve["profile"]
    if not isinstance(profile, dict) or not isinstance(reference_profile, dict):
        raise ValueError("D7 probe lacks count profile")
    count_names = (
        "cumulative_legal_actions",
        "cumulative_generated_policy_candidates",
        "cumulative_retained_pareto_candidates",
        "cumulative_state_expansions",
        "cumulative_action_combinations",
        "cumulative_unique_node_squads",
        "cumulative_tactical_requests",
        "cumulative_objective_winners_retained",
        "cumulative_strict_pareto_dominance_events",
        "cumulative_tie_equivalence_events",
        "peak_temporary_policy_candidates",
    )
    if any(profile[name] != reference_profile[name] for name in count_names):
        raise ValueError("D7 governed/reference count profile differs")
    if profile["cumulative_generated_policy_candidates"] != sum(
        _as_int(profile[name], name=name)
        for name in (
            "cumulative_retained_pareto_candidates",
            "cumulative_strict_pareto_dominance_events",
            "cumulative_tie_equivalence_events",
        )
    ):
        raise ValueError("D7 exact reduction counts do not reconcile")
    if profile["cumulative_legal_actions"] < 783057:
        raise ValueError("D7 stress does not dominate historical legal-action work")
    nodes = profile["nodes"]
    if not isinstance(nodes, list) or len(nodes) != 3:
        raise ValueError("D7 stress must expose exactly three count-only layers")
    layer_fields = (
        "depth",
        "gameweek",
        "reachable_states",
        "unique_economic_state_fingerprints",
        "legal_actions_generated",
        "action_combinations_considered",
        "unique_resulting_active_squads",
        "policy_candidates_generated",
        "pareto_candidates_retained",
        "objective_winners_retained",
        "strict_pareto_dominance_events",
        "tie_equivalence_events",
        "peak_temporary_candidate_population",
    )
    layers = [
        {name: node[name] for name in layer_fields} for node in nodes if isinstance(node, dict)
    ]
    if len(layers) != 3 or layers[-1]["reachable_states"] < 8187:
        raise ValueError("D7 terminal stress shape is insufficient")
    if layers[-1]["legal_actions_generated"] < 753864:
        raise ValueError("D7 terminal legal-action stress is insufficient")
    if layers[-1]["unique_resulting_active_squads"] < 190867:
        raise ValueError("D7 terminal resulting-squad stress is insufficient")
    return {
        "projection_ordering": ordering,
        "classification": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "candidate_pool_size": governed["candidate_pool_size"],
        "fixture_extra_players_per_position": governed["fixture_extra_players_per_position"],
        "root_incoming_candidates": governed["retained_incoming_count"],
        "terminal_incoming_candidates": governed["terminal_retained_incoming_count"],
        "root_terminal_incoming_overlap": governed["root_terminal_incoming_overlap"],
        "root_terminal_candidate_turnover": _as_int(
            governed["retained_incoming_count"], name="root incoming"
        )
        - _as_int(governed["root_terminal_incoming_overlap"], name="scope overlap"),
        "root_incoming_by_position": governed["root_incoming_by_position"],
        "terminal_incoming_by_position": governed["terminal_incoming_by_position"],
        "governed_cap_status": governed_solve["status"],
        "high_cap_status": reference_solve["status"],
        "governed_generated_policy_cap": governed["configured_max_generated_policy_candidates"],
        "governed_retained_pareto_cap": governed["configured_max_retained_pareto_candidates"],
        "governed_cumulative_legal_action_cap": governed[
            "configured_cumulative_legal_action_limit"
        ],
        "high_discovery_ceiling": reference["configured_max_generated_policy_candidates"],
        "complete_generated_policy_candidates": profile["cumulative_generated_policy_candidates"],
        "complete_cumulative_legal_actions": profile["cumulative_legal_actions"],
        "cumulative_retained_pareto_candidates": profile["cumulative_retained_pareto_candidates"],
        "state_expansions": profile["cumulative_state_expansions"],
        "action_candidates": profile["cumulative_action_combinations"],
        "tactical_requests": profile["cumulative_tactical_requests"],
        "unique_resulting_squads": profile["cumulative_unique_node_squads"],
        "peak_temporary_policy_candidates": profile["peak_temporary_policy_candidates"],
        "decision_semantic_sha256": governed_sha,
        "governed_high_decision_semantics_equal": True,
        "recommended_plan_equal": True,
        "no_transfer_baseline_equal": True,
        "root_counterfactual_equal": True,
        "complete_transfer_count_frontier_equal": True,
        "future_policy_equal": True,
        "objective_utilities_equal": True,
        "layers": layers,
        "governed_wall_seconds": governed_solve["wall_seconds"],
        "governed_cpu_seconds": governed_solve["cpu_seconds"],
        "high_wall_seconds": reference_solve["wall_seconds"],
        "high_cpu_seconds": reference_solve["cpu_seconds"],
        "peak_memory_bytes": peak_memory_bytes,
        "memory_measurement": (
            "WINDOWS_GET_PROCESS_PEAKWORKINGSET64_REVIEWER_OBSERVED_BASELINE_HIGH"
            if peak_memory_bytes is not None
            else "NOT_CAPTURED_FOR_THIS_CASE"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-governed", type=Path, required=True)
    parser.add_argument("--baseline-high", type=Path, required=True)
    parser.add_argument("--shifted-governed", type=Path, required=True)
    parser.add_argument("--shifted-high", type=Path, required=True)
    parser.add_argument("--baseline-high-peak-working-set-bytes", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        args.baseline_high_peak_working_set_bytes is not None
        and args.baseline_high_peak_working_set_bytes <= 0
    ):
        parser.error("baseline high peak working set must be positive")
    cases = (
        _case(
            _load(args.baseline_governed),
            _load(args.baseline_high),
            ordering="BASELINE_LIKE",
            peak_memory_bytes=args.baseline_high_peak_working_set_bytes,
        ),
        _case(
            _load(args.shifted_governed),
            _load(args.shifted_high),
            ordering="SHIFTED_SHADOW_LIKE",
        ),
    )
    maximum_generated = max(
        _as_int(case["complete_generated_policy_candidates"], name="generated count")
        for case in cases
    )
    maximum_legal = max(
        _as_int(case["complete_cumulative_legal_actions"], name="legal-action count")
        for case in cases
    )
    generated_cap = 2097152
    legal_cap = 2097152
    payload: dict[str, object] = {
        "schema_version": "current-team-strength-l7-d7-policy-capacity-v1",
        "classification": "OFFLINE_REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "immutable_parent": "57f578efa168919b63574fa8a3bd4656b6b6d4bf",
        "historical_l7": {
            "stage8_fixtures_complete": "30/30",
            "stage9_gameweeks_assembled": "3/3",
            "stage9_mc_passed": "3/3",
            "complete_cumulative_legal_actions": 783057,
            "generated_policy_first_crossing": 786433,
            "configured_generated_policy_cap": 786432,
            "backend_status": "TIME_RESOURCE_LIMIT_NO_INCUMBENT",
            "shadow_world_started": False,
        },
        "governance": {
            "schema_version": "multi-gameweek-search-policy-v2",
            "legacy_v1_compatibility": "EXPLICIT_FAIL_CLOSED",
            "max_policy_candidates_overload_confirmed": True,
            "max_generated_policy_candidates": generated_cap,
            "max_retained_pareto_candidates": 786432,
            "max_cumulative_legal_actions": legal_cap,
            "ten_million_role": "OFFLINE_DISCOVERY_CEILING_ONLY",
            "maximum_complete_generated_demand": maximum_generated,
            "generated_headroom": generated_cap - maximum_generated,
            "generated_headroom_fraction_of_demand": (generated_cap - maximum_generated)
            / maximum_generated,
            "maximum_complete_legal_action_demand": maximum_legal,
            "legal_action_headroom": legal_cap - maximum_legal,
            "legal_action_headroom_fraction_of_demand": (legal_cap - maximum_legal) / maximum_legal,
        },
        "remediation": {
            "lossless_streaming_pareto_reduction": True,
            "discovery_applied_transitions_replayed_not_retained": True,
            "logical_generated_policy_counter_preserved": True,
            "governance_field_separation": True,
            "generated_policy_cap_increased": True,
            "cumulative_action_headroom_increased": True,
            "candidate_scope_unchanged": True,
            "deterministic_linear_fast_path_authority_unchanged": True,
            "d6_no_transfer_baseline_reuse_preserved": True,
        },
        "cases": cases,
        "provider_access": {
            "fpl_requests": 0,
            "odds_requests": 0,
            "live_openfootball_requests": 0,
            "credentials_inspected": False,
        },
        "authority": {
            "l1_through_l7_consumed": True,
            "l8_authority_exists": False,
        },
    }
    payload["semantic_sha256"] = semantic_sha256(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"output": str(args.output), "semantic_sha256": payload["semantic_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
