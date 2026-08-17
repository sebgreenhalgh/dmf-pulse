"""Deterministic external runtime benchmarks for representative OPT-011 fixtures."""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

from dmf_pulse.optimisation.multi_gameweek_artifacts import load_canonical_json
from dmf_pulse.optimisation.multi_gameweek_models import MultiGameweekOptimisationRequest
from dmf_pulse.optimisation.multi_gameweek_service import optimise_multi_gameweek

CASES = (
    ("tiny_oracle", "simple_one_ft"),
    ("deterministic_multi_gameweek", "price_change_blocks_later_route"),
    ("scenario_tree", "injury_revealed_after_current_decision"),
)


def _leaf_count(request: MultiGameweekOptimisationRequest) -> int:
    parents = {node.parent_id for node in request.scenario_tree.nodes if node.parent_id is not None}
    return sum(node.node_id not in parents for node in request.scenario_tree.nodes)


def main() -> int:
    root = Path.cwd()
    fixture_root = root / "fixtures/optimisation/multi_gameweek/adversarial"
    rows: list[dict[str, Any]] = []
    for label, fixture in CASES:
        request = load_canonical_json(
            fixture_root / f"{fixture}.json", MultiGameweekOptimisationRequest
        )
        durations: list[float] = []
        result = None
        for _ in range(3):
            started = time.perf_counter()
            result = optimise_multi_gameweek(request)
            durations.append((time.perf_counter() - started) * 1000)
        assert result is not None
        rows.append(
            {
                "label": label,
                "fixture": fixture,
                "players": len(request.candidate_pool),
                "horizon_gameweeks": (
                    max(node.gameweek for node in request.scenario_tree.nodes)
                    - request.scenario_tree.root.gameweek
                    + 1
                ),
                "decision_nodes": len(request.scenario_tree.nodes),
                "scenario_leaves": _leaf_count(request),
                "actions_generated": result.solver_status.action_candidates,
                "state_expansions": result.solver_status.state_expansions,
                "policy_candidates": result.solver_status.policy_candidates,
                "backend": result.solver_status.backend,
                "status": result.solver_status.status.value,
                "guarantee": result.solver_status.optimality_guarantee.value,
                "runtime_ms_min": round(min(durations), 3),
                "runtime_ms_median": round(statistics.median(durations), 3),
                "runtime_ms_max": round(max(durations), 3),
            }
        )
    report = {
        "schema_version": "opt-011-benchmark-v1",
        "runs_per_case": 3,
        "timing_note": "External wall-clock evidence; not part of deterministic result hashes.",
        "cases": rows,
    }
    output = root / "evidence/tickets/OPT-011/benchmarks.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
